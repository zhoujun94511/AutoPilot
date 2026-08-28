"""编写收尾事后裁判：只加注，不改步骤、不改 goal_completed。

默认只在目标未完成时调用一次文本模型；``AUTOPILOT_AUTHORING_GOAL_JUDGE=0`` 关闭。
视觉裁判不得单独把用例改成 PASS/FAIL。
"""

from __future__ import annotations

import os
from typing import Any

from .contract import AuthoringError, GeneratedStep
from .llm_client import ChatFn, complete_json


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
) -> dict[str, Any]:
    """不耗 token 的收尾注记。"""
    notes = [w for w in (warnings or []) if w]
    if goal_completed:
        return {
            "passed": True,
            "reason": "模型宣告目标完成，且已有会话验证步骤",
            "confidence": 0.55,
            "source": "heuristic",
        }
    bits: list[str] = []
    if any("REPEAT_FAILED" in w or "重复操作" in w for w in notes):
        bits.append("重复操作熔断")
    if any("连续" in w and "失败" in w for w in notes):
        bits.append("连续步骤失败")
    if any("回合上限" in w or "步数上限" in w or "AI 调用上限" in w for w in notes):
        bits.append("预算耗尽")
    if not recorded:
        bits.append("无成功步骤")
    reason = "；".join(bits) if bits else "模型未宣告目标完成"
    return {
        "passed": False,
        "reason": reason,
        "confidence": 0.7 if bits else 0.5,
        "source": "heuristic",
    }


def maybe_llm_goal_judge(
    *,
    natural_language: str,
    recorded: list[GeneratedStep],
    goal_completed: bool,
    warnings: list[str],
    chat: ChatFn | None,
) -> dict[str, Any] | None:
    """未完成时可选补一刀文本判定；失败则返回 None，由启发式兜底。"""
    if goal_completed or chat is None or goal_judge_mode() != "llm":
        return None
    steps = [
        {"keyword_id": s.keyword_id, "comment": s.comment, "params": dict(s.params or {})}
        for s in (recorded or [])[:20]
    ]
    prompt = (
        "你是用例编写收尾检查器。根据用户目标和已成功执行的步骤，判断目标是否已被覆盖。\n"
        "只输出 JSON：{\"passed\": bool, \"reason\": \"一句话\", \"confidence\": 0.0到1.0}\n"
        "不要改写步骤。不确定时 passed=false。\n\n"
        f"用户目标：\n{(natural_language or '').strip()}\n\n"
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
) -> dict[str, Any]:
    """返回裁判字典；调用方只写入 warnings / decision_trace，不得据此改 PASS。"""
    if not goal_judge_enabled():
        return {}
    llm = maybe_llm_goal_judge(
        natural_language=natural_language,
        recorded=recorded,
        goal_completed=goal_completed,
        warnings=warnings,
        chat=chat,
    )
    if llm is not None:
        return llm
    return heuristic_goal_judge(
        goal_completed=goal_completed,
        recorded=recorded,
        warnings=warnings,
    )
