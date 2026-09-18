"""真机验证：应用解析 P0 链路（resolve / bootstrap / use_current_app）。

用法::

    python tools/verify_app_resolve_chain.py [--android SERIAL] [--ios UDID]

退出码：0=全部通过，1=有失败项。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from autopilot.authoring.app_resolve import (  # noqa: E402
    AppResolveAmbiguousError,
    AppResolveNotFoundError,
    InstalledApp,
    rank_app_matches,
    resolve_installed_app,
)
from autopilot.authoring.contract import AuthoringError, AuthoringRequest  # noqa: E402
from autopilot.authoring.session_bootstrap import prepare_authoring_session  # noqa: E402


def _ok(name: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"[PASS] {name}{suffix}")


def _fail(name: str, detail: str) -> None:
    print(f"[FAIL] {name} — {detail}")


def _detect_android_serial(explicit: str) -> str:
    if explicit:
        return explicit
    from autopilot.mobile.android_devices import list_usb_devices

    devs = list_usb_devices()
    if not devs:
        raise AuthoringError("未检测到 Android 设备")
    return devs[0].serial


def _detect_ios_udid(explicit: str) -> str:
    if explicit:
        return explicit
    from autopilot.mobile.ios_devices import list_usb_devices as list_ios_usb_devices

    devs = list_ios_usb_devices()
    if not devs:
        raise AuthoringError("未检测到 iOS 设备")
    return devs[0].udid


def verify_android_resolve(serial: str) -> bool:
    ok = True
    try:
        hit = resolve_installed_app("android", udid=serial, app_name="设置")
        if hit.package_name:
            _ok("android/设置解析", f"{hit.app_label} → {hit.package_name}")
        else:
            _fail("android/设置解析", "包名为空")
            ok = False
    except AuthoringError as exc:
        _fail("android/设置解析", str(exc))
        ok = False

    try:
        os.environ["AUTOPILOT_AUTHORING_LABEL_PROBES"] = "0"
        resolve_installed_app("android", udid=serial, app_name="绝对不存在的应用名xyz123")
        _fail("android/未命中", "应抛出 AppResolveNotFoundError")
        ok = False
    except AppResolveNotFoundError as exc:
        n = len(exc.candidates)
        _ok("android/未命中候选", f"附带 {n} 个候选")
        if n <= 0:
            _fail("android/未命中候选", "候选列表为空")
            ok = False
    except AuthoringError as exc:
        _fail("android/未命中", str(exc))
        ok = False

    return ok


def verify_ios_resolve(udid: str) -> bool:
    ok = True
    try:
        hit = resolve_installed_app("ios", udid=udid, app_name="设置")
        if "Preferences" in hit.package_name or "preferences" in hit.package_name.lower():
            _ok("ios/设置解析", f"{hit.app_label} → {hit.package_name}")
        else:
            _ok("ios/设置解析", f"{hit.app_label} → {hit.package_name}（非 Preferences，可能系统差异）")
    except AuthoringError as exc:
        _fail("ios/设置解析", str(exc))
        ok = False

    try:
        resolve_installed_app("ios", udid=udid, app_name="绝对不存在的应用名xyz123")
        _fail("ios/未命中", "应抛出 AppResolveNotFoundError")
        ok = False
    except AppResolveNotFoundError as exc:
        _ok("ios/未命中候选", f"附带 {len(exc.candidates)} 个候选")
    except AuthoringError as exc:
        _fail("ios/未命中", str(exc))
        ok = False

    return ok


def verify_bootstrap_use_current_app(platform: str, udid: str) -> bool:
    ok = True
    try:
        boot = prepare_authoring_session(
            AuthoringRequest(
                natural_language="在当前页面执行一步操作",
                platform=platform,
                mode="session",
                use_current_app=True,
            ),
            preferred_udid=udid,
            allow_nl_llm=False,
        )
        if not boot.request.use_current_app:
            _fail(f"{platform}/use_current_app", "request.use_current_app 未置位")
            ok = False
        elif boot.request.package_name:
            _fail(f"{platform}/use_current_app", f"包名应为空，实际 {boot.request.package_name!r}")
            ok = False
        else:
            _ok(f"{platform}/use_current_app bootstrap", "；".join(boot.notes[:2]))
    except AuthoringError as exc:
        _fail(f"{platform}/use_current_app bootstrap", str(exc))
        ok = False
    return ok


def verify_bootstrap_pick_app(platform: str, udid: str) -> bool:
    """模拟 UI pick_app：未命中时从候选中择一。"""
    picked: list[InstalledApp] = []

    def pick_app(_hint: str, cands: list[InstalledApp]) -> InstalledApp | None:
        if not cands:
            return None
        picked.append(cands[0])
        return cands[0]

    try:
        boot = prepare_authoring_session(
            AuthoringRequest(
                natural_language="打开神秘应用xyz",
                platform=platform,
                mode="session",
                app_label="神秘应用xyz",
            ),
            preferred_udid=udid,
            pick_app=pick_app,
            allow_nl_llm=False,
        )
        if not picked:
            _fail(f"{platform}/pick_app", "pick_app 未被调用")
            return False
        _ok(
            f"{platform}/pick_app 回落",
            f"用户择一 → {boot.request.package_name}",
        )
        return True
    except AuthoringError as exc:
        _fail(f"{platform}/pick_app", str(exc))
        return False


def verify_rank_on_device(platform: str, udid: str) -> bool:
    """在真机应用列表上跑 rank（不要求歧义）。"""
    try:
        if platform == "android":
            from autopilot.authoring.app_resolve import list_android_installed_packages

            apps = list_android_installed_packages(udid)
            hint = "设置"
        else:
            from autopilot.authoring.app_resolve import list_ios_installed_apps

            apps = list_ios_installed_apps(udid)
            hint = "设置"
        ranked = rank_app_matches(apps, hint, platform=platform, limit=5)
        if not ranked:
            _fail(f"{platform}/rank", f"「{hint}」无匹配分")
            return False
        top = ranked[0]
        _ok(
            f"{platform}/rank",
            f"top={top[1].app_label}({top[1].package_name}) score={top[0]}",
        )
        if len(ranked) >= 2 and top[0] - ranked[1][0] <= 10 and ranked[1][0] >= 60:
            _ok(f"{platform}/rank 歧义检测", "存在接近分数候选（IDE 会弹窗）")
        return True
    except (AuthoringError, AppResolveAmbiguousError) as exc:
        _fail(f"{platform}/rank", str(exc))
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="应用解析 P0 真机验证")
    parser.add_argument("--android", default="", help="Android serial（默认第一台）")
    parser.add_argument("--ios", default="", help="iOS UDID（默认第一台）")
    parser.add_argument("--skip-android", action="store_true")
    parser.add_argument("--skip-ios", action="store_true")
    args = parser.parse_args(argv)

    all_ok = True

    if not args.skip_android:
        try:
            serial = _detect_android_serial(args.android.strip())
            print(f"\n=== Android {serial} ===")
            all_ok &= verify_android_resolve(serial)
            all_ok &= verify_rank_on_device("android", serial)
            all_ok &= verify_bootstrap_use_current_app("android", serial)
            all_ok &= verify_bootstrap_pick_app("android", serial)
        except AuthoringError as exc:
            _fail("android/设备", str(exc))
            all_ok = False

    if not args.skip_ios:
        try:
            udid = _detect_ios_udid(args.ios.strip())
            print(f"\n=== iOS {udid} ===")
            all_ok &= verify_ios_resolve(udid)
            all_ok &= verify_rank_on_device("ios", udid)
            all_ok &= verify_bootstrap_use_current_app("ios", udid)
            all_ok &= verify_bootstrap_pick_app("ios", udid)
        except AuthoringError as exc:
            _fail("ios/设备", str(exc))
            all_ok = False

    print()
    if all_ok:
        print("[DONE] 真机验证全部通过")
        return 0
    print("[DONE] 存在失败项")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
