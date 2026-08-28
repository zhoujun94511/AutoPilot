"""Custom keyword editor for KeywordDef (.ks) files.

This editor keeps the existing step editing behavior, and adds a static
platform-visibility field for local params. When a visibility platform is set,
params with explicit platform tags only show when they match.
"""

from __future__ import annotations

from typing import Optional, cast

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...metadata import KeywordMeta
from ...model.keyworddef import KeywordDef, LocalParam
from ...model.testcase import Step, StepNode
from .case_editor import _node_display, build_default_params


_STEP_COLUMNS = ["Keyword", "Comment", "Params"]


class CustomKeywordEditor(QWidget):
    stepSelected = pyqtSignal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._kd: Optional[KeywordDef] = None
        self._rows: list[StepNode] = []
        self._rendering = False
        self._visibility_platform = ""
        self._ios_backend_mode = ""

        root = QVBoxLayout(self)

        form = QFormLayout()
        self.ed_id = QLineEdit()
        self.ed_id.setPlaceholderText("e.g. login_flow")
        self.ed_tag = QLineEdit()
        self.ed_tag.setPlaceholderText("optional, multiple tags separated by spaces")
        form.addRow("Keyword ID", self.ed_id)
        form.addRow("Tag", self.ed_tag)
        root.addLayout(form)

        # noinspection PyUnresolvedReferences
        self.ed_id.textChanged.connect(self._on_id_changed)
        # noinspection PyUnresolvedReferences
        self.ed_tag.textChanged.connect(self._on_tag_changed)

        self.lbl_visibility = QLabel("平台：全部")
        root.addWidget(self.lbl_visibility)
        root.addWidget(QLabel("Local Params"))
        self.params_table = QTableWidget(0, 3)
        self.params_table.setHorizontalHeaderLabels(["Param ID", "Default", "Visible On"])
        self.params_table.setAlternatingRowColors(True)
        self.params_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.params_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        # noinspection PyUnresolvedReferences
        self.params_table.itemChanged.connect(self._on_param_changed)
        self.params_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # noinspection PyUnresolvedReferences
        self.params_table.customContextMenuRequested.connect(self._show_param_menu)
        root.addWidget(self.params_table)

        pbar = QHBoxLayout()
        btn_add = QPushButton("+ Param")
        btn_del = QPushButton("- Param")
        # noinspection PyUnresolvedReferences
        btn_add.clicked.connect(self._add_param)
        # noinspection PyUnresolvedReferences
        btn_del.clicked.connect(self._del_param)
        pbar.addWidget(btn_add)
        pbar.addWidget(btn_del)
        pbar.addStretch(1)
        root.addLayout(pbar)

        root.addWidget(QLabel("Steps"))
        self.steps_table = QTableWidget(0, len(_STEP_COLUMNS))
        self.steps_table.setHorizontalHeaderLabels(_STEP_COLUMNS)
        self.steps_table.setAlternatingRowColors(True)
        self.steps_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        # noinspection PyUnresolvedReferences
        self.steps_table.itemSelectionChanged.connect(self._on_selection)
        # noinspection PyUnresolvedReferences
        self.steps_table.itemChanged.connect(self._on_step_item_changed)
        root.addWidget(self.steps_table, 1)

        from ..theme import init_panel_style

        self._ui_theme = init_panel_style(self, "form_editor")

    def apply_theme(self, theme: str) -> None:
        from ..theme import apply_panel_theme, resolve_theme

        self._ui_theme = resolve_theme(theme)
        apply_panel_theme(self, "form_editor", self._ui_theme)

    @property
    def keyworddef(self) -> Optional[KeywordDef]:
        return self._kd

    def set_visibility_platform(self, platform: str, ios_backend_mode: str = "") -> None:
        value = (platform or "").strip().lower()
        mode = (ios_backend_mode or "").strip().lower()
        if value == self._visibility_platform and mode == self._ios_backend_mode:
            return
        self._visibility_platform = value
        self._ios_backend_mode = mode
        self._update_visibility_label()
        if self._kd is not None:
            self._render_params()

    def _update_visibility_label(self) -> None:
        if self._visibility_platform:
            pretty = {
                "ios": "iOS",
                "android": "Android",
                "web": "Web",
            }.get(self._visibility_platform, self._visibility_platform)
            if self._visibility_platform == "ios":
                from ...keywords.mobile.platform import effective_ios_backend_label
                back = effective_ios_backend_label(self._ios_backend_mode or "auto")
                self.lbl_visibility.setText(f"平台：{pretty} · {back}")
            else:
                self.lbl_visibility.setText(f"平台：{pretty}")
        else:
            self.lbl_visibility.setText("平台：全部")

    def show_keyworddef(self, kd: KeywordDef) -> None:
        self._kd = kd
        self._rendering = True
        try:
            self.ed_id.setText(kd.ks_id)
            self.ed_tag.setText(kd.tag)
            self._render_params()
            self._render_steps()
        finally:
            self._rendering = False

    def _on_id_changed(self, text: str) -> None:
        if self._kd is not None and not self._rendering:
            self._kd.ks_id = text

    def _on_tag_changed(self, text: str) -> None:
        if self._kd is not None and not self._rendering:
            self._kd.tag = text

    def _visible_params(self) -> list[LocalParam]:
        if self._kd is None:
            return []
        plat = self._visibility_platform
        if not plat:
            return list(self._kd.params)
        out: list[LocalParam] = []
        for lp in self._kd.params:
            platforms = [p.strip().lower() for p in lp.visible_on_platforms if p.strip()]
            if not platforms or plat in platforms:
                out.append(lp)
        return out

    @staticmethod
    def _parse_platforms(text: str) -> list[str]:
        raw = (text or "").replace(";", ",").replace("\n", ",").replace("\r", ",")
        items = [p.strip().lower() for p in raw.split(",") if p.strip()]
        out: list[str] = []
        for item in items:
            if item not in out:
                out.append(item)
        return out

    def _render_params(self) -> None:
        self.params_table.setRowCount(0)
        if self._kd is None:
            return
        for lp in self._visible_params():
            r = self.params_table.rowCount()
            self.params_table.insertRow(r)
            self.params_table.setItem(r, 0, QTableWidgetItem(lp.param_id))
            self.params_table.setItem(r, 1, QTableWidgetItem(lp.default))
            self.params_table.setItem(r, 2, QTableWidgetItem(",".join(lp.visible_on_platforms)))

    def _show_param_menu(self, pos) -> None:
        from PyQt6.QtWidgets import QMenu

        menu = QMenu(self)
        has = self.params_table.currentRow() >= 0
        menu.addAction("Copy", self._copy_param).setEnabled(has)
        menu.addAction("Paste", self._paste_param)
        menu.addSeparator()
        menu.addAction("Delete", self._del_param).setEnabled(has)
        menu.exec(self.params_table.viewport().mapToGlobal(pos))

    def _copy_param(self) -> None:
        from PyQt6.QtWidgets import QApplication

        r = self.params_table.currentRow()
        if r < 0:
            return
        cells = [self.params_table.item(r, c).text() if self.params_table.item(r, c) else ""
                 for c in range(3)]
        QApplication.clipboard().setText("\t".join(cells))

    def _paste_param(self) -> None:
        from PyQt6.QtWidgets import QApplication

        if self._kd is None:
            return
        text = QApplication.clipboard().text()
        if not text.strip():
            return
        cells = (text.splitlines()[0].split("\t") + ["", "", ""])[:3]
        self._kd.params.append(
            LocalParam(
                param_id=cells[0] or "param",
                default=cells[1],
                visible_on_platforms=self._parse_platforms(cells[2]),
            )
        )
        self._render_params()

    def _add_param(self) -> None:
        if self._kd is None:
            return
        self._kd.params.append(LocalParam(param_id="param"))
        self._render_params()

    def _del_param(self) -> None:
        if self._kd is None:
            return
        r = self.params_table.currentRow()
        if 0 <= r < len(self._kd.params):
            self._kd.params.pop(r)
            self._render_params()

    def _on_param_changed(self, item: QTableWidgetItem) -> None:
        if self._rendering or self._kd is None:
            return
        r = item.row()
        if not (0 <= r < len(self._kd.params)):
            return
        if item.column() == 0:
            self._kd.params[r].param_id = item.text()
        elif item.column() == 1:
            self._kd.params[r].default = item.text()
        else:
            self._kd.params[r].visible_on_platforms = self._parse_platforms(item.text())

    def _render_steps(self, select_node: StepNode | None = None) -> None:
        self._rendering = True
        try:
            self.steps_table.setRowCount(0)
            self._rows.clear()
            if self._kd is None:
                return
            # noinspection PyTypeChecker
            ro = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            editable = cast(Qt.ItemFlag, ro | Qt.ItemFlag.ItemIsEditable)
            for node in self._kd.steps:
                kw, params, _ = _node_display(node)
                if not kw:
                    continue
                r = self.steps_table.rowCount()
                self.steps_table.insertRow(r)
                for col, text in enumerate((kw, node.comment, params)):
                    it = QTableWidgetItem(text)
                    it.setFlags(editable if col == 1 else ro)
                    self.steps_table.setItem(r, col, it)
                self._rows.append(node)
        finally:
            self._rendering = False

        if select_node is not None:
            for r, n in enumerate(self._rows):
                if n is select_node:
                    self.steps_table.selectRow(r)
                    break
        else:
            self._on_selection()

    def selected_node(self) -> StepNode | None:
        r = self.steps_table.currentRow()
        return self._rows[r] if 0 <= r < len(self._rows) else None

    def insert_step(self, keyword_id: str, meta: Optional[KeywordMeta] = None) -> Optional[Step]:
        if self._kd is None:
            return None
        comment = meta.name if (meta and meta.name) else ""
        step = Step(keyword_id=keyword_id, comment=comment, params=build_default_params(meta))
        r = self.steps_table.currentRow()
        if 0 <= r < len(self._rows):
            idx = self._kd.steps.index(self._rows[r])
            self._kd.steps.insert(idx + 1, step)
        else:
            self._kd.steps.append(step)
        self._render_steps(select_node=step)
        return step

    def remove_selected(self) -> None:
        node = self.selected_node()
        if node is not None and self._kd is not None and node in self._kd.steps:
            self._kd.steps.remove(node)
            self._render_steps()

    def move_selected(self, delta: int) -> None:
        if self._kd is None:
            return
        node = self.selected_node()
        if node is None:
            return
        idx = self._kd.steps.index(node)
        new_idx = idx + delta
        if 0 <= new_idx < len(self._kd.steps):
            self._kd.steps[idx], self._kd.steps[new_idx] = self._kd.steps[new_idx], self._kd.steps[idx]
            self._render_steps(select_node=node)

    def refresh_node_row(self, node: StepNode) -> None:
        for r, n in enumerate(self._rows):
            if n is node:
                _, params, _ = _node_display(cast(StepNode, node))
                item = self.steps_table.item(r, 2)
                if item is not None:
                    item.setText(params)
                return

    def _on_selection(self) -> None:
        # noinspection PyUnresolvedReferences
        self.stepSelected.emit(self.selected_node())

    def _on_step_item_changed(self, item: QTableWidgetItem) -> None:
        if self._rendering or item.column() != 1:
            return
        r = item.row()
        if 0 <= r < len(self._rows) and hasattr(self._rows[r], "comment"):
            self._rows[r].comment = item.text()
