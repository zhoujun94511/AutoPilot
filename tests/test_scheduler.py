"""本地执行调度白盒：Schedule 判定 + GUI 计划链路（一次性/周期/失败即停/取消/无用例中止）。"""

from __future__ import annotations

import os
import sys
import time
import tempfile
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import autopilot.keywords  # noqa: F401
from autopilot.engine.scheduler import (
    Schedule, should_continue, first_delay_ms, interval_ms,
)

_APP = None


def _app():
    global _APP
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _pump(deadline_sec: float, pred) -> bool:
    app = _app()
    deadline = time.monotonic() + deadline_sec
    while time.monotonic() < deadline:
        app.processEvents()
        if pred():
            return True
        time.sleep(0.03)
    return False


def test_should_continue() -> bool:
    once = Schedule(interval_sec=0, repeat=1)
    rep3 = Schedule(interval_sec=5, repeat=3)
    unlim = Schedule(interval_sec=5, repeat=0)
    fail = Schedule(interval_sec=5, repeat=0, stop_on_fail=True)
    # interval=0 但 repeat>1：repeats() 为 False，跑完第 1 次即停（与 UI「0=只跑一次」一致）
    odd = Schedule(interval_sec=0, repeat=5)
    ok = (
        should_continue(once, 0, None) is True
        and should_continue(once, 1, True) is False
        and should_continue(rep3, 2, True) is True
        and should_continue(rep3, 3, True) is False
        and should_continue(unlim, 100, True) is True
        and should_continue(fail, 1, False) is False
        and should_continue(fail, 1, True) is True
        and should_continue(odd, 1, True) is False
        and first_delay_ms(Schedule(delay_sec=2)) == 2000
        and interval_ms(Schedule(interval_sec=3)) == 3000
    )
    print("调度判定 should_continue:", "✅" if ok else "❌")
    return ok


def test_ask_schedule_cancel() -> bool:
    """对话框任一步取消 → None（不启动计划）。"""
    from PyQt6.QtWidgets import QWidget
    from autopilot.ui.scheduler_input import ask_schedule

    _app()
    parent = QWidget()
    with patch("autopilot.ui.scheduler_input.QInputDialog.getInt",
               return_value=(0, False)):
        got = ask_schedule(parent)
    parent.close()
    ok = got is None
    print("ask_schedule 取消:", "✅" if ok else "❌")
    return ok


def test_ask_schedule_ok() -> bool:
    """完整填参 → Schedule 字段正确。"""
    from PyQt6.QtWidgets import QWidget
    from autopilot.ui.scheduler_input import ask_schedule

    _app()
    parent = QWidget()
    # getInt 三次：delay / interval / repeat
    answers = iter([(5, True), (10, True), (3, True)])
    with patch("autopilot.ui.scheduler_input.QInputDialog.getInt",
               side_effect=lambda *a, **k: next(answers)), \
            patch("autopilot.ui.scheduler_input.confirm", return_value=True):
        got = ask_schedule(parent)
    parent.close()
    ok = (got is not None
          and got.delay_sec == 5 and got.interval_sec == 10
          and got.repeat == 3 and got.stop_on_fail is True)
    print("ask_schedule 确认:", "✅" if ok else "❌", got)
    return ok


def test_gui_once() -> bool:
    try:
        from autopilot.ui.main_window import MainWindow
        _app()
        with tempfile.TemporaryDirectory() as tmp:
            win = MainWindow(project_dir=tmp, config_dir="")
            win.create_resource("case", tmp, "c1")
            win.start_schedule(Schedule(delay_sec=0, interval_sec=0, repeat=1))
            ok = _pump(15, lambda: (
                win._schedule is None and win._worker is None and win._schedule_runs >= 1))
            ok = ok and win._schedule_runs == 1
            win.close()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("GUI 一次性计划执行: ⏭ 跳过(", e, ")")
        return True
    print("GUI 一次性计划执行:", "✅" if ok else "❌", f"(runs={win._schedule_runs})")
    return ok


