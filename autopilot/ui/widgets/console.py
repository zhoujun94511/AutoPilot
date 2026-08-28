"""执行控制台组件：结构化日志/步骤结果表 + 多维过滤 + 日志管理。

列：时间 | 级别 | 状态 | 关键字 | 说明 | 信息
- 级别(DEBUG/INFO/WARNING/ERROR)与步骤状态(PASS/FAIL/NOIMPL/SKIP/LOG)分列，语义不混。
- 过滤：状态下拉 + 级别阈值下拉(只看 ≥ 某级别) + 关键字/文本。
- 自动滚动开关 + 暂停(暂停时新行进缓冲，恢复后回放，便于回看上文)。
- 右键：复制(行/信息列/全部) + 打开当日日志/日志文件夹 + 导出当前视图。
- 双击某行联动选中编辑器中对应步骤。

兼容旧 API：log(message) 追加叙述行；show_result(result) 追加用例步骤；add_step(sr) 流式追加。
对外信号：stepActivated(str keyword_id) —— 双击结果行时发出。
"""

from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import pyqtSignal, Qt, QUrl
from PyQt6.QtGui import QColor, QKeySequence, QShortcut, QDesktopServices
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QPushButton, QCheckBox,
    QMenu, QApplication, QFileDialog, QMessageBox,
)

from ...engine import RunResult
from ...runtime.log import get_logger, LOG_TIME_FORMAT

# 步骤状态色（仅用于「状态」列：执行结果）——见 theme.status_color
# 日志级别色（仅用于「级别」列）——见 theme.level_color
# 列定义（用具名索引避免魔数）
_COLUMNS = ["时间", "级别", "状态", "来源", "说明", "信息"]
_COL_TIME, _COL_LEVEL, _COL_STATUS, _COL_KEYWORD, _COL_COMMENT, _COL_MESSAGE = range(6)

# 步骤状态 → 级别（执行结果落级别列用）；级别阈值排序
_STATUS_TO_LEVEL = {"PASS": "INFO", "FAIL": "ERROR", "NOIMPL": "WARNING",
                    "SKIP": "WARNING", "LOG": "INFO"}
_LEVEL_ORDER = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
_MAX_PAUSE_BUFFER = 5000


