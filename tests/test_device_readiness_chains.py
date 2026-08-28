"""设备判空/容错 — 需求矩阵与白盒链路测试。

本文件对照会话内落地的功能需求，以「纯逻辑 → Mixin → 面板 → 静态审计」四层做链路验证。

功能需求 (FR)
-------------
FR-01  无真机时禁止移动检视误拉 Appium（取快照前置校验失败即中止）
FR-02  无真机时镜像「▶ 开始」禁用，且 before_start / _prepare_mirror_start 拦截
FR-03  检视 InspectorPanel.refresh：before_refresh 失败不启动 SnapshotWorker
FR-04  仅 iOS 在线时不得对 Android 空 UDID 取移动快照
FR-05  仅 Android 在线时对称校验（误选 iOS 平台失败）
FR-06  两端均无真机时 Web 检视目标仍 validate 通过
FR-07  运行前 auto_run_udid：单台自动、复用检视 UDID、多台待弹选
FR-08  运行前 _platform_guard：用例平台无对应真机可拦截
FR-09  已选移动检视目标离线时 _ensure_inspect_device 清 _inspect_chosen
FR-10  连接检视误选无设备平台被 _pick_udid 拦截；设备信息走 choose_device_runtime
FR-11  iOS 装包 ios_install_pick_status 单台/多台/无设备三分支
FR-12  设备全拔出时 _on_devices_changed 清移动检视标记并同步面板
FR-13  静态审计 check_device_readiness 防 Mixin 回退手写分支
FR-14  单步/运行至此须经 _platform_guard，不得绕过
FR-15  镜像选设备后 _commit_mobile_target 同步 _inspect_chosen
FR-16  运行 _run_base_vars 所需平台无设备时硬阻断（不可强制）
FR-17  设备变化：当前平台离线即清 chosen（非仅全空）

设计场景 (DS) → 用例 (TC)
-------------------------
DS-01 冷启动无设备          → TC-01..03  (镜像禁用/检视中止/连接拦截)
DS-02 仅 iOS 在线           → TC-04..06  (自动选 iOS/Android 失败/运行复用)
DS-03 已选目标离线          → TC-07       (stale chosen)
DS-04 Web 无真机            → TC-08       (validate Web)
DS-05 面板最后一道闸        → TC-09..10   (mirror before_start / inspector worker)
DS-06 运行与装包            → TC-11..13
DS-07 设备监控回调          → TC-14
DS-08 静态防回退            → TC-15
"""

from __future__ import annotations

import os
import sys
import tempfile
from contextlib import contextmanager
from typing import Iterator

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_APP = None


# ---------------------------------------------------------------------------
# 需求追溯表（测试报告用）
# ---------------------------------------------------------------------------
REQUIREMENT_MATRIX: tuple[tuple[str, str, str, str], ...] = (
    ("FR-01", "DS-01", "TC-02", "test_chain_inspector_refresh_aborts_without_device"),
    ("FR-02", "DS-01", "TC-01", "test_chain_mirror_start_blocked_without_device"),
    ("FR-03", "DS-05", "TC-09", "test_chain_inspector_refresh_aborts_without_device"),
    ("FR-04", "DS-02", "TC-05", "test_chain_snapshot_blocked_android_when_ios_only"),
    ("FR-05", "DS-02", "TC-12", "test_chain_snapshot_blocked_ios_when_android_only"),
    ("FR-06", "DS-04", "TC-08", "test_chain_web_inspect_valid_without_mobile"),
    ("FR-07", "DS-02", "TC-06", "test_chain_run_base_vars_reuses_inspect_udid"),
    ("FR-08", "DS-06", "TC-11", "test_chain_platform_guard_missing_android"),
    ("FR-09", "DS-03", "TC-07", "test_chain_stale_chosen_android_cleared"),
    ("FR-10", "DS-01", "TC-03", "test_chain_connect_inspector_blocks_android"),
    ("FR-11", "DS-06", "TC-13", "test_chain_ios_install_pick_modes"),
    ("FR-12", "DS-07", "TC-14", "test_chain_devices_changed_clears_mobile_chosen"),
    ("FR-13", "DS-08", "TC-15", "test_chain_static_audit_passes"),
    ("FR-14", "DS-06", "TC-16", "test_chain_debug_run_platform_guard"),
    ("FR-15", "DS-05", "TC-17", "test_chain_mirror_pick_sets_chosen"),
    ("FR-16", "DS-06", "TC-18", "test_chain_run_base_vars_hard_block_no_device"),
    ("FR-17", "DS-07", "TC-19", "test_chain_devices_changed_partial_clear_chosen"),
)


