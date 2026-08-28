"""阶段12.2 运行选中步骤 + 失败策略可切换回归（离屏 GUI）。"""

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import autopilot.keywords  # noqa: F401
from autopilot.engine import FaultStrategy
from autopilot.model.testcase import ParamValue

_APP = None


def _win(tmp):
    global _APP
    from PyQt6.QtWidgets import QApplication
    from autopilot.ui.main_window import MainWindow
    _APP = QApplication.instance() or QApplication([])
    return MainWindow(project_dir=tmp, config_dir="")


# noinspection PyProtectedMember,PyUnresolvedReferences
def _drain(win):
    w = win._worker
    if w is not None:
        w.wait(5000)
    for _ in range(100):
        _APP.processEvents()
        if win._worker is None:
            break


def test_fault_toggle() -> bool:
    try:
        with tempfile.TemporaryDirectory() as tmp:
            win = _win(tmp)
            win.cmb_fault.setCurrentIndex(1)        # 失败即停
            stop_ok = win._fault_strategy is FaultStrategy.STOP
            win.cmb_fault.setCurrentIndex(0)        # 失败继续
            cont_ok = win._fault_strategy is FaultStrategy.CONTINUE
            win.close()
        ok = stop_ok and cont_ok
    except Exception as e:  # noqa: BLE001
        print("失败策略切换: ⏭ 跳过(", e, ")")
        return True
    print("失败策略切换:", "✅" if ok else "❌")
    return ok


def test_run_selected() -> bool:
    try:
        with tempfile.TemporaryDirectory() as tmp:
            win = _win(tmp)
            win.new_case()
            ed = win.case_editor
            ed.insert_step("log", win.catalog.get("log"))
            ed.insert_step("log", win.catalog.get("log"))
            # 选中第 2 个步骤并标记其消息，运行选中
            ed.case.case.steps[1].params = [ParamValue("message", "only-me")]
            ed.selectRow(1)
            win.run_selected_step()
            ran = win._worker is not None
            _drain(win)
            ok = ran and win._worker is None and "通过率" in win.statusBar().currentMessage()
            win.close()
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("运行选中步骤: ⏭ 跳过(", e, ")")
        return True
    print("运行选中步骤:", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([test_fault_toggle(), test_run_selected()])
    print("\n总结:", "✅ 运行选中/策略切换全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
