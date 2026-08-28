#!/usr/bin/env python3
"""iOS WDA-direct vs Appium 最小 parity 集执行器。

Win/Linux PR：--backend-mode wda；Mac nightly：--backend-mode appium。
Mac 双真机：tools/ios_parity_dual_run.py 或本工具 + --infra-only。
离线：--list / --validate-only 校验骨架结构。
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

# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (OSError, ValueError, UnicodeError):
    pass


def _parity_to_testcase(spec: dict):
    from autopilot.model.testcase import TestCase, Step, ParamValue

    steps: list[Step] = []
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
        platform="ios",
    )
    tc.case.steps = steps
    return tc


def _mac_preflight(udid: str) -> list[str]:
    """真机跑前快速检查（不建会话）。"""
    hints: list[str] = []
    from autopilot.mobile import ios_bootstrap as ib
    from autopilot.mobile.ios_devices import list_usb_devices

    exe = ib.resolve_go_ios()
    if exe is None or not exe.is_file():
        hints.append("未找到内置 go-ios（resources/re_go_ios/executable/mac/ios）")
    known = {d.udid for d in list_usb_devices()}
    if udid and udid not in known:
        hints.append(f"UDID {udid} 不在 usbmux 列表（解锁/信任/USB）")
    return hints


def _write_report(path: str, payload: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告已写入: {p}")


def run_parity(
    *,
    udid: str,
    backend_mode: str,
    case_ids: list[str],
    wda_bundle: str = "",
    stop_on_fail: bool = False,
) -> dict:
    from tests.ios_parity_skeleton import PARITY_CASES
    from autopilot.engine import run_suite, FaultStrategy
    from autopilot.mobile import ios_bootstrap as ib

    selected = {c["name"]: c for c in PARITY_CASES}
    cases = [_parity_to_testcase(selected[i]) for i in case_ids]
    base_vars = {
        "__device_udid__": udid,
        "__mobile_backend_mode__": backend_mode,
        "__current_platform__": "ios",
    }
    ib.merge_appium_ios_caps(base_vars, udid, wda_bundle.strip(), backend_mode)
    # 跑前清理残留隧道，降低 flaky
    ib.kill_goios_tunnel_agents()
    t0 = time.monotonic()
    suite = run_suite(
        cases,
        name=f"iOS-parity-{backend_mode}",
        platform="ios",
        wda_bundle=wda_bundle,
        backend_mode=backend_mode,
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
        "udid": udid,
        "backend_mode": backend_mode,
        "case_ids": case_ids,
        "passed": c["passed"],
        "total": c["total"],
        "failed": c["failed"],
        "duration_ms": elapsed_ms,
        "ok": c["failed"] == 0,
        "cases": case_rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="iOS parity 最小集（WDA / Appium 对照）")
    ap.add_argument("--list", action="store_true", help="列出 parity 用例 id")
    ap.add_argument("--list-devices", action="store_true", help="列出 USB 真机 UDID")
    ap.add_argument("--validate-only", action="store_true", help="仅离线校验骨架")
    ap.add_argument("--infra-only", action="store_true", help="只跑 infra 标签用例（无 UI 控件依赖）")
    ap.add_argument("--case", action="append", default=[], help="只跑指定 id（可重复）")
    ap.add_argument("--platform", default="ios", choices=["ios"])
    ap.add_argument("--udid", default="", help="绑定设备 UDID")
    ap.add_argument("--wda-bundle", default="")
    ap.add_argument("--backend-mode", default="auto", choices=["auto", "appium", "wda"])
    ap.add_argument("--stop-on-fail", action="store_true")
    ap.add_argument("--report", default="", help="JSON 报告路径（默认 logs/parity_<ts>.json）")
    ap.add_argument("--host", default="", help="报告 host 标记（如 mac / win，供 diff 归档）")
    ap.add_argument("--skip-preflight", action="store_true")
    args = ap.parse_args()

    from tests.ios_parity_skeleton import (
        PARITY_CASES,
        infra_parity_case_ids,
        parity_case_ids,
        validate_parity_skeleton,
    )

    if args.list_devices:
        from autopilot.mobile.ios_devices import list_usb_devices
        for d in list_usb_devices():
            print(f"{d.udid}\t{d.label}")
        return 0

    if args.list:
        ids = infra_parity_case_ids() if args.infra_only else parity_case_ids()
        for cid in ids:
            print(cid)
        return 0

    udid = args.udid.strip() or os.getenv("IOS_PARITY_UDID", "").strip()

    if args.validate_only or not udid:
        ok = validate_parity_skeleton()
        n_infra = len(infra_parity_case_ids())
        print("parity 骨架:", "OK" if ok else "FAIL",
              f"({len(PARITY_CASES)} cases, infra={n_infra})")
        if args.validate_only:
            return 0 if ok else 1
        if not udid:
            print("提示：未指定 --udid；真机请先 python tools/ios_device_list.py")
            return 0 if ok else 1

    ids = args.case or (infra_parity_case_ids() if args.infra_only else parity_case_ids())
    selected = {c["name"]: c for c in PARITY_CASES}
    missing = [i for i in ids if i not in selected]
    if missing:
        print(f"未知 parity id: {missing}", file=sys.stderr)
        return 2

    if not args.skip_preflight:
        hints = _mac_preflight(udid)
        if hints:
            print("预检提示：")
            for h in hints:
                print(f"  ⚠ {h}")
            print("  （设备需解锁、信任电脑、开发者模式；仍失败可加 --skip-preflight 强制跑）")

    rep = run_parity(
        udid=udid,
        backend_mode=args.backend_mode,
        case_ids=ids,
        wda_bundle=args.wda_bundle,
        stop_on_fail=args.stop_on_fail,
    )
    print(f"parity 完成 [{args.backend_mode}] @{udid[-8:]}："
          f"{rep['passed']}/{rep['total']} 通过，耗时 {rep['duration_ms']}ms")
    report_path = args.report.strip()
    if not report_path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = str(Path("logs") / f"parity_{udid[-8:]}_{args.backend_mode}_{ts}.json")
    payload = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "host": (args.host.strip() or os.getenv("IOS_PARITY_HOST", "") or "mac"),
        "runs": [rep],
    }
    _write_report(report_path, payload)
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