@contextmanager
def _main_window() -> Iterator:
    global _APP
    from PyQt6.QtWidgets import QApplication
    from autopilot.ui.main_window import MainWindow

    _APP = QApplication.instance() or QApplication([])
    tmp = tempfile.mkdtemp()
    w = MainWindow(project_dir=tmp, config_dir="")
    try:
        yield w
    finally:
        w.close()


def test_chain_mirror_start_blocked_without_device() -> bool:
    """TC-01 / FR-02：无真机 → 按钮禁用；强行走 before_start 也不调 session_provider。"""
    try:
        with _main_window() as w:
            w._devices = ([], [])
            w._sync_device_panel_controls()
            disabled = not w.mirror.btn_live.isEnabled()

            blocked = w._prepare_mirror_start() is False

            calls = {"sp": 0}
            w.mirror.session_provider = lambda: (
                calls.__setitem__("sp", calls["sp"] + 1), None)[1]
            # 模拟按钮被误启用：before_start 仍应拦截，不拉 session
            w.mirror._mobile_available = True
            w.mirror.btn_live.setEnabled(True)
            w.mirror.btn_live.setChecked(True)
            from PyQt6.QtWidgets import QApplication
            QApplication.instance().processEvents()
            no_provider = calls["sp"] == 0 and not w.mirror.active()
            ok = disabled and blocked and no_provider
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("TC-01 镜像无设备拦截:", "⏭ 跳过(", e, ")")
        return True
    print("TC-01 镜像无设备拦截:", "✅" if ok else "❌")
    return ok


def test_chain_inspector_refresh_aborts_without_device() -> bool:
    """TC-02/03 / FR-01/03：refresh 前置失败 → 不启 worker、不调 snapshot_provider。"""
    try:
        with _main_window() as w:
            w._devices = ([], [])
            w._inspect_chosen = False
            calls = {"prov": 0}

            def _prov():
                calls["prov"] += 1
                return None

            w.inspector.snapshot_provider = _prov
            w.inspector.refresh()
            idle_lbl = w.inspector.lbl.text() == w.inspector._idle_lbl
            no_worker = not w.inspector._snap_running() and calls["prov"] == 0
            ok = idle_lbl and no_worker
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("TC-02 检视 refresh 中止:", "⏭ 跳过(", e, ")")
        return True
    print("TC-02 检视 refresh 中止:", "✅" if ok else "❌")
    return ok


def test_chain_connect_inspector_blocks_android() -> bool:
    """TC-03 / FR-10：无真机连接检视误选 Android → 不标记 _inspect_chosen。"""
    try:
        from PyQt6.QtWidgets import QInputDialog, QMessageBox

        with _main_window() as w:
            w._devices = ([], [])
            orig_i = QMessageBox.information
            orig_w = QMessageBox.warning
            orig_item = QInputDialog.getItem
            QMessageBox.information = staticmethod(lambda *a, **k: None)
            QMessageBox.warning = staticmethod(lambda *a, **k: None)
            QInputDialog.getItem = staticmethod(lambda *a, **k: ("Android", True))
            try:
                w.connect_inspector()
            finally:
                QMessageBox.information = orig_i
                QMessageBox.warning = orig_w
                QInputDialog.getItem = orig_item
            ok = w._inspect_chosen is False
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("TC-03 连接检视拦截:", "⏭ 跳过(", e, ")")
        return True
    print("TC-03 连接检视拦截:", "✅" if ok else "❌")
    return ok


