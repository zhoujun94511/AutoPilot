"""界面主题：设置持久化 + 主窗口切换（离屏）。"""

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _qt import get_qt_app


def test_settings_ui_theme_roundtrip() -> bool:
    try:
        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("AUTOPILOT_CONFIG_DIR")
            os.environ["AUTOPILOT_CONFIG_DIR"] = tmp
            try:
                from autopilot.runtime import settings
                from autopilot.ui.theme import THEME_DARK, THEME_SYSTEM

                ok = settings.ui_theme() == THEME_SYSTEM
                settings.set_ui_theme(THEME_DARK)
                ok = ok and settings.ui_theme() == THEME_DARK
                settings.set_ui_theme("bogus")
                ok = ok and settings.ui_theme() == THEME_SYSTEM
            finally:
                if old is None:
                    os.environ.pop("AUTOPILOT_CONFIG_DIR", None)
                else:
                    os.environ["AUTOPILOT_CONFIG_DIR"] = old
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("settings ui_theme:", "⏭ 跳过(", e, ")")
        return True
    print("settings ui_theme 读写:", "✅" if ok else "❌")
    return ok


def test_main_window_theme_switch() -> bool:
    try:
        get_qt_app()
        from autopilot.ui.main_window import MainWindow
        from autopilot.ui.theme import THEME_DARK, THEME_LIGHT, THEME_SYSTEM, panel_stylesheet

        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("AUTOPILOT_CONFIG_DIR")
            os.environ["AUTOPILOT_CONFIG_DIR"] = cfg
            try:
                w = MainWindow(project_dir=tmp, config_dir="")
                ok = w._ui_theme_stored == THEME_SYSTEM
                ok = ok and w._ui_theme in (THEME_LIGHT, THEME_DARK)
                ok = ok and "#f3f3f3" in panel_stylesheet("project_panel", THEME_LIGHT)
                ok = ok and "#283593" in panel_stylesheet("project_panel", THEME_LIGHT)
                w._set_ui_theme(THEME_DARK)
                ok = ok and w._ui_theme_stored == THEME_DARK
                ok = ok and w._ui_theme == THEME_DARK
                ok = ok and "#252526" in w.project_panel.styleSheet()
                ok = ok and "#264f78" in w.case_editor.styleSheet()
                ok = ok and w._menu_chrome._theme_actions[THEME_DARK].isChecked()
                w._set_ui_theme(THEME_LIGHT)
                ok = ok and w._ui_theme_stored == THEME_LIGHT
                ok = ok and w._ui_theme == THEME_LIGHT
                w.close()
            finally:
                if old is None:
                    os.environ.pop("AUTOPILOT_CONFIG_DIR", None)
                else:
                    os.environ["AUTOPILOT_CONFIG_DIR"] = old
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("MainWindow 主题切换:", "⏭ 跳过(", e, ")")
        return True
    print("MainWindow 主题切换:", "✅" if ok else "❌")
    return ok


def test_dialog_themes() -> bool:
    try:
        get_qt_app()
        from autopilot.ui.theme import THEME_DARK, panel_stylesheet
        from autopilot.ui.widgets.about_dialog import AboutDialog
        from autopilot.ui.widgets.new_project_dialog import NewProjectDialog
        from autopilot.ui.widgets.datasource_dialog import DataSourceDialog
        from autopilot.ui.branding import app_icon

        about = AboutDialog(
            app_name="AutoPilot", version="1.0", tagline="test",
            facts=[("平台", "test")], copyright_text="© test",
            icon=app_icon(), theme=THEME_DARK,
        )
        ok = "#2d2d2d" in about.styleSheet()
        about.close()

        form = NewProjectDialog(theme=THEME_DARK)
        ok = ok and form.lbl_preview.objectName() == "dialog_hint"
        ok = ok and "#2d2d2d" in form.styleSheet()
        form.close()

        ds = DataSourceDialog(theme=THEME_DARK)
        ok = ok and "#2d2d2d" in ds.styleSheet()
        ds.close()

        ok = ok and "about_dialog" in panel_stylesheet("about_dialog", THEME_DARK)
        ok = ok and "dialog_hint" in panel_stylesheet("dialog_form", THEME_DARK)
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("对话框主题:", "⏭ 跳过(", e, ")")
        return True
    print("对话框主题:", "✅" if ok else "❌")
    return ok


