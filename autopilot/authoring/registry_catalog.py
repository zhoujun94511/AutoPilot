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
    for kid, meta in sorted(catalog.by_id.items(), key=lambda x: x[0]):
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
