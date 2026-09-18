"""从当前会话采集观察：移动/Web 为 UI 树，HTTP 为最近一次响应。"""

from __future__ import annotations

import json
import time
from typing import Any, Sequence

from ..intent.context_budget import serialize_elements
from ..intent.ui_context import collect_ui_elements, driver_from_ctx
from .app_task import packages_from_elements
from .contract import AuthoringError, normalize_platform
from .locator_cache import page_signature


def capture_ui_context(
    ctx: Any,
    platform: str,
    *,
    max_elements: int = 50,
    max_chars: int = 12000,
    prefer_texts: Sequence[str] | None = None,
) -> dict[str, Any]:
    """返回 ``{platform, elements_text, element_count, elements, screen}``。

    ``elements_text`` 始终是合法 JSON：先按元素优先级裁剪，再序列化，
    避免字符级截断把 JSON 切成半截喂给模型。
    """
    plat = normalize_platform(platform)
    if plat == "http":
        return capture_http_context(ctx, max_chars=max_chars)
    elements = collect_ui_elements(ctx, platform=plat)
    if not elements:
        raise AuthoringError("当前会话未采到可交互控件，请先连接检视器或打开目标页")
    trimmed = _trim_elements_for_budget(
        elements,
        max_elements=max_elements,
        max_chars=max_chars,
        prefer_texts=prefer_texts,
    )
    compact = serialize_elements(trimmed, mode="compact")
    text = json.dumps(compact, ensure_ascii=False)
    return {
        "platform": plat,
        "elements_text": text,
        "element_count": len(elements),
        "elements": trimmed,
        "screen": _screen_size(ctx, elements),
        "packages": list(packages_from_elements(trimmed or elements)),
    }


def _trim_elements_for_budget(
    elements: list[dict[str, Any]],
    *,
    max_elements: int,
    max_chars: int,
    prefer_texts: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """按优先级保留元素，保证序列化后不超过 ``max_chars``。"""
    ranked = sorted(
        elements,
        key=lambda item: _element_priority(item, prefer_texts=prefer_texts),
        reverse=True,
    )
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


def _element_priority(el: dict[str, Any], *, prefer_texts: Sequence[str] | None = None) -> int:
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
    blob = " ".join(
        [
            text,
            str(el.get("resource_id") or el.get("rid") or ""),
            *(str(item) for item in (el.get("locators") or []) if item),
        ]
    ).lower()
    for token in prefer_texts or ():
        tok = str(token or "").strip().lower()
        if tok and tok in blob:
            score += 50
            break
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


_MAX_HTTP_BODY_CHARS = 4000
_MAX_HTTP_HEADER_ITEMS = 12


def capture_http_context(ctx: Any, *, max_chars: int = 12000) -> dict[str, Any]:
    """接口编写的观察：会话是否已开启 + 最近一次 ``ctx.last_http``。

    尚未发请求也是合法观察，不得当成「未采到控件」。
    """
    state = getattr(ctx, "http_session", None) if ctx is not None else None
    last = getattr(ctx, "last_http", None) if ctx is not None else None
    if not isinstance(last, dict):
        last = {}
    body = str(last.get("body") or "")
    if len(body) > _MAX_HTTP_BODY_CHARS:
        body = body[:_MAX_HTTP_BODY_CHARS] + "…"
    raw_headers = last.get("headers") or {}
    headers: dict[str, str] = {}
    if isinstance(raw_headers, dict):
        for index, (key, value) in enumerate(raw_headers.items()):
            if index >= _MAX_HTTP_HEADER_ITEMS:
                break
            headers[str(key)] = str(value)[:200]
    last_request = None
    if last.get("status") not in (None, "") or last.get("url") or last.get("body"):
        last_request = {
            "url": str(last.get("url") or ""),
            "status": last.get("status"),
            "elapsed_ms": last.get("elapsed_ms"),
            "body": body,
            "headers": headers,
        }
    payload = {
        "kind": "http_observation",
        "session": {
            "begun": state is not None,
            "base_url": str(getattr(state, "base_url", "") or ""),
        },
        "last_request": last_request,
    }
    text = json.dumps(payload, ensure_ascii=False)
    if len(text) > max(256, int(max_chars)) and last_request is not None:
        last_request["body"] = str(last_request.get("body") or "")[:800] + "…"
        last_request["headers"] = {}
        payload["last_request"] = last_request
        text = json.dumps(payload, ensure_ascii=False)
    return {
        "platform": "http",
        "elements_text": text,
        "element_count": 1 if last_request else 0,
        "elements": [],
        "screen": "",
        "packages": [],
        "last_http": last_request,
    }


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
    prefer_texts: Sequence[str] | None = None,
) -> dict[str, Any]:
    """等页面稳定后再采页。

    借鉴 Midscene observe：以「连续若干次签名一致」为稳定条件，
    ``min_wait`` 只防止瞬时闪屏被当成终态；超时返回最后一次采页并在
    ``_meta.timed_out`` 标记，由编写器决定是否阻断 transition 结算。
    HTTP 无页面动画，直接采最近一次响应。
    """
    if normalize_platform(platform) == "http":
        cap = capture_http_context(ctx)
        return {**cap, "_meta": {"settled": True, "timed_out": False}}
    start = time.monotonic()
    deadline = start + max(0.0, timeout)
    last: dict[str, Any] = {}
    last_sig = ""
    same_count = 0
    need = max(1, int(stable_rounds))
    while time.monotonic() < deadline:
        try:
            cap = capture_ui_context(
                ctx,
                platform,
                max_elements=max_elements,
                prefer_texts=prefer_texts,
            )
        except AuthoringError:
            time.sleep(interval)
            continue
        sig = page_signature(str(cap.get("elements_text") or "[]"))
        same_count = same_count + 1 if sig == last_sig else 0
        last, last_sig = cap, sig
        if same_count >= need and time.monotonic() - start >= min_wait:
            return {
                **cap,
                "_meta": {"settled": True, "timed_out": False},
            }
        time.sleep(interval)
    if last:
        return {
            **last,
            "_meta": {"settled": False, "timed_out": True},
        }
    # 整个等待窗口内一次都没采到控件：把原始错误抛给调用方
    return capture_ui_context(
        ctx, platform, max_elements=max_elements, prefer_texts=prefer_texts
    )