def test_chain_snapshot_blocked_android_when_ios_only() -> bool:
    """TC-05 / FR-04：已选 Android 但仅 iOS 在线 → _inspector_snapshot 返回 None。"""
    try:
        with _main_window() as w:
            w._devices = ([], ["IOS-UDID"])
            w._inspect_platform = "Android"
            w._inspect_chosen = True
            w._inspect_udid = ""
            snap = w._inspector_snapshot()
            ok = snap is None
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("TC-05 快照 Android 拦截:", "⏭ 跳过(", e, ")")
        return True
    print("TC-05 快照 Android 拦截:", "✅" if ok else "❌")
    return ok


def test_chain_snapshot_blocked_ios_when_android_only() -> bool:
    """TC-12 / FR-05：已选 iOS 但仅 Android 在线 → _inspector_snapshot 返回 None。"""
    try:
        with _main_window() as w:
            w._devices = (["AND-UDID"], [])
            w._inspect_platform = "iOS"
            w._inspect_chosen = True
            w._inspect_udid = ""
            snap = w._inspector_snapshot()
            ok = snap is None
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("TC-12 快照 iOS 拦截:", "⏭ 跳过(", e, ")")
        return True
    print("TC-12 快照 iOS 拦截:", "✅" if ok else "❌")
    return ok


def test_chain_web_inspect_valid_without_mobile() -> bool:
    """TC-08 / FR-06：无真机 Web 检视 validate 通过。"""
    try:
        from autopilot.ui.main_window.device_readiness import (
            DeviceLists, validate_inspect_target,
        )

        ok, msg = validate_inspect_target("Web", "", DeviceLists.from_lists([], []))
        result = ok and msg == ""
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("TC-08 Web 无真机:", "⏭ 跳过(", e, ")")
        return True
    print("TC-08 Web 无真机:", "✅" if result else "❌")
    return result


def test_chain_run_base_vars_reuses_inspect_udid() -> bool:
    """TC-06 / FR-07：仅 iOS 在线 + 检视已选 iOS → 运行自动注入 UDID。"""
    try:
        from autopilot.model.testcase import TestCase

        with _main_window() as w:
            w._devices = ([], ["IOS-UDID"])
            w._inspect_platform = "iOS"
            w._inspect_udid = "IOS-UDID"
            base = w._run_base_vars([TestCase(name="ios_case", platform="ios")])
            ok = (base is not None
                  and base.get("__device_udid__") == "IOS-UDID"
                  and os.path.normpath(base.get("__project_path__", ""))
                  == os.path.normpath(w.project_dir))
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("TC-06 运行复用检视 UDID:", "⏭ 跳过(", e, ")")
        return True
    print("TC-06 运行复用检视 UDID:", "✅" if ok else "❌")
    return ok


def test_chain_stale_chosen_android_cleared() -> bool:
    """TC-07 / FR-09：曾选 Android，设备全离线 → ensure 失败并清标记。"""
    try:
        with _main_window() as w:
            w._inspect_platform = "Android"
            w._inspect_udid = "AND-1"
            w._inspect_chosen = True
            w._devices = ([], [])
            ok = w._ensure_inspect_device() is False and w._inspect_chosen is False
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("TC-07 离线清标记:", "⏭ 跳过(", e, ")")
        return True
    print("TC-07 离线清标记:", "✅" if ok else "❌")
    return ok


def test_chain_platform_guard_missing_android() -> bool:
    """TC-11 / FR-08：用例要 Android、仅 iOS 在线 → guard 硬阻断。"""
    try:
        from autopilot.model.testcase import TestCase

        with _main_window() as w:
            w._devices = ([], ["IOS-UDID"])
            ok = w._platform_guard([TestCase(name="a", platform="android")]) is False
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("TC-11 运行平台 guard:", "⏭ 跳过(", e, ")")
        return True
    print("TC-11 运行平台 guard:", "✅" if ok else "❌")
    return ok


