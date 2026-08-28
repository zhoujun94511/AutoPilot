"""编写入口的平台判定（对话框 / NL / 工程默认共用）。"""

from __future__ import annotations

from typing import Any

from ..ui.platform_labels import normalize_ui_platform
from .contract import AuthoringError

#: URL 形态更像接口而非页面时走 http，避免「有 http(s) 就当 web」
_API_URL_MARKS = (
    "/api/",
    "/api?",
    "/apis/",
    "/openapi",
    "/swagger",
    "/graphql",
    "://api.",
    "://api-",
)


def infer_platform_from_url(url: str) -> str:
    """有 URL 但未写平台时：API 形态 → http，否则 web。"""
    raw = (url or "").strip().lower()
    if not raw:
        return ""
    if any(mark in raw for mark in _API_URL_MARKS):
        return "http"
    return "web"


def inspect_platform_from_ctx(ctx: Any) -> str:
    if ctx is None or not hasattr(ctx, "get_var"):
        return ""
    raw = str(
        ctx.get_var("__inspect_platform__") or ctx.get_var("__current_platform__") or ""
    ).strip()
    return normalize_ui_platform(raw)


def resolve_authoring_platform(
    *,
    explicit: str = "",
    hints_platform: str = "",
    start_url: str = "",
    inspect_platform: str = "",
    project_platform: str = "",
) -> str:
    """显式选择 → NL 线索 → URL 推断 → 检视器 → 工程默认。

    工程默认 http 时，普通页面 URL 不抢成 web。
    """
    plat = normalize_ui_platform(explicit)
    if explicit and explicit.strip().lower() not in ("", "auto") and plat:
        return plat
    plat = normalize_ui_platform(hints_platform)
    url_plat = infer_platform_from_url(start_url)
    proj = normalize_ui_platform(project_platform)
    # 工程默认 http：页面 URL 推出的 web（含 merge_nl_hints 回填）不抢平台
    if proj == "http" and url_plat == "web" and plat in ("", "web"):
        return "http"
    if plat:
        return plat
    if url_plat:
        return url_plat
    insp = normalize_ui_platform(inspect_platform)
    if insp:
        return insp
    if proj:
        return proj
    raise AuthoringError(
        "未能识别平台：请在下拉框选择 iOS / Android / Web / HTTP，"
        "或在描述中写明（接口可写「接口测试」；Web 可填起始 URL）。"
    )
