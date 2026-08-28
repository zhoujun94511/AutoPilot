"""登录门禁·项目空间选择：选中态、多项目滚动适配与窗口定位。"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest

pytest.importorskip("PyQt6")

from _qt import get_qt_app  # noqa: E402


def _projects(n: int) -> list[dict[str, str]]:
    return [{"id": f"proj-{i:02d}", "name": f"Project {i:02d}"} for i in range(n)]


@pytest.fixture()
def gate(monkeypatch):
    get_qt_app()
    monkeypatch.setattr("autopilot.runtime.settings.mc_project_id", lambda: "")
    monkeypatch.setattr("autopilot.runtime.settings.mc_username", lambda: "")
    monkeypatch.setattr("autopilot.runtime.settings.mc_password", lambda: "")
    monkeypatch.setattr(
        "autopilot.runtime.settings.mc_server_url", lambda: "http://127.0.0.1:8000"
    )
    monkeypatch.setattr("autopilot.runtime.settings.mc_server_url_stored", lambda: "")
    from autopilot.ui.widgets.mgmt_login_gate_dialog import MgmtLoginGateDialog

    dlg = MgmtLoginGateDialog()
    yield dlg
    dlg.deleteLater()


def test_selected_row_marked_and_others_cleared(gate):
    """选中行 property=selected 供 QSS 画边框；切换后旧行必须复位。"""
    gate._populate_project_list(_projects(3))
    rows = gate._project_rows
    assert [r.property("selected") for r in rows] == ["true", "false", "false"]

    gate._project_list.setCurrentRow(2)
    assert [r.property("selected") for r in rows] == ["false", "false", "true"]


def test_row_size_hint_reserves_border(gate):
    """1px 选中边框需预留高度，否则选中瞬间行高跳动/文字被裁。"""
    gate._populate_project_list(_projects(2))
    row = gate._project_rows[0]
    assert row.row_size_hint().height() == row.sizeHint().height() + 2


def test_last_used_project_preselected(monkeypatch, gate):
    monkeypatch.setattr("autopilot.runtime.settings.mc_project_id", lambda: "proj-04")
    gate._populate_project_list(_projects(8))
    row = gate._project_list.currentRow()
    item = gate._project_list.item(row)
    assert item is not None
    assert item.data(0x0100) == "proj-04"  # Qt.ItemDataRole.UserRole
    assert gate._project_rows[row].property("selected") == "true"


def test_list_height_caps_at_visible_rows(gate):
    """项目多于一屏时列表高度封顶，剩下的滚动查看。"""
    gate._populate_project_list(_projects(12))
    cap = gate._project_list_height(gate._VISIBLE_PROJECT_ROWS)
    assert gate._project_list.height() == cap
    assert gate._project_list_height(20) == cap
    # 内容高度大于视口 → 垂直滚动条可用
    assert gate._project_list.verticalScrollBar().maximum() > 0


def test_list_height_fits_few_projects(gate):
    """项目少于一屏时不留空白，高度按实际行数收缩。"""
    gate._populate_project_list(_projects(2))
    assert gate._project_list.height() == gate._project_list_height(2)
    assert gate._project_list.height() < gate._project_list_height(
        gate._VISIBLE_PROJECT_ROWS
    )


def test_smooth_scroll_and_no_horizontal_bar(gate):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QAbstractItemView

    assert (
        gate._project_list.verticalScrollMode()
        == QAbstractItemView.ScrollMode.ScrollPerPixel
    )
    assert (
        gate._project_list.horizontalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )


def test_count_hint_and_search_visibility(gate):
    gate._populate_project_list(_projects(8))
    assert gate._project_search.isHidden() is False
    assert gate._project_count.isHidden() is False
    assert "共 8 个项目空间" in gate._project_count.text()
    assert "滚动" in gate._project_count.text()


def test_count_hint_hidden_for_single_project(gate):
    gate._populate_project_list(_projects(1))
    assert gate._project_count.isHidden() is True
    assert gate._project_search.isHidden() is True


def test_filter_updates_count_and_moves_selection(gate):
    gate._populate_project_list(_projects(8))
    gate._project_search.setText("proj-05")
    assert "匹配 1 / 8" in gate._project_count.text()
    row = gate._project_list.currentRow()
    item = gate._project_list.item(row)
    assert item is not None and not item.isHidden()
    assert item.data(0x0100) == "proj-05"
    assert gate._project_rows[row].property("selected") == "true"

    gate._project_search.setText("不存在的项目")
    assert gate._project_empty_hint.isHidden() is False
    assert "匹配 0 / 8" in gate._project_count.text()

    gate._project_search.clear()
    assert "共 8 个项目空间" in gate._project_count.text()
    assert gate._project_empty_hint.isHidden() is True


def test_center_dialog_keeps_window_inside_screen(gate):
    """无可见父窗口时回落屏幕居中，不允许贴到左上角。"""
    gate.adjustSize()
    gate.move(0, 0)
    gate._center_dialog()
    ref = gate._reference_center()
    assert ref is not None
    geo = gate.frameGeometry()
    assert abs(geo.center().x() - ref.x()) <= 2
    screen = gate.screen()
    if screen is not None:
        avail = screen.availableGeometry()
        assert geo.left() >= avail.left()
        assert geo.top() >= avail.top()


def test_step_switch_is_repainted_once(gate):
    """切页期间抑制重绘，结束后恢复，避免半布局窗口闪现。"""
    seen: list[bool] = []
    orig = gate._apply_step

    def spy(step: int) -> None:
        seen.append(gate.updatesEnabled())
        orig(step)

    gate._apply_step = spy  # type: ignore[method-assign]
    gate._show_step(gate._STEP_PROJECT)
    assert seen == [False]
    assert gate.updatesEnabled() is True
    assert gate._freeze_depth == 0


def test_frozen_paint_nesting(gate):
    with gate._frozen_paint():
        assert gate.updatesEnabled() is False
        with gate._frozen_paint():
            assert gate.updatesEnabled() is False
        # 内层退出不得提前恢复重绘
        assert gate.updatesEnabled() is False
    assert gate.updatesEnabled() is True
    assert gate._freeze_depth == 0


def test_building_rows_creates_no_toplevel_window(gate):
    """建行时不得冒出顶层窗口。

    对尚无 parent 的 widget 调 setVisible(True)，Qt 会把它当独立顶层窗口弹到
    屏幕上——表现为登录瞬间登录框左上方闪过一个小白框。
    """
    from PyQt6.QtCore import QEvent, QObject
    from PyQt6.QtWidgets import QWidget

    app = get_qt_app()
    strays: list[str] = []

    class _Spy(QObject):
        def eventFilter(self, obj, ev):  # noqa: N802 — Qt 命名
            if (
                ev.type() is QEvent.Type.Show
                and isinstance(obj, QWidget)
                and obj.isWindow()
                and obj is not gate
            ):
                strays.append(f"{type(obj).__name__}#{obj.objectName()}")
            return False

    spy = _Spy()
    app.installEventFilter(spy)
    try:
        gate._populate_project_list(_projects(3))
        app.processEvents()
    finally:
        app.removeEventFilter(spy)

    assert strays == []


def test_close_button_enabled_and_rejects(gate):
    """标题栏 X 必须可用：Windows 上去掉该 hint 只会画出一个点不动的 X。"""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QDialog

    assert bool(gate.windowFlags() & Qt.WindowType.WindowCloseButtonHint)
    gate.show()
    assert gate.close() is True
    # 关闭 = 未登录，调用方据此退出应用（与「退出应用」按钮同义）
    assert gate.result() == int(QDialog.DialogCode.Rejected)
    assert gate.logged_in is False


def test_first_frame_geometry_settled_before_map(gate):
    """首帧即最终几何。

    Windows 的 show() 先把原生窗口映射到屏幕、之后才派发 Show 事件；若等到
    showEvent 里才 adjustSize/居中，屏幕左上角会闪出一个未布局的小窗口。
    """
    from PyQt6.QtCore import QEvent, QObject
    from PyQt6.QtWidgets import QWidget

    app = get_qt_app()
    seen: list[tuple[int, int, int, int]] = []

    class _Spy(QObject):
        def eventFilter(self, obj, ev):  # noqa: N802 — Qt 命名
            if ev.type() is QEvent.Type.Show and isinstance(obj, QWidget) and obj is gate:
                geo = obj.geometry()
                seen.append((geo.x(), geo.y(), geo.width(), geo.height()))
            return False

    spy = _Spy()
    app.installEventFilter(spy)
    try:
        gate.show()
        app.processEvents()
    finally:
        app.removeEventFilter(spy)
        gate.hide()

    assert seen, "未捕获到门禁的 Show 事件"
    x, y, w, h = seen[0]
    assert (x, y) != (0, 0)          # 不得停在屏幕左上角
    assert h > 100                   # 已完成布局，不是 100x30 的默认尺寸
    ref = gate._reference_center()
    assert ref is not None
    assert abs((x + w // 2) - ref.x()) <= 8


def test_step_switch_settles_before_thaw(gate):
    """换页几何必须在解冻前定好，否则先以旧尺寸重绘一帧再跳动。"""
    gate.show()
    states: list[bool] = []
    orig = gate._settle_geometry

    def spy() -> None:
        states.append(gate.updatesEnabled())
        orig()

    gate._settle_geometry = spy  # type: ignore[method-assign]
    try:
        gate._show_step(gate._STEP_PROJECT)
    finally:
        gate.hide()
    assert states, "换页未重新定位窗口"
    assert all(s is False for s in states)


def test_resettle_skipped_while_frozen(gate):
    moved: list[int] = []
    gate._center_dialog = lambda: moved.append(1)  # type: ignore[method-assign]
    with gate._frozen_paint():
        gate._resettle()
    assert moved == []


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_login_gate_qss_draws_selection_border(theme):
    """选中态必须有边框而非仅底纹（浅色下淡蓝底纹辨识度不足）。"""
    from autopilot.ui.theme import panel_stylesheet

    qss = panel_stylesheet("login_gate", theme)
    marker = 'QWidget#list_pick_row[selected="true"]'
    assert marker in qss
    block = qss.split(marker, 1)[1].split("}", 1)[0]
    assert "border: 1px solid" in block
    assert "border-left: 3px solid" in block  # 左侧强调条
    assert "transparent" not in block
    # 未选中行占同样宽度的透明边框，选中时不产生位移
    base = qss.split("QDialog#login_gate_dialog QWidget#list_pick_row {", 1)[1]
    base_block = base.split("}", 1)[0]
    assert "border: 1px solid transparent" in base_block
    assert "border-left: 3px solid transparent" in base_block
    assert "::item:hover:!selected" in qss
    assert "QScrollBar::handle:vertical" in qss
    assert "QLabel#project_count" in qss


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_form_dialog_qss_draws_selection_border(theme):
    """设备/通用列表选择同样加边框，保持一致。"""
    from autopilot.ui.theme import panel_stylesheet

    qss = panel_stylesheet("dialog_form", theme)
    marker = "QDialog#form_dialog QListWidget#list_pick_list::item:selected"
    assert marker in qss
    block = qss.split(marker, 1)[1].split("}", 1)[0]
    assert "border: 1px solid" in block
    assert "transparent" not in block
