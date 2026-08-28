#!/usr/bin/env python3
"""Mac vs Win（或任意两侧）iOS parity JSON 报告逐步 diff。

典型流程：
  # Win 真机采集（在 Windows 上）
  python tools/ios_parity_run.py --udid <UDID> --infra-only --backend-mode wda --host win --report logs/parity_win_wda.json
  # Mac Appium golden
  python tools/ios_parity_run.py --udid <UDID> --infra-only --backend-mode appium --report logs/parity_mac_appium.json
  # diff
  python tools/ios_parity_diff.py --left logs/parity_mac_appium.json --right logs/parity_win_wda.json \\
      --label-left Mac-Appium --label-right Win-WDA

同机 WDA vs Appium：
  python tools/ios_parity_diff.py --preset mac-wda-vs-appium \\
      --left logs/parity_<udid>_wda_*.json --right logs/parity_<udid>_appium_*.json

双机 WDA 一致性（dual 报告内两 run）：
  python tools/ios_parity_diff.py --dual logs/parity_dual_<ts>.json
"""

from __future__ import annotations

import argparse
import glob
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


def _resolve_path(pattern: str) -> Path:
    p = Path(pattern)
    if p.exists():
        return p
    matches = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    if matches:
        return Path(matches[0])
    raise FileNotFoundError(f"找不到报告: {pattern}")


def _print_result(result) -> None:
    for line in result.summary_lines():
        print(line)
    if result.mismatches:
        print("\n不一致步骤：")
        for m in result.mismatches:
            print(f"  {m.key}")
            print(f"    {result.left_label}: {m.left_status} — {m.left_message[:120]}")
            print(f"    {result.right_label}: {m.right_status} — {m.right_message[:120]}")
    if result.only_left:
        print(f"\n仅 {result.left_label} 有 ({len(result.only_left)}):")
        for k in result.only_left[:10]:
            print(f"  {k}")
        if len(result.only_left) > 10:
            print(f"  ... +{len(result.only_left) - 10}")
    if result.only_right:
        print(f"\n仅 {result.right_label} 有 ({len(result.only_right)}):")
        for k in result.only_right[:10]:
            print(f"  {k}")


def _diff_dual_report(path: Path, *, strict: bool, report_out: str) -> int:
    from autopilot.mobile.ios.parity_report import (
        diff_parity_reports,
        diff_result_to_dict,
        load_parity_report,
    )

    data = load_parity_report(path)
    runs = data.get("runs") or []
    wda_runs = [r for r in runs if str(r.get("backend_mode", "")).lower() == "wda"]
    if len(wda_runs) < 2:
        print(f"dual 报告 WDA run 不足 2 条: {path}", file=sys.stderr)
        return 2
    left_run = wda_runs[0]
    right_run = wda_runs[1]
    left_report = {"runs": [left_run]}
    right_report = {"runs": [right_run]}
    lu = str(left_run.get("udid", ""))[-8:]
    ru = str(right_run.get("udid", ""))[-8:]
    result = diff_parity_reports(
        left_report,
        right_report,
        left_label=f"WDA@{lu}",
        right_label=f"WDA@{ru}",
        strict=strict,
    )
    _print_result(result)
    if report_out:
        payload = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "mode": "dual-wda",
            "source": str(path),
            **diff_result_to_dict(result),
        }
        Path(report_out).parent.mkdir(parents=True, exist_ok=True)
        Path(report_out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\ndiff 报告: {report_out}")
    return 0 if result.ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="iOS parity JSON 报告 diff（Mac vs Win / 双后端）")
    ap.add_argument("--left", default="", help="左侧/参考报告（支持 glob）")
    ap.add_argument("--right", default="", help="右侧/候选报告（支持 glob）")
    ap.add_argument("--dual", default="", help="dual 报告路径：对比其中前两条 WDA run")
    ap.add_argument("--label-left", default="")
    ap.add_argument("--label-right", default="")
    ap.add_argument("--left-backend", default="", choices=["", "wda", "appium"])
    ap.add_argument("--right-backend", default="", choices=["", "wda", "appium"])
    ap.add_argument("--left-udid", default="")
    ap.add_argument("--right-udid", default="")
    ap.add_argument("--preset", default="", choices=["", "mac-appium-vs-win-wda", "mac-wda-vs-appium"])
    ap.add_argument("--strict", action="store_true", help="严格比较原始 status（含 NOIMPL）")
    ap.add_argument("--report", default="", help="输出 diff JSON 到 logs/")
    ap.add_argument("--validate-only", action="store_true", help="离线自检（内置样例）")
    args = ap.parse_args()

    from autopilot.mobile.ios.parity_report import (
        diff_parity_reports,
        diff_result_to_dict,
        diff_step_maps,
        flatten_run_steps,
        load_parity_report,
    )

    if args.validate_only:
        sample_left = {
            "runs": [{
                "cases": [{
                    "name": "ios-session-infra",
                    "steps": [
                        {"keyword_id": "mobile_app_start", "status": "PASS"},
                        {"keyword_id": "mobile_swipe_direction", "status": "PASS"},
                    ],
                }],
            }],
        }
        sample_right = {
            "runs": [{
                "cases": [{
                    "name": "ios-session-infra",
                    "steps": [
                        {"keyword_id": "mobile_app_start", "status": "PASS"},
                        {"keyword_id": "mobile_swipe_direction", "status": "FAIL", "message": "x"},
                    ],
                }],
            }],
        }
        ok_case = diff_parity_reports(sample_left, sample_right, left_label="a", right_label="b")
        ok_self = diff_step_maps(
            flatten_run_steps(sample_left["runs"][0]),
            flatten_run_steps(sample_left["runs"][0]),
            left_label="x", right_label="x",
        ).ok
        ok = (not ok_case.ok) and ok_case.compared == 2 and ok_self
        print("ios_parity_diff validate-only:", "OK" if ok else "FAIL")
        return 0 if ok else 1

    if args.dual:
        out = args.report.strip() or str(
            Path("logs") / f"parity_diff_dual_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        return _diff_dual_report(_resolve_path(args.dual), strict=args.strict, report_out=out)

    left_label = args.label_left.strip()
    right_label = args.label_right.strip()
    left_backend = args.left_backend
    right_backend = args.right_backend

    if args.preset == "mac-appium-vs-win-wda":
        left_label = left_label or "Mac-Appium"
        right_label = right_label or "Win-WDA"
        left_backend = left_backend or "appium"
        right_backend = right_backend or "wda"
    elif args.preset == "mac-wda-vs-appium":
        left_label = left_label or "Mac-WDA"
        right_label = right_label or "Mac-Appium"
        left_backend = left_backend or "wda"
        right_backend = right_backend or "appium"

    if not args.left or not args.right:
        print("请指定 --left 与 --right，或 --dual <parity_dual.json>", file=sys.stderr)
        return 2

    left_path = _resolve_path(args.left)
    right_path = _resolve_path(args.right)
    if not left_label:
        left_label = left_path.stem
    if not right_label:
        right_label = right_path.stem

    result = diff_parity_reports(
        load_parity_report(left_path),
        load_parity_report(right_path),
        left_label=left_label,
        right_label=right_label,
        left_backend=left_backend,
        right_backend=right_backend,
        left_udid=args.left_udid.strip(),
        right_udid=args.right_udid.strip(),
        strict=args.strict,
    )
    _print_result(result)

    report_path = args.report.strip()
    if not report_path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = str(Path("logs") / f"parity_diff_{ts}.json")
    payload = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "left": str(left_path),
        "right": str(right_path),
        **diff_result_to_dict(result),
    }
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(report_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\ndiff 报告: {report_path}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
