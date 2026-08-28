#!/usr/bin/env python3
"""Mac Appium iOS Golden Reference 采集（Step 0–6 编排）。

Mac iOS 26+ Appium golden（已验证）：
  - go-ios 用户态隧道 + runwda → WDA 8100
  - Appium 仅 webDriverAgentUrl 直连（IOS_APPIUM_MANAGED=0，禁止 usePreinstalledWDA）
  - 多步骤采集前需常驻 WDA（8100），见 docs/setup/ios.md §5

WDA-direct 对照：同机 --backend-mode wda（Step 6）

用法：
  export IOS_APPIUM_MANAGED=0 IOS_PARITY_UDID=<UDID> IOS_MONKEY_BUNDLE_ID=<bundle>
  appium   # 4723
  python tools/ios_golden_reference_run.py --wda-bundle <WDA_BUNDLE> --ipa <IPA>
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (OSError, ValueError, UnicodeError):
    pass


def _env_udid(explicit: str) -> str:
    return (explicit or os.getenv("IOS_PARITY_UDID") or "").strip()


def _ensure_test002_mac(ipa: str) -> Path:
    src = Path(os.getenv(
        "TEST002_CASE",
        "/Users/crtm/Documents/testproject/plantscope/AIID/TEST002.tc.yaml",
    ))
    if not src.is_file():
        raise FileNotFoundError(f"TEST002 不存在: {src}")
    text = src.read_text(encoding="utf-8")
    win_ipa = r"D:\plantscope\AIID\ipa\aitou.ipa"
    if win_ipa in text:
        text = text.replace(win_ipa, ipa)
    out = Path("/tmp/TEST002_mac.tc.yaml")
    out.write_text(text, encoding="utf-8")
    return out


def _run(cmd: list[str], env: dict | None = None) -> tuple[int, str]:
    r = subprocess.run(
        cmd, cwd=str(ROOT), env=env or os.environ,
        capture_output=True, text=True,
    )
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, out


def main() -> int:
    ap = argparse.ArgumentParser(description="Mac Appium iOS Golden Reference 采集")
    ap.add_argument("--udid", default="")
    ap.add_argument("--wda-bundle", default="")
    ap.add_argument("--ipa", default="/Users/crtm/Documents/testproject/plantscope/AIID/ipa/aitou.ipa")
    ap.add_argument("--skip-wda-mac", action="store_true", help="跳过 Step 6 WDA-direct 对照")
    ap.add_argument("--stop-on-fail", action="store_true")
    args = ap.parse_args()

    import autopilot.keywords  # noqa: F401
    from autopilot.mobile import ios_bootstrap as ib

    udid = _env_udid(args.udid)
    if not udid:
        print("错误：请设置 --udid 或 IOS_PARITY_UDID", file=sys.stderr)
        return 2

    wda = (args.wda_bundle or os.getenv("IOS_WDA_BUNDLE") or "").strip()
    if not wda:
        try:
            wda = ib.IosDevicePrep(udid, "", log=lambda _m: None).discover_wda()
        except RuntimeError:
            wda = "com.facebook.WebDriverAgentRunner.crts.test.xctrunner.xctrunner"

    os.environ.setdefault("IOS_PARITY_UDID", udid)
    os.environ.setdefault("APPIUM_SERVER", "http://127.0.0.1:4723")
    os.environ.setdefault("IOS_MONKEY_BUNDLE_ID", "imobile.broadcast.app")
    os.environ.setdefault("ENABLE_GO_IOS_AGENT", "user")

    py = sys.executable
    results: dict = {"meta": {}, "steps": {}}

    print("=== Step 0: preflight ===")
    code0, out0 = _run([py, "tools/preflight.py"])
    print(out0[-1200:] if len(out0) > 1200 else out0)
    results["steps"]["preflight"] = {"exit_code": code0}

    ios_major = ib.device_ios_major(udid)
    ios_ver = ib.device_ios_version(udid)
    managed = ib.prefer_appium_managed(udid)
    print(f"设备 iOS {ios_ver or '?'} (major={ios_major}), Appium managed={managed}")

    if managed and not ib.tunneld_running():
        print("\n⚠ iOS 17+ Appium 需要 tunneld。请在另一终端执行：")
        print("  sudo python -m pymobiledevice3 remote tunneld")
        print("然后重跑本脚本。\n")
        results["steps"]["tunneld"] = {"running": False}
        if args.stop_on_fail:
            return 1
    else:
        results["steps"]["tunneld"] = {"running": ib.tunneld_running()}

    test002 = _ensure_test002_mac(args.ipa)
    env_appium = os.environ.copy()
    env_appium["IOS_BACKEND"] = "appium"
    env_appium["IOS_APPIUM_MANAGED"] = "1" if managed else "0"
    env_appium["IOS_KEEP_TUNNELD"] = "1"

    print("\n=== Step 2: Appium smoke ===")
    smoke_cmd = [py, "tools/appium_smoke_ios_managed.py", udid, wda] if managed else [
        py, "tools/appium_smoke_ios.py", udid, wda,
    ]
    if not managed:
        env_appium["IOS_KEEP_WDA"] = "1"
    code2, out2 = _run(smoke_cmd, env_appium)
    print(out2)
    results["steps"]["smoke_appium"] = {
        "exit_code": code2,
        "result": "PASS" if code2 == 0 and "result: PASS" in out2 else "FAIL",
        "managed": managed,
    }

    print("\n=== Step 3: parity (appium) ===")
    code3, out3 = _run([
        py, "tools/ios_parity_run.py",
        "--udid", udid,
        "--backend-mode", "appium",
        "--wda-bundle", wda,
    ], env_appium)
    print(out3)
    results["steps"]["parity_appium"] = {"exit_code": code3, "output_tail": out3[-800:]}

    print("\n=== Step 4: TEST002 (appium) ===")
    code4, out4 = _run([
        py, "tools/run_suite.py",
        "--cases", str(test002),
        "--platform", "ios",
        "--udid", udid,
        "--backend-mode", "appium",
        "--wda-bundle", wda,
        "--verbose",
    ] + (["--stop-on-fail"] if args.stop_on_fail else []), env_appium)
    print(out4)
    passed4 = "1/1" if "用例 1/1 通过" in out4 else "0/1"
    results["steps"]["test002"] = {"exit_code": code4, "passed": passed4}

    print("\n=== Step 5: Monkey (appium) ===")
    code5, out5 = _run([
        py, "tools/ios_monkey_run.py",
        "--udid", udid,
        "--bundle-id", os.environ["IOS_MONKEY_BUNDLE_ID"],
        "--ipa", args.ipa,
        "--backend-mode", "appium",
        "--wda-bundle", wda,
        "--duration-sec", "60",
        "--monkey-steps", "50",
        "--monkey-policy", "safe",
        "--syslog-mode", "ostrace",
    ], env_appium)
    print(out5)
    monkey_dir = ""
    for line in out5.splitlines():
        if "Monkey 完成，报告:" in line:
            monkey_dir = line.split(":", 1)[-1].strip()
    results["steps"]["monkey_appium"] = {"exit_code": code5, "report_dir": monkey_dir}

    if not args.skip_wda_mac:
        print("\n=== Step 6: parity + monkey (wda, 同机对照) ===")
        env_wda = os.environ.copy()
        env_wda["IOS_BACKEND"] = "wda"
        env_wda["IOS_KEEP_WDA"] = "1"
        code6a, out6a = _run([
            py, "tools/ios_parity_run.py",
            "--udid", udid, "--backend-mode", "wda", "--wda-bundle", wda,
        ], env_wda)
        print(out6a)
        code6b, out6b = _run([
            py, "tools/ios_monkey_run.py",
            "--udid", udid,
            "--bundle-id", os.environ["IOS_MONKEY_BUNDLE_ID"],
            "--backend-mode", "wda",
            "--wda-bundle", wda,
            "--duration-sec", "60",
            "--monkey-policy", "safe",
        ], env_wda)
        print(out6b)
        results["steps"]["parity_wda_mac"] = {"exit_code": code6a}
        results["steps"]["monkey_wda_mac"] = {"exit_code": code6b}

    report_path = ROOT / "logs" / f"golden_reference_{date.today().strftime('%Y%m%d')}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n采集摘要已写入: {report_path}")

    failed = [k for k, v in results["steps"].items()
              if isinstance(v, dict) and v.get("exit_code", 0) not in (0, None)]
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