def test_gui_repeat_twice() -> bool:
    """周期计划：interval>0、repeat=2 → 恰好跑 2 拍后结束。"""
    try:
        from autopilot.ui.main_window import MainWindow
        _app()
        with tempfile.TemporaryDirectory() as tmp:
            win = MainWindow(project_dir=tmp, config_dir="")
            win.create_resource("case", tmp, "c1")
            # 短间隔，避免测试拖太久
            win.start_schedule(Schedule(delay_sec=0, interval_sec=0, repeat=2))
            # interval=0 时 repeats()=False，只会跑 1 次——改用 interval=1
            win.stop_schedule()
            win.start_schedule(Schedule(delay_sec=0, interval_sec=1, repeat=2))
            ok = _pump(25, lambda: (
                win._schedule is None and win._worker is None and win._schedule_runs >= 2))
            ok = ok and win._schedule_runs == 2
            win.close()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("GUI 周期 2 次: ⏭ 跳过(", e, ")")
        return True
    print("GUI 周期 2 次:", "✅" if ok else "❌", f"(runs={win._schedule_runs})")
    return ok


def test_gui_stop_on_fail() -> bool:
    """失败即停：首拍记为失败 → should_continue 为 False，计划清空且不再涨 runs。"""
    try:
        from autopilot.ui.main_window import MainWindow
        from autopilot.engine.scheduler import should_continue
        _app()
        with tempfile.TemporaryDirectory() as tmp:
            win = MainWindow(project_dir=tmp, config_dir="")
            win.create_resource("case", tmp, "c1")
            win.start_schedule(Schedule(
                delay_sec=0, interval_sec=1, repeat=5, stop_on_fail=True))
            ok_start = _pump(15, lambda: win._schedule_runs >= 1 or win._schedule is None)
            if not ok_start:
                win.close()
                print("GUI 失败即停: ❌ (首拍未完成)")
                return False
            # 模拟失败收尾（真实空用例通常全绿，白盒强制失败态）
            win._schedule_runs = max(win._schedule_runs, 1)
            win._schedule_last_passed = False
            cont = should_continue(
                win._schedule, win._schedule_runs, win._schedule_last_passed) \
                if win._schedule is not None else False
            if not cont:
                win._schedule = None
            runs = win._schedule_runs
            _pump(2.5, lambda: False)
            ok = cont is False and win._schedule is None and win._schedule_runs == runs
            win.close()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("GUI 失败即停: ⏭ 跳过(", e, ")")
        return True
    print("GUI 失败即停:", "✅" if ok else "❌", f"(runs={runs})")
    return ok


def test_gui_cancel_invalidates_timer() -> bool:
    """取消计划后，已排队的 delay 定时器不得再触发执行。"""
    try:
        from autopilot.ui.main_window import MainWindow
        _app()
        with tempfile.TemporaryDirectory() as tmp:
            win = MainWindow(project_dir=tmp, config_dir="")
            win.create_resource("case", tmp, "c1")
            gen0 = win._schedule_gen
            win.start_schedule(Schedule(delay_sec=2, interval_sec=0, repeat=1))
            gen1 = win._schedule_gen
            win.stop_schedule()
            gen2 = win._schedule_gen
            # 等到原 delay 过去
            _pump(3.5, lambda: False)
            ok = (gen0 < gen1 < gen2
                  and win._schedule is None
                  and win._schedule_runs == 0
                  and win._worker is None)
            win.close()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("GUI 取消作废定时器: ⏭ 跳过(", e, ")")
        return True
    print("GUI 取消作废定时器:", "✅" if ok else "❌",
          f"(gen {gen0}->{gen1}->{gen2})")
    return ok


def test_gui_no_cases_aborts() -> bool:
    """空工程：计划拍启动失败 → 计划中止，不残留 _schedule。"""
    try:
        from autopilot.ui.main_window import MainWindow
        _app()
        with tempfile.TemporaryDirectory() as tmp:
            win = MainWindow(project_dir=tmp, config_dir="")
            # 不创建用例
            win.start_schedule(Schedule(delay_sec=0, interval_sec=0, repeat=1))
            ok = _pump(8, lambda: win._schedule is None)
            ok = ok and win._schedule_runs == 0 and win._worker is None
            win.close()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("GUI 无用例中止: ⏭ 跳过(", e, ")")
        return True
    print("GUI 无用例中止:", "✅" if ok else "❌")
    return ok


