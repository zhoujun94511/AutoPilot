"""导出 LLM 可用的关键字白名单目录。"""

from __future__ import annotations

from typing import Any

from ..intent.risk import risk_level
from ..metadata.keyword_meta import load_catalog
from ..metadata.keyword_platforms import platform_mismatch_reason, target_platforms
from .contract import (
    PLATFORM_KEYWORD_PREFIXES,
    AuthoringError,
    is_authoring_blocked_keyword,
)

_MOBILE_NAVIGATION_KEYWORDS = frozenset({
    "mobile_app_start",
    "mobile_element_click",
    "mobile_element_text_input",
    "mobile_element_text_clear",
    "mobile_presskey",
    "mobile_swipe_direction",
    "mobile_slip_for_element",
    "mobile_wait_element_visible",
    "mobile_verify_element_existed",
    "mobile_verify_element_visible",
    "mobile_verify_element_text",
})
_WEB_NAVIGATION_KEYWORDS = frozenset({
    "web_browser_open",
    "web_browser_locate",
    "web_browser_back",
    "web_browser_scroll_vertical_bar",
    "web_browser_wait_for_exist",
    "web_browser_wait_for_visible",
    "web_element_click",
    "web_element_text_input",
    "web_verify_element_existed",
    "web_verify_element_visible",
    "web_verify_element_text",
})
_HTTP_CORE_KEYWORDS = frozenset({
    "http_session_begin",
    "http_session_end",
    "http_get",
    "http_post",
    "http_put",
    "http_patch",
    "http_head",
    "http_options",
    "http_set_auth_bearer",
    "http_set_auth_basic",
    "http_set_auth_apikey",
    "http_assert_status",
    "http_assert_time_lt",
    "http_assert_body_contains",
    "json_assert_schema",
    "api_env_use",
})


def _looks_relevant(kid: str, platform: str) -> bool:
    prefixes = PLATFORM_KEYWORD_PREFIXES.get(platform, ())
    if any(kid.startswith(p) for p in prefixes):
        return True
    # 无前缀但仍属该平台的关键字（靠 platforms 元数据）
    return False


def build_keyword_catalog(
    platform: str,
    *,
    max_items: int = 80,
) -> list[dict[str, Any]]:
    """返回精简关键字 schema，供 prompt / 校验。

    过滤：平台不匹配、unsupported、irreversible、Data/SSH 黑名单（AUD-2026-15）。
    """
    plat = (platform or "").strip().lower()
    if plat not in ("android", "ios", "web", "http"):
        raise AuthoringError(f"catalog 仅支持 android/ios/web/http，收到 {platform!r}")

    catalog = load_catalog()
    out: list[dict[str, Any]] = []

    def _sort_key(item: tuple[str, Any]) -> tuple[int, str]:
        sort_kid = item[0]
        pinned = (
            plat in ("android", "ios")
            and sort_kid in _MOBILE_NAVIGATION_KEYWORDS
        ) or (plat == "web" and sort_kid in _WEB_NAVIGATION_KEYWORDS) or (
            plat == "http" and sort_kid in _HTTP_CORE_KEYWORDS
        )
        return 0 if pinned else 1, sort_kid

    for kid, meta in sorted(catalog.by_id.items(), key=_sort_key):
        if is_authoring_blocked_keyword(kid):
            continue
        if getattr(meta, "unsupported", False):
            continue
        if risk_level(kid) == "irreversible":
            continue
        if platform_mismatch_reason(plat, meta):
            continue
        allowed = target_platforms(meta)
        if allowed and plat not in allowed:
            continue
        if not allowed and not _looks_relevant(kid, plat):
            # Http/Public 等任意平台：仅保留短名单公共项
            if not kid.startswith(("public_", "common_", "log_", "sleep", "wait_")):
                continue
        params = []
        for p in getattr(meta, "params", None) or []:
            params.append(
                {
                    "id": getattr(p, "id", "") or getattr(p, "param_id", "") or "",
                    "name": getattr(p, "name", "") or "",
                    "required": bool(getattr(p, "required", False)),
                    "default": getattr(p, "default", "") or "",
                }
            )
        out.append(
            {
                "id": kid,
                "name": getattr(meta, "name", "") or kid,
                "category": getattr(meta, "category", "") or "",
                "params": params[:12],
            }
        )
        if len(out) >= max_items:
            break
    return out


def allowed_keyword_ids(platform: str) -> frozenset[str]:
    return frozenset(item["id"] for item in build_keyword_catalog(platform))
