"""P2/P3 边界回归：android-only 元数据、iOS combo 点选、parity CI 离线校验。"""

from __future__ import annotations

import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def test_android_only_browser_and_network_meta() -> bool:
    from autopilot.metadata import load_catalog
    from autopilot.metadata.keyword_platforms import (
        ANDROID_ONLY_KEYWORD_IDS,
        platform_mismatch_reason,
    )

    cat = load_catalog()
    ids = (
        "mobile_browser_open",
        "mobile_browser_close",
        "mobile_browser_locate",
        "mobile_set_network",
    )
    missing = [
        kid for kid in ids
        if kid not in ANDROID_ONLY_KEYWORD_IDS
        or cat.get(kid) is None
        or cat.get(kid).platforms != ["android"]
    ]
    reasons = [platform_mismatch_reason("ios", cat.get(kid)) for kid in ids]
    ok = not missing and all(r.startswith("Android 专有") for r in reasons)
    print("browser/network android-only 元数据:", "OK" if ok else f"FAIL {missing}")
    return ok


def test_ios_combo_select_by_text() -> bool:
    from autopilot.mobile.ios.picker import ios_combo_select

    combo = MagicMock()
    opt = MagicMock()
    opt.is_displayed.return_value = True
    drv = MagicMock()
    drv.find_elements.return_value = [opt]

    ios_combo_select(drv, combo, "内容", "北京")

    combo.click.assert_called_once()
    opt.click.assert_called_once()
    ok = drv.find_elements.call_count == 1
    print("ios combo 按文本点选:", "OK" if ok else "FAIL")
    return ok


def test_ios_combo_select_by_index() -> bool:
    from autopilot.mobile.ios.picker import ios_combo_select

    combo = MagicMock()
    opts = [MagicMock(), MagicMock()]
    for o in opts:
        o.is_displayed.return_value = True
    drv = MagicMock()
    drv.find_elements.return_value = opts

    ios_combo_select(drv, combo, "索引", "1")

    opts[1].click.assert_called_once()
    print("ios combo 按索引点选:", "OK")
    return True


def test_ios_reject_android_browser_keyword() -> bool:
    from autopilot.keywords.mobile.session import browser_open, _reject_ios_android_only
    from autopilot.keywords.registry import KeywordError
    from autopilot.keywords.context import ExecutionContext

    ctx = ExecutionContext()
    mgr = SimpleNamespace(platform="ios", has_driver=False)
    # patch get_manager via importing module
    import autopilot.keywords.mobile.session as sess_mod

    old = sess_mod.get_manager
    sess_mod.get_manager = lambda _c: mgr
    try:
        try:
            _reject_ios_android_only(ctx, "mobile_browser_open")
            ok = False
        except KeywordError as e:
            ok = "仅支持 Android" in str(e) and "native_web_swith_context" in str(e)
        try:
            browser_open(ctx)
            ok = False
        except KeywordError:
            pass
    finally:
        sess_mod.get_manager = old
    print("iOS 拦截 mobile_browser_open:", "OK" if ok else "FAIL")
    return ok


def test_infra_parity_case_ids() -> bool:
    from tests.ios_parity_skeleton import infra_parity_case_ids, PARITY_CASES

    ids = infra_parity_case_ids()
    expected = {c["name"] for c in PARITY_CASES if "infra" in (c.get("tags") or [])}
    ok = set(ids) == expected and len(ids) == 3
    print("infra parity ids:", "OK" if ok else f"FAIL {ids}")
    return ok


def test_parity_run_validate_only() -> bool:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(root, "tools", "ios_parity_run.py")
    proc = subprocess.run(
        [sys.executable, script, "--validate-only"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
    )
    ok = proc.returncode == 0 and "parity 骨架" in (proc.stdout + proc.stderr)
    print("ios_parity_run --validate-only:", "OK" if ok else f"FAIL rc={proc.returncode}")
    if not ok and proc.stderr:
        print(proc.stderr[:500])
    return ok


def main() -> int:
    ok = all([
        test_android_only_browser_and_network_meta(),
        test_ios_combo_select_by_text(),
        test_ios_combo_select_by_index(),
        test_ios_reject_android_browser_keyword(),
        test_infra_parity_case_ids(),
        test_parity_run_validate_only(),
    ])
    print("\n总结:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