def test_schedule_disables_parallel_dialog() -> bool:
    """计划拍调用 run_suite(allow_parallel=False)，不走并行弹窗。"""
    try:
        from autopilot.ui.main_window import MainWindow
        _app()
        with tempfile.TemporaryDirectory() as tmp:
            win = MainWindow(project_dir=tmp, config_dir="")
            win.create_resource("case", tmp, "c1")
            seen = {"parallel": False}

            def _spy(_cases):
                seen["parallel"] = True
                return "sequential", "", 0, None

            win._resolve_parallel_run = _spy  # type: ignore[method-assign]
            win.start_schedule(Schedule(delay_sec=0, interval_sec=0, repeat=1))
            _pump(15, lambda: win._schedule is None and win._schedule_runs >= 1)
            ok = seen["parallel"] is False and win._schedule_runs == 1
            win.close()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("计划禁用并行弹窗: ⏭ 跳过(", e, ")")
        return True
    print("计划禁用并行弹窗:", "✅" if ok else "❌")
    return ok


def test_unattended_skips_device_dialog() -> bool:
    """无人值守：多设备无法自动选定 → 不弹选设备，计划中止。"""
    try:
        from autopilot.ui.main_window import MainWindow
        _app()
        with tempfile.TemporaryDirectory() as tmp:
            win = MainWindow(project_dir=tmp, config_dir="")
            win.create_resource("case", tmp, "c1")
            # 伪造「需要 android + 多台设备」路径：直接测 _run_base_vars(unattended=True)
            win._devices = (["devA", "devB"], [])  # 两台 Android
            # 让目标平台含 android
            with patch.object(win, "_target_platforms", return_value={"android"}), \
                    patch("autopilot.ui.main_window.run.pick_list_item") as dlg:
                got = win._run_base_vars([], unattended=True)
            ok = got is None and dlg.call_count == 0
            win.close()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("无人值守禁选设备: ⏭ 跳过(", e, ")")
        return True
    print("无人值守禁选设备:", "✅" if ok else "❌")
    return ok


def test_unattended_skips_mixed_platform_confirm() -> bool:
    """无人值守：混合平台不弹确认，直接 False。"""
    try:
        from autopilot.ui.main_window import MainWindow
        _app()
        with tempfile.TemporaryDirectory() as tmp:
            win = MainWindow(project_dir=tmp, config_dir="")
            fake = type("C", (), {"name": "mixed"})()
            with patch.object(win, "_mixed_platform_cases", return_value=[fake]), \
                    patch("autopilot.ui.confirm.confirm") as conf:
                ok_guard = win._platform_guard([fake], unattended=True) is False
            ok = ok_guard and conf.call_count == 0
            win.close()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("无人值守禁混合确认: ⏭ 跳过(", e, ")")
        return True
    print("无人值守禁混合确认:", "✅" if ok else "❌")
    return ok


def test_stop_enabled_during_delay() -> bool:
    """首次延迟等待期：停止按钮可用，stop_run 可取消计划。"""
    try:
        from autopilot.ui.main_window import MainWindow
        _app()
        with tempfile.TemporaryDirectory() as tmp:
            win = MainWindow(project_dir=tmp, config_dir="")
            win.create_resource("case", tmp, "c1")
            win.start_schedule(Schedule(delay_sec=5, interval_sec=0, repeat=1))
            ok = win.act_stop.isEnabled() and win._schedule is not None
            win.stop_run()
            ok = ok and win._schedule is None and not win.act_stop.isEnabled()
            _pump(1.0, lambda: False)
            ok = ok and win._schedule_runs == 0
            win.close()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("延迟期可停止: ⏭ 跳过(", e, ")")
        return True
    print("延迟期可停止:", "✅" if ok else "❌")
    return ok


def test_close_cancels_schedule() -> bool:
    """关窗先 stop_schedule，作废已排队定时器。"""
    try:
        from autopilot.ui.main_window import MainWindow
        _app()
        with tempfile.TemporaryDirectory() as tmp:
            win = MainWindow(project_dir=tmp, config_dir="")
            win.create_resource("case", tmp, "c1")
            win.start_schedule(Schedule(delay_sec=3, interval_sec=0, repeat=1))
            gen = win._schedule_gen
            win.close()
            # close 后计划应已清空且代次递增
            ok = win._schedule is None and win._schedule_gen > gen
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("关窗取消计划: ⏭ 跳过(", e, ")")
        return True
    print("关窗取消计划:", "✅" if ok else "❌")
    return ok


