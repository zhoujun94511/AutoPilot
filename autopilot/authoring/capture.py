"""从当前会话采集精简 UI 树（Android / iOS / Web）。"""

from __future__ import annotations

import json
import time
from typing import Any

from ..intent.context_budget import serialize_elements
from ..intent.ui_context import collect_ui_elements, driver_from_ctx
from .contract import AuthoringError, normalize_platform


def capture_ui_context(
    ctx: Any,
    platform: str,
    *,
    max_elements: int = 50,
    max_chars: int = 12000,
) -> dict[str, Any]:
    """返回 ``{platform, elements_text, element_count, elements, screen}``。

    ``elements_text`` 始终是合法 JSON：先按元素优先级裁剪，再序列化，
    避免字符级截断把 JSON 切成半截喂给模型。
    """
    plat = normalize_platform(platform)
    elements = collect_ui_elements(ctx, platform=plat)
    if not elements:
        raise AuthoringError("当前会话未采到可交互控件，请先连接检视器或打开目标页")
    trimmed = _trim_elements_for_budget(elements, max_elements=max_elements, max_chars=max_chars)
    compact = serialize_elements(trimmed, mode="compact")
    text = json.dumps(compact, ensure_ascii=False)
    return {
        "platform": plat,
        "elements_text": text,
        "element_count": len(elements),
        "elements": trimmed,
        "screen": _screen_size(ctx, elements),
    }


def _trim_elements_for_budget(
    elements: list[dict[str, Any]],
    *,
    max_elements: int,
    max_chars: int,
) -> list[dict[str, Any]]:
    """按优先级保留元素，保证序列化后不超过 ``max_chars``。"""
    ranked = sorted(elements, key=_element_priority, reverse=True)
    kept: list[dict[str, Any]] = []
    for el in ranked:
        if len(kept) >= max(1, max_elements):
            break
        candidate = kept + [el]
        text = json.dumps(serialize_elements(candidate, mode="compact"), ensure_ascii=False)
        if kept and len(text) > max_chars:
            break
        kept.append(el)
    # 保持原始阅读顺序，方便模型结合坐标理解布局
    order = {id(el): i for i, el in enumerate(elements)}
    kept.sort(key=lambda e: order.get(id(e), 0))
    return kept


def _element_priority(el: dict[str, Any]) -> int:
    score = 0
    if el.get("editable") in (True, "true", "True", 1, "1"):
        score += 40
    if el.get("clickable") in (True, "true", "True", 1, "1"):
        score += 20
    text = str(
        el.get("text")
        or el.get("label")
        or el.get("name")
        or el.get("placeholder")
        or el.get("content_desc")
        or ""
    ).strip()
    if text:
        score += 10
    if el.get("locators"):
        score += 5
    return score


def _screen_size(ctx: Any, elements: list[dict[str, Any]]) -> str:
    """``宽x高``：优先 driver 窗口尺寸，其次控件包络。

    借鉴 Appium Inspector：屏幕尺寸来自会话，不猜最大控件。
    """
    from_driver = _window_size_from_driver(ctx)
    if from_driver:
        return from_driver
    return _bounds_envelope(elements)


def _window_size_from_driver(ctx: Any) -> str:
    drv = driver_from_ctx(ctx)
    if drv is None:
        return ""
    try:
        size = drv.get_window_size()
    except (AttributeError, TypeError, RuntimeError, OSError):
        return ""
    if not isinstance(size, dict):
        return ""
    try:
        w = int(size.get("width") or 0)
        h = int(size.get("height") or 0)
    except (TypeError, ValueError):
        return ""
    if w > 0 and h > 0:
        return f"{w}x{h}"
    return ""


def _bounds_envelope(elements: list[dict[str, Any]]) -> str:
    max_r = 0
    max_b = 0
    for el in elements:
        rect = el.get("bounds") or el.get("rect")
        if not isinstance(rect, (list, tuple)) or len(rect) < 4:
            continue
        try:
            x, y, w, h = int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])
        except (TypeError, ValueError):
            continue
        max_r = max(max_r, x + w)
        max_b = max(max_b, y + h)
    if max_r > 0 and max_b > 0:
        return f"{max_r}x{max_b}"
    return ""


#: 稳定等待：动态条件为主，固定下限只作兜底（可被调用方覆盖）
DEFAULT_SETTLE_MIN_WAIT = 1.5
DEFAULT_SETTLE_TIMEOUT = 12.0
DEFAULT_SETTLE_STABLE_ROUNDS = 2


def capture_settled_ui_context(
    ctx: Any,
    platform: str,
    *,
    max_elements: int = 50,
    min_wait: float = DEFAULT_SETTLE_MIN_WAIT,
    timeout: float = DEFAULT_SETTLE_TIMEOUT,
    interval: float = 1.0,
    stable_rounds: int = DEFAULT_SETTLE_STABLE_ROUNDS,
) -> dict[str, Any]:
    """等页面稳定后再采页。

    借鉴 Midscene observe：以「连续若干次签名一致」为稳定条件，
    ``min_wait`` 只防止瞬时闪屏被当成终态；超时返回最后一次采页，不中断编写。
    """
    start = time.monotonic()
    deadline = start + max(0.0, timeout)
    last: dict[str, Any] = {}
    last_sig = ""
    same_count = 0
    need = max(1, int(stable_rounds))
    while time.monotonic() < deadline:
        try:
            cap = capture_ui_context(ctx, platform, max_elements=max_elements)
        except AuthoringError:
            if last:
                return last
            time.sleep(interval)
            continue
        sig = f"{cap.get('element_count')}|{cap.get('elements_text')}"
        same_count = same_count + 1 if sig == last_sig else 0
        last, last_sig = cap, sig
        if same_count >= need and time.monotonic() - start >= min_wait:
            return cap
        time.sleep(interval)
    if last:
        return last
    # 整个等待窗口内一次都没采到控件：把原始错误抛给调用方
    return capture_ui_context(ctx, platform, max_elements=max_elements)
