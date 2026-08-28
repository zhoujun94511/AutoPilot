"""只读键值信息表对话框（设备信息、安装包元数据等）。"""

from __future__ import annotations

from typing import Optional, Sequence

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..theme import apply_dialog_theme

InfoRow = tuple[str, str]


class InfoSheetDialog(QDialog):
    """每行一个可选中复制的只读框（便于拷 Bundle ID / UDID 等）。"""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        title: str = "",
        rows: Sequence[InfoRow] = (),
        theme: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("form_dialog")
        self.setWindowTitle(title)
        row_list = list(rows)
        self.resize(560, min(640, 80 + len(row_list) * 28))

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        form = QFormLayout(inner)
        for k, v in row_list:
            if str(k).startswith("—") and not str(v).strip():
                lab = QLabel(f"<b>{k}</b>")
                form.addRow(lab)
                continue
            ed = QLineEdit(str(v))
            ed.setReadOnly(True)
            ed.setCursorPosition(0)
            form.addRow(k, ed)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        buttons = QDialogButtonBox(self)
        buttons.addButton("关闭", QDialogButtonBox.ButtonRole.RejectRole)
        # noinspection PyUnresolvedReferences
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self.apply_theme(theme)

    def apply_theme(self, theme: str | None = None) -> None:
        apply_dialog_theme(self, "dialog_form", theme)


def show_info_sheet(
    parent: Optional[QWidget],
    title: str,
    rows: Sequence[InfoRow],
    *,
    theme: str | None = None,
) -> None:
    """弹出只读信息表（模态）。"""
    InfoSheetDialog(parent, title, rows, theme=theme).exec()
