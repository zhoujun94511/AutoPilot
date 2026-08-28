"""规划/定位两阶段：先按目标描述在页摘要里解析 locator。

借鉴 Midscene deepThink 思想：规划「要点什么」与「定位符是什么」拆开。
默认用启发式匹配（不增加 LLM 调用）；``AUTOPILOT_AUTHORING_DEEP_THINK=1``
时，启发式失败再打一次廉价定位 LLM。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from .contract import AuthoringError, GeneratedStep
from .llm_client import ChatFn, complete_json

_ENV_DEEP_THINK = "AUTOPILOT_AUTHORING_DEEP_THINK"


def deep_think_enabled() -> bool:
    raw = (os.environ.get(_ENV_DEEP_THINK) or "0").strip().lower()
    return raw in ("1", "true", "yes", "on", "deep")


def parse_page_elements(elements_text: str) -> list[dict[str, Any]]:
    try:
        items = json.loads(elements_text or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(items, list):
        return []
    return [el for el in items if isinstance(el, dict) and str(el.get("l") or "").strip()]


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip().lower())


def match_hint_to_locator(
    hint: str,
    elements: list[dict[str, Any]],
    *,
    page_locators: set[str] | None = None,
) -> str:
    """用 comment / target 文案在页摘要里找最像的 ``l``。"""
    key = _norm(hint)
    if not key or not elements:
        return ""
    scored: list[tuple[int, str]] = []
    for el in elements:
        loc = str(el.get("l") or "").strip()
        if not loc:
            continue
        if page_locators is not None and loc not in page_locators:
            continue
        tx = _norm(str(el.get("tx") or ""))
        # 也比一下 locator 本体（name::无线局域网）
        loc_body = _norm(loc.split("::", 1)[-1] if "::" in loc else loc)
        score = 0
        if tx and (key == tx or key in tx or tx in key):
            score = 100 if key == tx else 80
        elif loc_body and (key == loc_body or key in loc_body or loc_body in key):
            score = 70 if key == loc_body else 50
        if score:
            scored.append((score, loc))
    if not scored:
        return ""
    scored.sort(key=lambda x: (-x[0], len(x[1])))
    return scored[0][1]


def _step_hint(step: GeneratedStep) -> str:
    params = step.params or {}
    for key in ("target", "hint", "label", "text"):
        val = str(params.get(key) or "").strip()
        # text 参数常是要输入的内容，不当控件名；仅当没有 comment 时作弱提示
        if key == "text":
            continue
        if val:
            return val
    return str(step.comment or "").strip()


def resolve_locators_heuristic(
    steps: list[GeneratedStep],
    elements_text: str,
    *,
    page_locators: set[str],
) -> tuple[list[GeneratedStep], list[str]]:
    """对定位类步骤：locator 缺失或不在页上时，用 hint 匹配 ``l``。"""
    elements = parse_page_elements(elements_text)
    notes: list[str] = []
    if not elements:
        return steps, notes
    for step in steps:
        params = step.params
        if not isinstance(params, dict):
            continue
        current = str(params.get("locator") or "").strip()
        if current and current in page_locators:
            continue
        hint = _step_hint(step)
        if not hint:
            continue
        hit = match_hint_to_locator(hint, elements, page_locators=page_locators)
        if not hit:
            continue
        params["locator"] = hit
        notes.append(f"定位解析：{hint} → {hit}")
    return steps, notes


def resolve_locators_via_llm(
    steps: list[GeneratedStep],
    elements_text: str,
    *,
    page_locators: set[str],
    chat: ChatFn | None = None,
) -> tuple[list[GeneratedStep], list[str]]:
    """启发式失败后的二次定位（仅补 locator，不改规划）。"""
    need: list[tuple[int, GeneratedStep, str]] = []
    for i, step in enumerate(steps):
        params = step.params if isinstance(step.params, dict) else {}
        current = str(params.get("locator") or "").strip()
        if current and current in page_locators:
            continue
        hint = _step_hint(step)
        if not hint:
            continue
        need.append((i, step, hint))
    if not need:
        return steps, []

    payload = [
        {"index": i, "keyword_id": s.keyword_id, "target": hint}
        for i, s, hint in need
    ]
    prompt = f"""根据当前页控件摘要，为下列目标补全可执行定位符。
只输出 JSON：{{"matches":[{{"index":0,"locator":"摘要里的 l 字段"}}]}}
不要编造摘要中不存在的 locator。找不到则 locator 为空串。

目标：
{json.dumps(payload, ensure_ascii=False)}

页摘要：
{elements_text or "[]"}
"""
    notes: list[str] = []
    try:
        data = complete_json(prompt, chat=chat, purpose="locate")
    except (AuthoringError, OSError, TypeError, ValueError, RuntimeError) as exc:
        notes.append(f"深度定位跳过：{exc}")
        return steps, notes
    matches = data.get("matches") if isinstance(data, dict) else None
    if not isinstance(matches, list):
        return steps, notes
    by_index = {
        int(m.get("index")): str(m.get("locator") or "").strip()
        for m in matches
        if isinstance(m, dict) and str(m.get("index") or "").isdigit()
    }
    for i, step, hint in need:
        loc = by_index.get(i) or ""
        if not loc or loc not in page_locators:
            continue
        if not isinstance(step.params, dict):
            step.params = {}
        step.params["locator"] = loc
        notes.append(f"深度定位：{hint} → {loc}")
    return steps, notes


def resolve_planned_locators(
    steps: list[GeneratedStep],
    elements_text: str,
    *,
    page_locators: set[str],
    chat: ChatFn | None = None,
    allow_deep_think: bool | None = None,
) -> tuple[list[GeneratedStep], list[str]]:
    """两阶段定位入口：启发式 →（可选）LLM。"""
    steps, notes = resolve_locators_heuristic(
        steps, elements_text, page_locators=page_locators
    )
    use_deep = deep_think_enabled() if allow_deep_think is None else allow_deep_think
    if not use_deep:
        return steps, notes
    still_need = False
    for step in steps:
        params = step.params if isinstance(step.params, dict) else {}
        loc = str(params.get("locator") or "").strip()
        if _step_hint(step) and (not loc or loc not in page_locators):
            still_need = True
            break
    if not still_need:
        return steps, notes
    steps, deep_notes = resolve_locators_via_llm(
        steps, elements_text, page_locators=page_locators, chat=chat
    )
    notes.extend(deep_notes)
    return steps, notes
