"""编写收尾事后裁判：只加注步骤，但 ``passed=false`` 会阻止上传。

默认 heuristic，不额外烧 token；``AUTOPILOT_AUTHORING_GOAL_JUDGE=0`` 关闭。
视觉裁判不得单独把用例改成 PASS/FAIL。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from .contract import AuthoringError, GeneratedStep
from .llm_client import ChatFn, complete_json
from .secrets import collect_secret_map, mask_history_row, mask_text


def goal_judge_mode() -> str:
    """off | heuristic | llm。默认 heuristic，避免编写收尾再烧一轮 token。"""
    raw = (os.environ.get("AUTOPILOT_AUTHORING_GOAL_JUDGE") or "heuristic").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return "off"
    if raw in {"llm", "1", "true", "on", "yes"}:
        return "llm"
    return "heuristic"


def goal_judge_enabled() -> bool:
    return goal_judge_mode() != "off"


def heuristic_goal_judge(
    *,
    goal_completed: bool,
    recorded: list[GeneratedStep],
    warnings: list[str],
    platform: str = "",
    natural_language: str = "",
    target_confirmed: bool = False,
) -> dict[str, Any]:
    """不耗 token 的收尾注记。模型 done 不足以单独通过。"""
    notes = [w for w in (warnings or []) if w]
    bits: list[str] = []
    if any("REPEAT_FAILED" in w or "重复操作" in w for w in notes):
        bits.append("重复操作熔断")
    if any("连续" in w and "失败" in w for w in notes):
        bits.append("连续步骤失败")
    if any("回合上限" in w or "步数上限" in w or "AI 调用上限" in w for w in notes):
        bits.append("预算耗尽")
    if not recorded:
        bits.append("无成功步骤")
    evidence_ok, evidence_reason = completion_evidence(
        recorded,
        platform=platform,
        natural_language=natural_language,
        model_done=goal_completed,
        target_confirmed=target_confirmed,
    )
    if not evidence_ok and evidence_reason:
        bits.append(evidence_reason)
    if bits:
        return {
            "passed": False,
            "reason": "；".join(dict.fromkeys(bits)),
            "confidence": 0.7,
            "source": "heuristic",
        }
    if goal_completed and evidence_ok:
        return {
            "passed": True,
            "reason": "模型宣告完成，且已有断言或已确认的目标动作",
            "confidence": 0.75,
            "source": "heuristic",
        }
    return {
        "passed": False,
        "reason": "模型未宣告目标完成",
        "confidence": 0.5,
        "source": "heuristic",
    }


def maybe_llm_goal_judge(
    *,
    natural_language: str,
    recorded: list[GeneratedStep],
    goal_completed: bool,
    warnings: list[str],
    chat: ChatFn | None,
    platform: str = "",
    target_confirmed: bool = False,
) -> dict[str, Any] | None:
    """未完成时可选补一刀文本判定；失败则返回 None，由启发式兜底。"""
    if goal_completed or chat is None or goal_judge_mode() != "llm":
        return None
    extra: list[str] = []
    for step in (recorded or [])[:20]:
        for val in (step.params or {}).values():
            if val is not None:
                extra.append(str(val))
    secret_map = collect_secret_map(natural_language, extra)
    steps = [
        mask_history_row(
            {
                "keyword_id": s.keyword_id,
                "comment": s.comment,
                "params": dict(s.params or {}),
            },
            secret_map,
        )
        for s in (recorded or [])[:20]
    ]
    prompt = (
        "你是用例编写收尾检查器。根据用户目标和已成功执行的步骤，判断目标是否已被覆盖。\n"
        "只输出 JSON：{\"passed\": bool, \"reason\": \"一句话\", \"confidence\": 0.0到1.0}\n"
        "不要改写步骤。不确定时 passed=false。\n\n"
        f"平台：{(platform or '').strip() or '未指定'}\n"
        f"目标动作已确认：{'是' if target_confirmed else '否'}\n"
        f"用户目标：\n{mask_text((natural_language or '').strip(), secret_map)}\n\n"
        f"已成功步骤：\n{steps}\n\n"
        f"编写警告：\n{(warnings or [])[-8:]}\n"
    )
    try:
        data = complete_json(prompt, chat=chat, purpose="planning")
    except AuthoringError:
        # 裁判失败不得打断编写；complete_json / 网关异常都收成 AuthoringError
        return None
    reason = str(data.get("reason") or "").strip()
    if not reason:
        return None
    try:
        conf = float(data.get("confidence") or 0.5)
    except (TypeError, ValueError):
        conf = 0.5
    return {
        "passed": bool(data.get("passed")),
        "reason": reason[:300],
        "confidence": max(0.0, min(1.0, conf)),
        "source": "llm",
    }


def judge_authoring_goal(
    *,
    natural_language: str,
    recorded: list[GeneratedStep],
    goal_completed: bool,
    warnings: list[str],
    chat: ChatFn | None = None,
    platform: str = "",
    target_confirmed: bool = False,
) -> dict[str, Any]:
    """返回裁判字典；不得改写已记录步骤，但 ``passed=false`` 应阻止上传。"""
    if not goal_judge_enabled():
        return {}
    llm = maybe_llm_goal_judge(
        natural_language=natural_language,
        recorded=recorded,
        goal_completed=goal_completed,
        warnings=warnings,
        chat=chat,
        platform=platform,
        target_confirmed=target_confirmed,
    )
    if llm is not None:
        return llm
    return heuristic_goal_judge(
        goal_completed=goal_completed,
        recorded=recorded,
        warnings=warnings,
        platform=platform,
        natural_language=natural_language,
        target_confirmed=target_confirmed,
    )


_ASSERT_MARKERS = ("_verify_", "verify_", "_assert_", "assert_")
_STOPWORDS = frozenset({
    "打开", "启动", "进入", "点击", "点", "一下", "然后", "接着", "并且", "以及",
    "帮我", "请", "在", "里", "中", "的", "了", "并", "用", "使用", "应用", "页面",
    "验证", "确认", "检查", "断言", "显示", "可见", "当前", "这个", "那个",
    "open", "click", "then", "and", "the", "app", "page", "verify", "check",
})
_HIGH_STAKES_RE = re.compile(
    r"购买|提交|支付|下单|登录|删除|发送|确认订单|付款|checkout|purchase|login|submit",
    re.IGNORECASE,
)


def _step_is_assert(step: GeneratedStep) -> bool:
    kid = (step.keyword_id or "").lower()
    return any(m in kid for m in _ASSERT_MARKERS)


def completion_evidence(
    recorded: list[GeneratedStep],
    *,
    platform: str,
    natural_language: str,
    model_done: bool,
    target_confirmed: bool,
) -> tuple[bool, str]:
    """模型 done 只是必要条件；要有断言或已确认 target 才算完成。"""
    if not model_done:
        return False, "模型未宣告目标完成"
    plat = (platform or "").strip().lower()
    has_assert = any(_step_is_assert(s) for s in recorded or [])
    if plat == "http" and not has_assert:
        return False, "HTTP 用例缺少断言步骤（http_assert_* / json_assert_*）"
    nl = natural_language or ""
    wants_assert = bool(re.search(
        r"确认|检查|验证|断言|校验|应当|应该|必须.*显示|可见|verify|assert|check\b",
        nl,
        re.IGNORECASE,
    ))
    if wants_assert and not has_assert:
        return False, "需求含确认/验证语义，但草稿中尚无断言步骤（verify_*）"
    if has_assert or target_confirmed:
        return True, ""
    return False, "仅有模型宣告完成，缺少已确认的目标动作或断言"


def goal_content_tokens(natural_language: str) -> list[str]:
    """从 NL 抽出可用于页面语义核对的实词。"""
    text = (natural_language or "").strip()
    if not text:
        return []
    splitters: list[str] = []
    for word in sorted(_STOPWORDS, key=len, reverse=True):
        if re.fullmatch(r"[A-Za-z]+", word):
            splitters.append(rf"\b{re.escape(word)}\b")
        else:
            splitters.append(re.escape(word))
    chunks = re.split(rf"(?:{'|'.join(splitters)})+", text) if splitters else [text]
    out: list[str] = []
    for chunk in chunks:
        parts = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}", chunk)
        for part in parts:
            key = part.strip().lower()
            if not key or key in _STOPWORDS or key in {x.lower() for x in out}:
                continue
            out.append(part)
    for match in _HIGH_STAKES_RE.finditer(text):
        word = (match.group(0) or "").strip()
        if word and word not in out and word.lower() not in {x.lower() for x in out}:
            out.append(word)
    return out


def high_stakes_goal(natural_language: str) -> bool:
    return bool(_HIGH_STAKES_RE.search(natural_language or ""))


def page_has_goal_token(elements_text: str, tokens: list[str]) -> bool:
    raw = elements_text or ""
    blob = raw.lower()
    try:
        data = json.loads(raw)
        blob = f"{blob}\n{json.dumps(data, ensure_ascii=False).lower()}"
    except (TypeError, ValueError):
        pass
    for token in tokens:
        if token and token.lower() in blob:
            return True
    return False
