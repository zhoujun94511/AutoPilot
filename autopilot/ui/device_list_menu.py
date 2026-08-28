"""已连接设备枢纽菜单：每台设备设检视 / 看信息 / 开镜像。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from PyQt6.QtWidgets import QMenu, QWidget


@dataclass(frozen=True)
class ConnectedDevice:
    """一台已连接真机。"""

    platform: str   # Android | iOS
    udid: str

    @property
    def label(self) -> str:
        return f"{self.platform} · {self.udid}"


def list_connected_devices(android: list[str] | None,
                           ios: list[str] | None) -> list[ConnectedDevice]:
    """从监控列表生成有序设备项（Android 在前）。"""
    out: list[ConnectedDevice] = []
    for u in android or []:
        u = str(u).strip()
        if u:
            out.append(ConnectedDevice("Android", u))
    for u in ios or []:
        u = str(u).strip()
        if u:
            out.append(ConnectedDevice("iOS", u))
    return out


def is_current_inspect_target(
    device: ConnectedDevice, *,
    inspect_chosen: bool, inspect_platform: str, inspect_udid: str,
) -> bool:
    if not inspect_chosen:
        return False
    plat = (inspect_platform or "").strip()
    udid = (inspect_udid or "").strip()
    return plat == device.platform and udid == device.udid


def build_connected_devices_menu(
    parent: Optional[QWidget],
    devices: list[ConnectedDevice],
    *,
    inspect_chosen: bool = False,
    inspect_platform: str = "",
    inspect_udid: str = "",
    on_set_inspect: Optional[Callable[[ConnectedDevice], None]] = None,
    on_show_info: Optional[Callable[[ConnectedDevice], None]] = None,
    on_start_mirror: Optional[Callable[[ConnectedDevice], None]] = None,
) -> QMenu:
    """构建「已连接设备」枢纽弹出菜单。

    每台真机：设为检视目标 / 查看设备信息 / 开始实时镜像。
    """
    menu = QMenu("已连接设备", parent)
    if not devices:
        empty = menu.addAction("（当前无已连接设备）")
        empty.setEnabled(False)
    else:
        for dev in devices:
            current = is_current_inspect_target(
                dev, inspect_chosen=inspect_chosen,
                inspect_platform=inspect_platform, inspect_udid=inspect_udid)
            title = f"{'✓ ' if current else ''}{dev.label}"
            sub = menu.addMenu(title)
            act_set = sub.addAction("设为检视目标")
            if current:
                act_set.setEnabled(False)
            if on_set_inspect is not None:
                # noinspection PyUnresolvedReferences
                act_set.triggered.connect(
                    lambda _=False, d=dev: on_set_inspect(d))
            act_info = sub.addAction("查看设备信息")
            if on_show_info is not None:
                # noinspection PyUnresolvedReferences
                act_info.triggered.connect(
                    lambda _=False, d=dev: on_show_info(d))
            act_mirror = sub.addAction("开始实时镜像")
            if on_start_mirror is not None:
                # noinspection PyUnresolvedReferences
                act_mirror.triggered.connect(
                    lambda _=False, d=dev: on_start_mirror(d))

    return menu
