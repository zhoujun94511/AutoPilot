"""中央区欢迎页 / 空编辑区切换：对齐 VS Code / IntelliJ 的工作区状态机。

无工程 → 欢迎页；有工程无文档 → 空编辑区；关最后标签不弹回「打开工程」仪表盘。
"""

from __future__ import annotations

import os

import pytest
from PyQt6.QtWidgets import QInputDialog

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from _qt import get_qt_app  # noqa: E402
from autopilot.runtime import settings  # noqa: E402
from autopilot.ui.main_window import MainWindow  # noqa: E402


@pytest.fixture
def qtapp():
    return get_qt_app()


@pytest.fixture(autouse=True)
def _isolate_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_CONFIG_DIR", str(tmp_path / "_cfg"))


def _win(project_dir: str = "") -> MainWindow:
    get_qt_app()
    return MainWindow(project_dir=project_dir, config_dir="")


def test_startup_without_project_shows_welcome(qtapp):
    win = _win("")
    try:
        assert win.center.currentWidget() is win.welcome
        assert win.center.currentWidget() is not win.empty_workspace
    finally:
        win.close()


def test_startup_with_project_shows_empty_workspace(qtapp, tmp_path):
    win = _win(str(tmp_path))
    try:
        assert win.center.currentWidget() is win.empty_workspace
        assert win.center.currentWidget() is not win.welcome
        assert win._doc_tab_row.isHidden()
    finally:
        win.close()


def test_open_project_from_welcome_goes_to_empty_workspace(qtapp, tmp_path):
    win = _win("")
    try:
        assert win.center.currentWidget() is win.welcome
        win.open_project(str(tmp_path))
        assert win.project_dir == str(tmp_path)
        assert win.center.currentWidget() is win.empty_workspace
        assert len(win._open_docs) == 0
    finally:
        win.close()


def test_close_last_tab_keeps_empty_workspace_when_project_open(qtapp, tmp_path):
    win = _win(str(tmp_path))
    try:
        case = win.create_resource("case", str(tmp_path), "IDLE01")
        win._on_file_activated(case)
        assert win.center.currentWidget() is win.case_editor
        win.close_current()
        assert len(win._open_docs) == 0
        assert win.center.currentWidget() is win.empty_workspace
        assert win.center.currentWidget() is not win.welcome
    finally:
        win.close()


def test_untitled_case_without_project_returns_to_welcome(qtapp, monkeypatch):
    monkeypatch.setattr(
        QInputDialog, "getItem", staticmethod(lambda *a, **k: ("通用", True))
    )
    win = _win("")
    try:
        win.new_case()
        assert win.center.currentWidget() is win.case_editor
        win.close_current()
        assert win.center.currentWidget() is win.welcome
    finally:
        win.close()


def test_close_project_returns_to_welcome_and_forgets_last(qtapp, tmp_path):
    win = _win(str(tmp_path))
    try:
        win.open_project(str(tmp_path))
        assert settings.last_project() == os.path.normpath(str(tmp_path))
        recents = [os.path.normpath(p) for p in settings.recent_projects()]
        assert os.path.normpath(str(tmp_path)) in recents
        case = win.create_resource("case", str(tmp_path), "IDLE02")
        win._on_file_activated(case)
        win.close_project()
        assert (win.project_dir or "") == ""
        assert len(win._open_docs) == 0
        assert win.center.currentWidget() is win.welcome
        assert settings.last_project() == ""
        recents = [os.path.normpath(p) for p in settings.recent_projects()]
        assert os.path.normpath(str(tmp_path)) in recents
    finally:
        win.close()


def test_save_on_idle_center_does_not_write_closed_case(qtapp, tmp_path):
    win = _win(str(tmp_path))
    try:
        case = win.create_resource("case", str(tmp_path), "IDLE03")
        win._on_file_activated(case)
        win.close_current()
        win.save_current()
        assert win.center.currentWidget() is win.empty_workspace
    finally:
        win.close()
