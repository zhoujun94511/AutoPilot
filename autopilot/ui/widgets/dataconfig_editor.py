"""数据配置(.properties)编辑器组件：K-V 表格 + 注释 编辑。

每行 = 一个数据项：键 / 值 / 注释（注释对应 !key:comment 行）。
编辑后即时回写到 DataConfig 模型（保序）。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QMenu, QApplication,
    QTableWidget, QTableWidgetItem, QHeaderView,
)

from ...model.dataconfig import DataConfig


_COLUMNS = ["键", "值", "注释"]


class DataConfigEditor(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cfg: Optional[DataConfig] = None
        self._rendering = False

        root = QVBoxLayout(self)
        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setAlternatingRowColors(True)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        # noinspection PyUnresolvedReferences
        self.table.itemChanged.connect(self._on_changed)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # noinspection PyUnresolvedReferences
        self.table.customContextMenuRequested.connect(self._show_menu)
        root.addWidget(self.table, 1)

        bar = QHBoxLayout()
        btn_add = QPushButton("+ 行")
        btn_del = QPushButton("- 行")
        # noinspection PyUnresolvedReferences
        btn_add.clicked.connect(self.add_row)
        # noinspection PyUnresolvedReferences
        btn_del.clicked.connect(self.remove_row)
        bar.addWidget(btn_add)
        bar.addWidget(btn_del)
        bar.addStretch(1)
        root.addLayout(bar)

        from ..theme import init_panel_style

        self._ui_theme = init_panel_style(self, "form_editor")

    def apply_theme(self, theme: str) -> None:
        from ..theme import apply_panel_theme, resolve_theme

        self._ui_theme = resolve_theme(theme)
        apply_panel_theme(self, "form_editor", self._ui_theme)

    @property
    def dataconfig(self) -> Optional[DataConfig]:
        return self._cfg

    def show_dataconfig(self, cfg: DataConfig) -> None:
        self._cfg = cfg
        self._render()

    def _render(self) -> None:
        self._rendering = True
        try:
            self.table.setRowCount(0)
            if self._cfg is None:
                return
            for key, value in self._cfg.entries:
                self._append_row(key, value, self._cfg.comments.get(key, ""))
        finally:
            self._rendering = False

    # ---- 右键菜单：复制/粘贴/删除行 ----
    def _show_menu(self, pos) -> None:
        menu = QMenu(self)
        has = self.table.currentRow() >= 0
        menu.addAction("复制行", self._copy_row).setEnabled(has)
        menu.addAction("粘贴行", self._paste_row)
        menu.addSeparator()
        menu.addAction("删除行", self.remove_row).setEnabled(has)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _copy_row(self) -> None:
        r = self.table.currentRow()
        if r < 0:
            return
        cells = [self.table.item(r, c).text() if self.table.item(r, c) else ""
                 for c in range(self.table.columnCount())]
        QApplication.clipboard().setText("\t".join(cells))

    def _paste_row(self) -> None:
        text = QApplication.clipboard().text()
        if not text.strip() or self._cfg is None:
            return
        cells = (text.splitlines()[0].split("\t") + ["", "", ""])[:3]
        self._append_row(cells[0], cells[1], cells[2])   # setItem 会触发模型同步

    def _append_row(self, key: str, value: str, comment: str) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        for col, text in enumerate((key, value, comment)):
            self.table.setItem(r, col, QTableWidgetItem(text))

    def add_row(self) -> None:
        if self._cfg is None:
            return
        self._append_row("key", "", "")
        self._sync_to_model()

    def remove_row(self) -> None:
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)
            self._sync_to_model()

    def _on_changed(self, _item: QTableWidgetItem) -> None:
        if not self._rendering:
            self._sync_to_model()

    def _sync_to_model(self) -> None:
        """把整张表回写到模型（保序；空键行忽略）。"""
        if self._cfg is None:
            return
        entries: list[tuple[str, str]] = []
        comments: dict[str, str] = {}
        for r in range(self.table.rowCount()):
            key = self._cell(r, 0)
            if not key:
                continue
            entries.append((key, self._cell(r, 1)))
            c = self._cell(r, 2)
            if c:
                comments[key] = c
        self._cfg.entries = entries
        self._cfg.comments = comments

    def _cell(self, row: int, col: int) -> str:
        it = self.table.item(row, col)
        return it.text().strip() if it is not None else ""
