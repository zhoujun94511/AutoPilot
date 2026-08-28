"""用例步骤编辑器组件：展示并编辑一个 TestCase 的步骤树。

职责：渲染 shell→步骤（含嵌套）；支持插入/删除/上移/下移步骤。
为支持就地编辑，每行记录其「所属父列表」与「所属 shell 名」，
这样插入/删除直接作用到模型对应的 list，再重渲染。

对外信号：
  stepSelected(object node) —— 选中某步骤节点时发出（参数表单订阅）。
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QAbstractItemView, QTableWidget, QTableWidgetItem, QHeaderView

from ...model.testcase import (
    Step,
    StepSet,
    StepVerbs,
    StepInnerCase,
    StepNode,
    ParamValue,
    TestCase,
)
from ...metadata import KeywordMeta, KeywordCatalog
from ...runtime import settings
from ..theme import effective_theme
from .step_param_rules import format_step_params


_COLUMNS = ["关键字", "参数", "说明", "备注", "所属段"]
_SHELL_LABELS = {"before": "前置", "case": "主体", "after": "后置", "fault": "异常"}
_COL_KEYWORD, _COL_PARAMS, _COL_DESC, _COL_REMARK, _COL_SHELL = range(5)


@dataclass
class _RowRef:
    node: StepNode
    parent: list      # 包含该 node 的列表（shell.steps 或某容器的 children）
    shell: str        # 所属 shell 名（before/case/after/fault）


def _index_by_identity(lst: list, obj) -> int:
    """按对象身份(is)找索引；找不到返回 -1。

    步骤是 dataclass，默认按「值」相等——list.index/remove/in 在存在内容相同的步骤
    (如连续粘贴同一步骤)时会命中「第一个相等项」而非目标本身，导致插入/删除错位。
    凡按选中节点定位其在父列表中的位置，一律走本函数（身份判定）。
    """
    for i, x in enumerate(lst):
        if x is obj:
            return i
    return -1


def build_default_params(meta: Optional[KeywordMeta]) -> list[ParamValue]:
    """由关键字元数据生成默认参数（带默认值的填默认，必填项留空占位）。"""
    if meta is None:
        return []
    out: list[ParamValue] = []
    for pm in meta.params:
        if pm.default:
            out.append(ParamValue(pm.param_id, pm.default))
        elif pm.required:
            out.append(ParamValue(pm.param_id, ""))
    return out


def _node_display(node: object, case_platform: str = "") -> tuple[str, str, str]:
    """返回 (关键字原文, 参数文本, 第三列占位——说明由目录动态解析)。"""
    if isinstance(node, Step):
        return node.keyword_id, format_step_params(node, case_platform), ""
    if isinstance(node, StepVerbs):
        return f"[ks]{node.ks_id}", "  ".join(
            f"{p.param_id}={p.value}" for p in node.params
        ), ""
    if isinstance(node, StepSet):
        return "[组]" + node.name, node.datapool, node.comment
    if isinstance(node, StepInnerCase):
        return "[内嵌]", node.relative_path, node.comment
    return "", "", ""


class CaseEditor(QTableWidget):
    stepSelected = pyqtSignal(object)
    keywordDropped = pyqtSignal(str)   # 关键字库拖拽放置时发出（id 或 ks:: 前缀）
    editParamsRequested = pyqtSignal(object)   # 双击「参数」列：请主窗口弹出/聚焦参数面板

    def __init__(self, parent=None) -> None:
        super().__init__(0, len(_COLUMNS), parent)
        self.setObjectName("case_editor")
        self.setHorizontalHeaderLabels(_COLUMNS)
        hdr = self.horizontalHeader()
        # 列宽策略：关键字/参数可手动拖拽(Interactive)；「说明」列 Stretch 永远吸收富余
        # (拖别的列右侧不会留白)；「所属段」固定窄宽、不可拖(Fixed)、内容少不占地。
        # 初始按视口宽度以约 2:3:4:1(关键字:参数:说明:所属段) 铺开，未手动调过则随窗口重排。
        hdr.setSectionResizeMode(_COL_KEYWORD, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(_COL_PARAMS, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(_COL_DESC, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(_COL_REMARK, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(_COL_SHELL, QHeaderView.ResizeMode.Fixed)
        hdr.setStretchLastSection(False)
        self.setColumnWidth(_COL_SHELL, self._SHELL_W)
        self.setColumnWidth(_COL_REMARK, self._REMARK_W)
        self._col_user_resized = False   # 用户是否手动拖过列宽
        self._applying_ratio = False     # 抑制程序性设宽被误判为手动
        # noinspection PyUnresolvedReferences
        hdr.sectionResized.connect(self._on_section_resized)
        # 视觉：斑马行 + 行高 + 左侧序号（对标参考实现的「序号」列）
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(True)
        self.setAcceptDrops(True)   # 接收关键字库拖拽
        self._case: Optional[TestCase] = None
        self._catalog: Optional[KeywordCatalog] = None   # 解析关键字 id→中文名（与关键字库一致）
        self._default_platform: str = ""   # 工程默认平台（用例未标 platform 时用于参数列/显隐）
        self._rows: list[_RowRef] = []
        self._rendering = False  # 渲染期间忽略 itemChanged，避免回写抖动
        self._undo: list = []        # 撤销栈（整文档深拷贝快照）
        self._redo: list = []
        self._clipboard: list = []   # 复制/剪切的步骤节点（深拷贝，支持多行）
        self._ui_theme = effective_theme(settings.ui_theme())
        # 整行选择 + 多选：支持多行复制/剪切/粘贴（对标现代编辑器）
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # noinspection PyUnresolvedReferences
        self.itemSelectionChanged.connect(self._on_selection)
        # noinspection PyUnresolvedReferences
        self.itemChanged.connect(self._on_item_changed)
        # noinspection PyUnresolvedReferences
        self.cellDoubleClicked.connect(self._on_cell_double_clicked)
        # noinspection PyUnresolvedReferences
        self.cellClicked.connect(self._on_cell_clicked)

    def _emit_edit_params_if_step(self, row: int) -> None:
        if 0 <= row < len(self._rows):
            node = self._rows[row].node
            if node is not None and (
                getattr(node, "params", None) is not None
                or isinstance(node, (StepSet, StepInnerCase))
            ):
                # noinspection PyUnresolvedReferences
                self.editParamsRequested.emit(node)

    def _on_cell_clicked(self, row: int, col: int) -> None:
        """单击关键字/参数/说明列 → 聚焦右侧参数面板（同行再点说明列也需生效）。"""
        if col in (_COL_KEYWORD, _COL_PARAMS, _COL_DESC):
            self._emit_edit_params_if_step(row)

    def _on_cell_double_clicked(self, row: int, col: int) -> None:
        """双击关键字/参数/说明列 → 弹出参数面板；备注列保留行内编辑。"""
        if col == _COL_REMARK:
            return
        self._emit_edit_params_if_step(row)

    @property
    def case(self) -> Optional[TestCase]:
        return self._case

    def set_catalog(self, catalog: Optional[KeywordCatalog]) -> None:
        """注入关键字目录，使「关键字」列显示中文名（与关键字库一致）。"""
        self._catalog = catalog
        if self._case is not None:
            self._render()

    def set_default_platform(self, platform: str) -> None:
        """工程默认平台：用例 platform 为空时用于参数列渲染与条件显隐。"""
        self._default_platform = (platform or "").strip().lower()

    def _keyword_label(self, node: object, fallback: str) -> str:
        """关键字列显示文案：标准关键字用目录里的中文名，缺目录/自定义则回退原文案。"""
        kid = getattr(node, "keyword_id", None)
        if kid and self._catalog is not None:
            meta = self._catalog.get(kid)
            if meta is not None and meta.name:
                return meta.name
        return fallback

    def _default_parent_list(self) -> list:
        """无选中时新步骤追加到的目标列表（用例默认 case shell）。子类可重写。"""
        return self._case.case.steps

    def selected_node(self) -> object:
        row = self.currentRow()
        return self._rows[row].node if 0 <= row < len(self._rows) else None

    def shell_move_targets(self) -> list[tuple[str, str]]:
        """当前选中的「顶层步骤」可移动到的其它执行段 [(name, 中文标签)]。

        无选中、或选中的是嵌套在 if/循环体内的步骤（不宜跨段移动）→ 返回 []。
        """
        if self._case is None:
            return []
        row = self.currentRow()
        if not (0 <= row < len(self._rows)):
            return []
        ref = self._rows[row]
        if ref.parent not in [s.steps for s in self._case.shells]:   # 仅顶层步骤
            return []
        return [(s.name, _SHELL_LABELS.get(s.name, s.name))
                for s in self._case.shells if s.name != ref.shell]

    def move_selected_to_shell(self, shell_name: str) -> bool:
        """把选中的顶层步骤移动到指定执行段（前置/主体/后置/异常）。"""
        if self._case is None:
            return False
        row = self.currentRow()
        if not (0 <= row < len(self._rows)):
            return False
        ref = self._rows[row]
        target = next((s for s in self._case.shells if s.name == shell_name), None)
        if (target is None or ref.parent is target.steps
                or ref.parent not in [s.steps for s in self._case.shells]):
            return False
        i = _index_by_identity(ref.parent, ref.node)
        if i < 0:
            return False
        self._push_undo()
        ref.parent.pop(i)                 # 身份定位删除，避免误删内容相同的其它步骤
        target.steps.append(ref.node)
        self._render(select_node=ref.node)
        return True

    # ---- 渲染 ----
    def show_case(self, tc: TestCase) -> None:
        self._case = tc
        self._render()

    def rerender(self, select_node: object = None) -> None:
        """公开重绘入口（平台变更等外部刷新用，避免调用方碰 ``_render``）。"""
        self._render(select_node=select_node)

    def _render(self, select_node: object = None) -> None:
        self._rendering = True
        try:
            self.setRowCount(0)
            self._rows.clear()
            if self._case is None:
                return
            for shell in self._case.shells:
                for node in shell.steps:
                    self._add_node_row(shell.name, node, shell.steps, depth=0)
        finally:
            self._rendering = False
        if select_node is not None:
            self._select_node(select_node)
        else:
            self._on_selection()

    def _step_description(self, node: object) -> str:
        """关键字通用说明：优先关键字目录，组/内嵌回退 node.comment。"""
        kid = getattr(node, "keyword_id", None)
        if kid and self._catalog:
            meta = self._catalog.get(kid)
            if meta:
                return meta.comment or meta.name or ""
        if isinstance(node, (StepSet, StepInnerCase)):
            return getattr(node, "comment", "") or ""
        return getattr(node, "comment", "") or ""

    def _case_platform(self) -> str:
        if self._case is None:
            return self._default_platform
        plat = (self._case.platform or "").strip().lower()
        if plat in ("android", "ios", "web"):
            return plat
        return self._default_platform

    def _row_color(self, key: str) -> QColor:
        from ..theme import semantic_color

        return QColor(semantic_color(key, self._ui_theme))

    def _add_node_row(self, shell: str, node: StepNode, parent: list, depth: int) -> None:
        kw, params, _ = _node_display(node, self._case_platform())
        if not kw:
            return
        desc = self._step_description(node)
        remark = getattr(node, "remark", "") or ""
        label = self._keyword_label(node, kw)     # 关键字列显示中文名（与关键字库一致）
        kid = getattr(node, "keyword_id", None) or getattr(node, "ks_id", None)
        row = self.rowCount()
        self.insertRow(row)
        # noinspection PyTypeChecker
        ro_flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        shell_label = "" if shell == "case" else shell   # 主体 case 留空，仅前置/后置/异常显示
        disabled = getattr(node, "is_run", True) is False   # 禁用步骤：整行灰显 + 前缀标记
        kw_cell = ("    " * depth) + ("⊘ " if disabled else "") + label
        cells = (kw_cell, params, desc, remark, shell_label)
        for col, text in enumerate(cells):
            item = QTableWidgetItem(text)
            if col == _COL_REMARK:   # 仅「备注」列可编辑，回写 node.remark
                item.setFlags(ro_flags | Qt.ItemFlag.ItemIsEditable)
            else:
                item.setFlags(ro_flags)
            if disabled:
                item.setForeground(self._row_color("disabled"))
                f = item.font(); f.setItalic(True); item.setFont(f)
            elif col == _COL_KEYWORD and kid:
                item.setToolTip(f"关键字 ID：{kid}")   # 悬停看原始 id（参数名/逻辑不变）
            elif col == _COL_PARAMS:
                item.setForeground(self._row_color("muted"))
                item.setToolTip((params + "\n\n" if params else "") + "单击或双击编辑参数（在右侧「参数」面板）")
            elif col == _COL_DESC:
                item.setForeground(self._row_color("muted"))
                tip = "单击或双击在此列也可编辑参数（右侧「参数」面板）"
                if desc:
                    item.setToolTip(desc + "\n\n" + tip)
                else:
                    item.setToolTip(tip)
            elif col == _COL_REMARK and remark:
                item.setToolTip(remark)
            elif col == _COL_SHELL and shell_label:
                item.setForeground(self._row_color("shell_muted"))
            self.setItem(row, col, item)
        self._rows.append(_RowRef(node, parent, shell))
        children = getattr(node, "children", None)
        if children is not None:
            for child in children:
                self._add_node_row(shell, child, children, depth + 1)

    def select_by_keyword(self, keyword_id: str) -> bool:
        """选中首个匹配该 keyword_id 的步骤行（控制台↔编辑器联动）。"""
        for row, ref in enumerate(self._rows):
            node = ref.node
            kid = getattr(node, "keyword_id", None) or getattr(node, "ks_id", None)
            if kid == keyword_id:
                self.selectRow(row)
                self.scrollToItem(self.item(row, 0))
                return True
        return False

    def _select_node(self, node: object) -> None:
        for row, ref in enumerate(self._rows):
            if ref.node is node:
                self.selectRow(row)
                return

    # ---- 撤销 / 重做 ----
    def _push_undo(self) -> None:
        if self._case is not None:
            self._undo.append(copy.deepcopy(self._case))
            self._redo.clear()
            if len(self._undo) > 100:
                self._undo.pop(0)

    def undo(self) -> None:
        if not self._undo:
            return
        self._redo.append(copy.deepcopy(self._case))
        self._case = self._undo.pop()
        self._render()

    def redo(self) -> None:
        if not self._redo:
            return
        self._undo.append(copy.deepcopy(self._case))
        self._case = self._redo.pop()
        self._render()

    # ---- 剪贴板（支持多行）----
    def _selected_refs(self) -> list:
        """选中的行(去重、按可视顺序)对应的 _RowRef；无多选则回退到 currentRow。"""
        rows = sorted({idx.row() for idx in self.selectedIndexes()})
        if not rows:
            r = self.currentRow()
            rows = [r] if 0 <= r < len(self._rows) else []
        return [self._rows[r] for r in rows if 0 <= r < len(self._rows)]

    @staticmethod
    def _topmost_refs(refs: list) -> list:
        """剔除「其祖先也在选中集里」的行，避免父子同时选中导致重复拷贝/误删。"""
        def in_subtree(container, target) -> bool:
            for c in getattr(container, "children", None) or []:
                if c is target or in_subtree(c, target):
                    return True
            return False
        return [r for r in refs
                if not any(o is not r and in_subtree(o.node, r.node) for o in refs)]

    def copy_selected(self) -> None:
        top = self._topmost_refs(self._selected_refs())
        if top:
            self._clipboard = [copy.deepcopy(r.node) for r in top]   # 按可视顺序整批

    def cut_selected(self) -> None:
        top = self._topmost_refs(self._selected_refs())
        if not top:
            return
        self._clipboard = [copy.deepcopy(r.node) for r in top]
        self._push_undo()
        for r in top:                       # 身份删除，防误删内容相同的其它步骤
            i = _index_by_identity(r.parent, r.node)
            if i >= 0:
                r.parent.pop(i)
        self._render()

    def paste(self) -> Optional[object]:
        """把剪贴板里的节点整批插到目标位置下方；选中最后一个，便于连续整批粘贴继续下叠。"""
        if not self._clipboard or self._case is None:
            return None
        parent, idx = self._insert_target()
        self._push_undo()
        nodes = [copy.deepcopy(n) for n in self._clipboard]
        if idx is None:
            parent.extend(nodes)
        else:
            for k, n in enumerate(nodes):
                parent.insert(idx + k, n)
        self._render(select_node=nodes[-1])
        return nodes[-1]

    # ---- 编辑操作 ----
    def _insert_target(self) -> tuple[list, Optional[int]]:
        """计算新节点插入的 (目标列表, 索引)。索引为 None 表示追加。

        选中条件步骤 → 插到其 if 体末尾（else 标记之前）；
        选中步骤组 → 插到其子步骤末尾；
        其它 → 插到选中节点所在列表、该节点之后；无选中 → 追加到默认 shell。
        """
        row = self.currentRow()
        if not (0 <= row < len(self._rows)):
            return self._default_parent_list(), None
        ref = self._rows[row]
        node = ref.node
        # 仅真正的 if/if-else 步骤作为容器（else/end 只是标记，不当容器）
        if isinstance(node, Step) and node.keyword_id in (
                "exec_control_if_end", "exec_control_if_else_end"):
            ch = node.children
            for i, c in enumerate(ch):
                if isinstance(c, Step) and c.keyword_id == "else":
                    return ch, i
            return ch, len(ch)
        if isinstance(node, StepSet):
            return node.children, len(node.children)
        i = _index_by_identity(ref.parent, node)   # 身份定位，避免内容相同步骤命中错项
        return (ref.parent, i + 1) if i >= 0 else (ref.parent, None)

    def insert_prebuilt(self, node: object) -> Optional[object]:
        """把已构建的节点插入到目标位置（条件/循环/组合等由调用方构建）。"""
        if self._case is None:
            return None
        self._push_undo()
        parent, idx = self._insert_target()
        if idx is None:
            parent.append(node)
        else:
            parent.insert(idx, node)
        self._render(select_node=node)
        return node

    def insert_loop_pair(self, start_node: object, end_node: object) -> Optional[object]:
        """插入循环 start/end 标记对（其间即循环体，选中 start 后插入步骤即进入体内）。"""
        if self._case is None:
            return None
        self._push_undo()
        parent, idx = self._insert_target()
        if idx is None:
            parent.append(start_node)
            parent.append(end_node)
        else:
            parent.insert(idx, start_node)
            parent.insert(idx + 1, end_node)
        self._render(select_node=start_node)
        return start_node

    def insert_step(self, keyword_id: str, meta: Optional[KeywordMeta] = None) -> Optional[Step]:
        """插入一个关键字步骤（位置由 _insert_target 决定）。"""
        if self._case is None:
            return None
        # 「说明」默认填关键字描述(comment)而非名字——名字已在「关键字」列显示，避免两列重复
        comment = (meta.comment or meta.name) if meta else ""
        step = Step(keyword_id=keyword_id, comment=comment, params=build_default_params(meta))
        return self.insert_prebuilt(step)

    def insert_stepset(self, name: str = "步骤组") -> Optional[StepSet]:
        """插入一个空步骤组(StepSet)。可绑定数据源后按行驱动其子步骤。"""
        if self._case is None:
            return None
        return self.insert_prebuilt(StepSet(name=name))

    def case_prefix_to_selected(self) -> Optional[list]:
        """从 case 主体首步到「选中步骤所属顶层步骤」的前缀(含)，用于「运行至此」。

        选中项在 case 主体内(含嵌套) → 返回其顶层祖先及之前的所有主体步骤；否则 None。
        """
        node = self.selected_node()
        if node is None or self._case is None:
            return None
        top = self._case.case.steps

        def contains(n, target) -> bool:
            if n is target:
                return True
            return any(contains(c, target) for c in (getattr(n, "children", None) or []))

        for i, t in enumerate(top):
            if contains(t, node):
                return top[: i + 1]
        return None

    def toggle_selected_disabled(self) -> bool:
        """启用/禁用选中步骤(切 is_run)：禁用的步骤执行时跳过、界面灰显。"""
        node = self.selected_node()
        if node is None or not hasattr(node, "is_run"):
            return False
        self._push_undo()
        node.is_run = not node.is_run
        self._render(select_node=node)
        return True

    def selected_stepset(self) -> Optional[StepSet]:
        node = self.selected_node()
        return node if isinstance(node, StepSet) else None

    def set_selected_datapool(self, spec: str) -> bool:
        """给选中的步骤组设置/清除数据源绑定 datapool=DATATABLE(...)。"""
        node = self.selected_stepset()
        if node is None:
            return False
        self._push_undo()
        node.datapool = spec or ""
        self._render(select_node=node)
        return True

    def governing_datapool(self, node) -> str:
        """节点所受数据池约束：最近的「绑定了 datapool 的步骤组」祖先，否则用例级 datapool。"""
        if self._case is None or node is None:
            return ""

        def ancestry(nodes, target):
            for n in nodes:
                if n is target:
                    return [n]
                ch = getattr(n, "children", None)
                if ch:
                    sub = ancestry(ch, target)
                    if sub:
                        return [n] + sub
            return None

        path = []
        for shell in self._case.shells:      # TestCase/TestSuite 都有 shells（套件无 case 壳）
            path = ancestry(shell.steps, node) or []
            if path:
                break
        for anc in reversed(path):
            dp = getattr(anc, "datapool", "") or ""
            if isinstance(anc, StepSet) and dp and "NONE" not in dp.upper():
                return dp
        return getattr(self._case, "datapool", "") or ""

    def governing_columns(self, node) -> list[str]:
        """节点受约束数据池的列名（供参数 COLUMN 选择器）；无绑定/读不到返回 []。"""
        dp = self.governing_datapool(node)
        if not dp:
            return []
        from ...engine.executor import datatable_columns
        base = ""
        sp = getattr(self._case, "source_path", "") if self._case else ""
        if sp:
            base = os.path.dirname(sp)
        return datatable_columns(dp, base)

    def insert_innercase(self, abs_path: str) -> Optional[StepInnerCase]:
        """把一个 .tc 文件插入为内嵌用例引用（相对当前用例目录存 relative_path）。"""
        if self._case is None or not abs_path:
            return None
        rel = abs_path
        base = os.path.dirname(self._case.source_path) if self._case.source_path else ""
        if base:
            # noinspection PyBroadException
            try:
                rel = os.path.relpath(abs_path, base)
            except Exception:
                rel = abs_path
        return self.insert_prebuilt(StepInnerCase(relative_path=rel, comment="内嵌用例"))

    def insert_stepverbs(self, ks_id: str) -> Optional[StepVerbs]:
        """插入一个自定义关键字调用(StepVerbs)。插到选中行之后，无选中则追加到 case。"""
        if self._case is None:
            return None
        return self.insert_prebuilt(StepVerbs(ks_id=ks_id, comment=""))

    def remove_selected(self) -> None:
        top = self._topmost_refs(self._selected_refs())   # 支持多行：删所有选中的顶层步骤
        if not top:
            return
        self._push_undo()
        for ref in top:                                    # 身份定位，防误删内容相同的步骤
            i = _index_by_identity(ref.parent, ref.node)
            if i >= 0:
                ref.parent.pop(i)
        self._render()

    def move_selected(self, delta: int) -> None:
        """在同一父列表内上移(-1)/下移(+1)选中节点。"""
        row = self.currentRow()
        if not (0 <= row < len(self._rows)):
            return
        ref = self._rows[row]
        idx = _index_by_identity(ref.parent, ref.node)   # 身份定位，防内容相同步骤错位
        if idx < 0:
            return
        new_idx = idx + delta
        if 0 <= new_idx < len(ref.parent):
            self._push_undo()
            ref.parent[idx], ref.parent[new_idx] = ref.parent[new_idx], ref.parent[idx]
            self._render(select_node=ref.node)

    def _duplicate_selected(self) -> None:
        """复制当前步骤并插到其后（Ctrl+D）。"""
        if self.selected_node() is not None:
            self.copy_selected()
            self.paste()

    # ---- 键盘快捷键（对标序列编辑器；单元格编辑态不触发，交给编辑器本身）----
    def keyPressEvent(self, e) -> None:
        if self.state() == QAbstractItemView.State.EditingState:
            super().keyPressEvent(e)
            return
        key, mod = e.key(), e.modifiers()
        ctrl = mod & Qt.KeyboardModifier.ControlModifier
        if key == Qt.Key.Key_Delete:
            self.remove_selected()
            return
        if ctrl and key == Qt.Key.Key_Up:
            self.move_selected(-1)
            return
        if ctrl and key == Qt.Key.Key_Down:
            self.move_selected(1)
            return
        if ctrl and key == Qt.Key.Key_D:
            self._duplicate_selected()
            return
        super().keyPressEvent(e)

    # ---- 拖拽放置 ----
    @staticmethod
    def _dropped_tc(md) -> Optional[str]:
        """拖拽 mime 里若含 .tc 文件路径(URL)，返回其绝对路径，用于插入内嵌用例。"""
        if md.hasUrls():
            for u in md.urls():
                p = u.toLocalFile()
                if p.lower().endswith((".tc.yaml", ".tc.yml", ".tc")):
                    return p
        return None

    # ---- 列宽自适应（约 2:3:4:1，可手动覆盖）----
    _SHELL_W = 72
    _REMARK_W = 180
    _KW_PARAM_RATIO = (2, 3)

    def _on_section_resized(self, *_a) -> None:
        if not self._applying_ratio:      # 程序性重排不算；用户手动拖过 → 停用自动比例
            self._col_user_resized = True

    def _apply_col_ratio(self) -> None:
        # 视口宽度扣掉固定的「所属段」后，按 2:3 给 关键字/参数，剩余归 Stretch 的「说明」
        avail = self.viewport().width() - self._SHELL_W - self._REMARK_W
        if avail <= 0:
            return
        a, b = self._KW_PARAM_RATIO
        total_parts = a + b + 4            # 说明占约 4 份
        kw = max(int(avail * a / total_parts), 60)
        params = max(int(avail * b / total_parts), 60)
        self._applying_ratio = True
        try:
            self.setColumnWidth(_COL_KEYWORD, kw)
            self.setColumnWidth(_COL_PARAMS, params)
            # 说明列 Stretch 自动占满剩余；所属段固定，均无需在此设宽
        finally:
            self._applying_ratio = False

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if not self._col_user_resized:    # 用户没手动调过 → 跟随窗口按比例重排
            self._apply_col_ratio()

    def dragEnterEvent(self, event) -> None:
        md = event.mimeData()
        if md.hasText() or self._dropped_tc(md):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        md = event.mimeData()
        if md.hasText() or self._dropped_tc(md):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        md = event.mimeData()
        tc_path = self._dropped_tc(md)
        if tc_path and self._case is not None:      # 拖 .tc 进来 → 内嵌用例
            item = self.itemAt(event.position().toPoint())
            if item is not None:
                self.selectRow(item.row())
            event.acceptProposedAction()
            self.insert_innercase(tc_path)
            return
        if not md.hasText():
            super().dropEvent(event)
            return
        # 把放置位置那一行设为当前行，使插入落到该步骤之后/容器内
        item = self.itemAt(event.position().toPoint())
        if item is not None:
            self.selectRow(item.row())
        event.acceptProposedAction()
        # noinspection PyUnresolvedReferences
        self.keywordDropped.emit(md.text())

    # ---- 信号 / 刷新 ----
    def _on_selection(self) -> None:
        # noinspection PyUnresolvedReferences
        self.stepSelected.emit(self.selected_node())

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._rendering or item.column() != _COL_REMARK:
            return
        row = item.row()
        if 0 <= row < len(self._rows):
            node = self._rows[row].node
            if hasattr(node, "remark") and node.remark != item.text():
                self._push_undo()
                node.remark = item.text()

    def refresh_node_row(self, node: object) -> None:
        """节点被外部编辑后就地刷新其行（不重渲染整表，避免抢输入焦点）。"""
        for row, ref in enumerate(self._rows):
            if ref.node is node:
                kw, params, _ = _node_display(node, self._case_platform())
                label = self._keyword_label(node, kw)
                kw_item = self.item(row, _COL_KEYWORD)
                if kw_item is not None:
                    text = kw_item.text()
                    stripped = text.lstrip()
                    indent = text[: len(text) - len(stripped)]
                    disabled = stripped.startswith("⊘ ")
                    kw_item.setText(indent + ("⊘ " if disabled else "") + label)
                self.item(row, _COL_DESC).setText(self._step_description(node))
                self.item(row, _COL_REMARK).setText(getattr(node, "remark", "") or "")
                self.item(row, _COL_PARAMS).setText(params)
                return

    def apply_theme(self, theme: str) -> None:
        from ..theme import apply_panel_theme, resolve_theme

        self._ui_theme = resolve_theme(theme)
        apply_panel_theme(self, "case_editor", self._ui_theme)
        if self._case is not None:
            self._render()
        self.viewport().update()
