"""iOS parity 报告 diff 离线回归。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def test_flatten_and_self_diff() -> bool:
    from autopilot.mobile.ios.parity_report import diff_step_maps, flatten_run_steps

    run = {
        "cases": [{
            "name": "ios-alert-policy",
            "steps": [
                {"keyword_id": "ios_alert_set_policy", "status": "PASS"},
                {"keyword_id": "ios_alert_set_enabled", "status": "PASS"},
            ],
        }],
    }
    flat = flatten_run_steps(run)
    ok = len(flat) == 2 and "ios-alert-policy::0::ios_alert_set_policy" in flat
    res = diff_step_maps(flat, flat, left_label="a", right_label="b")
    ok = ok and res.ok and res.compared == 2
    print("parity flatten self-diff:", "OK" if ok else "FAIL")
    return ok


def test_normalize_fail_equivalence() -> bool:
    from autopilot.mobile.ios.parity_report import diff_step_maps, flatten_run_steps, normalize_step_status

    ok = normalize_step_status("NOIMPL") == "FAIL" and normalize_step_status("PASS") == "PASS"
    left = flatten_run_steps({"cases": [{
        "name": "c", "steps": [{"keyword_id": "k", "status": "FAIL"}],
    }]})
    right = flatten_run_steps({"cases": [{
        "name": "c", "steps": [{"keyword_id": "k", "status": "NOIMPL"}],
    }]})
    res = diff_step_maps(left, right)
    ok = ok and res.ok
    print("parity FAIL≈NOIMPL:", "OK" if ok else "FAIL")
    return ok


def test_driver_device_info_via_wda_status() -> bool:
    from autopilot.mobile.ios.device_info import driver_device_info

    drv = MagicMock(spec=[])
    drv.capabilities = {
        "webDriverAgentUrl": "http://127.0.0.1:8100",
        "platformVersion": "18.6",
        "deviceName": "iPhone",
    }
    status = {"os": {"version": "18.6.2"}, "device": "iPhone", "ios": {"ip": "10.0.0.1"}}
    with patch("httpx.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"value": status}
        info = driver_device_info(drv)
    ok = info.get("ip") == "10.0.0.1" and info.get("version") == "18.6.2"
    print("driver_device_info Appium/WDA status:", "OK" if ok else f"FAIL {info}")
    return ok


def test_diff_cli_validate_only() -> bool:
    import subprocess

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "tools", "ios_parity_diff.py")
    proc = subprocess.run(
        [sys.executable, script, "--validate-only"],
        cwd=root, capture_output=True, text=True, timeout=30,
    )
    ok = proc.returncode == 0 and "OK" in proc.stdout
    print("ios_parity_diff --validate-only:", "OK" if ok else f"FAIL rc={proc.returncode}")
    return ok


def test_diff_reports_file() -> bool:
    from autopilot.mobile.ios.parity_report import diff_parity_reports, load_parity_report

    left = {
        "runs": [{
            "backend_mode": "wda",
            "cases": [{
                "name": "ios-session-infra",
                "steps": [
                    {"keyword_id": "mobile_app_start", "status": "PASS"},
                    {"keyword_id": "mobile_app_close", "status": "PASS"},
                ],
            }],
        }],
    }
    right = dict(left)
    with tempfile.TemporaryDirectory() as td:
        lp = Path(td) / "l.json"
        rp = Path(td) / "r.json"
        lp.write_text(json.dumps(left), encoding="utf-8")
        rp.write_text(json.dumps(right), encoding="utf-8")
        res = diff_parity_reports(load_parity_report(lp), load_parity_report(rp))
    ok = res.ok and res.compared == 2
    print("diff_parity_reports files:", "OK" if ok else "FAIL")
    return ok


def main() -> int:
    ok = all([
        test_flatten_and_self_diff(),
        test_normalize_fail_equivalence(),
        test_driver_device_info_via_wda_status(),
        test_diff_cli_validate_only(),
        test_diff_reports_file(),
    ])
    print("\n总结:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
