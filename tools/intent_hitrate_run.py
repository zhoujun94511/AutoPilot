#!/usr/bin/env python3
"""Intent / Binding / Vision 真机与浏览器命中率验证。

示例：
  # Android Settings（需 Appium :4723 + 真机）
  python tools/intent_hitrate_run.py --platform android --udid <android-udid>

  # 浏览器对照
  python tools/intent_hitrate_run.py --platform web

  # 两轮：第 1 轮 resolved，第 2 轮期望 cache；可选腐蚀 Binding 测自愈
  python tools/intent_hitrate_run.py --platform android --udid <android-udid> --rounds 2 --heal-probe

  # 开启 Vision（需 API Key）
  python tools/intent_hitrate_run.py --platform android --udid <android-udid> --vision
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (OSError, ValueError, UnicodeError):
    pass

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "intent_hitrate"

DEFAULT_CASES = {
    "android": [
        "android_settings_assert.tc.yaml",
        "android_settings_click.tc.yaml",
    ],
    "ios": [
        "ios_settings_assert.tc.yaml",
        "ios_settings_click.tc.yaml",
    ],
    "web": [
        "web_example_assert.tc.yaml",
    ],
}


def _web_fixture_url() -> str:
    html = (FIXTURE_DIR / "web_fixture.html").resolve()
    return html.as_uri()


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _collect_hits(suite) -> Counter:
    hits: Counter = Counter()
    for cr in getattr(suite, "results", None) or []:
        for sr in getattr(cr, "results", None) or []:
            if str(getattr(sr, "keyword_id", "") or "") != "intent_act":
                continue
            hit = str(getattr(sr, "binding_hit", "") or "").strip() or (
                "failed" if str(getattr(sr, "status", "")) == "FAIL" else "unknown"
            )
            hits[hit] += 1
            if bool(getattr(sr, "heal_applied", False)):
                hits["heal_flag"] += 1
            if bool(getattr(sr, "rolled_back", False)):
                hits["rolled_back_flag"] += 1
            fr = str(getattr(sr, "fail_reason", "") or "").strip()
            if fr:
                hits[f"reason:{fr}"] += 1
    return hits


def _intent_step_rows(suite) -> list[dict]:
    rows: list[dict] = []
    for cr in getattr(suite, "results", None) or []:
        for sr in getattr(cr, "results", None) or []:
            if str(getattr(sr, "keyword_id", "") or "") != "intent_act":
                continue
            rows.append(
                {
                    "case": getattr(cr, "case_name", ""),
                    "intent_id": getattr(sr, "intent_id", "") or "",
                    "status": getattr(sr, "status", ""),
                    "binding_hit": getattr(sr, "binding_hit", "") or "",
                    "heal_applied": bool(getattr(sr, "heal_applied", False)),
                    "fail_reason": getattr(sr, "fail_reason", "") or "",
                    "fail_reason_label": getattr(sr, "fail_reason_label", "") or "",
                    "rolled_back": bool(getattr(sr, "rolled_back", False)),
                    "message": (getattr(sr, "message", "") or "")[:240],
                    "duration_ms": int(getattr(sr, "duration_ms", 0) or 0),
                }
            )
    return rows


def _corrupt_bindings(project_dir: Path) -> int:
    """把已写入 Binding 的 locator 改成必然失败的值，用于自愈探针。"""
    bind_dir = project_dir / "bindings"
    if not bind_dir.is_dir():
        return 0
    n = 0
    for path in bind_dir.glob("*.json"):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        steps = doc.get("steps") if isinstance(doc.get("steps"), dict) else {}
        changed = False
        for step in steps.values():
            if not isinstance(step, dict):
                continue
            params = step.get("params") if isinstance(step.get("params"), dict) else {}
            if "locator" in params:
                params["locator"] = "xpath:://*[@text='__hitrate_corrupt_never__']"
                step["params"] = params
                changed = True
        if changed:
            path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            n += 1
    return n


def _prepare_project(work: Path, case_names: list[str]) -> list[Path]:
    if work.exists():
        shutil.rmtree(work)
    (work / "bindings").mkdir(parents=True)
    (work / "reports").mkdir(parents=True)
    cases_dir = work / "cases"
    cases_dir.mkdir(parents=True)
    paths: list[Path] = []
    for name in case_names:
        src = FIXTURE_DIR / name
        if not src.is_file():
            raise FileNotFoundError(f"缺少样例用例: {src}")
        dst = cases_dir / name
        shutil.copy2(src, dst)
        paths.append(dst)
    return paths


def _reset_android_settings(udid: str) -> None:
    """把 Settings 拉回首页，避免 noReset 会话停在子页导致断言假失败。"""
    from autopilot.mobile.adb import run_adb

    serial = (udid or "").strip()
    prefix = ["-s", serial] if serial else []
    run_adb([*prefix, "shell", "am", "force-stop", "com.android.settings"])
    run_adb(
        [
            *prefix,
            "shell",
            "am",
            "start",
            "-a",
            "android.settings.SETTINGS",
            "-f",
            "0x10008000",  # ACTIVITY_NEW_TASK | ACTIVITY_CLEAR_TASK
        ]
    )
    time.sleep(1.2)


def _prepare_ios_wda(udid: str, *, wda_bundle: str = "") -> str:
    """go-ios 隧道 + runwda + 转发，返回本机 WDA URL。"""
    from autopilot.mobile import ios_bootstrap as ib

    os.environ.setdefault("IOS_USE_GOIOS", "1")
    os.environ.setdefault("ENABLE_GO_IOS_AGENT", "user")
    prep = ib.IosDevicePrep(
        udid,
        (wda_bundle or os.environ.get("IOS_WDA_BUNDLE") or "").strip(),
        log=lambda m: print(f"[ios-prep] {m}", flush=True),
    )
    url = prep.prepare()
    print(f"[ios-prep] WDA ready: {url}", flush=True)
    return url


def _adapt_ios_labels(_udid: str, case_paths: list[Path]) -> None:
    """按当前 Settings 页可见文案微调 fixture（英/中）。"""
    try:
        from autopilot.keywords.mobile.wda_client import WdaClient
    except ImportError:
        return
    port = int(os.environ.get("IOS_WDA_LOCAL_PORT", "8100") or "8100")
    try:
        client = WdaClient(f"http://127.0.0.1:{port}")
        client.create_session(bundle_id="")
        bid = "com.apple.Preferences"
        # 必须冷启动到设置首页，否则可能停在 WLAN 子页看不到 Bluetooth
        try:
            client.terminate_app(bid)
        except (OSError, RuntimeError, TypeError, ValueError):
            pass
        try:
            client.launch_app(bid)
        except (OSError, RuntimeError, TypeError, ValueError):
            try:
                client.activate_app(bid)
            except (OSError, RuntimeError, TypeError, ValueError):
                pass
        time.sleep(1.2)
        page_source = client.source() or ""
        try:
            client.delete_session()
        except (OSError, RuntimeError, TypeError, ValueError):
            pass
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"[ios-prep] 跳过文案适配: {exc}", flush=True)
        return

    wifi = "Wi-Fi"
    bt = "Bluetooth"
    if "无线局域网" in page_source:
        wifi = "无线局域网"
    elif "WLAN" in page_source and "Wi-Fi" not in page_source:
        wifi = "WLAN"
    # 中文设置常见「蓝牙」；若树里同时有英文无障碍串，仍以可见「蓝牙」为准
    if "蓝牙" in page_source and (
        "WLAN" in page_source or "无线局域网" in page_source or "Bluetooth" not in page_source
    ):
        bt = "蓝牙"
    elif "Bluetooth" not in page_source and "蓝牙" in page_source:
        bt = "蓝牙"
    print(f"[ios-prep] Settings 文案适配: wifi={wifi!r} bluetooth={bt!r}", flush=True)

    for path in case_paths:
        text = path.read_text(encoding="utf-8")
        text = text.replace("target: Wi-Fi", f"target: {wifi}")
        text = text.replace("text: Wi-Fi", f"text: {wifi}")
        text = text.replace("点击 Wi-Fi", f"点击 {wifi}")
        text = text.replace("target: Bluetooth", f"target: {bt}")
        text = text.replace("text: Bluetooth", f"text: {bt}")
        path.write_text(text, encoding="utf-8")


def _run_once(
    *,
    case_paths: list[Path],
    platform: str,
    udid: str,
    project_dir: Path,
    verbose: bool,
    wda_bundle: str = "",
    skip_ios_prep: bool = False,
):
    import autopilot.keywords  # noqa: F401
    import autopilot.intent.keyword  # noqa: F401

    from autopilot.engine import FaultStrategy, run_suite
    from autopilot.engine.suite import load_case

    if platform == "android":
        from autopilot.mobile.android_env import apply_android_env

        apply_android_env()
        _reset_android_settings(udid)
    elif platform == "ios" and not skip_ios_prep:
        _prepare_ios_wda(udid, wda_bundle=wda_bundle)
        _adapt_ios_labels(udid, case_paths)

    base_vars: dict = {
        "__project_path__": str(project_dir),
        "__run_platform__": platform,
        "__current_platform__": platform,
    }
    if platform == "web":
        base_vars["__hitrate_web_url__"] = _web_fixture_url()
    if udid:
        base_vars["__device_udid__"] = udid
    if platform == "android":
        base_vars["__appium_caps__"] = {
            "noReset": True,
            "forceAppLaunch": True,
            "newCommandTimeout": 120,
            "uiautomator2ServerInstallTimeout": 120000,
        }
    elif platform == "ios":
        base_vars["__mobile_backend_mode__"] = "wda"
        os.environ.setdefault("IOS_USE_GOIOS", "1")
        os.environ.setdefault("AUTOPILOT_INTENT_KEEP_WDA", "1")
        os.environ.setdefault("IOS_KEEP_WDA", "1")
        from autopilot.mobile import ios_bootstrap as ib

        # WDA-direct：不经 Appium；仍写入 caps 供会话层读取 webDriverAgentUrl
        ib.merge_appium_ios_caps(
            base_vars,
            udid,
            (wda_bundle or os.environ.get("IOS_WDA_BUNDLE") or "").strip(),
            "wda",
        )
        # merge 在 wda 模式下直接 return；显式补本地 URL
        port = int(os.environ.get("IOS_WDA_LOCAL_PORT", "8100") or "8100")
        base_vars["__appium_caps__"] = {
            "webDriverAgentUrl": f"http://127.0.0.1:{port}",
            "udid": udid,
            "noReset": True,
        }
        if wda_bundle:
            base_vars["__wda_bundle__"] = wda_bundle
            base_vars["__appium_caps__"]["wdaBundleId"] = wda_bundle

    on_step = None
    if verbose:

        def on_step(sr):  # noqa: F811
            hit = getattr(sr, "binding_hit", "") or ""
            extra = f" hit={hit}" if hit else ""
            msg = (getattr(sr, "message", None) or getattr(sr, "remark", None) or "")[:200]
            print(
                f"  [{sr.status}] {sr.keyword_id} ({sr.duration_ms}ms){extra} {msg}",
                flush=True,
            )

    cases = [load_case(str(p)) for p in case_paths]
    return run_suite(
        cases,
        name=f"intent-hitrate-{platform}",
        platform=platform if platform in ("android", "ios") else "",
        fault_strategy=FaultStrategy.CONTINUE,
        base_vars=base_vars,
        on_step=on_step,
    )


def _summarize(hits: Counter) -> dict:
    intent_total = sum(
        v
        for k, v in hits.items()
        if k in ("cache", "resolved", "healed", "failed", "unknown", "rolled_back")
    )
    success = hits["cache"] + hits["resolved"] + hits["healed"] + hits["rolled_back"]
    rate = (success / intent_total) if intent_total else 0.0
    reasons = {k[7:]: v for k, v in hits.items() if str(k).startswith("reason:")}
    return {
        "intent_steps": intent_total,
        "success": success,
        "hit_rate": round(rate, 4),
        "cache": hits["cache"],
        "resolved": hits["resolved"],
        "healed": hits["healed"],
        "rolled_back": hits["rolled_back"],
        "failed": hits["failed"],
        "heal_flag": hits["heal_flag"],
        "fail_reasons": reasons,
    }


def _run_vision_compare(args: argparse.Namespace) -> int:
    """Vision OFF → ON 对照；无 Key 时 ON 轮标记 skipped。"""
    from autopilot.intent.config import vision_api_key

    base = Path(args.work_dir) if args.work_dir else (ROOT / "logs" / f"intent_hitrate_cmp_{_now_stamp()}")
    base.mkdir(parents=True, exist_ok=True)
    compare: dict = {
        "schema": "intent_hitrate_compare.v1",
        "platform": args.platform,
        "udid": args.udid if args.platform != "web" else "",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "legs": [],
    }
    exit_code = 0
    for vision_on in (False, True):
        label = "vision_on" if vision_on else "vision_off"
        print(f"\n######## COMPARE {label} ########")
        if vision_on:
            if not vision_api_key():
                compare["legs"].append(
                    {"leg": label, "skipped": True, "reason": "no_vision_api_key"}
                )
                print("跳过 Vision ON：未配置 AUTOPILOT_VISION_API_KEY / OPENAI_API_KEY 等")
                continue
            os.environ["AUTOPILOT_INTENT_VISION"] = "1"
            if args.vision_when:
                os.environ["AUTOPILOT_VISION_WHEN"] = args.vision_when
        else:
            os.environ["AUTOPILOT_INTENT_VISION"] = "0"

        # 复用本文件 main 战役逻辑：临时改 args 跑子目录
        saved = (
            args.vision,
            args.work_dir,
            args.compare_vision,
            args.keep_work,
        )
        try:
            args.vision = vision_on
            args.compare_vision = False
            args.keep_work = True
            args.work_dir = str(base / label)
            code = _run_campaign_body(args)
        finally:
            args.vision, args.work_dir, args.compare_vision, args.keep_work = saved

        if code:
            exit_code = code
        summary_path = base / label / "reports" / "hitrate_summary.json"
        leg_info: dict = {"leg": label, "skipped": False, "exit_code": code}
        if summary_path.is_file():
            try:
                leg_info["summary"] = json.loads(
                    summary_path.read_text(encoding="utf-8")
                ).get("overall")
            except (OSError, json.JSONDecodeError):
                pass
        compare["legs"].append(leg_info)

    compare["finished_at"] = datetime.now(timezone.utc).isoformat()
    out = base / "compare_summary.json"
    out.write_text(json.dumps(compare, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mirror = ROOT / "logs" / f"intent_hitrate_compare_{args.platform}_{_now_stamp()}.json"
    shutil.copy2(out, mirror)
    print(f"\n对照汇总 → {mirror}")
    return exit_code


def _run_campaign_body(args: argparse.Namespace) -> int:
    """单次命中率战役（main 主体）。"""
    if args.vision:
        os.environ["AUTOPILOT_INTENT_VISION"] = "1"
    else:
        os.environ["AUTOPILOT_INTENT_VISION"] = "0"
    if args.vision_when:
        os.environ["AUTOPILOT_VISION_WHEN"] = args.vision_when

    case_names = list(args.cases) if args.cases else list(DEFAULT_CASES.get(args.platform, []))
    if not case_names:
        print(f"错误：平台 {args.platform} 无默认用例，请用 --cases 指定", file=sys.stderr)
        return 2

    work = Path(args.work_dir) if args.work_dir else (ROOT / "logs" / f"intent_hitrate_{_now_stamp()}")
    case_paths = _prepare_project(work, case_names)
    print(f"工程: {work}")
    print(f"用例: {[p.name for p in case_paths]}")
    print(
        f"Vision={'ON' if os.environ.get('AUTOPILOT_INTENT_VISION', '').strip() in ('1', 'true', 'yes', 'on') else 'OFF'}"
        f" when={os.environ.get('AUTOPILOT_VISION_WHEN', 'fallback')}"
    )

    udid = (args.udid or "").strip()
    if not udid:
        if args.platform == "android":
            udid = os.environ.get("ANDROID_SERIAL", "").strip()
        elif args.platform == "ios":
            udid = os.environ.get("IOS_PARITY_UDID", "").strip()
        if args.platform in {"android", "ios"} and not udid:
            print("请通过 --udid 或 ANDROID_SERIAL / IOS_PARITY_UDID 指定设备", file=sys.stderr)
            return 2
    wda_bundle = (getattr(args, "wda_bundle", "") or os.environ.get("IOS_WDA_BUNDLE") or "").strip()
    skip_prep = bool(getattr(args, "skip_ios_prep", False))
    if args.platform == "ios":
        if not skip_prep:
            _prepare_ios_wda(udid, wda_bundle=wda_bundle)
        else:
            print("[ios-prep] 跳过隧道/runwda（--skip-ios-prep）", flush=True)
        # 无论是否 prep，都按当前 Settings 文案改写 fixture（英/中）
        _adapt_ios_labels(udid, case_paths)
        skip_prep = True  # 后续轮次复用已起的 WDA

    rounds = max(1, int(args.rounds))
    if args.heal_probe and rounds < 2:
        rounds = 2

    report: dict = {
        "schema": "intent_hitrate.v1",
        "platform": args.platform,
        "udid": udid if args.platform != "web" else "",
        "vision": os.environ.get("AUTOPILOT_INTENT_VISION", "0"),
        "vision_when": os.environ.get("AUTOPILOT_VISION_WHEN", "fallback"),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "rounds": [],
    }

    from autopilot.report import cases_from_suite, write_result_json

    overall = Counter()
    exit_code = 0
    for i in range(1, rounds + 1):
        if args.heal_probe and i == 2:
            n = _corrupt_bindings(work)
            print(f"\n--- heal-probe: 已腐蚀 {n} 个 Binding 文件 ---")
        print(f"\n=== Round {i}/{rounds} ===")
        t0 = time.monotonic()
        suite = _run_once(
            case_paths=case_paths,
            platform=args.platform,
            udid=udid,
            project_dir=work,
            verbose=args.verbose,
            wda_bundle=wda_bundle,
            skip_ios_prep=skip_prep,
        )
        elapsed = int((time.monotonic() - t0) * 1000)
        hits = _collect_hits(suite)
        summary = _summarize(hits)
        overall.update(
            {
                k: hits[k]
                for k in (
                    "cache",
                    "resolved",
                    "healed",
                    "rolled_back",
                    "failed",
                    "unknown",
                    "heal_flag",
                )
            }
        )
        for k, v in hits.items():
            if str(k).startswith("reason:"):
                overall[k] += v
        c = suite.case_counts()
        print(
            f"用例 {c['passed']}/{c['total']} 通过 | intent 命中率 "
            f"{summary['hit_rate']:.0%} "
            f"(cache={summary['cache']} resolved={summary['resolved']} "
            f"healed={summary['healed']} rolled_back={summary.get('rolled_back', 0)} "
            f"failed={summary['failed']}) "
            f"| {elapsed}ms"
        )
        if c["failed"]:
            exit_code = 1
        result_path = work / "reports" / f"result_round{i}.json"
        write_result_json(
            str(result_path),
            job_id=f"intent-hitrate-{args.platform}-r{i}",
            status="passed" if c["failed"] == 0 else "failed",
            suite_name=suite.name,
            passed=c["passed"],
            failed=c["failed"],
            total=c["total"],
            duration_ms=elapsed,
            project_id="intent-hitrate",
            platform=args.platform,
            device_udids=[args.udid] if args.udid and args.platform != "web" else None,
            cases=cases_from_suite(suite, project_dir=str(work)),
        )
        report["rounds"].append(
            {
                "round": i,
                "summary": summary,
                "case_counts": c,
                "duration_ms": elapsed,
                "steps": _intent_step_rows(suite),
                "result_json": str(result_path),
            }
        )

    report["overall"] = _summarize(overall)
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    out_json = work / "reports" / "hitrate_summary.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    mirror = logs / f"intent_hitrate_{args.platform}_{_now_stamp()}.json"
    shutil.copy2(out_json, mirror)
    print(f"\n汇总: 命中率 {report['overall']['hit_rate']:.0%} → {mirror}")
    return exit_code


def main() -> int:
    # 与 run.py / intent CLI 一致：加载仓库根 .env（已有环境变量不覆盖）
    try:
        from autopilot.runtime.env_file import load_env_file

        load_env_file(ROOT / ".env", override=False)
    except (ImportError, OSError, TypeError, ValueError):
        pass

    ap = argparse.ArgumentParser(description="Intent 真机/浏览器命中率验证")
    ap.add_argument("--platform", choices=["android", "web", "ios"], default="android")
    ap.add_argument(
        "--udid",
        default="",
        help="设备 UDID（android 读 ANDROID_SERIAL，ios 读 IOS_PARITY_UDID；勿把实验室序列号写进仓库）",
    )
    ap.add_argument("--wda-bundle", default="", help="iOS WDA bundle id（空=自动发现）")
    ap.add_argument(
        "--skip-ios-prep",
        action="store_true",
        help="跳过隧道/runwda（已手工起好 WDA:8100 时用）",
    )
    ap.add_argument("--cases", nargs="*", help="覆盖默认 fixture 用例文件名")
    ap.add_argument("--rounds", type=int, default=1, help="重复轮次（≥2 可观察 cache）")
    ap.add_argument(
        "--heal-probe",
        action="store_true",
        help="第 1 轮结束后腐蚀 Binding，再跑一轮期望 healed",
    )
    ap.add_argument("--vision", action="store_true", help="设置 AUTOPILOT_INTENT_VISION=1")
    ap.add_argument(
        "--compare-vision",
        action="store_true",
        help="先后跑 Vision OFF/ON 对照（无 API Key 时 ON 轮跳过并记录）",
    )
    ap.add_argument("--vision-when", default="", help="fallback|empty|always")
    ap.add_argument("--work-dir", default="", help="临时工程目录（默认 logs/intent_hitrate_<ts>）")
    ap.add_argument("--keep-work", action="store_true", help="保留临时工程")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if args.compare_vision:
        return _run_vision_compare(args)
    return _run_campaign_body(args)


if __name__ == "__main__":
    raise SystemExit(main())
