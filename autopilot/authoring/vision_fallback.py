"""采页为空时的可选 Vision 兜底（默认关闭，避免无意烧配额）。

开启：``AUTOPILOT_AUTHORING_VISION_FALLBACK=1``，且 Intent Vision 已启用。
把 Vision 候选压成 compact 页摘要，让编写 Agent 仍走传统关键字路径。
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..runtime.log import get_logger

log = get_logger("authoring.vision_fallback")

_ENV = "AUTOPILOT_AUTHORING_VISION_FALLBACK"


def vision_fallback_enabled() -> bool:
    raw = (os.environ.get(_ENV) or "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def candidates_to_elements(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Vision 候选 → 编写器用的 compact 元素（``l`` / ``tx`` / ``t``）。"""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        params = row.get("params") if isinstance(row.get("params"), dict) else {}
        loc = str(
            params.get("locator")
            or row.get("locator")
            or ""
        ).strip()
        if not loc or loc in seen:
            continue
        seen.add(loc)
        tx = str(
            row.get("target")
            or row.get("label")
            or params.get("text")
            or loc.split("::", 1)[-1]
        ).strip()[:80]
        kid = str(row.get("keyword_id") or "")
        editable = 1 if "text_input" in kid or "type" in kid else 0
        clickable = 1 if "click" in kid or editable else 1
        item: dict[str, Any] = {"l": loc, "tx": tx, "t": "VisionHint"}
        if clickable:
            item["ck"] = 1
        if editable:
            item["ed"] = 1
        out.append(item)
        if len(out) >= 30:
            break
    return out


def enrich_empty_page_via_vision(
    *,
    ctx: Any,
    platform: str,
    natural_language: str,
) -> tuple[str, int, list[str]]:
    """返回 ``(elements_text, element_count, notes)``；未启用或失败则空摘要。"""
    notes: list[str] = []
    if not vision_fallback_enabled():
        return "[]", 0, notes
    try:
        from ..intent.vision import vision_candidates, vision_enabled
    except ImportError:
        notes.append("Vision 兜底不可用：未安装 intent.vision")
        return "[]", 0, notes
    if not vision_enabled():
        notes.append(
            "已开编写 Vision 兜底，但 Intent Vision 未启用"
            "（需 AUTOPILOT_INTENT_VISION=1）"
        )
        return "[]", 0, notes

    target = (natural_language or "").strip()[:200] or "列出当前页可点击与可输入控件"
    try:
        rows = vision_candidates(
            action="observe",
            target=target,
            value="",
            platform=platform,
            ctx=ctx,
            enhanced=False,
        )
    except (OSError, RuntimeError, TypeError, ValueError, ImportError) as exc:
        log.warning("authoring vision fallback failed: %s", exc)
        notes.append(f"Vision 兜底失败：{exc}")
        return "[]", 0, notes

    elements = candidates_to_elements(list(rows or []))
    if not elements:
        notes.append("Vision 兜底未返回可用控件")
        return "[]", 0, notes
    text = json.dumps(elements, ensure_ascii=False)
    notes.append(f"Vision 兜底：注入 {len(elements)} 个控件线索")
    return text, len(elements), notes
