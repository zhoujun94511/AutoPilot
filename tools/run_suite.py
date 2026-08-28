#!/usr/bin/env python3
"""无头批量执行：支持串行与同平台多设备并行（每台完整复跑全部用例）。

示例：
  python tools/run_suite.py --project ./myproj
  python tools/run_suite.py --project ./myproj --parallel --platform android --workers 2
  python tools/run_suite.py --cases path/to/case.tc.yaml --platform ios --udid <UDID> --backend-mode wda -v
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (OSError, ValueError, UnicodeError):
    pass


def _list_android() -> list[str]:
    from autopilot.mobile.adb import ensure_adb, run_adb
    from autopilot.ui.device_monitor import parse_adb_devices
    if not ensure_adb():
        return []
    return parse_adb_devices(run_adb(["devices"]))


def _list_ios() -> list[str]:
    from autopilot.ui.device_monitor import DeviceMonitor
    return DeviceMonitor.list_ios()


def main() -> int:
    ap = argparse.ArgumentParser(description="AutoPilot 无头批量执行")
    ap.add_argument("--project", help="工程目录（发现全部用例）")
    ap.add_argument("--cases", nargs="*", help="指定用例文件路径")
    ap.add_argument("--parallel", action="store_true", help="同平台多设备并行")
    ap.add_argument("--platform", choices=["android", "ios"], default="android")
    ap.add_argument("--workers", type=int, default=0, help="并行 worker 数（0=全部已连接设备）")
    ap.add_argument("--wda-bundle", default="", help="iOS WDA bundle id（可选）")
    ap.add_argument("--udid", default="", help="单设备串行执行时绑定的 UDID")
    ap.add_argument("--backend-mode", default="auto", choices=["auto", "appium", "wda"],
                    help="iOS 会话后端（默认 auto）")
    ap.add_argument("--stop-on-fail", action="store_true", help="失败即停")
    ap.add_argument(
        "--kill-on-shard-fail", action="store_true",
        help="并行时任一台设备失败即请求停止其它设备（默认失败隔离，互不影响）")
    ap.add_argument("--verbose", "-v", action="store_true", help="逐步输出步骤结果")
    args = ap.parse_args()

    from autopilot.engine import run_suite, run_project_directory, FaultStrategy
    from autopilot.engine.suite import load_case

    fs = FaultStrategy.STOP if args.stop_on_fail else FaultStrategy.CONTINUE
    mode = "parallel_device" if args.parallel else "sequential"
    isolate = not args.kill_on_shard_fail
    udids = None
    base_vars: dict = {}
    on_step = None
    if args.verbose:
        def on_step(sr):
            msg = (getattr(sr, "remark", None) or getattr(sr, "message", None) or "")[:240]
            print(f"[{sr.status}] {sr.keyword_id} ({sr.duration_ms}ms) {msg}", flush=True)
    if args.udid.strip():
        base_vars["__device_udid__"] = args.udid.strip()
    if args.backend_mode:
        base_vars["__mobile_backend_mode__"] = args.backend_mode
    if args.parallel:
        udids = _list_android() if args.platform == "android" else _list_ios()
        if not udids:
            print(f"错误：未检测到 {args.platform} 设备", file=sys.stderr)
            return 2
        n = args.workers if args.workers > 0 else len(udids)
        print(f"并行模式：{args.platform} × {min(n, len(udids))} 台 → {udids[:n]}"
              f"（失败隔离：{'开' if isolate else '关'}）")

    if args.project:
        suite = run_project_directory(
            args.project,
            mode=mode,
            platform=args.platform,
            parallel_workers=args.workers,
            device_udids=udids,
            wda_bundle=args.wda_bundle,
            backend_mode=args.backend_mode,
            fault_strategy=fs,
            base_vars=base_vars or None,
            on_step=on_step,
            parallel_fault_isolation=isolate,
        )
    elif args.cases:
        cases = [load_case(p) for p in args.cases]
        suite = run_suite(
            cases,
            name="CLI",
            mode=mode,
            platform=args.platform,
            parallel_workers=args.workers,
            device_udids=udids,
            wda_bundle=args.wda_bundle,
            backend_mode=args.backend_mode,
            fault_strategy=fs,
            base_vars=base_vars or None,
            on_step=on_step,
            parallel_fault_isolation=isolate,
        )
    else:
        ap.print_help()
        return 1

    c = suite.case_counts()
    print(f"完成：{suite.name} — 用例 {c['passed']}/{c['total']} 通过，耗时 {suite.duration_ms}ms")
    return 0 if c["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
