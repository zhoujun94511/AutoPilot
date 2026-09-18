"""IDE 平台选项与展示标签（工程 / 用例 / AI 编写共用）。"""

from __future__ import annotations

from ..runtime.job_platforms import (
    JOB_PLATFORMS,
    PLATFORM_HTTP,
    is_deviceless_platform,
    is_http_platform,
    is_web_platform,
)

# (value, 展示名)；空串 = 通用 / 未指定
PLATFORM_MENU_CHOICES: tuple[tuple[str, str], ...] = (
    ("", "通用"),
    ("android", "Android"),
    ("ios", "iOS"),
    ("web", "Web"),
    ("http", "HTTP / API"),
)

PLATFORM_LABELS: dict[str, str] = {
    "": "通用",
    "android": "Android",
    "ios": "iOS",
    "web": "Web",
    "http": "HTTP / API",
}

SUPPORTED_RUNTIME_PLATFORMS = JOB_PLATFORMS


def platform_label(plat: str) -> str:
    raw = (plat or "").strip().lower()
    return PLATFORM_LABELS.get(raw, plat or "通用")


def normalize_ui_platform(raw: str) -> str:
    p = (raw or "").strip().lower()
    if p in SUPPORTED_RUNTIME_PLATFORMS:
        return p
    if p in ("iphone", "ipad"):
        return "ios"
    if p in ("browser", "w"):
        return "web"
    if p in ("api", "rest"):
        return PLATFORM_HTTP
    return ""


def default_authoring_platform(project_platform: str) -> str:
    """工程默认平台 → 编写弹窗初始选项；无法识别时用自动。"""
    p = normalize_ui_platform(project_platform)
    if p in ("android", "ios", "web", "http"):
        return p
    return "auto"


__all__ = [
    "PLATFORM_MENU_CHOICES",
    "PLATFORM_LABELS",
    "SUPPORTED_RUNTIME_PLATFORMS",
    "platform_label",
    "normalize_ui_platform",
    "default_authoring_platform",
    "is_deviceless_platform",
    "is_http_platform",
    "is_web_platform",
]
