"""步骤组数据源绑定对话框：把「类型 + 文件 + 私有」拼成 DATATABLE(路径,私有)。

绑定后引擎按数据行逐行执行该步骤组的子步骤；子步骤参数用 COLUMN(列名,默认) 取当前行列值。
选「不绑定」则清空绑定（步骤组只跑一次）。
"""

from __future__ import annotations

import re

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QHBoxLayout, QComboBox, QLineEdit,
    QPushButton, QCheckBox, QLabel, QDialogButtonBox, QFileDialog,
)

from ..theme import apply_dialog_theme

# 类型 → 文件过滤器
_TYPES = [("不绑定", ""), ("Excel", "*.xlsx *.xlsm"), ("CSV", "*.csv"), ("JSONArray", "*.json")]


def parse_spec(spec: str) -> tuple[str, str, bool]:
    """DATATABLE(源,私有) → (类型标签, 路径, 私有)。无绑定/NONE → ('不绑定','',False)。"""
    m = re.match(r"^DATATABLE\s*\((.*)\)\s*$", (spec or "").strip(), re.IGNORECASE | re.DOTALL)
    if not m:
        return "不绑定", "", False
    inner = m.group(1).strip()
    source, priv = (inner.rsplit(",", 1) + ["false"])[:2] if "," in inner else (inner, "false")
    source = source.strip()
    if not source or source.upper() == "NONE":
        return "不绑定", "", False
    low = source.lower()
    label = ("Excel" if low.endswith((".xlsx", ".xlsm"))
             else "CSV" if low.endswith(".csv")
             else "JSONArray" if low.endswith(".json") else "CSV")
    return label, source, priv.strip().lower() in ("true", "1", "yes", "t")


class DataSourceDialog(QDialog):
    def __init__(self, parent=None, spec: str = "", base_dir: str = "",
                 theme: str | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("form_dialog")
        self.setWindowTitle("绑定数据源")
        self.setMinimumWidth(420)
        self._base_dir = base_dir
        cur_type, cur_path, cur_priv = parse_spec(spec)

        root = QVBoxLayout(self)
        form = QFormLayout()
        self.cb_type = QComboBox()
        for label, _ in _TYPES:
            self.cb_type.addItem(label)
        self.cb_type.setCurrentText(cur_type)
        # noinspection PyUnresolvedReferences
        self.cb_type.currentTextChanged.connect(self._refresh)
        form.addRow("数据源类型", self.cb_type)

        path_row = QHBoxLayout()
        self.ed_path = QLineEdit(cur_path)
        self.ed_path.setPlaceholderText("选择数据文件（首行为列名）")
        self.btn_browse = QPushButton("浏览…")
        # noinspection PyUnresolvedReferences
        self.btn_browse.clicked.connect(self._browse)
        path_row.addWidget(self.ed_path, 1)
        path_row.addWidget(self.btn_browse)
        form.addRow("数据文件", path_row)

        self.cb_private = QCheckBox("私有作用域（数据行只在本步骤组内生效）")
        self.cb_private.setChecked(cur_priv if spec else True)
        form.addRow("", self.cb_private)
        root.addLayout(form)

        self.lbl_hint = QLabel()
        self.lbl_hint.setObjectName("dialog_hint")
        self.lbl_hint.setWordWrap(True)
        root.addWidget(self.lbl_hint)

        buttons = QDialogButtonBox(self)
        buttons.addButton("确定", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        # noinspection PyUnresolvedReferences
        buttons.accepted.connect(self.accept)
        # noinspection PyUnresolvedReferences
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        # noinspection PyUnresolvedReferences
        self.ed_path.textChanged.connect(self._refresh)
        # noinspection PyUnresolvedReferences
        self.cb_private.toggled.connect(self._refresh)
        self.apply_theme(theme)
        self._refresh()

    def apply_theme(self, theme: str | None = None) -> None:
        apply_dialog_theme(self, "dialog_form", theme)

    def _filter(self) -> str:
        for label, filt in _TYPES:
            if label == self.cb_type.currentText():
                return filt
        return ""

    def _browse(self) -> None:
        filt = self._filter()
        pat = f"数据文件 ({filt})" if filt else "所有文件 (*)"
        path, _ = QFileDialog.getOpenFileName(
            self, "选择数据文件", self.ed_path.text() or self._base_dir, pat)
        if path:
            self.ed_path.setText(path)

    def _bound(self) -> bool:
        return self.cb_type.currentText() != "不绑定"

    def _refresh(self, *_a) -> None:
        bound = self._bound()
        self.ed_path.setEnabled(bound)
        self.btn_browse.setEnabled(bound)
        self.cb_private.setEnabled(bound)
        self.lbl_hint.setText(f"绑定后：{self.spec()}" if bound
                              else "不绑定：步骤组只执行一次（清除现有绑定）")

    def spec(self) -> str:
        """当前设置对应的 datapool 绑定串。不绑定 → DATATABLE(NONE,false)。"""
        if not self._bound():
            return "DATATABLE(NONE,false)"
        path = self.ed_path.text().strip()
        priv = "true" if self.cb_private.isChecked() else "false"
        return f"DATATABLE({path},{priv})"
