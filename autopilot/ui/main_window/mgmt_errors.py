"""管理台 Mixin 共享异常元组（AUD-2026-17：避免 session/delivery 循环导入）。"""

from __future__ import annotations

from ...mgmt import MgmtClientError


def build_session_errs() -> tuple[type[BaseException], ...]:

    errs: tuple[type[BaseException], ...] = (
        MgmtClientError,
        OSError,
        RuntimeError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
    )
    try:
        import httpx  # 延迟：httpx 未装时仍可识别本机异常

        return *errs, httpx.HTTPError
    except ImportError:
        return errs


SESSION_ERRS = build_session_errs()
