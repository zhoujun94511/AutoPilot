#!/usr/bin/env python3
"""Mac 双真机 × WDA/Appium 基础设施 parity 矩阵。

默认：每台 USB 设备各跑 wda + appium 后端，用例为 infra 标签（无特定 App UI）。
报告：logs/parity_dual_<timestamp>.json

用法：
  python tools/ios_parity_dual_run.py
  python tools/ios_parity_dual_run.py --udid <A> --udid <B>
  python tools/ios_parity_dual_run.py --backend wda --infra-only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (OSError, ValueError, UnicodeError):
    pass


def main() -> int:
    ap = argparse.ArgumentParser(description="双 iOS 真机 parity 矩阵（Mac）")
    ap.add_argument("--udid", action="append", default=[], help="指定 UDID（可重复；默认全部 USB 设备）")
    ap.add_argument("--backend", action="append", default=[], choices=["wda", "appium"],
                    help="后端（默认 wda+appium）")
    ap.add_argument("--all-cases", action="store_true",
                    help="跑全部 parity 用例（默认仅 infra，无 UI 控件依赖）")
    ap.add_argument("--infra-only", action="store_true",
                    help="仅 infra 用例（默认行为，显式声明用）")
    ap.add_argument("--case", action="append", default=[], help="覆盖用例 id 列表")
    ap.add_argument("--report", default="", help="JSON 报告路径")
    ap.add_argument("--stop-on-fail", action="store_true")
    args = ap.parse_args()

    from autopilot.mobile.ios_devices import list_usb_devices
    from tests.ios_parity_skeleton import infra_parity_case_ids, parity_case_ids, validate_parity_skeleton
    from tools.ios_parity_run import run_parity

    if not validate_parity_skeleton():
        print("parity 骨架校验失败", file=sys.stderr)
        return 2

    udids = [u.strip() for u in args.udid if u.strip()]
    if not udids:
        udids = [d.udid for d in list_usb_devices()]
    if not udids:
        print("未发现 USB iOS 设备；请解锁并信任此 Mac", file=sys.stderr)
        return 1

    backends = args.backend or ["wda", "appium"]
    if args.all_cases and args.infra_only:
        print("错误：--all-cases 与 --infra-only 互斥", file=sys.stderr)
        return 2
    case_ids = args.case or (
        parity_case_ids() if args.all_cases else infra_parity_case_ids()
    )

    devs = list_usb_devices()
    dev_by_udid = {d.udid: d for d in devs}
    device_meta = []
    for u in udids:
        d = dev_by_udid.get(u)
        if d:
            device_meta.append({
                "udid": d.udid,
                "name": d.name,
                "ios_version": d.ios_version,
                "product_type": d.product_type,
                "label": d.label,
            })
        else:
            device_meta.append({"udid": u})

    print(f"双机 parity：{len(udids)} 台 × {len(backends)} 后端 × {len(case_ids)} 用例")
    for u in udids:
        print(f"  - {u}")
    print(f"  backends: {backends}")
    print(f"  cases: {case_ids}")

    runs: list[dict] = []
    failed = 0
    for udid in udids:
        for backend in backends:
            print(f"\n>>> {udid[-8:]} / {backend} ...")
            # noinspection PyBroadException
            try:
                rep = run_parity(
                    udid=udid,
                    backend_mode=backend,
                    case_ids=case_ids,
                    stop_on_fail=args.stop_on_fail,
                )
            except Exception as e:
                rep = {
                    "udid": udid,
                    "backend_mode": backend,
                    "case_ids": case_ids,
                    "ok": False,
                    "error": str(e),
                    "passed": 0,
                    "total": len(case_ids),
                    "failed": len(case_ids),
                }
            runs.append(rep)
            status = "OK" if rep.get("ok") else "FAIL"
            print(f"    {status} {rep.get('passed', 0)}/{rep.get('total', 0)}")
            if not rep.get("ok"):
                failed += 1

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = args.report.strip() or str(Path("logs") / f"parity_dual_{ts}.json")
    payload = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "host": "mac-dual",
        "udids": udids,
        "devices": device_meta,
        "backends": backends,
        "case_ids": case_ids,
        "infra_only": not args.all_cases,
        "runs": runs,
        "summary": {
            "matrices": len(runs),
            "failed_matrices": failed,
            "ok": failed == 0,
        },
    }
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(report_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告: {report_path}")
    print(f"总结: {len(runs) - failed}/{len(runs)} 矩阵通过")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
