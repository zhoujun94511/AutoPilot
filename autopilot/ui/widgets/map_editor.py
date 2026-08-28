"""对象库(.map)编辑器组件：树形展示元素层级 + 编辑定位方式。

职责：展示 MapFile 的元素树（名称 + locator 摘要）；选中元素后编辑其
locator（type/value/mode，AND/OR 显示 tag+properties 摘要）；增删元素。
供测试步骤以 map::文件::元素 引用。

对外信号：
  dirtyChanged(bool) —— 内容是否有未保存修改（供主窗口提示，可选）。
"""

from __future__ import annotations

import os
from typing import Optional

from ..theme import apply_panel_theme, init_panel_style, resolve_theme

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QPushButton,
    QFormLayout,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QLabel,
    QMenu,
)

from ...model.mapfile import MapFile, MapElement, Locator, LOCATOR_TYPES


_ROLE_ELEMENT = Qt.ItemDataRole.UserRole


def _locator_summary(loc: Optional[Locator]) -> str:
    if loc is None:
        return ""
    if loc.type in ("AND", "OR"):
        return f"{loc.type}(tag={loc.tag}, props={len(loc.properties)})"
    return f"{loc.type}={loc.value}"


def _element_summary(el) -> str:
    """树第 2 列：通用定位摘要 + 平台专属标记(如 [A][i])，一眼看出哪些配了分平台。"""
    s = _locator_summary(el.locator)
    marks = "".join(m for p, m in (
        ("android", "[A]"),
        ("ios", "[i]"),
        ("ios_appium", "[iA]"),
        ("ios_wda", "[iW]"),
    )
                    if el.locators_by_platform.get(p) is not None)
    return (s + "  " + marks).strip() if marks else s


