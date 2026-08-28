"""查找引用面板：输入目标 + 结果列表，双击打开并定位行。"""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
)


class SearchResultsPanel(QWidget):
    """输入引用目标并展示命中；(path, line) 经 fileActivated 发出。"""

    fileActivated = pyqtSignal(str, int)  # path, line
    searchRequested = pyqtSignal(str)     # target

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("search_results_panel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        head = QHBoxLayout()
        self._title = QLabel("查找引用")
        self._title.setObjectName("search_results_title")
        self._count = QLabel("")
        self._count.setObjectName("search_results_count")
        head.addWidget(self._title, 1)
        head.addWidget(self._count, 0)
        lay.addLayout(head)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._input = QLineEdit()
        self._input.setObjectName("search_results_input")
        self._input.setPlaceholderText(
            "关键字 id / 中文名 / ks::… / map::…，或任意文本，回车查找")
        self._input.setClearButtonEnabled(True)
        # noinspection PyUnresolvedReferences
        self._input.returnPressed.connect(self._emit_search)
        self._btn = QPushButton("查找")
        self._btn.setObjectName("search_results_btn")
        self._btn.setFixedWidth(64)
        # noinspection PyUnresolvedReferences
        self._btn.clicked.connect(self._emit_search)
        row.addWidget(self._input, 1)
        row.addWidget(self._btn, 0)
        lay.addLayout(row)

        self._list = QListWidget()
        self._list.setObjectName("search_results_list")
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # noinspection PyUnresolvedReferences
        self._list.itemDoubleClicked.connect(self._on_activate)
        # noinspection PyUnresolvedReferences
        self._list.itemActivated.connect(self._on_activate)
        lay.addWidget(self._list, 1)
        self._project_dir = ""

    def set_project_dir(self, project_dir: str) -> None:
        self._project_dir = project_dir or ""

    def focus_input(self, text: str = "") -> None:
        """升起面板时聚焦输入框；可预填 target。"""
        if text:
            self._input.setText(text)
            self._input.selectAll()
        self._input.setFocus()

    def show_results(self, target: str, hits: list[tuple[str, int, str]]) -> None:
        self._list.clear()
        t = (target or "").strip()
        if t and self._input.text().strip() != t:
            self._input.setText(t)
        self._title.setText(f"查找引用：{t}" if t else "查找引用")
        self._count.setText(f"{len(hits)} 处" if hits else ("无结果" if t else ""))
        root = os.path.normpath(self._project_dir) if self._project_dir else ""
        for path, line, text in hits:
            rel = path
            if root:
                # noinspection PyBroadException
                try:
                    rel = os.path.relpath(path, root)
                except Exception:
                    rel = path
            rel = rel.replace("\\", "/")
            item = QListWidgetItem(f"{rel}:{line}  {text}")
            item.setData(Qt.ItemDataRole.UserRole, (path, int(line)))
            item.setToolTip(path)
            self._list.addItem(item)

    def clear_results(self) -> None:
        self._list.clear()
        self._title.setText("查找引用")
        self._count.setText("")

    def _emit_search(self) -> None:
        t = self._input.text().strip()
        if not t:
            self._count.setText("请输入目标")
            self._input.setFocus()
            return
        # noinspection PyUnresolvedReferences
        self.searchRequested.emit(t)

    def _on_activate(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        path, line = data
        # noinspection PyUnresolvedReferences
        self.fileActivated.emit(str(path), int(line))
