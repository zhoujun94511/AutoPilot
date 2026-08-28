"""阶段13.3 跨平台 adb 能力补齐回归（用 fake adb，无需真机）。

验证由内置 adb 实现的 mobile_app_reset_saveinfo / 扩展后的 mobile_get_deviceinfo。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import autopilot.keywords  # noqa: F401
from autopilot.keywords.mobile import session as sess
from autopilot.keywords.mobile import misc
from autopilot.keywords.context import ExecutionContext


def test_app_reset() -> bool:
    calls = []
    orig_shell, orig_serial = sess.adb_shell, sess._serial
    sess.adb_shell = lambda cmd, serial="", timeout=30: calls.append(cmd) or ""
    sess._serial = lambda _c: "DEV1"
    try:
        sess.app_reset_save_info(ExecutionContext(), packageName="com.demo.app")
    finally:
        sess.adb_shell, sess._serial = orig_shell, orig_serial
    ok = (any("force-stop com.demo.app" in c for c in calls)
          and any("monkey -p com.demo.app" in c and "LAUNCHER" in c for c in calls))
    print("app_reset(保留数据,adb force-stop+重启):", "✅" if ok else "❌")
    return ok


def test_deviceinfo_extended() -> bool:
    canned = {
        "wm size": "Physical size: 1080x2400",
        "wm density": "Physical density: 440",
        "getprop ro.product.cpu.abi": "arm64-v8a",
        "getprop ro.build.fingerprint": "brand/x/y:13/abc",
    }
    orig_shell, orig_serial = misc.adb_shell, misc._serial
    misc.adb_shell = lambda cmd, serial="", timeout=30: canned.get(cmd.strip(), "")
    misc._serial = lambda _c: "DEV1"
    try:
        f = misc.get_device_info
        ctx = ExecutionContext()
        res = f(ctx, deviceInfo="resolution", outVar="a")
        den = f(ctx, deviceInfo="density", outVar="b")
        abi = f(ctx, deviceInfo="abi", outVar="c")
        fp = f(ctx, deviceInfo="fingerprint", outVar="d")
    finally:
        misc.adb_shell, misc._serial = orig_shell, orig_serial
    ok = (res == {"a": "1080x2400"} and den == {"b": "440"}
          and abi == {"c": "arm64-v8a"} and fp == {"d": "brand/x/y:13/abc"})
    print("deviceinfo 扩展(分辨率/密度/abi/指纹):", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([test_app_reset(), test_deviceinfo_extended()])
    print("\n总结:", "✅ adb 能力补齐全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
