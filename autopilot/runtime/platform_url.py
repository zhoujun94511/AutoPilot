"""Platform 基址解析（IDE / Runner bootstrap 层）。

有效 URL 由 ``mc_server_url()`` / ``platform_base_url()`` 统一给出。

优先级（``include_settings=True`` 时）：
  1. 企业部署 ``AUTOPILOT_PLATFORM_URL`` / ``platform.url``（默认锁定）
  2. ``settings.json`` → ``mc_server_url``
  3. ``MC_SERVER`` / ``MC_PLATFORM_URL``
  4. ``MC_HOST`` + ``MC_PORT``。``0.0.0.0`` 换成本机局域网 IP，没有则 ``127.0.0.1``
"""

from __future__ import annotations

import os
import socket

from .platform_deploy import allow_user_platform_url_override, deploy_platform_url


def local_lan_ip() -> str | None:
    """本机对外的局域网 IPv4。取不到时返回 None。"""
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
    except OSError:
        return None
    finally:
        if sock is not None:
            sock.close()
    if not ip or ip.startswith("127."):
        return None
    return ip


def _advertise_host(host: str) -> str:
    """监听地址换成客户端能访问的地址。``0.0.0.0`` 不是合法访问主机。"""
    h = (host or "127.0.0.1").strip() or "127.0.0.1"
    if h in ("0.0.0.0", "::", "[::]"):
        return local_lan_ip() or "127.0.0.1"
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

    host = _advertise_host(os.environ.get("MC_HOST", "127.0.0.1"))
    return f"http://{host}:{platform_port()}"


def _production_env() -> bool:
    return os.environ.get("MC_ENV", "").strip().lower() in ("prod", "production")


def align_dev_platform_url() -> str | None:
    """调试时临时采用当天的局域网地址，只放进本进程环境变量，不写配置文件。

    生产（``MC_ENV=production``）直接跳过，地址用域名。
    ``AUTOPILOT_PLATFORM_LAN=0`` 关闭。已设置 ``AUTOPILOT_PLATFORM_URL`` /
    ``MC_SERVER`` / ``MC_PLATFORM_URL`` 时不覆盖。settings.json 里的地址仍优先。
    """
    if _production_env():
        return None
    if os.environ.get("AUTOPILOT_PLATFORM_LAN", "1").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return None
    if any(
        (os.environ.get(key) or "").strip()
        for key in ("AUTOPILOT_PLATFORM_URL", "MC_SERVER", "MC_PLATFORM_URL")
    ):
        return None
    ip = local_lan_ip()
    if not ip:
        return None
    port = platform_port()
    try:
        with socket.create_connection((ip, port), timeout=0.35):
            pass
    except OSError:
        return None
    url = f"http://{ip}:{port}"
    os.environ["MC_PLATFORM_URL"] = url
    return url
