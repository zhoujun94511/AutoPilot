"""主题样式注册表：调用名必须存在，关键界面必须实际获得浅/深色 QSS。"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from autopilot.ui.theme import (
    THEME_DARK,
    THEME_LIGHT,
    panel_stylesheet,
    registered_panel_names,
    qss_dark,
    qss_light,
)

ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = ROOT / "autopilot" / "ui"
_THEME_CALL_NAME_ARG = {
    "apply_panel_theme": 1,
    "init_panel_style": 1,
    "apply_dialog_theme": 1,
    "panel_stylesheet": 0,
}


def _literal_theme_names() -> list[tuple[Path, int, str]]:
    """收集 UI 源码里主题 API 使用的字面量名称。"""
    found: list[tuple[Path, int, str]] = []
    for path in UI_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute) else ""
            )
            arg_index = _THEME_CALL_NAME_ARG.get(name)
            if arg_index is None or len(node.args) <= arg_index:
                continue
            arg = node.args[arg_index]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.append((path, node.lineno, arg.value))
    return found


def test_all_literal_theme_names_are_registered():
    missing: list[str] = []
    for path, line, name in _literal_theme_names():
        try:
            panel_stylesheet(name, THEME_LIGHT)
            panel_stylesheet(name, THEME_DARK)
        except ValueError:
            missing.append(f"{path.relative_to(ROOT)}:{line} → {name!r}")
    assert not missing, "存在未注册、会导致界面无样式的主题名：" + "；".join(missing)


def test_unknown_theme_name_fails_fast():
    with pytest.raises(ValueError, match="未知主题样式名"):
        panel_stylesheet("typo_or_unregistered", THEME_LIGHT)


@pytest.mark.parametrize("theme", [THEME_LIGHT, THEME_DARK])
def test_key_surfaces_have_dedicated_styles(theme):
    welcome = panel_stylesheet("welcome_panel", theme)
    authoring = panel_stylesheet("ai_authoring_dialog", theme)
    empty = panel_stylesheet("empty_state", theme)

    assert "QWidget#welcome_panel" in welcome
    assert "QFrame#welcome_card" in welcome
    assert "QWidget#empty_workspace" in empty
    assert "QPushButton#empty_workspace_action" not in empty
    assert "QPushButton#dialog_btn_danger" in panel_stylesheet("dialog_button_bar", theme)
    assert "QDialog#confirm_dialog" in panel_stylesheet("confirm_dialog", theme)
    assert "QDialog#ai_authoring_dialog" in authoring
    assert "QTableWidget#authoring_steps" in authoring
    assert "QLabel#authoring_status" in authoring
    assert 'QLabel#authoring_badge[badge_kind="done"]' in authoring
    assert "QPushButton#authoring_stop" in authoring
    assert "QPushButton#authoring_stop:disabled" in authoring
    assert "QPushButton#primary_action:disabled" in authoring
    assert "QToolButton#authoring_advanced" in authoring
    assert "QScrollArea#authoring_advanced_scroll" in authoring


def test_authoring_inputs_have_readable_min_height():
    """高级选项首次展开前 QSS padding 会把未 polish 的输入框挤扁。"""
    for theme in (THEME_LIGHT, THEME_DARK):
        qss = panel_stylesheet("ai_authoring_dialog", theme)
        input_rule = qss.split("QDialog#ai_authoring_dialog QLineEdit,", 1)[1].split("}", 1)[0]
        assert "min-height:" in input_rule
        check_rule = qss.split("QDialog#ai_authoring_dialog QCheckBox", 1)[1].split("}", 1)[0]
        assert "min-height:" in check_rule
        pt_rule = qss.split("QDialog#ai_authoring_dialog QPlainTextEdit {", 1)[1].split("}", 1)[0]
        assert "min-height: 28px" not in pt_rule


def test_authoring_spinbox_keeps_native_arrows():
    """专用对话框样式也不能重现 QSpinBox 箭头消失问题。"""
    for theme in (THEME_LIGHT, THEME_DARK):
        qss = panel_stylesheet("ai_authoring_dialog", theme)
        spin_rule = qss.split("QDialog#ai_authoring_dialog QSpinBox", 1)[1].split("}", 1)[0]
        assert "border:" not in spin_rule
        assert "padding:" not in spin_rule


def test_light_dark_qss_constants_match():
    """浅/深色模块必须暴露同一组 *_QSS，避免一边漏登记。"""
    light = {n for n in dir(qss_light) if n.endswith("_QSS")}
    dark = {n for n in dir(qss_dark) if n.endswith("_QSS")}
    assert light == dark, (
        f"仅浅色有：{sorted(light - dark)}；仅深色有：{sorted(dark - light)}"
    )


def test_registered_names_cover_key_surfaces():
    names = registered_panel_names()
    for required in (
        "welcome_panel",
        "ai_authoring_dialog",
        "login_gate",
        "dialog_form",
        "dialog_button_bar",
        "confirm_dialog",
        "about_dialog",
    ):
        assert required in names
