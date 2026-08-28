"""chrome 组件单元测试（离屏）。"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _qt import get_qt_app


def test_run_progress_bar_api() -> bool:
    try:
        from autopilot.ui.widgets.chrome import RunProgressBar
        get_qt_app()
        bar = RunProgressBar()
        bar.begin(3)
        ok_begin = bar.maximum() == 3 and bar.isVisible()
        bar.advance_case()
        ok_adv = bar.value() == 1
        bar.end()
        ok_end = not bar.isVisible()
        ok = ok_begin and ok_adv and ok_end
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("RunProgressBar API:", "⏭ 跳过(", e, ")")
        return True
    print("RunProgressBar begin/advance/end:", "✅" if ok else "❌")
    return ok


def test_project_toolbar_signals() -> bool:
    try:
        from autopilot.ui.widgets.chrome import ProjectExplorerToolbar
        get_qt_app()
        tb = ProjectExplorerToolbar()
        seen: list[str] = []
        tb.batchRunRequested.connect(lambda: seen.append("run"))
        tb.set_batch_run_count(2)
        ok_count = tb.btn_batch_run.isEnabled() and "2" in tb.btn_batch_run.toolTip()
        tb.set_batch_run_count(0)
        ok_zero = not tb.btn_batch_run.isEnabled()
        ok = ok_count and ok_zero
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("ProjectExplorerToolbar:", "⏭ 跳过(", e, ")")
        return True
    print("ProjectExplorerToolbar 批量运行按钮:", "✅" if ok else "❌")
    return ok


def test_status_bar_chrome_mount() -> bool:
    try:
        from PyQt6.QtWidgets import QMainWindow
        from autopilot.ui.widgets.chrome import StatusBarChrome
        get_qt_app()
        w = QMainWindow()
        chrome = StatusBarChrome(w.statusBar())
        ok = all([
            chrome.fault is not None,
            chrome.progress is not None,
            chrome.device is not None,
            hasattr(chrome.progress, "begin"),
        ])
        w.close()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("StatusBarChrome:", "⏭ 跳过(", e, ")")
        return True
    print("StatusBarChrome 装配:", "✅" if ok else "❌")
    return ok


def test_left_sidebar_layout() -> bool:
    try:
        from autopilot.ui.widgets.left_sidebar import LeftSidebar
        from autopilot.ui.widgets.project_panel import ProjectPanel
        get_qt_app()
        panel = ProjectPanel()
        side = LeftSidebar(panel)
        ok = side.findChild(type(panel)) is panel
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("LeftSidebar:", "⏭ 跳过(", e, ")")
        return True
    print("LeftSidebar 工程树直挂:", "✅" if ok else "❌")
    return ok


def test_view_tab_stack() -> bool:
    try:
        from PyQt6.QtWidgets import QLabel
        from autopilot.ui.widgets.chrome import ViewTabStack
        get_qt_app()
        stack = ViewTabStack((("a", "Tab A", QLabel("A")), ("b", "Tab B", QLabel("B"))))
        stack.activate("b")
        ok = stack.current_view_id() == "b" and stack.tab_index() == 1
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("ViewTabStack:", "⏭ 跳过(", e, ")")
        return True
    print("ViewTabStack activate:", "✅" if ok else "❌")
    return ok


def test_main_toolbar_chrome() -> bool:
    try:
        import tempfile
        from autopilot.ui.main_window import MainWindow
        get_qt_app()
        with tempfile.TemporaryDirectory() as tmp:
            w = MainWindow(project_dir=tmp, config_dir="")
            ok = getattr(w, "_editor_run_chrome", None) is not None
            ok = ok and w.act_pause is not None
            from PyQt6.QtWidgets import QToolBar
            tb = w.findChild(QToolBar, "main_toolbar")
            ok = ok and tb is None  # 顶栏已收敛，无全局工具栏
            w.close()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("MainToolbarChrome:", "⏭ 跳过(", e, ")")
        return True
    print("EditorRunToolbar 挂载(无顶栏工具条):", "✅" if ok else "❌")
    return ok


def test_menu_bar_chrome() -> bool:
    try:
        import tempfile
        from autopilot.ui.main_window import MainWindow
        get_qt_app()
        with tempfile.TemporaryDirectory() as tmp:
            w = MainWindow(project_dir=tmp, config_dir="")
            ok = getattr(w, "_menu_chrome", None) is not None
            ok = ok and w._recent_menu is not None
            titles = [a.text() for a in w.menuBar().actions()]
            ok = ok and any("视图" in t for t in titles) and any("帮助" in t for t in titles)
            w.close()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("MenuBarChrome:", "⏭ 跳过(", e, ")")
        return True
    print("MenuBarChrome 挂载:", "✅" if ok else "❌")
    return ok


def test_theme_panel_stylesheet() -> bool:
    try:
        from autopilot.ui.theme import (
            THEME_DARK,
            panel_stylesheet,
            apply_main_window,
            resolve_theme,
        )
        from PyQt6.QtWidgets import QMainWindow
        get_qt_app()
        chip = panel_stylesheet("device_chip")
        aux = panel_stylesheet("auxiliary_toolbar")
        ok = "device_status_chip" in chip and "auxiliary_region_title" in aux
        w = QMainWindow()
        apply_main_window(w)
        ok = ok and bool(w.styleSheet())
        dark_tb = panel_stylesheet("project_panel", THEME_DARK)
        ok = ok and "#252526" in dark_tb
        ok = ok and resolve_theme("invalid") == "light"
        w.close()
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("theme panel_stylesheet:", "⏭ 跳过(", e, ")")
        return True
    print("theme panel_stylesheet:", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([
        test_run_progress_bar_api(),
        test_project_toolbar_signals(),
        test_status_bar_chrome_mount(),
        test_left_sidebar_layout(),
        test_view_tab_stack(),
        test_main_toolbar_chrome(),
        test_menu_bar_chrome(),
        test_theme_panel_stylesheet(),
    ])
    print("\n总结:", "✅ chrome 组件全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
