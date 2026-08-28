"""New project dialog with parent directory, project name and default platform."""

from __future__ import annotations

import os

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ..theme import apply_dialog_theme


class NewProjectDialog(QDialog):
    def __init__(self, parent=None, base_dir: str = "", theme: str | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("form_dialog")
        self.setWindowTitle("新建工程")
        self.setMinimumWidth(440)

        root = QVBoxLayout(self)
        form = QFormLayout()

        loc_row = QHBoxLayout()
        self.ed_loc = QLineEdit(base_dir)
        self.ed_loc.setPlaceholderText("工程将创建在此目录下")
        btn_browse = QPushButton("浏览...")
        # noinspection PyUnresolvedReferences
        btn_browse.clicked.connect(self._browse)
        loc_row.addWidget(self.ed_loc, 1)
        loc_row.addWidget(btn_browse)
        form.addRow("位置", loc_row)

        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("例如：MyTestProject")
        form.addRow("工程名称", self.ed_name)

        self.cmb_platform = QComboBox()
        self.cmb_platform.addItem("通用", "")
        self.cmb_platform.addItem("Android", "android")
        self.cmb_platform.addItem("iOS", "ios")
        self.cmb_platform.addItem("Web", "web")
        self.cmb_platform.addItem("HTTP / API", "http")
        form.addRow("工程默认平台", self.cmb_platform)

        root.addLayout(form)

        self.lbl_preview = QLabel()
        self.lbl_preview.setObjectName("dialog_hint")
        self.lbl_preview.setWordWrap(True)
        root.addWidget(self.lbl_preview)

        self.buttons = QDialogButtonBox(self)
        self.btn_ok = self.buttons.addButton("创建", QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        # noinspection PyUnresolvedReferences
        self.buttons.accepted.connect(self.accept)
        # noinspection PyUnresolvedReferences
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

        # noinspection PyUnresolvedReferences
        self.ed_loc.textChanged.connect(self._refresh)
        # noinspection PyUnresolvedReferences
        self.ed_name.textChanged.connect(self._refresh)
        self.apply_theme(theme)
        self._refresh()

    def apply_theme(self, theme: str | None = None) -> None:
        apply_dialog_theme(self, "dialog_form", theme)

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择工程的父目录", self.ed_loc.text())
        if d:
            self.ed_loc.setText(d)

    def parent_dir(self) -> str:
        return self.ed_loc.text().strip()

    def project_name(self) -> str:
        return self.ed_name.text().strip()

    def project_platform(self) -> str:
        return str(self.cmb_platform.currentData() or "")

    def target_path(self) -> str:
        p, n = self.parent_dir(), self.project_name()
        return os.path.join(p, n) if p and n else ""

    def _refresh(self) -> None:
        path = self.target_path()
        if not self.parent_dir() or not self.project_name():
            self.lbl_preview.setText("请填写位置与工程名称")
            self.btn_ok.setEnabled(False)
            return
        exists = os.path.isdir(path)
        self.lbl_preview.setText(
            f"将创建：{path}" + ("（目录已存在，将直接打开）" if exists else ""))
        self.btn_ok.setEnabled(True)
