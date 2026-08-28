"""设备插拔动态监测：后台轮询 Android(adb) + iOS(usbmux)，变化时发信号。

轻量、best-effort：工具缺失/出错只当「无设备」，不抛、不刷屏。仅在设备集合变化时发信号。
"""

from __future__ import annotations

import sys

from PyQt6.QtCore import QThread, pyqtSignal


def parse_adb_states(text: str) -> list:
    """解析 `adb devices` 输出为 [(serial, state), …]（纯函数、可测）。

    state 常见：device(就绪) / offline(掉线) / unauthorized(未授权) / no permissions 等。"""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices"):
            continue
        parts = line.split("\t") if "\t" in line else line.split()
        if len(parts) >= 2:
            out.append((parts[0], parts[1]))
    return out


def parse_adb_devices(text: str) -> list[str]:
    """取已授权(device 状态)的序列号——只有这些才能真正检视/镜像（纯函数、可测）。"""
    return [s for s, st in parse_adb_states(text) if st == "device"]


def parse_pmd3_usbmux(stdout: str) -> list[str]:
    """解析 `pymobiledevice3 usbmux list` 的 JSON，取设备 UDID（纯函数、可测）。"""
    from ..mobile.ios_devices import parse_usbmux_list

    return [d.udid for d in parse_usbmux_list(stdout or "")]


class DeviceMonitor(QThread):
    changed = pyqtSignal(list, list)   # (android 序列号列表, iOS UDID 列表)

    def __init__(self, interval: float = 3.0, parent=None) -> None:
        super().__init__(parent)
        self.interval = interval
        self._stop = False
        self._last = None

    def run(self) -> None:
        while not self._stop:
            snap = (tuple(self._android()), tuple(self._ios()))
            if snap != self._last:
                self._last = snap
                # noinspection PyUnresolvedReferences
                self.changed.emit(list(snap[0]), list(snap[1]))
            for _ in range(max(1, int(self.interval * 10))):
                if self._stop:
                    return
                self.msleep(100)

    def stop(self) -> None:
        self._stop = True
        self.wait(2500)

    def _android(self) -> list[str]:
        # noinspection PyBroadException
        try:
            from ..mobile import adb
            exe = adb.ensure_adb()
            if not exe:
                return []
            states = parse_adb_states(adb.run_adb(["devices"]))
            self._diagnose_android(states, adb)        # offline/unauthorized → 提示 + 自动重连
            return [s for s, st in states if st == "device"]
        except Exception:
            return []

    def _diagnose_android(self, states: list, adb) -> None:
        """已插上但非 device 态(offline/unauthorized)的设备：别静默当「无」，给可操作提示；
        offline 多为 USB/驱动抖动 → 自动 `adb reconnect offline` 尝试恢复。仅在异常集变化时动作。"""
        problems = sorted((s, st) for s, st in states if st != "device")
        if problems == getattr(self, "_last_adb_problems", None):
            return                                     # 状态没变，不重复提示/重连（防刷屏）
        self._last_adb_problems = problems
        if not problems:
            return
        from ..runtime.log import get_logger
        log = get_logger("设备")
        offline = [s for s, st in problems if st == "offline"]
        unauth = [s for s, st in problems if st in ("unauthorized", "no permissions")]
        if offline:
            log.warning("检测到 Android 设备掉线(offline)：%s —— 正在尝试 adb reconnect 自动恢复，"
                        "若无效请重插 USB", offline)
            # noinspection PyBroadException
            try:
                adb.run_adb(["reconnect", "offline"])
            except Exception:
                pass
        if unauth:
            log.warning("检测到 Android 设备未授权(unauthorized)：%s —— 请在手机上确认"
                        "「允许 USB 调试」弹窗（可勾选始终允许）", unauth)

    @staticmethod
    def list_ios() -> list[str]:
        """公开的 iOS UDID 列举(供工具/外部调用，避免触碰内部 _ios)。"""
        return DeviceMonitor._ios()

    @staticmethod
    def _ios() -> list[str]:
        """优先进程内 usbmux 列举（快、零 spawn）；不可用才回退子进程。

        原先每 3s spawn 一个 `python -m pymobiledevice3`，冷启动常 >8s 超时 → iOS 恒为空。
        进程内 list_devices 仅首次 import 有成本，之后毫秒级。"""
        devs = DeviceMonitor._ios_inproc()
        if devs is not None:
            return devs
        # noinspection PyBroadException
        try:
            from ..runtime.subproc import run as _run

            r = _run([sys.executable, "-m", "pymobiledevice3", "usbmux", "list"],
                     capture_output=True, timeout=15)
            return parse_pmd3_usbmux((r.stdout or b"").decode("utf-8", "replace"))
        except Exception:
            return []

    @staticmethod
    def _ios_inproc():
        """进程内 pymobiledevice3 列举 UDID；不可用返回 None（区别于「空列表=无设备」）。"""
        # noinspection PyBroadException
        try:
            import asyncio
            from pymobiledevice3.usbmux import list_devices
            res = list_devices()
            if asyncio.iscoroutine(res):
                res = asyncio.run(res)        # 该版本 list_devices 是协程
            out, seen = [], set()
            for d in res or []:
                uid = getattr(d, "serial", None) or getattr(d, "udid", None)
                if uid and uid not in seen:
                    seen.add(uid)
                    out.append(uid)
            return out
        except Exception:
            return None
