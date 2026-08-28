"""关键字库面板：顶部搜索过滤框 + 分类/分组树（来自 config XML 元数据）。

对标 VSCode 命令面板：实时按 名称/ID/说明 过滤，命中展开、保留所属分组。
拖拽/双击/右键插入仍由内部树承担，容器只加搜索与委托。

对外信号：
  keywordActivated(str keyword_id) —— 双击或右键「插入」时发出（用于插入步骤）。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QMimeData
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QHeaderView, QWidget, QVBoxLayout, QLineEdit, QLabel,
)

from ..actions import qicon
from ...runtime import settings
from ...metadata import load_catalog, KeywordCatalog


# 关键字 id 存放在 item 的 UserRole
_ROLE_KEYWORD_ID = Qt.ItemDataRole.UserRole
_COLUMNS = ["关键字", "关键字 ID", "说明"]


class _KeywordTree(QTreeWidget):
    keywordActivated = pyqtSignal(str)
    findReferencesRequested = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("keyword_tree")
        self._theme = "light"
        # 分栏：关键字名 / ID / 说明——把原先挤在一行的「名(id)」拆开，层级更清晰
        self.setColumnCount(len(_COLUMNS))
        self.setHeaderLabels(_COLUMNS)
        self.setColumnWidth(0, 240)
        self.setColumnWidth(1, 200)
        hdr = self.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.catalog: Optional[KeywordCatalog] = None
        self._target_platform: str = ""       # 当前用例/工程目标平台（android/ios/web）
        self._custom_top: Optional[QTreeWidgetItem] = None   # 「自定义关键字」分组根节点
        self._recent_top: Optional[QTreeWidgetItem] = None   # 「常用关键字」分组根节点
        self._refresh_tree_icons("light")
        # 视觉分层：斑马行、加行高、缩进、展开箭头
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        self.setIndentation(16)
        self.setRootIsDecorated(True)
        self.setDragEnabled(True)   # 支持拖拽关键字到用例编辑器
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # noinspection PyUnresolvedReferences
        self.customContextMenuRequested.connect(self._show_menu)
        # noinspection PyUnresolvedReferences
        self.itemDoubleClicked.connect(self._on_double_click)

    def _refresh_tree_icons(self, theme: str) -> None:
        from ..theme import icon_color

        self._star_icon = qicon("mdi6.star-outline", icon_color("tree_star", theme))
        self._folder_icon = qicon("mdi6.folder-outline", icon_color("tree_folder", theme))
        self._kw_icon = qicon("mdi6.flash-outline", icon_color("tree_keyword", theme))

    def _show_menu(self, pos) -> None:
        from PyQt6.QtWidgets import QMenu, QApplication
        it = self.itemAt(pos)
        kid = it.data(0, _ROLE_KEYWORD_ID) if it is not None else None
        menu = QMenu(self)
        act_copy = menu.addAction("复制关键字 ID")
        act_copy.setEnabled(bool(kid))
        act_ins = menu.addAction("插入到当前用例")
        act_ins.setEnabled(bool(kid))
        act_ref = menu.addAction("查找引用")
        act_ref.setEnabled(bool(kid))
        chosen = menu.exec(self.viewport().mapToGlobal(pos))
        if chosen is act_copy and kid:
            QApplication.clipboard().setText(str(kid))
        elif chosen is act_ins and kid:
            # noinspection PyUnresolvedReferences
            self.keywordActivated.emit(str(kid))
        elif chosen is act_ref and kid:
            # noinspection PyUnresolvedReferences
            self.findReferencesRequested.emit(str(kid))

    def mimeData(self, items):
        """拖拽时把关键字 id（或 ks:: 前缀）放进 mime text，供用例编辑器接收。"""
        md = QMimeData()
        for it in items:
            kid = it.data(0, _ROLE_KEYWORD_ID)
            if kid:
                md.setText(str(kid))
                settings.bump_keyword_usage(str(kid))   # 拖拽插入也计频次（树在拖拽中不重建）
                break
        return md

    def _ensure_group(self, segments: list[str],
                      cache: dict[tuple, QTreeWidgetItem]) -> Optional[QTreeWidgetItem]:
        """按 segments 逐级建出嵌套分组节点（已存在则复用），返回最深节点。"""
        parent: Optional[QTreeWidgetItem] = None
        for i in range(len(segments)):
            key = tuple(segments[: i + 1])
            node = cache.get(key)
            if node is None:
                node = QTreeWidgetItem([segments[i]])
                self._style_group(node)
                if parent is None:
                    self.addTopLevelItem(node)
                else:
                    parent.addChild(node)
                cache[key] = node
            parent = node
        return parent

    def _fg(self, key: str) -> QBrush:
        from ..theme import semantic_color

        return QBrush(QColor(semantic_color(key, self._theme)))

    def _style_group(self, node: QTreeWidgetItem) -> None:
        """分组节点：加粗 + 文件夹图标 + 深色，和叶子区分开。"""
        f = node.font(0)
        f.setBold(True)
        node.setFont(0, f)
        node.setForeground(0, self._fg("group_fg"))
        if self._folder_icon is not None:
            node.setIcon(0, self._folder_icon)

    def _platform_tip(self, meta) -> str:
        from ...metadata.keyword_platforms import platform_mismatch_reason
        if meta.unsupported:
            return meta.unsupported_reason or "平台专有，不支持"
        reason = platform_mismatch_reason(self._target_platform, meta)
        return reason

    def _style_keyword_item(self, item: QTreeWidgetItem, meta) -> None:
        """按 unsupported / 平台不匹配 灰显叶子节点。"""
        tip = self._platform_tip(meta)
        if meta.unsupported or tip:
            prefix = "⛔ " if meta.unsupported else "⊘ "
            item.setText(0, prefix + meta.name)
            for col in range(len(_COLUMNS)):
                item.setForeground(col, self._fg("disabled"))
                if tip:
                    item.setToolTip(col, tip)
        else:
            self._style_leaf(item)

    def _style_leaf(self, item: QTreeWidgetItem) -> None:
        """关键字叶子：名带图标、ID/说明列弱化，让名字突出。"""
        if self._kw_icon is not None:
            item.setIcon(0, self._kw_icon)
        item.setForeground(0, QBrush())
        item.setForeground(1, self._fg("id_fg"))
        item.setForeground(2, self._fg("desc_fg"))

    def _refresh_tree_styles(self) -> None:
        """主题或平台变化后重刷分组/叶子前景色。"""
        if self.catalog is None:
            return

        def visit(item: QTreeWidgetItem) -> None:
            kid = item.data(0, _ROLE_KEYWORD_ID)
            if kid:
                meta = self.catalog.by_id.get(str(kid))
                if meta is not None:
                    self._style_keyword_item(item, meta)
            else:
                self._style_group(item)
            for ci in range(item.childCount()):
                visit(item.child(ci))

        for ti in range(self.topLevelItemCount()):
            visit(self.topLevelItem(ti))

    def apply_tree_theme(self, theme: str) -> None:
        """主题切换后刷新树图标与前景色。"""
        self._theme = theme
        self._refresh_tree_icons(theme)
        self._refresh_tree_styles()

    def set_target_platform(self, platform: str) -> None:
        """用例/工程平台变化时刷新灰显（不重建整棵树）。"""
        plat = (platform or "").strip().lower()
        if plat == self._target_platform:
            return
        self._target_platform = plat
        self._refresh_platform_styles()

    def _refresh_platform_styles(self) -> None:
        if self.catalog is None:
            return

        def visit(item: QTreeWidgetItem) -> None:
            kid = item.data(0, _ROLE_KEYWORD_ID)
            if kid:
                meta = self.catalog.by_id.get(str(kid))
                if meta is not None:
                    item.setText(0, meta.name)
                    item.setText(1, meta.keyword_id)
                    item.setText(2, meta.comment or "")
                    for col in range(len(_COLUMNS)):
                        item.setToolTip(col, "")
                    self._style_keyword_item(item, meta)
            for ci in range(item.childCount()):
                visit(item.child(ci))

        for ti in range(self.topLevelItemCount()):
            visit(self.topLevelItem(ti))

    def load(self, config_dir: Optional[str] = None) -> KeywordCatalog:
        """加载关键字目录并构建「嵌套分组树 + 分栏」。config_dir 为 None 用项目内资源。"""
        self.catalog = load_catalog(config_dir)
        self.clear()
        cache: dict[tuple, QTreeWidgetItem] = {}
        for meta in sorted(self.catalog.by_id.values(),
                           key=lambda m: [m.category] + m.group_path + [m.name]):
            group = self._ensure_group([meta.category] + meta.group_path, cache)
            item = QTreeWidgetItem([meta.name, meta.keyword_id, meta.comment or ""])
            item.setData(0, _ROLE_KEYWORD_ID, meta.keyword_id)
            self._style_keyword_item(item, meta)
            if group is not None:
                group.addChild(item)
            else:
                self.addTopLevelItem(item)
        self.rebuild_recent()
        self._refresh_platform_styles()
        return self.catalog

    def rebuild_recent(self, top_n: int = 8) -> None:
        """按使用频次在树顶置「常用关键字」分组(高频优先)，省得每次到角落里翻。

        只收已在目录中的内建关键字；空使用记录则不显示该分组。可重复调用(先摘旧再建)。"""
        old = self._recent_top
        if old is not None:
            idx = self.indexOfTopLevelItem(old)
            if idx >= 0:
                self.takeTopLevelItem(idx)
            self._recent_top = None
        if self.catalog is None:
            return
        ranked = [kid for kid in settings.keyword_usage_ranked()
                  if kid in self.catalog.by_id][:top_n]
        if not ranked:
            return
        top = QTreeWidgetItem(["常用关键字"])
        self._style_group(top)
        if self._star_icon is not None:
            top.setIcon(0, self._star_icon)
        self.insertTopLevelItem(0, top)   # 置顶，第一眼就能看到
        self._recent_top = top
        for kid in ranked:
            meta = self.catalog.by_id[kid]
            it = QTreeWidgetItem([meta.name, meta.keyword_id, meta.comment or ""])
            it.setData(0, _ROLE_KEYWORD_ID, meta.keyword_id)
            self._style_keyword_item(it, meta)
            top.addChild(it)
        top.setExpanded(True)

    def set_custom_keywords(self, store) -> None:
        """把工程内自定义关键字(.ks)挂到「自定义关键字」分组下（ks:: 前缀标记）。"""
        existing = getattr(self, "_custom_top", None)
        if existing is not None:
            idx = self.indexOfTopLevelItem(existing)
            if idx >= 0:
                self.takeTopLevelItem(idx)
        top = QTreeWidgetItem(["自定义关键字"])
        self._style_group(top)
        self.addTopLevelItem(top)
        self._custom_top = top
        for ks_id in sorted(store.by_id):
            child = QTreeWidgetItem([ks_id, ks_id, "自定义"])
            child.setData(0, _ROLE_KEYWORD_ID, f"ks::{ks_id}")
            self._style_leaf(child)
            top.addChild(child)
        top.setExpanded(True)

    def _on_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        keyword_id = item.data(0, _ROLE_KEYWORD_ID)
        if keyword_id:
            # noinspection PyUnresolvedReferences
            self.keywordActivated.emit(keyword_id)


class KeywordPanel(QWidget):
    """容器：搜索框 + 关键字树。对外 API 与原 KeywordPanel 兼容（委托到内部树）。"""
    keywordActivated = pyqtSignal(str)
    findReferencesRequested = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(2, 2, 2, 2)
        v.setSpacing(2)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("搜索关键字（名称 / ID / 说明）…")
        self.filter.setClearButtonEnabled(True)
        # noinspection PyUnresolvedReferences
        self.filter.textChanged.connect(self._apply_filter)
        v.addWidget(self.filter)
        self._platform_hint = QLabel("")
        self._platform_hint.setObjectName("keyword_platform_hint")
        self._platform_hint.setWordWrap(True)
        v.addWidget(self._platform_hint)
        self.tree = _KeywordTree()
        v.addWidget(self.tree, 1)
        from ..theme import init_panel_style

        self._ui_theme = init_panel_style(self, "keyword_panel")
        self.tree._theme = self._ui_theme
        # noinspection PyUnresolvedReferences
        self.tree.keywordActivated.connect(self._on_activated)
        # noinspection PyUnresolvedReferences
        self.tree.findReferencesRequested.connect(self.findReferencesRequested.emit)

    def current_keyword_id(self) -> str:
        it = self.tree.currentItem()
        if it is None:
            return ""
        kid = it.data(0, _ROLE_KEYWORD_ID)
        return str(kid) if kid else ""

    def _on_activated(self, kid: str) -> None:
        """插入即记一次频次，刷新「常用」分组（高频自动上浮），再转发给上层插入。"""
        settings.bump_keyword_usage(kid)
        self.tree.rebuild_recent()
        self._apply_filter(self.filter.text())
        # noinspection PyUnresolvedReferences
        self.keywordActivated.emit(kid)

    # ---- 兼容委托 ----
    @property
    def catalog(self):
        return self.tree.catalog

    def load(self, config_dir: Optional[str] = None) -> KeywordCatalog:
        cat = self.tree.load(config_dir)
        self._apply_filter(self.filter.text())
        return cat

    def set_custom_keywords(self, store) -> None:
        self.tree.set_custom_keywords(store)
        self._apply_filter(self.filter.text())

    def set_target_platform(self, platform: str, *, hint: str = "") -> None:
        self._set_platform_hint(hint)
        self.tree.set_target_platform(platform)

    def _set_platform_hint(self, hint: str) -> None:
        self._platform_hint.setText((hint or "").strip())
        self._platform_hint.setVisible(bool((hint or "").strip()))

    # ---- 过滤 ----
    def _apply_filter(self, text: str) -> None:
        t = (text or "").strip().lower()

        def visit(item: QTreeWidgetItem) -> bool:
            if item.childCount() > 0:                      # 分组：任一后代可见则可见
                any_vis = False
                for ci in range(item.childCount()):
                    any_vis = visit(item.child(ci)) or any_vis
                item.setHidden(not any_vis)
                if t and any_vis:
                    item.setExpanded(True)                 # 过滤时自动展开命中分组
                return any_vis
            if not t:                                      # 叶子：空过滤全显
                item.setHidden(False)
                return True
            hay = " ".join(item.text(c) for c in range(len(_COLUMNS))).lower()
            vis = t in hay
            item.setHidden(not vis)
            return vis

        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i))

    def apply_theme(self, theme: str) -> None:
        from ..theme import apply_panel_theme

        resolved = apply_panel_theme(self, "keyword_panel", theme)
        self.tree.apply_tree_theme(resolved)
        self.tree.viewport().update()