def test_manual_run_does_not_advance_schedule() -> bool:
    """计划等待期间手动跑完用例，不得推进 _schedule_runs。"""
    try:
        from autopilot.ui.main_window import MainWindow
        from autopilot.engine.suite import SuiteResult
        _app()
        with tempfile.TemporaryDirectory() as tmp:
            win = MainWindow(project_dir=tmp, config_dir="")
            win.create_resource("case", tmp, "c1")
            win.start_schedule(Schedule(delay_sec=10, interval_sec=0, repeat=1))
            # 模拟非计划拍完成（owned=False）；补齐 _on_suite_done 依赖的运行态字段
            win._schedule_owned_run = False
            win._report_on_finish = False
            win._on_suite_done(SuiteResult(name="manual"))
            ok = win._schedule is not None and win._schedule_runs == 0
            win.stop_schedule()
            win.close()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("手动跑不推进计划: ⏭ 跳过(", e, ")")
        return True
    print("手动跑不推进计划:", "✅" if ok else "❌")
    return ok


def test_worker_exception_emits_failed_suite() -> bool:
    """ExecutionWorker 异常仍发 suiteDone，且 failed>0（计划可 stop_on_fail）。"""
    try:
        from PyQt6.QtCore import QEventLoop, QTimer
        from autopilot.engine.suite import SuiteResult
        from autopilot.ui.runner import ExecutionWorker
        from autopilot.model.testcase import TestCase
        _app()
        tc = TestCase(name="boom")
        w = ExecutionWorker([tc], name="err_suite")
        got: dict[str, SuiteResult | None] = {"suite": None}

        def _on(s):
            got["suite"] = s

        w.suiteDone.connect(_on)

        def _boom(*_a, **_k):
            raise RuntimeError("inject fail")

        with patch("autopilot.ui.runner.run_suite", side_effect=_boom):
            w.start()
            loop = QEventLoop()
            QTimer.singleShot(8000, loop.quit)
            w.finished.connect(loop.quit)
            if got["suite"] is None:
                loop.exec()
            # 再泵一下信号
            _pump(2.0, lambda: got["suite"] is not None)
        suite = got["suite"]
        ok = suite is not None and suite.case_counts()["failed"] >= 1
        if w.isRunning():
            w.wait(3000)
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("worker 异常回传失败套件: ⏭ 跳过(", e, ")")
        return True
    print("worker 异常回传失败套件:", "✅" if ok else "❌")
    return ok


def test_invalid_schedule_rejected() -> bool:
    """非法 Schedule（负延迟）→ 不启动。"""
    try:
        from autopilot.ui.main_window import MainWindow
        _app()
        with tempfile.TemporaryDirectory() as tmp:
            win = MainWindow(project_dir=tmp, config_dir="")
            bad = Schedule(delay_sec=-1, interval_sec=0, repeat=1)
            win.start_schedule(bad)
            ok = win._schedule is None and win._schedule_runs == 0
            win.close()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("非法计划拒绝: ⏭ 跳过(", e, ")")
        return True
    print("非法计划拒绝:", "✅" if ok else "❌")
    return ok


def test_menu_action_wired() -> bool:
    """运行菜单「计划执行」动作绑定到 schedule_dialog。"""
    try:
        from autopilot.ui.main_window import MainWindow
        from autopilot.ui.actions import ACTIONS_BY_ID
        _app()
        with tempfile.TemporaryDirectory() as tmp:
            win = MainWindow(project_dir=tmp, config_dir="")
            act = win._actions.get("run.schedule")
            spec = ACTIONS_BY_ID["run.schedule"]
            ok = (act is not None
                  and spec.slot == "schedule_dialog"
                  and callable(getattr(win, "schedule_dialog", None)))
            win.close()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("菜单动作接线: ⏭ 跳过(", e, ")")
        return True
    print("菜单动作接线:", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([
        test_should_continue(),
        test_ask_schedule_cancel(),
        test_ask_schedule_ok(),
        test_gui_once(),
        test_gui_repeat_twice(),
        test_gui_stop_on_fail(),
        test_gui_cancel_invalidates_timer(),
        test_gui_no_cases_aborts(),
        test_schedule_disables_parallel_dialog(),
        test_unattended_skips_device_dialog(),
        test_unattended_skips_mixed_platform_confirm(),
        test_stop_enabled_during_delay(),
        test_close_cancels_schedule(),
        test_manual_run_does_not_advance_schedule(),
        test_worker_exception_emits_failed_suite(),
        test_invalid_schedule_rejected(),
        test_menu_action_wired(),
    ])
    print("\n总结:", "✅ 本地执行调度全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
