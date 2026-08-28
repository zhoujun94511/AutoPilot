"""设备在线状态与移动检视/镜像目标校验（纯逻辑，无 Qt）。

与 device_select（多设备弹选规则）分工：
  - device_select   → 交互选哪一台
  - device_readiness → 有没有机、目标是否合法、文案与 UDID 补齐

GUI 层（DeviceMixin）只负责读 _devices、写状态、弹窗/日志；规则集中在本模块便于单测与复用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Validation = tuple[bool, str]

PlatformUI = Literal["Android", "iOS", "Web"]


def normalize_platform_ui(plat: str) -> str:
    """统一 UI 层平台名：Android | iOS | Web | 原样。"""
    p = (plat or "").strip()
    low = p.lower()
    if low == "android":
        return "Android"
    if low == "ios":
        return "iOS"
    if low == "web":
        return "Web"
    return p


@dataclass(frozen=True)
class DeviceLists:
    """当前监控到的真机列表（不可变快照）。"""

    android: tuple[str, ...] = ()
    ios: tuple[str, ...] = ()

    @classmethod
    def from_lists(cls, android, ios) -> DeviceLists:
        return cls(tuple(android or ()), tuple(ios or ()))

    def has_mobile(self) -> bool:
        return bool(self.android or self.ios)

    def count_summary(self) -> tuple[int, int]:
        return len(self.android), len(self.ios)

    def for_platform(self, plat: str) -> list[str]:
        p = normalize_platform_ui(plat)
        if p == "Android":
            return list(self.android)
        if p == "iOS":
            return list(self.ios)
        return []

    @staticmethod
    def alternate_platform(plat: str) -> str:
        return "iOS" if normalize_platform_ui(plat) == "Android" else "Android"


def no_mobile_message(*, for_mirror: bool = False) -> str:
    lines = [
        "当前未检测到已连接的 Android / iOS 真机。",
        "请插入设备并完成 USB 调试授权（Android）或信任此电脑（iOS）。",
    ]
    if for_mirror:
        lines.append("实时镜像仅支持真机，连接设备后再点「▶ 开始」。")
    else:
        lines.append("也可在控件检视器点「🔄 刷新快照」选择 Web，进行浏览器检视。")
    return "\n".join(lines)


def no_device_placeholder(*, for_mirror: bool = False) -> str:
    """设备监控为空时，检视/镜像区占位文案。"""
    base = "未检测到设备\n请插入并授权（USB 调试 / 信任此电脑）"
    if for_mirror:
        return f"{base}\n连接后点 ▶ 开始"
    return f"{base}\n检视器「刷新快照」可选 Web；镜像需真机在线"


def default_inspect_platform_index(devices: DeviceLists) -> int:
    """连接检视设备对话框默认项：无真机→Web(2)；有 Android→0；仅 iOS→1。"""
    a_n, i_n = devices.count_summary()
    if a_n + i_n == 0:
        return 2
    if a_n > 0:
        return 0
    return 1


def resolve_udid(platform: str, udid: str, devices: DeviceLists) -> str:
    """单台在线且 udid 为空时自动补齐；否则返回去空白后的 udid。"""
    plat = normalize_platform_ui(platform)
    if plat not in ("Android", "iOS"):
        return (udid or "").strip()
    current = (udid or "").strip()
    if current:
        return current
    detected = devices.for_platform(plat)
    if len(detected) == 1:
        return detected[0]
    return ""


def validate_mobile_target(
    platform: str,
    udid: str,
    devices: DeviceLists,
) -> Validation:
    """校验 Android/iOS 检视/镜像目标是否可连（不含 Web）。"""
    plat = normalize_platform_ui(platform)
    if plat not in ("Android", "iOS"):
        return False, "未选择移动平台目标，请先连接或选择真机。"
    detected = devices.for_platform(plat)
    resolved = resolve_udid(plat, udid, devices)
    if not detected:
        if not devices.has_mobile():
            return False, no_mobile_message()
        alt = devices.alternate_platform(plat)
        alt_n = len(devices.for_platform(alt))
        extra = f"当前仅有 {alt} 设备在线（{alt_n} 台），请改选 {alt}。" if alt_n else ""
        return False, (
            f"未检测到已连接的 {plat} 设备。{extra}"
            "请插入真机并完成授权，或重新选择检视平台。"
        )
    if resolved and resolved not in detected:
        return False, f"检视目标 {plat} · {resolved} 已不在线，请重新选择设备。"
    if not resolved and len(detected) > 1:
        return False, f"检测到多台 {plat} 设备，请指定具体 UDID。"
    return True, ""


def validate_inspect_target(
    platform: str,
    udid: str,
    devices: DeviceLists,
) -> Validation:
    """校验控件检视目标（含 Web）。"""
    plat = normalize_platform_ui(platform)
    if plat == "Web":
        return True, ""
    if plat not in ("Android", "iOS"):
        return False, "未选择检视平台，请点「刷新快照」或「设备 ▸ 连接检视设备」选择。"
    return validate_mobile_target(plat, udid, devices)


def pick_udid_unavailable_message(platform: str, devices: DeviceLists) -> str:
    """连接检视设备时，选定平台但无在线设备。"""
    plat = normalize_platform_ui(platform)
    alt = devices.alternate_platform(plat)
    alt_list = devices.for_platform(alt)
    if alt_list:
        return (
            f"未检测到已连接的 {plat} 设备。\n"
            f"当前已检测到 {alt} 设备（{len(alt_list)} 台），请改选 {alt}。\n"
            "请插入真机并完成授权后重试。"
        )
    return no_mobile_message()


def mirror_device_gone(
    plat: str,
    mirror_udid: str,
    devices: DeviceLists,
) -> bool:
    """镜像/检视中的设备是否已不在列表（纯逻辑，与 DeviceMixin._mirror_gone 一致）。"""
    p = (plat or "").lower()
    present = list(devices.android) if p.startswith("android") else (
        list(devices.ios) if p == "ios" else [])
    udid = (mirror_udid or "").strip()
    if udid:
        return udid not in present
    return not present


# ---- 运行 / 设备信息（runtime 平台名 android | ios）----


def present_runtime_platforms(devices: DeviceLists) -> set[str]:
    out: set[str] = set()
    if devices.android:
        out.add("android")
    if devices.ios:
        out.add("ios")
    return out


def missing_runtime_platforms(needed: set[str], devices: DeviceLists) -> set[str]:
    """用例需要的平台中，当前未连接真机的子集。"""
    present = present_runtime_platforms(devices)
    return {p for p in needed if p in ("android", "ios") and p not in present}


def auto_run_udid(
    platform_runtime: str,
    devices: DeviceLists,
    *,
    inspect_platform: str = "",
    inspect_udid: str = "",
) -> str | None:
    """运行前自动解析 UDID：无设备→None；复用检视目标；单台→直接用；多台→None（须弹选）。"""
    plat = (platform_runtime or "").strip().lower()
    if plat not in ("android", "ios"):
        return None
    avail = devices.for_platform(plat)
    if not avail:
        return None
    current = (inspect_udid or "").strip()
    if normalize_platform_ui(inspect_platform).lower() == plat and current in avail:
        return current
    if len(avail) == 1:
        return avail[0]
    return None


def no_device_info_message() -> str:
    return (
        "未检测到已连接设备。\n"
        "请插入真机并完成 USB 调试授权（Android）或信任此电脑（iOS）。"
    )


def no_ios_install_message() -> str:
    return "未检测到 iOS 设备。可手动输入 UDID（留空=默认设备）："


def ios_install_pick_status(devices: DeviceLists) -> tuple[str, str]:
    """iOS 装包选设备：单台→('ok', udid)；多台→('multi', '')；无→('manual', '')。"""
    ios = list(devices.ios)
    if len(ios) == 1:
        return "ok", ios[0]
    if len(ios) > 1:
        return "multi", ""
    return "manual", ""
