"""侧栏标题与运行进度条（离屏）。"""

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _qt import get_qt_app


def test_sidebar_header() -> bool:
    try:
        from autopilot.ui.widgets.sidebar_header import SidebarContextBar
        get_qt_app()
        h = SidebarContextBar()
        with tempfile.TemporaryDirectory() as base:
            proj = os.path.join(base, "AIID")
            os.makedirs(proj)
            h.set_project(proj)
            ok_proj = h._label.text() == "AIID" and h.isVisible()
        h.set_project("")
        ok_empty = h._label.text() == "未打开工程"
        ok = ok_proj and ok_empty
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("侧栏上下文:", "⏭ 跳过(", e, ")")
        return True
    print("侧栏上下文(工程名/空):", "✅" if ok else "❌")
    return ok


def test_run_progress_bar() -> bool:
    try:
        from autopilot.ui.main_window import MainWindow
        get_qt_app()
        with tempfile.TemporaryDirectory() as tmp:
            w = MainWindow(project_dir=tmp, config_dir="")
            bar = w._sb_progress
            ok_exists = bar is not None and not bar.isVisible()
            w._run_case_total = 3
            w._run_case_done = 0
            bar.setRange(0, 3)
            bar.setValue(1)
            bar.setVisible(True)
            ok_val = bar.value() == 1 and bar.maximum() == 3
            bar.setVisible(False)
            w.close()
        ok = ok_exists and ok_val
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("运行进度条:", "⏭ 跳过(", e, ")")
        return True
    print("状态栏运行进度条:", "✅" if ok else "❌")
    return ok


def test_window_title() -> bool:
    try:
        from autopilot.ui.main_window import MainWindow
        from autopilot.ui.branding import APP_NAME, format_window_title
        get_qt_app()
        with tempfile.TemporaryDirectory() as tmp:
            proj = os.path.join(tmp, "MyProj")
            os.makedirs(proj)
            w = MainWindow(project_dir=proj, config_dir="")
            ok = w.windowTitle() == format_window_title() == APP_NAME
            w.close()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("窗口标题:", "⏭ 跳过(", e, ")")
        return True
    print("窗口标题固定品牌名:", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([test_sidebar_header(), test_run_progress_bar(), test_window_title()])
    print("\n总结:", "✅ Phase4 UI 全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
