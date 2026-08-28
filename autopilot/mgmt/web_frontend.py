"""管理台网页基址：联调与生产只打开同一套前端。

``start_dev.py`` 会拉起 Vite :5173，并把 Platform :8000 的根路径重定向过去。
IDE「打开管理台」若仍打开 :8000 上的 ``dist``，会和 Vite 两套 hashed 资源互相 404。

规则：
- 显式 ``mc_web_url`` 最高优先
- ``AUTOPILOT_MC_DEV_WEB=0`` 强制走 API 同源（生产静态页）
- 本机 API :8000 且 Vite :5173 在听 → 打开 Vite（与浏览器联调同一套）
- ``AUTOPILOT_MC_DEV_WEB=1`` 本机时直接用 :5173（不探测）
"""

from __future__ import annotations

import os
import socket
from collections.abc import Callable
from urllib.parse import urlparse

DEV_VITE_PORT = 5173
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


def _flag_on(raw: str) -> bool:
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _flag_off(raw: str) -> bool:
    return raw.strip().lower() in ("0", "false", "no", "off")


def vite_port_open(host: str, port: int = DEV_VITE_PORT, timeout: float = 0.35) -> bool:
    h = "127.0.0.1" if (host or "").strip() in ("localhost", "::1", "") else host
    try:
        with socket.create_connection((h, port), timeout=timeout):
            return True
    except OSError:
        return False


def resolve_web_frontend_url(
    *,
    api_url: str,
    configured_web: str = "",
    env: dict[str, str] | None = None,
    vite_open: Callable[[str], bool] | None = None,
) -> str:
    configured = (configured_web or "").strip().rstrip("/")
    if configured:
        return configured

    url = (api_url or "http://127.0.0.1:8000").strip().rstrip("/")
    parsed = urlparse(url if "://" in url else f"http://{url}")
    host = (parsed.hostname or "127.0.0.1").strip()
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    scheme = parsed.scheme or "http"
    vite = f"{scheme}://{'127.0.0.1' if host in _LOOPBACK else host}:{DEV_VITE_PORT}"

    environ = env if env is not None else os.environ
    flag = (environ.get("AUTOPILOT_MC_DEV_WEB") or "").strip()
    if _flag_off(flag):
        return url

    loopback_api = host in _LOOPBACK and port == 8000
    if _flag_on(flag) and host in _LOOPBACK:
        return vite
    if not loopback_api:
        return url

    probe = vite_open or vite_port_open
    if probe(host):
        return vite
    return url
