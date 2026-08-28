"""多 CLI 并行时 iOS 设备 UDID 认领（避免多进程抢同一台真机）。"""

from __future__ import annotations

import atexit
import json
import os
from datetime import datetime
from typing import Any

_REGISTERED_RELEASE: tuple[str, str] | None = None


def lease_root(project_dir: str) -> str:
    return os.path.join(project_dir or os.getcwd(), "logs", "ios_monkey", ".leases")


def _safe_name(udid: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in (udid or ""))


def _lease_path(root: str, udid: str) -> str:
    return os.path.join(root, f"{_safe_name(udid)}.json")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    # 严禁在 Windows 用 os.kill(pid, 0) 探测存活：signal.CTRL_C_EVENT == 0，
    # os.kill(pid, 0) 会被解释为 GenerateConsoleCtrlEvent(CTRL_C_EVENT, pid)，
    # 向进程组发送 Ctrl+C（可中断/误杀同控制台进程，含自身）。用 psutil 跨平台探测。
    try:
        import psutil
        return psutil.pid_exists(pid)
    except (ImportError, OSError):
        pass
    if os.name == "nt":
        import ctypes

        process_query_limited = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(process_query_limited, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_lease(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _is_stale(path: str) -> bool:
    info = _read_lease(path)
    pid = int(info.get("pid") or 0)
    return not _pid_alive(pid)


def _remove_lease(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def purge_stale_leases(project_dir: str) -> int:
    """清理已退出进程留下的 lease 文件，返回清除数量。"""
    root = lease_root(project_dir)
    if not os.path.isdir(root):
        return 0
    removed = 0
    for name in os.listdir(root):
        if not name.endswith(".json"):
            continue
        path = os.path.join(root, name)
        if _is_stale(path):
            _remove_lease(path)
            removed += 1
    return removed


def try_claim_udid(udid: str, project_dir: str, *, pid: int | None = None) -> bool:
    """原子认领 UDID；若已有活跃 lease 则失败。"""
    root = lease_root(project_dir)
    os.makedirs(root, exist_ok=True)
    path = _lease_path(root, udid)
    if os.path.isfile(path):
        if _is_stale(path):
            _remove_lease(path)
        else:
            return False
    meta = {
        "udid": udid,
        "pid": int(pid if pid is not None else os.getpid()),
        "startedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return True


def release_udid(udid: str, project_dir: str) -> None:
    global _REGISTERED_RELEASE
    if not udid:
        return
    path = _lease_path(lease_root(project_dir), udid)
    info = _read_lease(path)
    pid = int(info.get("pid") or 0)
    if info and (pid == os.getpid() or not _pid_alive(pid)):
        _remove_lease(path)
    if _REGISTERED_RELEASE == (udid, project_dir):
        _REGISTERED_RELEASE = None


def register_release_on_exit(udid: str, project_dir: str) -> None:
    """进程正常退出时兜底释放 lease（不含 SIGKILL）。"""
    global _REGISTERED_RELEASE
    if not udid:
        return
    _REGISTERED_RELEASE = (udid, project_dir)

    def _atexit() -> None:
        if _REGISTERED_RELEASE == (udid, project_dir):
            release_udid(udid, project_dir)

    atexit.register(_atexit)


def acquire_udid(
    devices: list[str],
    project_dir: str,
    *,
    explicit: str = "",
    always_lease: bool = False,
) -> tuple[str, bool]:
    """返回 (udid, 是否由本模块认领需在结束时 release)。"""
    udid = (explicit or "").strip()
    if udid:
        return udid, False

    purge_stale_leases(project_dir)
    devs = sorted({d.strip() for d in devices if str(d or "").strip()})
    if not devs:
        return "", False
    if len(devs) == 1 and not always_lease:
        return devs[0], False

    for candidate in devs:
        if try_claim_udid(candidate, project_dir):
            return candidate, True
    return "", False
