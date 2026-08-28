"""Android parity 骨架与工具离线回归。"""

from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def test_android_parity_skeleton() -> bool:
    from tests.android_parity_skeleton import (
        infra_parity_case_ids,
        parity_case_ids,
        validate_parity_skeleton,
    )

    infra = infra_parity_case_ids()
    ok = validate_parity_skeleton() and len(parity_case_ids()) >= 3 and len(infra) == 3
    print("android parity skeleton:", "OK" if ok else "FAIL", parity_case_ids())
    return ok


def test_android_env_resolve() -> bool:
    from autopilot.mobile.android_env import resolve_android_sdk_root

    sdk = resolve_android_sdk_root()
    ok = sdk is not None and sdk.is_dir()
    print("android sdk resolve:", "OK" if ok else "SKIP/ FAIL", sdk)
    return ok


def test_android_devices_list_offline() -> bool:
    from autopilot.mobile.android_devices import list_usb_devices

    devs = list_usb_devices()
    ok = isinstance(devs, list)
    print("android list_usb_devices:", "OK" if ok else "FAIL", len(devs), "device(s)")
    return ok


def test_android_parity_run_validate() -> bool:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "tools", "android_parity_run.py")
    proc = subprocess.run(
        [sys.executable, script, "--validate-only"],
        cwd=root, capture_output=True, text=True, timeout=30,
    )
    ok = proc.returncode == 0 and "android parity 骨架" in (proc.stdout + proc.stderr)
    print("android_parity_run --validate-only:", "OK" if ok else f"FAIL rc={proc.returncode}")
    return ok


def main() -> int:
    ok = all([
        test_android_parity_skeleton(),
        test_android_env_resolve(),
        test_android_devices_list_offline(),
        test_android_parity_run_validate(),
    ])
    print("\n总结:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