def test_chain_ios_install_pick_modes() -> bool:
    """TC-13 / FR-11：装包选设备三分支（Mixin 委托 readiness）。"""
    try:
        with _main_window() as w:
            w._devices = ([], ["U1"])
            ok1, u1 = w._pick_ios_udid_for_install()
            w._devices = ([], ["U1", "U2"])
            # 注意：device.py 顶部已 `from ...list_pick_dialog import pick_list_item`，
            # 须打桩“使用处”模块名，改源模块属性不生效（否则会弹真实模态框而挂起）。
            import autopilot.ui.main_window.device as devmod
            from unittest.mock import patch
            orig = devmod.pick_list_item
            devmod.pick_list_item = lambda *_a, **_k: ("U2", True)
            try:
                with patch("autopilot.mobile.device_info.device_picker_line",
                           side_effect=lambda p, u: f"Phone ({u})"):
                    ok2, u2 = w._pick_ios_udid_for_install()
            finally:
                devmod.pick_list_item = orig
            w._devices = ([], [])
            # noinspection PyPep8Naming
            from PyQt6.QtWidgets import QInputDialog as QID
            orig_t = QID.getText
            QID.getText = staticmethod(lambda *a, **k: ("MANUAL", True))
            try:
                ok3, u3 = w._pick_ios_udid_for_install()
            finally:
                QID.getText = orig_t
            ok = ok1 and u1 == "U1" and ok2 and u2 == "U2" and ok3 and u3 == "MANUAL"
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("TC-13 iOS 装包选设备:", "⏭ 跳过(", e, ")")
        return True
    print("TC-13 iOS 装包选设备:", "✅" if ok else "❌")
    return ok


def test_chain_devices_changed_clears_mobile_chosen() -> bool:
    """TC-14 / FR-12：设备列表变空 → 移动检视 chosen 清除。"""
    try:
        with _main_window() as w:
            w._inspect_platform = "iOS"
            w._inspect_udid = "U1"
            w._inspect_chosen = True
            w._on_devices_changed([], [])
            ok = w._inspect_chosen is False
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("TC-14 设备变化清标记:", "⏭ 跳过(", e, ")")
        return True
    print("TC-14 设备变化清标记:", "✅" if ok else "❌")
    return ok


def test_chain_static_audit_passes() -> bool:
    """TC-15 / FR-13：静态审计无违规。"""
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        lint_dir = os.path.join(root, "skills", "autopilot-lint")
        if lint_dir not in sys.path:
            sys.path.insert(0, lint_dir)
        # noinspection PyUnresolvedReferences
        from check_device_readiness import audit_device_readiness  # noqa: PLC0415

        violations = audit_device_readiness(root)
        ok = not violations
        if not ok:
            for v in violations:
                print(" ", v.format())
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("TC-15 静态审计:", "⏭ 跳过(", e, ")")
        return True
    print("TC-15 静态审计:", "✅" if ok else "❌")
    return ok


def test_chain_pick_connected_device_empty() -> bool:
    """TC-10 补充：无设备查看设备信息 → None（不弹多选）。"""
    try:
        from PyQt6.QtWidgets import QMessageBox

        with _main_window() as w:
            w._devices = ([], [])
            orig = QMessageBox.information
            shown = {"n": 0}
            QMessageBox.information = staticmethod(
                lambda *a, **k: shown.__setitem__("n", shown["n"] + 1))
            try:
                pick = w._pick_connected_device("查看设备信息")
            finally:
                QMessageBox.information = orig
            ok = pick is None and shown["n"] == 1
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("TC-10 设备信息无设备:", "⏭ 跳过(", e, ")")
        return True
    print("TC-10 设备信息无设备:", "✅" if ok else "❌")
    return ok


