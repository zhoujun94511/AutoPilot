"""工程树组件：只浏览可编辑的工程资源（用例/套件/计划/对象库/关键字/数据配置）。

对标 Katalon Test Explorer、Airtest 脚本列表、Eclipse TestCase Explorer：
安装包、运行日志、HTML 报告不进这棵树，从设备菜单、控制台或运行结果打开。
文件按类型过滤；目录在子树内无任何可见文件时不展示（避免「空文件夹」）。
apk/ipa/logs/reports 以及 diag_* 诊断落盘默认隐藏。
config 不整目录隐藏：其下 DataConfig.properties 是数据配置，仍可从树打开。

对外信号：
  fileActivated(str path) —— 双击某个工程文件时发出。
"""

from __future__ import annotations

import os
import time
from typing import Optional

from PyQt6.QtCore import pyqtSignal, QModelIndex, QSortFilterProxyModel, Qt
from PyQt6.QtGui import QFileSystemModel, QColor, QPainter
from PyQt6.QtWidgets import QApplication, QTreeView

from ..actions import qicon
from ..theme import semantic_color
from ...runtime import settings


# 工程树可见文件：可编辑资源。不用裸 *.yaml，避免把 api_env 等配置和报告带进来。
# .tc.yaml 等复合后缀必须单独列出（QDir 的 *.tc 匹配不到 foo.tc.yaml）。
PROJECT_FILE_FILTERS = [
    "*.tc", "*.tc.yaml", "*.tc.yml",
    "*.ts", "*.ts.yaml", "*.ts.yml",
    "*.tp", "*.tp.yaml", "*.tp.yml",
    "*.map", "*.map.yaml", "*.map.yml",
    "*.ks", "*.ks.yaml", "*.ks.yml",
    "*.properties",
]
# 不展示的目录（缓存/编译/VCS/依赖/IDE 元数据等）
_IGNORED_DIRS = {
    "__pycache__", ".git", ".svn", ".hg", ".venv", "venv", "node_modules",
    ".idea", ".vscode", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "dist", "build", ".eggs", "__MACOSX",
}
# 运行产物目录（任意层级）。config 不在此列，以便打开 DataConfig.properties。
_ARTIFACT_DIRS = {
    "apk", "ipa", "logs", "log", "reports", "report",
}
_HIDDEN_DIR_NAMES = {n.casefold() for n in _IGNORED_DIRS} | _ARTIFACT_DIRS


def _norm_path(path: str) -> str:
    """大小写与分隔符无关的路径比较键。"""
    return os.path.normcase(os.path.normpath(path))


def _model_path(path: str) -> str:
    """交给 QFileSystemModel 的路径。

    Windows 临时目录常是 ``ADMINI~1`` 这种 8.3 短名，模型回调却是长路径。
    两边不一致时根节点挂不上，树会从盘符整棵铺开。
    """
    if not path:
        return ""
    try:
        return os.path.normpath(os.path.realpath(path))
    except OSError:
        return os.path.normpath(path)


def _ignored_dir(name: str) -> bool:
    """目录名是否应从工程树排除。"""
    if not name or name.startswith("."):
        return True
    if name.casefold() in _HIDDEN_DIR_NAMES:
        return True
    # 诊断脚本落盘（diag_onboarding* 等），非工程编辑资源
    return name.startswith("diag_")


# 按类型给图标（对标 VSCode file icons，一眼区分用例/套件/对象库…）
_TYPE_ICONS = {
    ".tc": ("mdi6.file-document-outline", "#1565C0"),
    ".ts": ("mdi6.format-list-checks", "#00897B"),
    ".tp": ("mdi6.clipboard-text-outline", "#6A1B9A"),
    ".map": ("mdi6.map-marker-outline", "#E65100"),
    ".properties": ("mdi6.cog-outline", "#546E7A"),
    ".ks": ("mdi6.puzzle-outline", "#AD1457"),
    ".apk": ("mdi6.android", "#3DDC84"),
    ".ipa": ("mdi6.apple", "#757575"),
    ".html": ("mdi6.file-code-outline", "#43A047"),
    ".jsonl": ("mdi6.code-json", "#F9A825"),
    ".json": ("mdi6.code-json", "#F9A825"),
    ".log": ("mdi6.text-box-outline", "#78909C"),
    ".txt": ("mdi6.text-box-outline", "#90A4AE"),
}
_ICON_CACHE: dict = {}


