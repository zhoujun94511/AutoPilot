"""通用目标应用参数获取。

这里只处理显式目标 App 参数与设备安装信息，不包含产品/系统应用场景。
内置诊断场景位于 :mod:`autopilot.diagnostics.scenarios`。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from ..mobile.adb import run_adb


@dataclass(frozen=True)
class TargetAppParams:
    """转化自动化可用的目标应用参数。"""

    platform: str
    package_name: str
    udid: str = ""
    app_label: str = ""
    main_activity: str = ""
    version_name: str = ""
    source: str = ""  # explicit|explicit+adb
    scenario: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def mobile_start_params(self) -> dict[str, str]:
        plat = (self.platform or "android").strip().lower()
        typ = "Android" if plat == "android" else "iOS"
        out = {"type": typ, "packageName": self.package_name}
        if self.main_activity and plat == "android":
            out["activityName"] = self.main_activity
        return out


def _adb(args: list[str], *, udid: str, timeout: int = 20) -> str:
    return run_adb(args, serial=(udid or "").strip(), timeout=timeout)


def android_adb_soft(args: list[str], *, udid: str, timeout: int = 20) -> str:
    """adb 调用失败时返回空串（探测场景不向上抛）。"""
    import subprocess

    try:
        return _adb(args, udid=udid, timeout=timeout)
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        return ""


def android_package_exists(udid: str, package: str) -> bool:
    """检查 Android 设备是否安装指定包。"""
    out = android_adb_soft(["shell", "pm", "path", package], udid=udid)
    if package in (out or "") and "package:" in (out or ""):
        return True
    out = android_adb_soft(["shell", "pm", "list", "packages", package], udid=udid)
    return f"package:{package}" in (out or "").replace("\r", "")


def android_package_version(udid: str, package: str) -> str:
    """读取 Android 包的 versionName；探测失败返回空串。"""
    out = android_adb_soft(
        ["shell", "dumpsys", "package", package], udid=udid, timeout=40
    )
    m = re.search(r"versionName=(\S+)", out or "")
    return (m.group(1) if m else "").strip()


def acquire_target_app(
    *,
    udid: str = "",
    package_name: str = "",
    platform: str = "android",
    app_label: str = "",
    main_activity: str = "",
    verify_installed: bool = True,
) -> TargetAppParams:
    """获取显式目标 App 参数，并可从 Android 真机补全版本。

    通用 API 不再隐式选择 ``android_settings``。调用方必须提供
    ``package_name``；诊断脚本应通过场景注册表获取预设。
    """
    plat = (platform or "android").strip().lower()
    if plat not in ("android", "ios"):
        raise ValueError(f"不支持的移动平台: {platform!r}")
    pkg = (package_name or "").strip()
    label = (app_label or "").strip()
    serial = (udid or "").strip()

    if not pkg:
        raise ValueError(
            "package_name 不能为空；内置诊断场景请使用 "
            "autopilot.diagnostics.scenarios.get_scenario()"
        )

    version = ""
    verified_by_adb = False
    if serial and plat == "android" and verify_installed:
        if not android_package_exists(serial, pkg):
            raise RuntimeError(f"设备 {serial} 未安装目标包: {pkg}")
        verified_by_adb = True
        version = android_package_version(serial, pkg)

    return TargetAppParams(
        platform=plat,
        package_name=pkg,
        udid=serial,
        app_label=label or pkg,
        main_activity=(main_activity or "").strip(),
        version_name=version,
        source="explicit+adb" if verified_by_adb else "explicit",
        scenario="",
    )
