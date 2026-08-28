"""从列表选一项：完整显示长文本（UDID 等），避免 QInputDialog.getItem 下拉截断。

短标签（平台名、浏览器类型等）仍用 QInputDialog.getItem；设备 UDID / 跨平台选机等
走本模块的 pick_list_item / list_pick_ask，供 device_select.choose_device 注入 ask 回调。

可选 ``values``：列表展示 ``items``，确认后返回对应 ``values[i]``（用于「机型 (UDID)」展示、回传纯 id）。
"""

from __future__ import annotations

import re
from typing import Callable, Optional, Sequence

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..theme import apply_dialog_theme

ListPickAsk = Callable[[list[str], int], Optional[str]]

# 「机型/名称  (UDID)」或末尾括号 id
_RE_TRAIL_ID = re.compile(r"^(?P<title>.+?)\s+\((?P<id>[^)]+)\)\s*$")


def _split_display(text: str) -> tuple[str, str]:
    """拆成主标题 + 副标题（多为 UDID/序列号）；无法拆则副标题为空。"""
    s = (text or "").strip()
    if not s:
        return "", ""
    if (s.startswith("（") and "手动" in s) or (s.startswith("(") and "手动" in s):
        return s, ""
    m = _RE_TRAIL_ID.match(s)
    if m:
        return m.group("title").strip(), m.group("id").strip()
    if " · " in s:
        left, _, right = s.partition(" · ")
        right = right.strip()
        # 右侧像纯 id（长串、无空格）时作副标题
        if right and " " not in right and len(right) >= 6:
            return left.strip(), right
    return s, ""