def _suffix_kind(path: str) -> str:
    """归一后缀：a.tc.yaml/a.tc → .tc；events.jsonl → .jsonl。"""
    low = path.lower()
    if low.endswith(".jsonl"):
        return ".jsonl"
    for k in _TYPE_ICONS:
        if low.endswith(k) or low.endswith(k + ".yaml") or low.endswith(k + ".yml"):
            return k
    return ""


def display_name(name: str) -> str:
    """去掉已知类型后缀显示（类型由图标表达）：启动应用.tc.yaml → 启动应用。"""
    kind = _suffix_kind(name)
    if not kind:
        return name
    low = name.lower()
    for suf in (kind + ".yaml", kind + ".yml", kind):
        if low.endswith(suf):
            return name[: -len(suf)] or name
    return name


def _file_icon(path: str, is_dir: bool):
    key = "<dir>" if is_dir else _suffix_kind(path)
    if not key:
        return None
    if key not in _ICON_CACHE:
        if is_dir:
            _ICON_CACHE[key] = qicon("mdi6.folder-outline", "#F4B400")
        else:
            name, color = _TYPE_ICONS[key]
            _ICON_CACHE[key] = qicon(name, color)
    return _ICON_CACHE[key]


class _ProjectFilter(QSortFilterProxyModel):
    """在 QFileSystemModel 之上：隐藏噪音目录与隐藏项；文件类型过滤交给源模型。

    另对标参考实现的 TestCase Explorer getChecked：用例(.tc)行带复选框，可勾选一批
    交「批量运行」；勾目录=勾其下全部用例，目录显示三态(全勾/部分/未勾)。
    """

    checkedChanged = pyqtSignal()        # 勾选集变化 → 面板刷新「批量运行(N)」

    def __init__(self, fs: QFileSystemModel, parent=None) -> None:
        super().__init__(parent)
        self._fs = fs
        self._active = False        # 无工程时全拒，绝不把整盘文件系统铺出来
        self._project = ""          # 工程目录(规范化)；其父目录下只放行它本身做根节点
        self._parent = ""           # 工程父目录(规范化)
        self._name_filter = ""      # 名称过滤(小写)；命中文件的父目录靠递归过滤保留
        self._checked: dict = {}    # 规范化键 → 真实路径（已勾选的用例文件）
        self.setSourceModel(fs)
        self.setRecursiveFilteringEnabled(True)   # 子项命中则保留其祖先目录

    @staticmethod
    def _norm(path: str) -> str:
        return _norm_path(path)

    def _case_descendants(self, src: QModelIndex) -> list:
        """目录(源索引)下递归收集所有用例(.tc)的真实路径，跳过噪音目录。"""
        out = []
        for r in range(self._fs.rowCount(src)):
            ch = self._fs.index(r, 0, src)
            if self._fs.isDir(ch):
                name = self._fs.fileName(ch)
                if _ignored_dir(name):
                    continue
                out.extend(self._case_descendants(ch))
            elif _suffix_kind(self._fs.filePath(ch)) == ".tc":
                out.append(self._fs.filePath(ch))
        return out

    def _file_matches_name_filter(self, name: str) -> bool:
        if not self._name_filter:
            return True
        hay = (name + " " + display_name(name)).lower()
        return self._name_filter in hay

    def _has_visible_descendant(self, src: QModelIndex) -> bool:
        """目录下是否存在通过类型/名称过滤的文件（或含可见子目录）。"""
        for r in range(self._fs.rowCount(src)):
            ch = self._fs.index(r, 0, src)
            if not ch.isValid():
                continue
            name = self._fs.fileName(ch)
            if self._fs.isDir(ch):
                if _ignored_dir(name):
                    continue
                if self._has_visible_descendant(ch):
                    return True
            elif self._file_matches_name_filter(name):
                return True
        return False

    def _check_state(self, src: QModelIndex):
        """该源索引应显示的勾选态：用例=勾/未勾；目录=三态；其它=None(无框)。"""
        if self._fs.isDir(src):
            desc = self._case_descendants(src)
            if not desc:
                return None
            n = sum(1 for p in desc if self._norm(p) in self._checked)
            if n == 0:
                return Qt.CheckState.Unchecked
            if n == len(desc):
                return Qt.CheckState.Checked
            return Qt.CheckState.PartiallyChecked
        if _suffix_kind(self._fs.filePath(src)) == ".tc":
            in_set = self._norm(self._fs.filePath(src)) in self._checked
            return Qt.CheckState.Checked if in_set else Qt.CheckState.Unchecked
        return None

    def checked_paths(self) -> list:
        """已勾选且仍存在的用例文件真实路径（排序，稳定）。"""
        return sorted(p for p in self._checked.values() if os.path.isfile(p))

    def clear_checks(self) -> None:
        if self._checked:
            self._checked.clear()
            self.layoutChanged.emit()      # 简单可靠地刷新全部复选框
            # noinspection PyUnresolvedReferences
            self.checkedChanged.emit()

    def rebase_paths(self, old: str, new: str) -> None:
        """将勾选用例路径随文件/目录重命名迁移。"""
        old_norm = self._norm(old)
        prefix = old_norm + os.sep
        changed = False
        updated = {}
        for path in self._checked.values():
            norm = self._norm(path)
            if norm == old_norm:
                rebased = new
            elif norm.startswith(prefix):
                rebased = os.path.join(new, os.path.relpath(path, old))
            else:
                rebased = path
            updated[self._norm(rebased)] = rebased
            changed = changed or rebased != path
        if changed:
            self._checked = updated
            self.layoutChanged.emit()
            # noinspection PyUnresolvedReferences
            self.checkedChanged.emit()

    def drop_paths(self, path: str) -> None:
        """移除被删除文件/目录及其子树的勾选记录。"""
        norm = self._norm(path)
        prefix = norm + os.sep
        kept = {
            key: value for key, value in self._checked.items()
            if self._norm(value) != norm and not self._norm(value).startswith(prefix)
        }
        if len(kept) != len(self._checked):
            self._checked = kept
            self.layoutChanged.emit()
            # noinspection PyUnresolvedReferences
            self.checkedChanged.emit()

    def all_case_paths(self) -> list:
        """当前过滤条件下工程内全部可见用例路径。"""
        if not self._project:
            return []
        src = self._fs.index(self._project)
        if not src.isValid():
            return []
        paths = self._case_descendants(src)
        if self._name_filter:
            paths = [p for p in paths
                     if self._file_matches_name_filter(os.path.basename(p))]
        return paths

    def check_all_cases(self) -> int:
        """勾选当前可见的全部用例；返回勾选数量。"""
        paths = self.all_case_paths()
        if not paths:
            return 0
        self._set_checked(paths, True)
        src = self._fs.index(self._project)
        root_proxy = self.mapFromSource(src) if src.isValid() else QModelIndex()
        if root_proxy.isValid():
            self._emit_subtree(root_proxy)
        # noinspection PyUnresolvedReferences
        self.checkedChanged.emit()
        return len(paths)

    def invert_visible_checks(self) -> int:
        """反选当前可见用例（未勾→勾、已勾→取消）；返回操作后勾选数。"""
        paths = self.all_case_paths()
        if not paths:
            return len(self.checked_paths())
        for p in paths:
            norm = self._norm(p)
            if norm in self._checked:
                self._checked.pop(norm, None)
            else:
                self._checked[norm] = p
        src = self._fs.index(self._project)
        root_proxy = self.mapFromSource(src) if src.isValid() else QModelIndex()
        if root_proxy.isValid():
            self._emit_subtree(root_proxy)
        # noinspection PyUnresolvedReferences
        self.checkedChanged.emit()
        return len(self.checked_paths())

    def _set_checked(self, paths, on: bool) -> None:
        for p in paths:
            if on:
                self._checked[self._norm(p)] = p
            else:
                self._checked.pop(self._norm(p), None)

    def _emit_subtree(self, index: QModelIndex) -> None:
        if index is None or not index.isValid():
            return
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        for r in range(self.rowCount(index)):
            self._emit_subtree(self.index(r, 0, index))

    def set_active(self, on: bool) -> None:
        if on != self._active:
            self._active = on
            self.invalidateFilter()

    def set_project(self, path: str) -> None:
        self._project = os.path.normcase(os.path.normpath(path)) if path else ""
        self._parent = os.path.normcase(os.path.dirname(os.path.normpath(path))) if path else ""
        self.invalidateFilter()

    def set_name_filter(self, text: str) -> None:
        self._name_filter = (text or "").strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:
        if not self._active:        # 未打开工程 → 一行不显示（只留空态占位）
            return False
        idx = self._fs.index(row, 0, parent)
        if not idx.isValid():
            return False
        fp = os.path.normcase(os.path.normpath(self._fs.filePath(idx)))
        # 顶层（父=工程的父目录）：只放行工程目录本身，作为唯一根节点（不暴露同级兄弟）
        if self._parent and parent.isValid():
            parent_fp = os.path.normcase(os.path.normpath(self._fs.filePath(parent)))
            if parent_fp == self._parent:
                # 工程根：无过滤恒显；有过滤时由递归过滤据子项命中决定保留
                return fp == self._project and not self._name_filter
        name = self._fs.fileName(idx)
        is_dir = self._fs.isDir(idx)
        if is_dir and _ignored_dir(name):
            return False
        if self._name_filter:
            if is_dir:
                return False        # 目录本身不直接命中，靠递归(子文件命中)保留
            hay = (name + " " + display_name(name)).lower()
            return self._name_filter in hay
        if is_dir:
            return self._has_visible_descendant(idx)
        return True

    def flags(self, index):
        f = super().flags(index)
        if index.column() == 0:
            src = self.mapToSource(index)
            if self._fs.isDir(src):
                if self._case_descendants(src):     # 有用例的目录才给框（可整勾）
                    f |= Qt.ItemFlag.ItemIsUserCheckable
            elif _suffix_kind(self._fs.filePath(src)) == ".tc":
                f |= Qt.ItemFlag.ItemIsUserCheckable
        return f

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if index.column() == 0 and role == Qt.ItemDataRole.CheckStateRole:
            src = self.mapToSource(index)
            on = Qt.CheckState(value) == Qt.CheckState.Checked
            if self._fs.isDir(src):
                self._set_checked(self._case_descendants(src), on)
            elif _suffix_kind(self._fs.filePath(src)) == ".tc":
                self._set_checked([self._fs.filePath(src)], on)
            else:
                return False
            self._emit_subtree(index)               # 自身+后代复选框刷新
            p = index.parent()
            while p.isValid():                      # 祖先目录三态刷新
                self.dataChanged.emit(p, p, [Qt.ItemDataRole.CheckStateRole])
                p = p.parent()
            # noinspection PyUnresolvedReferences
            self.checkedChanged.emit()
            return True
        return super().setData(index, value, role)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        # 第 0 列：按类型替换图标 + 文件名去后缀显示（完整名作悬停提示）
        if index.column() == 0:
            src = self.mapToSource(index)
            if role == Qt.ItemDataRole.CheckStateRole:
                return self._check_state(src)
            if role == Qt.ItemDataRole.DecorationRole:
                ic = _file_icon(self._fs.filePath(src), self._fs.isDir(src))
                if ic is not None:
                    return ic
            elif not self._fs.isDir(src):
                name = self._fs.fileName(src)
                if role == Qt.ItemDataRole.DisplayRole:
                    return display_name(name)
                if role == Qt.ItemDataRole.ToolTipRole:
                    return name        # 悬停看完整文件名
        return super().data(index, role)