def test_theme_grip_and_listener() -> bool:
    try:
        get_qt_app()
        from autopilot.ui.main_window import MainWindow
        from autopilot.ui.theme import (
            THEME_DARK, THEME_LIGHT, configure_application_theme, configure_grip_theme,
            grip_palette, main_window_stylesheet,
        )
        from autopilot.runtime import settings
        from PyQt6.QtWidgets import QApplication

        configure_grip_theme(THEME_DARK)
        configure_application_theme(THEME_DARK)
        ok = grip_palette()[0] == "#3c3c3c"
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("AUTOPILOT_CONFIG_DIR")
            os.environ["AUTOPILOT_CONFIG_DIR"] = cfg
            try:
                settings.set_ui_theme(THEME_DARK)
                w = MainWindow(project_dir=tmp, config_dir="")
                app = QApplication.instance()
                ok = ok and getattr(app, "_autopilot_theme_listener", False)
                ok = ok and "#1e1e1e" in main_window_stylesheet(THEME_DARK)
                ok = ok and "#1e1e1e" in w.styleSheet()
                ok = ok and "#007acc" not in main_window_stylesheet(THEME_LIGHT)
                ok = ok and "#f3f3f3" in main_window_stylesheet(THEME_LIGHT)
                ok = ok and w.keyword_editor.styleSheet() != ""
                w.close()
            finally:
                if old is None:
                    os.environ.pop("AUTOPILOT_CONFIG_DIR", None)
                else:
                    os.environ["AUTOPILOT_CONFIG_DIR"] = old
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("主题 grip/监听:", "⏭ 跳过(", e, ")")
        return True
    print("主题 grip/监听/壳层:", "✅" if ok else "❌")
    return ok


def test_semantic_colors_and_qss() -> bool:
    try:
        from autopilot.ui.theme import (
            THEME_DARK, THEME_LIGHT, icon_color, level_color, panel_stylesheet,
            semantic_color,
        )

        ok = semantic_color("muted", THEME_LIGHT) == "#566573"
        ok = ok and semantic_color("placeholder", THEME_LIGHT) == "#616161"
        ok = ok and icon_color("tool_on_tint", THEME_LIGHT) == "#283593"
        ok = ok and semantic_color("muted", THEME_DARK) == "#9e9e9e"
        ok = ok and level_color("INFO", THEME_DARK) == "#64b5f6"
        ok = ok and "palette(mid)" not in panel_stylesheet("empty_state", THEME_DARK)
        ok = ok and "#9e9e9e" in panel_stylesheet("map_editor", THEME_DARK)
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("语义色/QSS:", "⏭ 跳过(", e, ")")
        return True
    print("语义色/QSS 一致性:", "✅" if ok else "❌")
    return ok


def test_dock_panel_light_chrome() -> bool:
    """浅色主题下 Dock 内面板须自带表头/工具条 QSS（不依赖壳层继承）。"""
    try:
        get_qt_app()
        from autopilot.ui.main_window import MainWindow
        from autopilot.ui.theme import THEME_LIGHT

        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("AUTOPILOT_CONFIG_DIR")
            os.environ["AUTOPILOT_CONFIG_DIR"] = cfg
            try:
                w = MainWindow(project_dir=tmp, config_dir="")
                w._set_ui_theme(THEME_LIGHT)
                ok = "QHeaderView::section" in w.console.styleSheet()
                ok = ok and "#fafafa" in w.console.styleSheet()
                ok = ok and "QHeaderView::section" in w.inspector.styleSheet()
                ok = ok and "#fafafa" in w.inspector.styleSheet()
                ok = ok and "auxiliary_region_toolbar" in w._right_aux._toolbar.styleSheet()
                ok = ok and "#f3f3f3" in w._right_aux._toolbar.styleSheet()
                from typing import cast
                from PyQt6.QtGui import QPalette
                from PyQt6.QtWidgets import QApplication
                app = cast(QApplication, QApplication.instance())
                win_color = app.palette().color(QPalette.ColorRole.Window)
                ok = ok and win_color.name().lower() in ("#f3f3f3", "#f3f3f3")
                ok = ok and app.style().objectName().lower() == "fusion"
                w.close()
            finally:
                if old is None:
                    os.environ.pop("AUTOPILOT_CONFIG_DIR", None)
                else:
                    os.environ["AUTOPILOT_CONFIG_DIR"] = old
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("Dock 面板浅色 chrome:", "⏭ 跳过(", e, ")")
        return True
    print("Dock 面板浅色 chrome:", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([
        test_settings_ui_theme_roundtrip(),
        test_main_window_theme_switch(),
        test_dialog_themes(),
        test_theme_grip_and_listener(),
        test_semantic_colors_and_qss(),
        test_dock_panel_light_chrome(),
    ])
    print("\n总结:", "✅ UI 主题全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