class _PickRow(QWidget):
    """列表行：主文案 + 次要 id，选中态由外层同步 property。"""

    # 选中态带 1px 边框；sizeHint 需预留，否则选中瞬间文字被裁、行高跳动
    _SELECT_BORDER_PX = 1

    def __init__(self, title: str, subtitle: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("list_pick_row")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(2)
        self._title_text = title
        self._subtitle_text = subtitle or ""
        self._title = QLabel(title, self)
        self._title.setObjectName("list_pick_title")
        self._title.setWordWrap(False)
        self._title.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        lay.addWidget(self._title)
        self._sub = QLabel(subtitle, self)
        self._sub.setObjectName("list_pick_sub")
        self._sub.setWordWrap(False)
        self._sub.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        lay.addWidget(self._sub)
        # 必须先挂到父控件/布局里再设可见性：对尚无 parent 的 widget 调
        # setVisible(True)，Qt 会把它当独立顶层窗口弹到屏幕上闪一下。
        self._sub.setVisible(bool(subtitle))
        self.setToolTip("\n".join(t for t in (title, subtitle) if t))

    def row_size_hint(self) -> QSize:
        """给 QListWidgetItem 用的行高：sizeHint 加上选中边框占位。"""
        hint = self.sizeHint()
        return QSize(hint.width(), hint.height() + self._SELECT_BORDER_PX * 2)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self._title.style().unpolish(self._title)
        self._title.style().polish(self._title)
        self._sub.style().unpolish(self._sub)
        self._sub.style().polish(self._sub)

    def matches_query(self, query: str) -> bool:
        q = (query or "").strip().lower()
        if not q:
            return True
        blob = f"{self._title_text} {self._subtitle_text}".lower()
        return q in blob


class ListPickDialog(QDialog):
    """列表单选对话框（双行展示机型/名称与 id，不截断）。"""

    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        prompt: str,
        items: Sequence[str],
        current: int = 0,
        theme: str | None = None,
        values: Sequence[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self._items = [str(t) for t in items]
        if values is not None and len(values) != len(self._items):
            raise ValueError("values 长度必须与 items 一致")
        self._values = [str(v) for v in values] if values is not None else None
        self.setObjectName("form_dialog")
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        if prompt:
            lab = QLabel(prompt)
            lab.setObjectName("dialog_hint")
            lab.setWordWrap(True)
            layout.addWidget(lab)

        frame = QFrame()
        frame.setObjectName("list_pick_frame")
        frame_lay = QVBoxLayout(frame)
        frame_lay.setContentsMargins(0, 0, 0, 0)
        frame_lay.setSpacing(0)

        self._list = QListWidget()
        self._list.setObjectName("list_pick_list")
        self._list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._list.setSpacing(2)
        self._list.setUniformItemSizes(False)
        self._rows: list[_PickRow] = []

        for i, text in enumerate(self._items):
            item = QListWidgetItem()
            if self._values is not None:
                item.setData(Qt.ItemDataRole.UserRole, self._values[i])
            else:
                item.setData(Qt.ItemDataRole.UserRole, text)
            primary, secondary = _split_display(text)
            row = _PickRow(primary or text, secondary)
            item.setSizeHint(row.row_size_hint())
            self._list.addItem(item)
            self._list.setItemWidget(item, row)
            self._rows.append(row)

        idx = max(0, min(current, len(self._items) - 1))
        self._list.setCurrentRow(idx)
        # noinspection PyUnresolvedReferences
        self._list.itemDoubleClicked.connect(self.accept)
        # noinspection PyUnresolvedReferences
        self._list.currentRowChanged.connect(self._sync_row_selected)
        frame_lay.addWidget(self._list)
        layout.addWidget(frame, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        buttons = QDialogButtonBox(self)
        buttons.setObjectName("list_pick_buttons")
        buttons.addButton("确定", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        # noinspection PyUnresolvedReferences
        buttons.accepted.connect(self.accept)
        # noinspection PyUnresolvedReferences
        buttons.rejected.connect(self.reject)
        btn_row.addWidget(buttons)
        layout.addLayout(btn_row)

        self.setMinimumWidth(480)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        n = max(len(self._items), 1)
        # 双行约 48px，限制高度避免过高
        self._list.setMinimumHeight(min(max(n * 52 + 8, 120), 320))
        self._sync_row_selected(idx)
        self.apply_theme(theme)

    def _sync_row_selected(self, row: int) -> None:
        for i, w in enumerate(self._rows):
            w.set_selected(i == row)

    def apply_theme(self, theme: str | None = None) -> None:
        apply_dialog_theme(self, "dialog_form", theme)
        # 主题切换后重刷选中态
        self._sync_row_selected(self._list.currentRow())

    def selected_text(self) -> str:
        row = self._list.currentRow()
        if row < 0:
            return ""
        item = self._list.item(row)
        if item is None:
            return ""
        data = item.data(Qt.ItemDataRole.UserRole)
        if data is not None:
            return str(data)
        if self._values is not None:
            return self._values[row]
        return self._items[row]

    def has_selection(self) -> bool:
        return self._list.currentRow() >= 0


def pick_list_item(
    parent: Optional[QWidget],
    title: str,
    prompt: str,
    items: Sequence[str],
    current: int = 0,
    *,
    theme: str | None = None,
    values: Sequence[str] | None = None,
) -> tuple[str, bool]:
    """弹列表对话框；返回 (选中项或 values 对应值, 是否确认)。"""
    if not items:
        return "", False
    dlg = ListPickDialog(
        parent, title, prompt, items, current, theme=theme, values=values)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return "", False
    if not dlg.has_selection():
        return "", False
    return dlg.selected_text(), True


def list_pick_ask(
    parent: Optional[QWidget],
    title: str,
    prompt: str,
    *,
    values: Sequence[str] | None = None,
) -> ListPickAsk:
    """构造 device_select.choose_device 用的 ask(labels, idx) 回调。

    若提供 ``values``，确认后返回 values[i]（通常是纯 UDID），否则返回展示文案。
    """

    def ask(labels: list[str], idx: int) -> Optional[str]:
        sel, ok = pick_list_item(
            parent, title, prompt, labels, idx, values=values)
        return sel if ok else None

    return ask
