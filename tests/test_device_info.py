"""设备信息汇总（离线可测）。"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autopilot.mobile.device_info import collect_android_device_info


def test_android_sheet_offline() -> bool:
    props = {
        "ro.product.marketname": "SM-G9860",
        "ro.product.brand": "samsung",
        "ro.build.version.release": "13",
        "ro.build.version.sdk": "33",
        "ro.soc.manufacturer": "QTI",
        "ro.soc.model": "qcom",
        "ro.product.cpu.abilist": "arm64-v8a,armeabi-v7a",
        "ro.serialno": "R5CN30EQKNM",
        "ro.board.platform": "kona",
    }

    def fake_shell(cmd, _serial="", **_kw):
        if cmd.startswith("getprop "):
            return props.get(cmd.split(" ", 1)[1], "")
        if "wm size" in cmd:
            return "Physical size: 1080x2400"
        if "wm density" in cmd:
            return "Physical density: 450"
        if "wlan0" in cmd:
            return "inet 192.168.0.190/24"
        return ""

    with patch("autopilot.mobile.adb.adb_shell", fake_shell):
        sheet = collect_android_device_info("R5CN30EQKNM")
    data = dict(sheet.rows)
    ok = (
        sheet.platform == "android"
        and data.get("设备品牌") == "samsung"
        and data.get("SDK 版本") == "33"
        and "arm64-v8a" in (data.get("CPU 架构") or "")
        and data.get("IP 地址") == "192.168.0.190"
        and "1080" in (data.get("分辨率") or "")
    )
    print("Android 设备信息(离线):", "✅" if ok else "❌", data)
    return ok


def test_marketing_name() -> bool:
    from autopilot.mobile.ios_marketing import marketing_name
    ok = (
        marketing_name("iPhone17,3") == "iPhone 16"
        and marketing_name("iPhone18,1") == "iPhone 17 Pro"
        and marketing_name("iPhone99,9") == "iPhone99,9"
    )
    print("iOS ProductType 营销名:", "✅" if ok else "❌")
    return ok


def test_ios_get_value_uses_key_kwarg() -> bool:
    """回归：位置参数会进 domain，返回 {}；必须 get_value(key=...)。"""
    import asyncio
    from autopilot.mobile import device_info as di

    class FakeLd:
        @staticmethod
        def get_value(domain=None, key=None):
            if key == "DeviceName":
                return "iPhone"
            if domain == "DeviceName" and key is None:
                return {}
            return None

    async def _run():
        return await di._ios_get_value(FakeLd(), "DeviceName")

    got = asyncio.run(_run())
    ok = got == "iPhone"
    # _disp 也不应把 {} 渲成字面量
    ok = ok and di._disp({}) == "—" and di._disp("") == "—"
    print("iOS get_value(key=):", "✅" if ok else "❌", repr(got))
    return ok


def test_ios_disk_rows_from_domain() -> bool:
    """磁盘键在 com.apple.disk_usage，根域无值；已使用=总量-闲置。"""
    import asyncio
    from autopilot.mobile import device_info as di

    class FakeLd:
        @staticmethod
        def get_value(domain=None, key=None):
            if domain == "com.apple.disk_usage" and key is None:
                return {
                    "TotalDiskCapacity": 256_000_000_000,
                    "TotalDataAvailable": 100_000_000_000,
                    "TotalDataCapacity": 240_000_000_000,
                }
            if domain == "com.apple.disk_usage" and key == "NANDBlockSize":
                return 4096
            if key in ("TotalDiskCapacity", "TotalDataAvailable"):
                raise RuntimeError("MissingValue")
            return None

    async def _run():
        return await di._ios_disk_rows(FakeLd())

    rows = dict(asyncio.run(_run()))
    ok = (
        rows.get("总体空间") == "256.00 GB"
        and rows.get("闲置空间") == "100.00 GB"
        and rows.get("已使用空间") == "156.00 GB"
        and rows.get("存储块规格") == "4096 B"
        and di._fmt_bytes(1_500_000) == "1.50 MB"
    )
    print("iOS 磁盘信息(域):", "✅" if ok else "❌", rows)
    return ok


def main() -> int:
    ok = all([
        test_android_sheet_offline(),
        test_marketing_name(),
        test_ios_get_value_uses_key_kwarg(),
        test_ios_disk_rows_from_domain(),
    ])
    print("\n总结:", "✅" if ok else "❌")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
