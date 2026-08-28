"""测试计划(.tp)编辑器组件：本地执行配置表单 + 成员列表。

字段：名称 / 数据配置 / 失败重试次数 / 起止时间；成员为用例/套件的相对路径。
编辑即时回写到 TestPlan 模型。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QSpinBox,
    QLabel, QListWidget, QPushButton, QInputDialog,
)

from ...model.testplan import TestPlan


class TestPlanEditor(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tp: Optional[TestPlan] = None
        self._rendering = False

        root = QVBoxLayout(self)
        form = QFormLayout()
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("如：回归计划_每日")
        self.ed_dataconfig = QLineEdit()
        self.ed_dataconfig.setPlaceholderText("数据配置相对路径，可留空")
        self.sp_fault = QSpinBox()
        self.sp_fault.setRange(0, 999)
        self.ed_start = QLineEdit()
        self.ed_start.setPlaceholderText("YYYY-MM-DD HH:MM:SS，可留空")
        self.ed_end = QLineEdit()
        self.ed_end.setPlaceholderText("YYYY-MM-DD HH:MM:SS，可留空")
        form.addRow("名称", self.ed_name)
        form.addRow("数据配置", self.ed_dataconfig)
        form.addRow("失败重试次数", self.sp_fault)
        form.addRow("开始时间", self.ed_start)
        form.addRow("结束时间", self.ed_end)
        root.addLayout(form)
        # noinspection PyUnresolvedReferences
        self.ed_name.textChanged.connect(lambda t: self._set("name", t))
        # noinspection PyUnresolvedReferences
        self.ed_dataconfig.textChanged.connect(lambda t: self._set("dataconfig", t))
        # noinspection PyUnresolvedReferences
        self.sp_fault.valueChanged.connect(lambda v: self._set("fault_times", v))
        # noinspection PyUnresolvedReferences
        self.ed_start.textChanged.connect(lambda t: self._set("start_time", t))
        # noinspection PyUnresolvedReferences
        self.ed_end.textChanged.connect(lambda t: self._set("end_time", t))

        root.addWidget(QLabel("成员（用例/套件相对路径）"))
        self.members = QListWidget()
        self.members.setAlternatingRowColors(True)
        root.addWidget(self.members, 1)
        bar = QHBoxLayout()
        btn_add = QPushButton("+ 成员")
        btn_del = QPushButton("- 成员")
        # noinspection PyUnresolvedReferences
        btn_add.clicked.connect(self._add_member)
        # noinspection PyUnresolvedReferences
        btn_del.clicked.connect(self._del_member)
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
    def testplan(self) -> Optional[TestPlan]:
        return self._tp

    def show_testplan(self, tp: TestPlan) -> None:
        self._tp = tp
        self._rendering = True
        try:
            self.ed_name.setText(tp.name)
            self.ed_dataconfig.setText(tp.dataconfig)
            self.sp_fault.setValue(tp.fault_times)
            self.ed_start.setText(tp.start_time)
            self.ed_end.setText(tp.end_time)
            self.members.clear()
            self.members.addItems(tp.members)
        finally:
            self._rendering = False

    def _set(self, attr: str, value) -> None:
        if self._tp is not None and not self._rendering:
            setattr(self._tp, attr, value)

    def _add_member(self) -> None:
        if self._tp is None:
            return
        text, ok = QInputDialog.getText(self, "添加成员", "相对路径：")
        if ok and text.strip():
            self._tp.members.append(text.strip())
            self.members.addItem(text.strip())

    def _del_member(self) -> None:
        if self._tp is None:
            return
        r = self.members.currentRow()
        if 0 <= r < len(self._tp.members):
            self._tp.members.pop(r)
            self.members.takeItem(r)