class Console(QWidget):
    stepActivated = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("autopilot_console")
        self._log_handler = None        # install_log_bridge() 装上的 QtConsoleHandler
        self._paused = False
        self._buffer: list = []         # 暂停期间缓冲的待渲染行
        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("状态"))
        self.cmb_status = QComboBox()
        self.cmb_status.addItems(["全部", "PASS", "FAIL", "NOIMPL", "SKIP", "LOG"])
        # noinspection PyUnresolvedReferences
        self.cmb_status.currentIndexChanged.connect(self._apply_filter)
        bar.addWidget(self.cmb_status)
        bar.addWidget(QLabel("级别"))
        self.cmb_level = QComboBox()
        self.cmb_level.addItems(["全部", "DEBUG", "INFO", "WARNING", "ERROR"])
        # noinspection PyUnresolvedReferences
        self.cmb_level.currentIndexChanged.connect(self._apply_filter)
        bar.addWidget(self.cmb_level)
        self.ed_filter = QLineEdit()
        self.ed_filter.setPlaceholderText("按关键字/说明/信息过滤…")
        # noinspection PyUnresolvedReferences
        self.ed_filter.textChanged.connect(self._apply_filter)
        bar.addWidget(self.ed_filter, 1)
        self.chk_debug = QCheckBox("调试")
        self.chk_debug.setToolTip("纳入 DEBUG 开发细节日志（默认只显示业务日志，DEBUG 仅落文件）")
        # noinspection PyUnresolvedReferences
        self.chk_debug.toggled.connect(self._on_debug_toggled)
        bar.addWidget(self.chk_debug)
        self.chk_autoscroll = QCheckBox("自动滚动")
        self.chk_autoscroll.setChecked(True)
        bar.addWidget(self.chk_autoscroll)
        self.btn_pause = QPushButton("暂停")
        self.btn_pause.setCheckable(True)
        # noinspection PyUnresolvedReferences
        self.btn_pause.toggled.connect(self._on_pause_toggled)
        bar.addWidget(self.btn_pause)
        btn_clear = QPushButton("清空")
        # noinspection PyUnresolvedReferences
        btn_clear.clicked.connect(self.clear_log)
        bar.addWidget(btn_clear)
        root.addLayout(bar)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.verticalHeader().setVisible(True)   # 左侧行号
        self.table.horizontalHeader().setSectionResizeMode(
            _COL_MESSAGE, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(_COL_TIME, 150)
        self.table.setColumnWidth(_COL_LEVEL, 64)
        self.table.setColumnWidth(_COL_STATUS, 64)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # noinspection PyUnresolvedReferences
        self.table.customContextMenuRequested.connect(self._context_menu)
        # noinspection PyUnresolvedReferences
        self.table.cellDoubleClicked.connect(self._on_double_click)
        sc = QShortcut(QKeySequence.StandardKey.Copy, self.table)
        # noinspection PyUnresolvedReferences
        sc.activated.connect(self._copy_selection)
        root.addWidget(self.table, 1)

        from ..theme import init_panel_style
        self._ui_theme = init_panel_style(self, "console")

    # ---- 日志桥接（让纯 logging 来源也进控制台）----
    def install_log_bridge(self) -> None:
        """把根 logger 的记录桥接进本控制台。应用级只在主控制台调用一次。"""
        if getattr(self, "_log_handler", None) is not None:
            return
        from ..log_bridge import QtConsoleHandler
        from ...runtime.log import attach_handler, detach_handler
        h = QtConsoleHandler()
        # noinspection PyUnresolvedReferences
        h.emitter.record.connect(self._on_log_record)
        attach_handler(h)
        self._log_handler = h
        # noinspection PyUnresolvedReferences
        self.destroyed.connect(lambda *_: detach_handler(h))

    def _on_debug_toggled(self, on: bool) -> None:
        """「调试」开关：把桥接 handler 阈值在 DEBUG↔INFO 间切换（文件始终全量）。"""
        if self._log_handler is not None:
            self._log_handler.setLevel(logging.DEBUG if on else logging.INFO)

    def _on_log_record(self, created: float, levelname: str,
                       source: str, message: str) -> None:
        level = levelname if levelname in _LEVEL_ORDER else "INFO"
        ts = datetime.fromtimestamp(created).strftime(LOG_TIME_FORMAT)
        # 纯日志行：只标级别，状态列留空（状态是「执行结果」专用）
        self._emit_row(ts, level, "", source, "", message)

    # ---- 兼容旧 API（前端叙述日志）----
    def log(self, message: str, source: str = "", level: str = "INFO") -> None:
        """前端叙述日志。source=分类（如「运行/文件/设备」），level=INFO/WARNING/ERROR。

        约定见 docs/ui-design.md：进行/完成→INFO，前置条件/提示→WARNING，失败/异常→ERROR。"""
        level = level if level in _LEVEL_ORDER else "INFO"
        ts = datetime.now().strftime(LOG_TIME_FORMAT)
        for line in str(message).split("\n"):
            self._emit_row(ts, level, "", source, "", line)
        # 同步渲染过了（ap_no_gui），仅镜像到文件/CI 出口，便于事后回溯
        get_logger("ui").log(logging.getLevelName(level), "%s%s",
                             f"[{source}] " if source else "", message,
                             extra={"ap_no_gui": True})

    def show_result(self, result: RunResult) -> None:
        self.log(f"执行用例：{result.case_name}", "结果")
        for r in result.results:
            self.add_step(r)
        self.log(f"统计：{result.counts()}", "结果")

    # ---- 流式追加 ----
    def add_step(self, sr) -> None:
        ts = datetime.now().strftime(LOG_TIME_FORMAT)
        level = _STATUS_TO_LEVEL.get(sr.status, "INFO")
        self._emit_row(ts, level, sr.status, sr.keyword_id, sr.comment, sr.message)

    def clear_log(self) -> None:
        self.table.setRowCount(0)
        self._buffer.clear()

    # ---- 暂停 / 自动滚动 ----
    def _on_pause_toggled(self, paused: bool) -> None:
        self._paused = paused
        self.btn_pause.setText("继续" if paused else "暂停")
        if not paused:                  # 恢复 → 回放缓冲
            buf, self._buffer = self._buffer, []
            for row in buf:
                self._render_row(*row)

    # ---- 行渲染（暂停时进缓冲）----
    def _emit_row(self, ts: str, level: str, status: str,
                  keyword: str, comment: str, message: str) -> None:
        if self._paused:
            self._buffer.append((ts, level, status, keyword, comment, message))
            if len(self._buffer) > _MAX_PAUSE_BUFFER:
                self._buffer.pop(0)
            return
        self._render_row(ts, level, status, keyword, comment, message)

    def _render_row(self, ts: str, level: str, status: str,
                    keyword: str, comment: str, message: str) -> None:
        from ..theme import level_color, status_color

        r = self.table.rowCount()
        self.table.insertRow(r)
        cells = (ts, level, status, keyword, comment, message)
        for col, text in enumerate(cells):
            it = QTableWidgetItem(text)
            if col == _COL_LEVEL:
                color = level_color(text, self._ui_theme)
                if color:
                    it.setForeground(QColor(color))
            elif col == _COL_STATUS:
                color = status_color(text, self._ui_theme)
                if color:
                    it.setForeground(QColor(color))
            self.table.setItem(r, col, it)
        if self.chk_autoscroll.isChecked():
            self.table.scrollToBottom()
        self._apply_row_filter(r)

    # ---- 过滤 ----
    def _matches(self, row: int) -> bool:
        want_status = self.cmb_status.currentText()
        if want_status != "全部" and self._cell(row, _COL_STATUS) != want_status:
            return False
        want_level = self.cmb_level.currentText()
        if want_level != "全部":
            row_lv = _LEVEL_ORDER.get(self._cell(row, _COL_LEVEL), 0)
            if row_lv < _LEVEL_ORDER.get(want_level, 0):   # 阈值：只看 ≥ 所选级别
                return False
        kw = self.ed_filter.text().strip().lower()
        if kw:
            joined = " ".join(self._cell(row, c)
                              for c in (_COL_KEYWORD, _COL_COMMENT, _COL_MESSAGE)).lower()
            if kw not in joined:
                return False
        return True

    def _cell(self, row: int, col: int) -> str:
        it = self.table.item(row, col)
        return it.text() if it else ""

    def _apply_row_filter(self, row: int) -> None:
        self.table.setRowHidden(row, not self._matches(row))

    def _apply_filter(self) -> None:
        for r in range(self.table.rowCount()):
            self._apply_row_filter(r)

    def _on_double_click(self, row: int, _col: int) -> None:
        kid = self._cell(row, _COL_KEYWORD)
        if kid:
            # noinspection PyUnresolvedReferences
            self.stepActivated.emit(kid)

    # ---- 复制（选中行/仅信息列/全部）----
    def _selected_rows(self) -> list:
        rows = sorted({i.row() for i in self.table.selectedItems()})
        if not rows and self.table.currentRow() >= 0:
            rows = [self.table.currentRow()]
        return rows

    def _row_text(self, r: int, cols) -> str:
        return "\t".join(self._cell(r, c) for c in cols)

    def _copy_selection(self) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        cols = range(self.table.columnCount())
        QApplication.clipboard().setText("\n".join(self._row_text(r, cols) for r in rows))

    def _copy_message(self) -> None:
        rows = self._selected_rows()
        if rows:
            QApplication.clipboard().setText(
                "\n".join(self._row_text(r, [_COL_MESSAGE]) for r in rows))

    def _visible_rows(self) -> list:
        return [r for r in range(self.table.rowCount()) if not self.table.isRowHidden(r)]

    def _copy_all(self) -> None:
        cols = range(self.table.columnCount())
        QApplication.clipboard().setText(
            "\n".join(self._row_text(r, cols) for r in self._visible_rows()))

    # ---- 日志文件入口 + 导出 ----
    @staticmethod
    def _open_path(path: str) -> bool:
        if not path:
            return False
        # noinspection PyUnresolvedReferences
        return QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_logfile(self) -> None:
        from ...runtime.log import current_logfile
        path = current_logfile()
        if not (path and self._open_path(path)):
            QMessageBox.information(self, "日志", "当前没有日志文件（未配置落盘或运行于离屏/测试）。")

    def _open_logdir(self) -> None:
        from ...runtime.log import log_dir
        self._open_path(log_dir())

    def _export_view(self) -> None:
        rows = self._visible_rows()
        if not rows:
            QMessageBox.information(self, "导出", "当前没有可导出的行。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出当前视图", "autopilot_console.log", "日志 (*.log *.txt)")
        if not path:
            return
        cols = range(self.table.columnCount())
        text = "\t".join(_COLUMNS) + "\n" + "\n".join(self._row_text(r, cols) for r in rows)
        # noinspection PyBroadException
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "导出失败", str(e))

    def _context_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction("复制（整行）\tCtrl+C", self._copy_selection)
        menu.addAction("复制「信息」列", self._copy_message)
        menu.addAction("复制全部（当前筛选）", self._copy_all)
        menu.addSeparator()
        menu.addAction("导出当前视图…", self._export_view)
        menu.addAction("打开当日日志文件", self._open_logfile)
        menu.addAction("打开日志文件夹", self._open_logdir)
        menu.addSeparator()
        menu.addAction("全选", self.table.selectAll)
        menu.addAction("清空", self.clear_log)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _refresh_row_colors(self) -> None:
        from ..theme import level_color, status_color

        for r in range(self.table.rowCount()):
            for col, getter in (
                (_COL_LEVEL, level_color),
                (_COL_STATUS, status_color),
            ):
                it = self.table.item(r, col)
                if it is None:
                    continue
                color = getter(it.text(), self._ui_theme)
                if color:
                    it.setForeground(QColor(color))

    def apply_theme(self, theme: str) -> None:
        from ..theme import apply_panel_theme

        self._ui_theme = apply_panel_theme(self, "console", theme)
        self._refresh_row_colors()
