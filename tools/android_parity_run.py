#!/usr/bin/env python3
"""Android Appium 基础设施 parity 执行器。

离线：--list / --validate-only
真机：需 Appium 4723 + UiAutomator2 驱动 + ANDROID_HOME

用法：
  python tools/android_device_list.py
  python tools/android_parity_run.py --serial <serial> --infra-only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (OSError, ValueError, UnicodeError):
    pass

import autopilot.keywords  # noqa: F401


def _parity_to_testcase(spec: dict):
    from autopilot.model.testcase import TestCase, Step, ParamValue

    steps: list[Step] = [
        Step(keyword_id="appium_start", comment="确保 Appium 就绪"),
    ]
    for raw in spec.get("steps", []):
        params = [
            ParamValue(param_id=k, value=str(v))
            for k, v in (raw.get("params") or {}).items()
        ]
        out_name = raw.get("out", "")
        if out_name:
            params.append(ParamValue(param_id="out", value=str(out_name)))
        steps.append(Step(
            keyword_id=raw["keyword_id"],
            comment=raw.get("comment", ""),
            params=params,
        ))
    tc = TestCase(
        name=spec["name"],
        source_path=f"<parity:{spec['name']}>",
        platform="android",
    )
    tc.case.steps = steps
    return tc


def run_parity(*, serial: str, case_ids: list[str], stop_on_fail: bool = False) -> dict:
    from tests.android_parity_skeleton import PARITY_CASES
    from autopilot.engine import run_suite, FaultStrategy
    from autopilot.mobile.android_env import apply_android_env

    apply_android_env()
    selected = {c["name"]: c for c in PARITY_CASES}
    cases = [_parity_to_testcase(selected[i]) for i in case_ids]
    base_vars = {
        "__device_udid__": serial,
        "__current_platform__": "android",
        "__appium_caps__": {
            "noReset": True,
            "newCommandTimeout": 180,
            "uiautomator2ServerInstallTimeout": 180000,
            "uiautomator2ServerLaunchTimeout": 120000,
            "adbExecTimeout": 120000,
            "ignoreHiddenApiPolicyError": True,
            "skipDeviceInitialization": False,
        },
    }
    t0 = time.monotonic()
    suite = run_suite(
        cases,
        name="Android-parity",
        platform="android",
        fault_strategy=FaultStrategy.STOP if stop_on_fail else FaultStrategy.CONTINUE,
        base_vars=base_vars,
    )
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    c = suite.case_counts()
    case_rows = []
    for cr in suite.results:
        case_rows.append({
            "name": cr.case_name,
            "passed": cr.passed,
            "duration_ms": cr.duration_ms,
            "steps": [
                {
                    "keyword_id": sr.keyword_id,
                    "status": sr.status,
                    "message": (sr.message or "")[:500],
                }
                for sr in cr.results
            ],
        })
    return {
        "serial": serial,
        "backend_mode": "appium",
        "case_ids": case_ids,
        "passed": c["passed"],
        "total": c["total"],
        "failed": c["failed"],
        "duration_ms": elapsed_ms,
        "ok": c["failed"] == 0,
        "cases": case_rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Android parity 基础设施集")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument("--infra-only", action="store_true", help="仅 infra 用例（默认）")
    ap.add_argument("--all-cases", action="store_true")
    ap.add_argument("--case", action="append", default=[])
    ap.add_argument("--serial", default="", help="adb serial")
    ap.add_argument("--stop-on-fail", action="store_true")
    ap.add_argument("--report", default="")
    ap.add_argument("--host", default="")
    args = ap.parse_args()

    from tests.android_parity_skeleton import (
        PARITY_CASES,
        infra_parity_case_ids,
        parity_case_ids,
        validate_parity_skeleton,
    )
    from autopilot.mobile.android_devices import list_usb_devices
    from autopilot.mobile.android_env import apply_android_env, resolve_android_sdk_root

    if args.list_devices:
        apply_android_env()
        sdk = resolve_android_sdk_root()
        if sdk:
            print(f"ANDROID_SDK_ROOT: {sdk}")
        for d in list_usb_devices():
            print(f"{d.serial}\t{d.label}")
        return 0

    if args.list:
        ids = infra_parity_case_ids() if not args.all_cases else parity_case_ids()
        for cid in ids:
            print(cid)
        return 0

    if args.validate_only:
        ok = validate_parity_skeleton()
        n = len(infra_parity_case_ids())
        print("android parity 骨架:", "OK" if ok else "FAIL",
              f"({len(PARITY_CASES)} cases, infra={n})")
        return 0 if ok else 1

    serial = args.serial.strip() or os.getenv("ANDROID_PARITY_SERIAL", "").strip()
    if not serial:
        apply_android_env()
        devs = list_usb_devices()
        if devs:
            serial = devs[0].serial
    if not serial:
        print("未发现在线 Android 设备；请指定 --serial 或 USB 调试授权", file=sys.stderr)
        return 1

    ids = args.case or (parity_case_ids() if args.all_cases else infra_parity_case_ids())
    selected = {c["name"]: c for c in PARITY_CASES}
    missing = [i for i in ids if i not in selected]
    if missing:
        print(f"未知 parity id: {missing}", file=sys.stderr)
        return 2

    sdk = apply_android_env()
    if sdk is None:
        print("警告：未找到 ANDROID_HOME/SDK_ROOT，Appium 可能无法建会话")

    rep = run_parity(serial=serial, case_ids=ids, stop_on_fail=args.stop_on_fail)
    print(f"parity 完成 [appium] @{serial[-8:]}："
          f"{rep['passed']}/{rep['total']} 通过，耗时 {rep['duration_ms']}ms")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = args.report.strip() or str(
        Path("logs") / f"parity_android_{serial[-8:]}_{ts}.json"
    )
    payload = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "host": (
            args.host.strip()
            or os.getenv("ANDROID_PARITY_HOST", "").strip()
            or ("win" if sys.platform.startswith("win") else "mac")
        ),
        "runs": [rep],
    }
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(report_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告已写入: {report_path}")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
