"""Platform 基址解析（IDE / Runner bootstrap 层）。

有效 URL 由 ``mc_server_url()`` / ``platform_base_url()`` 统一给出。

优先级（``include_settings=True`` 时）：
  1. 企业部署 ``AUTOPILOT_PLATFORM_URL`` / ``platform.url``（默认锁定）
  2. ``settings.json`` → ``mc_server_url``
  3. ``MC_SERVER`` / ``MC_PLATFORM_URL``
  4. ``MC_HOST`` + ``MC_PORT`` → ``http://127.0.0.1:8000``
"""

from __future__ import annotations

import os

from .platform_deploy import allow_user_platform_url_override, deploy_platform_url


def _loopback_host(host: str) -> str:
    h = (host or "127.0.0.1").strip() or "127.0.0.1"
    if h in ("0.0.0.0", "::"):
        return "127.0.0.1"
    return h


def platform_port() -> int:
    raw = (os.environ.get("MC_PORT", "8000") or "8000").strip()
    try:
        return int(raw)
    except ValueError:
        return 8000


def _settings_server_url() -> str:
    from . import settings

    return settings.mc_server_url_stored()


def platform_base_url(*, include_settings: bool = True) -> str:
    deploy = deploy_platform_url()
    if deploy and not allow_user_platform_url_override():
        return deploy

    if include_settings:
        stored = _settings_server_url()
        if stored:
            return stored

    if deploy:
        return deploy

    for key in ("MC_SERVER", "MC_PLATFORM_URL"):
        raw = (os.environ.get(key) or "").strip().rstrip("/")
        if raw:
            return raw

    host = _loopback_host(os.environ.get("MC_HOST", "127.0.0.1"))
    return f"http://{host}:{platform_port()}"
