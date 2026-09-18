"""确认框与可复用对话框按钮条。"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from _qt import get_qt_app  # noqa: E402
from autopilot.ui.theme import THEME_DARK, THEME_LIGHT, panel_stylesheet  # noqa: E402
from autopilot.ui.widgets.confirm_dialog import ConfirmDialog  # noqa: E402
from autopilot.ui.widgets.dialog_buttons import DialogButtonBar  # noqa: E402


def test_danger_delete_uses_red_primary_and_cancel_default():
    get_qt_app()
    dlg = ConfirmDialog(
        None, "确认删除", "确定删除文件「11」？", danger=True, yes_text="确定", cancel_text="取消",
        default="cancel",
    )
    try:
        assert dlg.button_bar.primary.objectName() == "dialog_btn_danger"
        assert dlg.button_bar.primary.text() == "确定"
        assert dlg.button_bar.secondary.objectName() == "dialog_btn_secondary"
        assert dlg.button_bar.secondary.text() == "取消"
        assert dlg.button_bar.secondary.isDefault()
        assert not dlg.button_bar.primary.isDefault()
        assert dlg.button_bar.extra is None
        qss = dlg.button_bar.styleSheet()
        assert "QPushButton#dialog_btn_danger" in qss
        assert "padding: 5px 12px" in qss
        assert "border-radius: 4px" in qss
        assert "background: #c62828" not in qss
        assert "min-height: 32px" not in qss
        assert "QLabel#confirm_text" in dlg.styleSheet()
        assert "QLabel#confirm_title" not in dlg.styleSheet()
        assert not hasattr(dlg, "_title")
    finally:
        dlg.close()


def test_question_confirm_uses_primary_blue():
    get_qt_app()
    dlg = ConfirmDialog(None, "计划执行", "失败即停？", danger=False)
    try:
        assert dlg.button_bar.primary.objectName() == "dialog_btn_primary"
        assert dlg.button_bar.primary.isDefault()
    finally:
        dlg.close()


def test_tri_buttons_expose_extra_and_choice():
    get_qt_app()
    dlg = ConfirmDialog(
        None, "本机 Runner", "发现未纳入清单的设备",
        danger=True, yes_text="排除后继续", no_text="全部上报", cancel_text="取消",
        default="cancel",
    )
    try:
        assert dlg.button_bar.extra is not None
        assert dlg.button_bar.extra.text() == "全部上报"
        dlg.button_bar.extra.click()
        assert dlg.choice == "no"
    finally:
        dlg.close()


def test_dialog_button_bar_is_reusable_component():
    get_qt_app()
    bar = DialogButtonBar(primary_text="保存", secondary_text="放弃", danger=False)
    try:
        assert bar.objectName() == "dialog_button_bar"
        assert bar.primary.objectName() == "dialog_btn_primary"
        assert bar.secondary.objectName() == "dialog_btn_secondary"
        assert "QPushButton#dialog_btn_primary" in bar.styleSheet()
    finally:
        bar.close()


def test_confirm_and_button_bar_qss_registered():
    for theme in (THEME_LIGHT, THEME_DARK):
        bar = panel_stylesheet("dialog_button_bar", theme)
        dlg = panel_stylesheet("confirm_dialog", theme)
        assert "QWidget#dialog_button_bar" in bar
        assert "QPushButton#dialog_btn_primary" in bar
        assert "QPushButton#dialog_btn_danger" in bar
        assert "QPushButton#dialog_btn_secondary" in bar
        assert "QDialog#confirm_dialog" in dlg
        assert "QLabel#confirm_text" in dlg
        assert "QLabel#confirm_title" not in dlg
        assert "background: #c62828" not in bar