class ProjectTree(QTreeView):
    fileActivated = pyqtSignal(str)
    renameRequested = pyqtSignal()      # F2：请主窗口走重命名
    deleteRequested = pyqtSignal()      # Delete：请主窗口走删除
    checkedChanged = pyqtSignal()       # 勾选用例集变化（转发自代理）

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("project_tree")
        self._fs = QFileSystemModel(self)
        self._fs.setNameFilters(PROJECT_FILE_FILTERS)
        self._fs.setNameFilterDisables(False)     # 非匹配文件隐藏，而非置灰
        self._proxy = _ProjectFilter(self._fs, self)
        self.setModel(self._proxy)
        self._root: Optional[str] = None
        self._path_root = ""
        self._model_root = ""
        for col in (1, 2, 3):  # 隐藏大小/类型/修改时间列
            self.hideColumn(col)
        self.setHeaderHidden(True)
        self.setAlternatingRowColors(True)
        self.setDragEnabled(True)          # 允许把 .tc 拖进用例编辑器→内嵌用例引用
        self.setDragDropMode(QTreeView.DragDropMode.DragOnly)
        # noinspection PyUnresolvedReferences
        self.doubleClicked.connect(self._emit_activated)
        # noinspection PyUnresolvedReferences
        self._proxy.checkedChanged.connect(self.checkedChanged)   # 转发勾选变化
        # 预取整棵工程子树（独立于代理过滤），否则懒加载下过滤看不到未展开目录里的文件
        # noinspection PyUnresolvedReferences
        self._fs.directoryLoaded.connect(self._prefetch_children)

    def _prefetch_children(self, path: str) -> None:
        if not self._root:
            return
        rp = os.path.normcase(_model_path(self._root))
        np = os.path.normcase(os.path.normpath(path))
        if not (np == rp or np.startswith(rp + os.sep)):
            return                      # 只预取工程子树内，不碰其它
        self._proxy.invalidateFilter()    # 目录内容变化后重算「空文件夹」过滤
        idx = self._fs.index(path)
        for r in range(self._fs.rowCount(idx)):
            ch = self._fs.index(r, 0, idx)
            if self._fs.isDir(ch):
                name = self._fs.fileName(ch)
                if _ignored_dir(name):
                    continue
                if self._fs.canFetchMore(ch):
                    self._fs.fetchMore(ch)   # 触发其 directoryLoaded → 级联加载

    def set_root(self, path: str) -> None:
        previous = self._root
        self._root = path
        valid = bool(path) and os.path.isdir(path)
        if valid and previous and _norm_path(previous) != _norm_path(path):
            # 切换到另一个工程时，旧工程的勾选不能带入新工程。
            self._proxy.clear_checks()
        self._proxy.set_active(valid)
        if valid:
            # 以「工程目录」为根节点：root 设到其父目录，代理只放行工程目录本身
            model_path = _model_path(path)
            self._path_root, self._model_root = path, model_path
            parent = os.path.dirname(model_path) or model_path
            self._proxy.set_project(model_path)
            self._fs.setRootPath(model_path)
            self.setRootIndex(self._proxy.mapFromSource(self._fs.index(parent)))
            self.expandToDepth(0)       # 展开工程根，直接露出其内容
        else:
            # 无工程：不挂任何根，配合代理全拒 → 树彻底空白，只显示「未打开工程」占位
            self._proxy.set_project("")
            # 释放 QFileSystemModel 对旧工程目录的监视。Windows 下如果
            # 仍挂着旧根就直接重命名工程目录，目录改名可能被模型的目录
            # 监视句柄阻断，或改名后继续回调旧路径。
            self._fs.setRootPath("")
            self.setRootIndex(QModelIndex())
            if previous:
                # 仅 setRootPath("") 在 Windows 下不会立刻释放 QFileSystemWatcher/QFileInfoGatherer
                # 对旧工程目录的句柄；重建 QFileSystemModel 并销毁旧实例才能彻底解除占用。
                old_fs = self._fs
                new_fs = QFileSystemModel(self)
                new_fs.setNameFilters(PROJECT_FILE_FILTERS)
                new_fs.setNameFilterDisables(False)
                # noinspection PyUnresolvedReferences
                new_fs.directoryLoaded.connect(self._prefetch_children)
                self._fs = new_fs
                self._proxy._fs = new_fs
                self._proxy.setSourceModel(new_fs)
                try:
                    # noinspection PyUnresolvedReferences
                    old_fs.directoryLoaded.disconnect(self._prefetch_children)
                except (TypeError, RuntimeError):
                    pass
                old_fs.setParent(None)
                old_fs.deleteLater()
            self._proxy.invalidateFilter()
        self.viewport().update()        # 触发空态提示重绘

    def paintEvent(self, e) -> None:
        super().paintEvent(e)
        if not self._root or not os.path.isdir(self._root):
            self._draw_hint("未打开工程\n\n「文件 ▸ 新建工程」创建新工程，\n或「打开工程」选择现有目录")
        elif self._proxy.rowCount(self.rootIndex()) == 0:
            self._draw_hint("空工程\n\n在此处右键，或用「文件 ▸ 新建」添加用例/测试套等")

    def _draw_hint(self, text: str) -> None:
        color = semantic_color("hint", settings.ui_theme())
        p = QPainter(self.viewport())
        p.setPen(QColor(color))
        r = self.viewport().rect().adjusted(16, 0, -16, 0)
        p.drawText(r, int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap), text)
        p.end()

    def _logical_path(self, path: str) -> str:
        """Keep public paths in the spelling used to open this project."""
        if not self._path_root or not self._model_root:
            return path
        normalized = _norm_path(path)
        model_root = _norm_path(self._model_root)
        if normalized == model_root:
            return self._path_root
        if normalized.startswith(model_root + os.sep):
            return os.path.join(self._path_root, os.path.relpath(path, self._model_root))
        return path

    def _internal_path(self, path: str) -> str:
        # Retain this mapping while set_root("") detaches the filesystem model
        # for a root rename; the old path may already have disappeared.
        logical_root = _norm_path(self._path_root) if self._path_root else ""
        normalized = _norm_path(path)
        if logical_root and normalized == logical_root:
            return self._model_root
        if logical_root and normalized.startswith(logical_root + os.sep):
            return os.path.join(self._model_root, os.path.relpath(path, self._path_root))
        return _model_path(path)

    def selected_path(self) -> Optional[str]:
        """当前选中项的绝对路径；无选中返回根目录。"""
        idx = self.currentIndex()
        if idx.isValid():
            return self._logical_path(self._fs.filePath(self._proxy.mapToSource(idx)))
        return getattr(self, "_root", None)

    def selected_dir(self) -> Optional[str]:
        """选中项所在目录：选中目录则返回自身，选中文件则返回其父目录。"""
        path = self.selected_path()
        if not path:
            return None
        return path if os.path.isdir(path) else os.path.dirname(path)

    def _emit_activated(self, index: QModelIndex) -> None:
        src = self._proxy.mapToSource(index)
        path = self._fs.filePath(src)
        if not self._fs.isDir(src):
            # noinspection PyUnresolvedReferences
            self.fileActivated.emit(self._logical_path(path))

    def refresh(self) -> None:
        """强制重扫工程目录（外部新增用例等文件时有效）。

        旧实现仅重复 set_root(同路径)，Qt 不会重读磁盘，等于空操作。
        """
        if not self._root or not os.path.isdir(self._root):
            return
        root = _model_path(self._root)
        parent = os.path.dirname(root) or root

        expanded: set[str] = set()

        def collect_expanded(proxy_idx: QModelIndex) -> None:
            if not proxy_idx.isValid():
                return
            for r in range(self._proxy.rowCount(proxy_idx)):
                child = self._proxy.index(r, 0, proxy_idx)
                if self.isExpanded(child):
                    src = self._proxy.mapToSource(child)
                    expanded.add(os.path.normcase(self._fs.filePath(src)))
                collect_expanded(child)

        collect_expanded(self.rootIndex())

        self._fs.setRootPath("")
        self._proxy.invalidateFilter()
        self._fs.setRootPath(root)
        self._proxy.set_project(root)
        self.setRootIndex(self._proxy.mapFromSource(self._fs.index(parent)))

        app = QApplication.instance()
        if app is not None:
            deadline = time.monotonic() + 2.0
            root_idx = self._fs.index(root)
            while time.monotonic() < deadline:
                app.processEvents()
                if self._fs.rowCount(root_idx) > 0 or self._fs.canFetchMore(root_idx):
                    break

        self._prefetch_children(root)
        if app is not None:
            for _ in range(80):
                app.processEvents()

        self.expandToDepth(0)

        def restore_expanded(proxy_idx: QModelIndex) -> None:
            if not proxy_idx.isValid():
                return
            for r in range(self._proxy.rowCount(proxy_idx)):
                child = self._proxy.index(r, 0, proxy_idx)
                src = self._proxy.mapToSource(child)
                fp = os.path.normcase(self._fs.filePath(src))
                if fp in expanded:
                    self.expand(child)
                restore_expanded(child)

        restore_expanded(self.rootIndex())
        self.viewport().update()

    def checked_paths(self) -> list:
        """已勾选用例(.tc)的真实路径列表（供「批量运行」）。"""
        return sorted(self._logical_path(path) for path in self._proxy.checked_paths())

    def clear_checks(self) -> None:
        self._proxy.clear_checks()

    def rebase_paths(self, old: str, new: str) -> None:
        self._proxy.rebase_paths(old, new)
        self._proxy.rebase_paths(self._internal_path(old), self._internal_path(new))

    def drop_paths(self, path: str) -> None:
        self._proxy.drop_paths(path)
        self._proxy.drop_paths(self._internal_path(path))

    def check_all_cases(self) -> int:
        return self._proxy.check_all_cases()

    def invert_visible_checks(self) -> int:
        return self._proxy.invert_visible_checks()

    def visible_case_count(self) -> int:
        return len(self._proxy.all_case_paths())

    def collapse_subdirs(self) -> None:
        """折叠工程内所有子目录；工程根（如 AIID）保持一行可见但子级收起。"""
        self.collapseAll()
        root = self.rootIndex()
        if not root.isValid():
            return
        for r in range(self._proxy.rowCount(root)):
            proj = self._proxy.index(r, 0, root)
            if not proj.isValid():
                continue
            self.expand(proj)      # 工程根行保持在树中
            self.collapse(proj)    # 其下子目录全部收起

    def set_name_filter(self, text: str) -> None:
        """按名称过滤工程树；有过滤词时展开以露出命中项。"""
        self._proxy.set_name_filter(text)
        if (text or "").strip():
            self.expandAll()
        else:
            self.expandToDepth(0)       # 清空过滤：回到只展开工程根

    def keyPressEvent(self, e) -> None:
        k = e.key()
        if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            idx = self.currentIndex()
            if idx.isValid():
                self._emit_activated(idx)      # 打开
            return
        if k == Qt.Key.Key_F2 and self.currentIndex().isValid():
            # noinspection PyUnresolvedReferences
            self.renameRequested.emit()
            return
        if k == Qt.Key.Key_Delete and self.currentIndex().isValid():
            # noinspection PyUnresolvedReferences
            self.deleteRequested.emit()
            return
        super().keyPressEvent(e)
