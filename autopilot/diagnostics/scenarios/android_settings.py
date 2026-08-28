"""Android Settings 内置冒烟场景。

用于无需业务 APK 的生成→转化→真机诊断，不是通用目标 App 默认值。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, replace

from ...mgmt.target_app import (
    TargetAppParams,
    acquire_target_app,
    android_adb_soft,
)


@dataclass(frozen=True)
class AndroidSettingsScenario:
    name: str = "android_settings"
    description: str = "系统设置首页 Wi-Fi/WLAN 可见性冒烟诊断"

    @staticmethod
    def requirement() -> str:
        return (
            "在 Android 真机上打开系统设置应用，确认首页存在 Wi-Fi 或 WLAN 入口文案。"
            "只需 1 条用例：打开设置后断言 Wi-Fi/WLAN 可见。"
        )

    @staticmethod
    def _resolve_component(udid: str) -> tuple[str, str]:
        """通过 SETTINGS intent 解析真实包名/Activity（适配 MIUI 等）。"""
        android_adb_soft(
            [
                "shell",
                "am",
                "start",
                "-a",
                "android.settings.SETTINGS",
                "-f",
                "0x10008000",
            ],
            udid=udid,
        )
        time.sleep(0.8)
        dump = android_adb_soft(
            ["shell", "dumpsys", "window"], udid=udid, timeout=40
        )
        match = re.search(
            r"mCurrentFocus=Window\{[^}]*\s([^\s/]+)/([^\s}]+)", dump or ""
        )
        if not match:
            dump = android_adb_soft(
                ["shell", "dumpsys", "activity", "activities"],
                udid=udid,
                timeout=40,
            )
            match = re.search(
                r"(?:mResumedActivity|topResumedActivity).*?\s"
                r"([^\s/]+)/([^\s}]+)",
                dump or "",
            )
        if match:
            return match.group(1).strip(), match.group(2).strip()
        return "com.android.settings", ""

    def acquire_target_app(self, *, udid: str = "") -> TargetAppParams:
        serial = (udid or "").strip()
        package_name = "com.android.settings"
        activity = ""
        source_suffix = ""

        if serial:
            package_name, activity = self._resolve_component(serial)
            source_suffix = "+settings-intent"

        target = acquire_target_app(
            udid=serial,
            package_name=package_name,
            platform="android",
            app_label="Settings",
            main_activity=activity,
            verify_installed=bool(serial),
        )
        return replace(
            target,
            source=f"diagnostic:{self.name}{source_suffix}",
            scenario=self.name,
        )

    @staticmethod
    def resolve_assert_target(*, udid: str = "") -> str:
        """根据 Settings 页面文案解析 Wi-Fi / WLAN 本地化名称。"""
        serial = (udid or "").strip()
        if not serial:
            return "Wi-Fi"
        try:
            android_adb_soft(
                [
                    "shell",
                    "am",
                    "start",
                    "-a",
                    "android.settings.SETTINGS",
                    "-f",
                    "0x10008000",
                ],
                udid=serial,
            )
            android_adb_soft(
                ["shell", "uiautomator", "dump", "/sdcard/ap_target.xml"],
                udid=serial,
            )
            xml = android_adb_soft(
                ["shell", "cat", "/sdcard/ap_target.xml"],
                udid=serial,
            )
        except (RuntimeError, OSError, TypeError, ValueError):
            return "Wi-Fi"
        if "WLAN" in xml and "Wi-Fi" not in xml:
            return "WLAN"
        if "无线局域网" in xml:
            return "无线局域网"
        return "Wi-Fi"


ANDROID_SETTINGS_SCENARIO = AndroidSettingsScenario()