class MapEditor(QWidget):
    dirtyChanged = pyqtSignal(bool)
    findReferencesRequested = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._mapfile: Optional[MapFile] = None
        self._current: Optional[MapElement] = None
        self._editing = False

        layout = QVBoxLayout(self)

        # 顶部：元素树
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["元素", "定位"])
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # noinspection PyUnresolvedReferences
        self.tree.customContextMenuRequested.connect(self._show_tree_menu)
        self.tree.setAlternatingRowColors(True)
        # noinspection PyUnresolvedReferences
        self.tree.currentItemChanged.connect(self._on_select)
        layout.addWidget(self.tree, stretch=3)

        # 中部：增删按钮
        btns = QHBoxLayout()
        self.btn_add = QPushButton("添加元素")
        self.btn_add_child = QPushButton("添加子元素")
        self.btn_del = QPushButton("删除元素")
        # noinspection PyUnresolvedReferences
        self.btn_add.clicked.connect(lambda: self._add_element(child=False))
        # noinspection PyUnresolvedReferences
        self.btn_add_child.clicked.connect(lambda: self._add_element(child=True))
        # noinspection PyUnresolvedReferences
        self.btn_del.clicked.connect(self._del_element)
        for b in (self.btn_add, self.btn_add_child, self.btn_del):
            btns.addWidget(b)
        layout.addLayout(btns)

        # 底部：locator 编辑表单
        form_host = QWidget()
        self._form = QFormLayout(form_host)
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("如：login_button")
        # noinspection PyUnresolvedReferences
        self.ed_name.textChanged.connect(self._on_name_changed)
        # 定位符适用平台(对标 @AndroidFindBy/@iOSXCUITFindBy)：切换编辑哪一套
        self.cb_platform = QComboBox()
        for label, slot in (
            ("通用", ""),
            ("Android", "android"),
            ("iOS", "ios"),
            ("iOS-Appium", "ios_appium"),
            ("iOS-WDA", "ios_wda"),
        ):
            self.cb_platform.addItem(label, slot)
        # noinspection PyUnresolvedReferences
        self.cb_platform.currentIndexChanged.connect(self._on_slot_changed)
        self.cb_type = QComboBox()
        self.cb_type.addItems(sorted(LOCATOR_TYPES))
        # noinspection PyUnresolvedReferences
        self.cb_type.currentTextChanged.connect(self._on_locator_changed)
        self.ed_value = QLineEdit()
        self.ed_value.setPlaceholderText("按定位类型填入（XPath / id / CSS …）")
        # noinspection PyUnresolvedReferences
        self.ed_value.textChanged.connect(self._on_locator_changed)
        self.sp_mode = QSpinBox()
        self.sp_mode.setRange(0, 99)
        # noinspection PyUnresolvedReferences
        self.sp_mode.valueChanged.connect(self._on_locator_changed)
        self._form.addRow("名称", self.ed_name)
        self._form.addRow("定位符适用", self.cb_platform)
        self._form.addRow("定位类型", self.cb_type)
        self._form.addRow("定位值", self.ed_value)
        self._form.addRow("匹配模式", self.sp_mode)
        self.lbl_hint = QLabel("在上方列表选择元素后编辑；或点「+」新建")
        self.lbl_hint.setObjectName("map_editor_hint")
        self._form.addRow(self.lbl_hint)
        layout.addWidget(form_host, stretch=2)

        self._ui_theme = init_panel_style(self, "map_editor")

    # ---- 数据 ----
    @property
    def mapfile(self) -> Optional[MapFile]:
        return self._mapfile

    def show_map(self, mf: MapFile, select: Optional[MapElement] = None) -> None:
        self._mapfile = mf
        self._rebuild_tree(select=select)

    def _rebuild_tree(self, select: Optional[MapElement] = None) -> None:
        self.tree.clear()
        if self._mapfile is None:
            return
        for el in self._mapfile.elements:
            self.tree.addTopLevelItem(self._build_item(el))
        self.tree.expandAll()
        if select is not None:
            self._select_element(select)

    def _build_item(self, el: MapElement) -> QTreeWidgetItem:
        item = QTreeWidgetItem([el.name, _element_summary(el)])
        item.setData(0, _ROLE_ELEMENT, el)
        for child in el.children:
            item.addChild(self._build_item(child))
        return item

    def _select_element(self, el: MapElement) -> None:
        def walk(item: QTreeWidgetItem) -> bool:
            if item.data(0, _ROLE_ELEMENT) is el:
                self.tree.setCurrentItem(item)
                return True
            return any(walk(item.child(c)) for c in range(item.childCount()))

        for i in range(self.tree.topLevelItemCount()):
            if walk(self.tree.topLevelItem(i)):
                return

    def current_map_ref(self) -> str:
        """当前选中元素的 map::文件stem::元素名；无选中则空。"""
        if self._mapfile is None or self._current is None:
            return ""
        src = getattr(self._mapfile, "source_path", "") or ""
        base = os.path.basename(src) if src else (getattr(self._mapfile, "name", "") or "map")
        stem = base
        for suf in (".map.yaml", ".map.yml", ".map"):
            if stem.lower().endswith(suf):
                stem = stem[: -len(suf)]
                break
        else:
            stem = os.path.splitext(stem)[0]
        name = (self._current.name or "").strip()
        if not stem or not name:
            return ""
        return f"map::{stem}::{name}"

    def _show_tree_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if item is not None:
            self.tree.setCurrentItem(item)
        menu = QMenu(self)
        act_ref = menu.addAction("查找引用")
        ref = self.current_map_ref()
        act_ref.setEnabled(bool(ref))
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is act_ref and ref:
            # noinspection PyUnresolvedReferences
            self.findReferencesRequested.emit(ref)

    # ---- 选中 → 填充表单 ----
    def _on_select(self, item: Optional[QTreeWidgetItem], _prev: Optional[QTreeWidgetItem]) -> None:
        el = item.data(0, _ROLE_ELEMENT) if item is not None else None
        self._current = el
        self._editing = True
        try:
            if el is None:
                self.ed_name.clear()
                self.ed_value.clear()
                self.lbl_hint.setText("选中元素以编辑")
                return
            self.ed_name.setText(el.name)
            self.cb_platform.setCurrentIndex(0)   # 选中元素先回到「通用」槽
            self._load_slot(el, "")
        finally:
            self._editing = False

    _SLOT_HINTS = {
        "ios_appium": "iOS-Appium 槽：Mac/Appium 会话优先；推荐 predicate(name) / name::",
        "ios_wda": "iOS-WDA 槽：Win/Linux WDA-direct 优先；推荐 predicate(label) / class-chain",
    }

    def _load_slot(self, el: "MapElement", slot: str) -> None:
        """把元素在指定平台槽("" 通用 / android / ios)的定位符载入表单。"""
        loc = (el.locators_by_platform.get(slot) if slot else el.locator) or Locator()
        self.cb_type.setCurrentText(loc.type)
        self.ed_value.setText(loc.value)
        self.sp_mode.setValue(loc.mode)
        tip = "AND/OR 复合定位 tag/properties 暂只读" if loc.type in ("AND", "OR") else ""
        if slot in self._SLOT_HINTS:
            tip = (tip + " ｜ " if tip else "") + self._SLOT_HINTS[slot]
        elif slot:
            tip = (tip + " ｜ " if tip else "") + f"仅 {slot} 设备生效；留空=用通用"
        self.lbl_hint.setText(tip or "在上方列表选择元素后编辑；或点「+」新建")

    def _on_slot_changed(self, *_args) -> None:
        if self._current is not None:
            self._editing = True
            try:
                self._load_slot(self._current, self.cb_platform.currentData() or "")
            finally:
                self._editing = False

    # ---- 编辑回写 ----
    def _on_name_changed(self, text: str) -> None:
        if self._editing or self._current is None:
            return
        self._current.name = text
        self._refresh_current_item()
        # noinspection PyUnresolvedReferences
        self.dirtyChanged.emit(True)

    def _on_locator_changed(self, *_args) -> None:
        if self._editing or self._current is None:
            return
        slot = self.cb_platform.currentData() or ""
        ltype = self.cb_type.currentText()
        value = self.ed_value.text()
        mode = self.sp_mode.value()
        if slot:
            # 平台槽：有值才存；清空则移除该槽(回退通用)，避免留空槽误命中
            if value or ltype in ("AND", "OR"):
                loc = self._current.locators_by_platform.get(slot) or Locator()
                loc.type, loc.value, loc.mode = ltype, value, mode
                self._current.locators_by_platform[slot] = loc
            else:
                self._current.locators_by_platform.pop(slot, None)
        else:
            if self._current.locator is None:
                self._current.locator = Locator()
            loc = self._current.locator
            loc.type = ltype
            if ltype not in ("AND", "OR"):
                loc.value = value
                loc.mode = mode
        self._refresh_current_item()
        # noinspection PyUnresolvedReferences
        self.dirtyChanged.emit(True)

    def _refresh_current_item(self) -> None:
        item = self.tree.currentItem()
        if item is not None and self._current is not None:
            item.setText(0, self._current.name)
            item.setText(1, _element_summary(self._current))

    # ---- 增删 ----
    def _add_element(self, child: bool) -> None:
        if self._mapfile is None:
            return
        new_el = MapElement(name="new_element", locator=Locator(type="XPATH", value=""))
        if child and self._current is not None:
            self._current.children.append(new_el)
        else:
            self._mapfile.elements.append(new_el)
        self._rebuild_tree(select=new_el)
        # noinspection PyUnresolvedReferences
        self.dirtyChanged.emit(True)

    def _del_element(self) -> None:
        if self._mapfile is None or self._current is None:
            return
        target = self._current

        def remove_from(lst: list[MapElement]) -> bool:
            if target in lst:
                lst.remove(target)
                return True
            return any(remove_from(e.children) for e in lst)

        remove_from(self._mapfile.elements)
        self._current = None
        self._rebuild_tree()
        # noinspection PyUnresolvedReferences
        self.dirtyChanged.emit(True)

    def apply_theme(self, theme: str) -> None:
        self._ui_theme = resolve_theme(theme)
        apply_panel_theme(self, "map_editor", self._ui_theme)