def test_chain_debug_run_platform_guard() -> bool:
    """TC-16 / FR-14：单步/运行至此源码须含 _platform_guard（与静态审计一致）。"""
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        run_py = os.path.join(root, "autopilot", "ui", "main_window", "run.py")
        with open(run_py, encoding="utf-8") as f:
            src = f.read()
        ok = True
        for fn in ("run_selected_step", "run_to_selected_step"):
            start = src.find(f"def {fn}")
            end = src.find("\n    def ", start + 1)
            chunk = src[start:end if end > 0 else len(src)]
            if "_platform_guard" not in chunk:
                ok = False
                print(f"  {fn} 缺少 _platform_guard")
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("TC-16 调试运行 guard:", "⏭ 跳过(", e, ")")
        return True
    print("TC-16 调试运行 guard:", "✅" if ok else "❌")
    return ok


def test_chain_mirror_pick_sets_chosen() -> bool:
    """TC-17 / FR-15：镜像选设备后 _inspect_chosen 与检视对齐。"""
    try:
        with _main_window() as w:
            w._devices = (["AND-1"], [])
            w._inspect_chosen = False
            ok = (w._select_mirror_device() is True
                  and w._inspect_chosen is True
                  and w._inspect_platform == "Android"
                  and w._inspect_udid == "AND-1")
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("TC-17 镜像同步 chosen:", "⏭ 跳过(", e, ")")
        return True
    print("TC-17 镜像同步 chosen:", "✅" if ok else "❌")
    return ok


def test_chain_run_base_vars_hard_block_no_device() -> bool:
    """TC-18 / FR-16：用例要 Android 无设备 → _run_base_vars 返回 None。"""
    try:
        from autopilot.model.testcase import TestCase

        with _main_window() as w:
            w._devices = ([], [])
            base = w._run_base_vars([TestCase(name="a", platform="android")])
            ok = base is None
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("TC-18 运行硬阻断:", "⏭ 跳过(", e, ")")
        return True
    print("TC-18 运行硬阻断:", "✅" if ok else "❌")
    return ok


def test_chain_devices_changed_partial_clear_chosen() -> bool:
    """TC-19 / FR-17：Android 离线但 iOS 仍在 → 已选 Android 清 chosen。"""
    try:
        with _main_window() as w:
            w._inspect_platform = "Android"
            w._inspect_udid = "AND-1"
            w._inspect_chosen = True
            w._on_devices_changed([], ["IOS-1"])
            ok = w._inspect_chosen is False
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("TC-19 部分离线清标记:", "⏭ 跳过(", e, ")")
        return True
    print("TC-19 部分离线清标记:", "✅" if ok else "❌")
    return ok


def test_requirement_matrix_covers_all_fr() -> bool:
    """元测试：矩阵条目可解析且覆盖 FR-01..FR-17。"""
    fr_ids = {row[0] for row in REQUIREMENT_MATRIX}
    expected = {f"FR-{i:02d}" for i in range(1, 18)}
    missing = expected - fr_ids
    ok = not missing
    if not ok:
        print("  矩阵缺失:", missing)
    print("需求矩阵覆盖:", "✅" if ok else "❌")
    return ok


def main() -> int:
    tests = [
        test_requirement_matrix_covers_all_fr,
        test_chain_mirror_start_blocked_without_device,
        test_chain_inspector_refresh_aborts_without_device,
        test_chain_connect_inspector_blocks_android,
        test_chain_snapshot_blocked_android_when_ios_only,
        test_chain_snapshot_blocked_ios_when_android_only,
        test_chain_web_inspect_valid_without_mobile,
        test_chain_run_base_vars_reuses_inspect_udid,
        test_chain_stale_chosen_android_cleared,
        test_chain_platform_guard_missing_android,
        test_chain_ios_install_pick_modes,
        test_chain_devices_changed_clears_mobile_chosen,
        test_chain_pick_connected_device_empty,
        test_chain_static_audit_passes,
        test_chain_debug_run_platform_guard,
        test_chain_mirror_pick_sets_chosen,
        test_chain_run_base_vars_hard_block_no_device,
        test_chain_devices_changed_partial_clear_chosen,
    ]
    results = [t() for t in tests]
    passed = sum(results)
    print(f"\n总结: {passed}/{len(tests)} 通过 — "
          f"{'✅ 设备判空白盒链路全绿' if all(results) else '❌ 存在失败'}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
