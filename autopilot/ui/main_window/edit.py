"""主窗口·步骤编辑 Mixin：插入步骤/控制流/循环、剪贴板/撤销转发、步骤选中联动。"""

from __future__ import annotations

from ...metadata.keyword_platforms import platform_mismatch_reason
from ...model.testcase import Step, StepVerbs, StepSet, StepInnerCase
from ..widgets.case_editor import build_default_params


# 仅供静态检查解析 self.* —— 运行时 Mixin 实际由 MainWindow 组合，这里"继承"只在类型检查时生效（运行时为 object，无循环依赖）。
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .window import MainWindow
    _Base = MainWindow
else:
    _Base = object


class EditMixin(_Base):
    def _edit_op(self, method: str) -> None:
        """剪贴板/撤销重做转发给当前用例/套件编辑器（CaseEditor 系）。"""
        editor = self._current_case_editor()
        if editor is None:
            self.console.log("请先在用例/套件编辑器中操作", "编辑", "WARNING")
            return
        getattr(editor, method)()

    def _on_console_step_activated(self, keyword_id: str) -> None:
        """双击控制台结果行 → 在当前用例/套件编辑器中定位该关键字步骤。"""
        editor = self._current_case_editor()
        if editor is None:
            self.console.log("请先在用例/套件编辑器中打开文件，再定位步骤", "运行", "WARNING")
            return
        if not editor.select_by_keyword(keyword_id):
            self.console.log(f"未找到关键字步骤：{keyword_id}", "运行", "WARNING")

    def _step_editor_op(self, method: str, *args) -> None:
        """把删除/上移/下移等操作转发给当前步骤编辑器。"""
        editor = self._current_step_editor()
        if editor is None or getattr(editor, "case", None) is None:
            self.console.log("请先打开用例或套件，再编辑步骤", "编辑", "WARNING")
            return
        getattr(editor, method)(*args)

    def _build_step(self, keyword_id: str) -> Step:
        meta = self.catalog.get(keyword_id) if self.catalog else None
        comment = meta.name if (meta and meta.name) else ""
        return Step(keyword_id, comment=comment, params=build_default_params(meta))

    def insert_control(self, keyword_id: str) -> None:
        """插入条件控制块（if / if-else）。"""
        editor = self._current_case_editor()
        if editor is None or editor.case is None:
            self.console.log("请先在用例/套件编辑器中操作", "编辑", "WARNING")
            return
        node = self._build_step(keyword_id)
        if keyword_id == "exec_control_if_else_end":
            node.children = [Step("else", comment="否则")]
        editor.insert_prebuilt(node)
        self.console.log(f"已插入条件：{keyword_id}（选中条件行插 if 体，选中「否则」行插 else 体）", "编辑")

    def insert_loop(self, loop_kind: str) -> None:
        """插入循环块（keyword/mobile）。选中 Loop_Start 行后插入步骤即进入循环体。"""
        editor = self._current_case_editor()
        if editor is None or editor.case is None:
            self.console.log("请先在用例/套件编辑器中操作")
            return
        start_id = "mobile_loop_start" if loop_kind == "mobile" else "keyword_loop_start"
        end_id = "mobile_loop_end" if loop_kind == "mobile" else "keyword_loop_end"
        editor.insert_loop_pair(self._build_step(start_id), self._build_step(end_id))
        self.console.log("已插入循环：在「循环开始」行后添加的步骤会在循环内反复执行", "编辑")

    def _on_keyword_activated(self, keyword_id: str) -> None:
        # 自定义关键字（ks:: 前缀）：插入 StepVerbs 调用，仅用例编辑器支持
        if keyword_id.startswith("ks::"):
            ks_id = keyword_id[4:]
            if self.case_editor.case is None or self._current_step_editor() is not self.case_editor:
                self.console.log("请先在用例编辑器中打开一个用例，再插入自定义关键字调用", "编辑", "WARNING")
                return
            if self.case_editor.insert_stepverbs(ks_id) is not None:
                self.console.log(f"已插入自定义关键字调用：{ks_id}", "编辑")
            return
        editor = self._current_step_editor()
        if editor is self.case_editor and self.case_editor.case is None:
            self.console.log("请先打开一个用例，再插入关键字步骤", "编辑", "WARNING")
            return
        if editor is self.keyword_editor and self.keyword_editor.keyworddef is None:
            self.console.log("请先新建或打开一个自定义关键字，再插入步骤", "编辑", "WARNING")
            return
        meta = self.catalog.get(keyword_id) if self.catalog else None
        if meta is not None and hasattr(self, "_effective_keyword_target_platform"):
            reason = platform_mismatch_reason(self._effective_keyword_target_platform(), meta)
            if reason:
                self.console.log(f"关键字 {keyword_id}：{reason}", "编辑", "WARNING")
        if editor.insert_step(keyword_id, meta) is not None:
            name = (meta.name if meta and getattr(meta, "name", "") else keyword_id)
            self.console.log(f"已添加步骤：{name}", "编辑")

    def _on_step_selected(self, node: object) -> None:
        if isinstance(node, Step):
            meta = self.catalog.get(node.keyword_id) if self.catalog else None
            editor = self._current_step_editor()
            if editor is self.keyword_editor:
                cols = []
            elif editor is not None and hasattr(editor, "governing_columns"):
                cols = editor.governing_columns(node)
            else:
                cols = []
            case_plat = self._effective_case_platform() if hasattr(self, "_effective_case_platform") else ""
            if not case_plat and editor is not None and getattr(editor, "case", None) is not None:
                case_plat = editor.case.platform or ""
            self.param_form.show_step(node, meta, cols, case_platform=case_plat)
        elif isinstance(node, StepVerbs):
            editor = self._current_case_editor()
            cols = editor.governing_columns(node) if editor is not None else []
            case_plat = self._effective_case_platform() if hasattr(self, "_effective_case_platform") else ""
            kd = self._lookup_keyword_def(node.ks_id) if hasattr(self, "_lookup_keyword_def") else None
            self.param_form.show_stepverbs(node, kd, cols, case_platform=case_plat)
        elif isinstance(node, StepSet):
            self.param_form.show_stepset(node)
        elif isinstance(node, StepInnerCase):
            self.param_form.show_innercase(node)
        else:
            # 无步骤选中：回退到当前用例追踪字段
            editor = self._current_case_editor() if hasattr(self, "_current_case_editor") else None
            tc = getattr(editor, "case", None) if editor is not None else None
            if tc is not None and hasattr(self.param_form, "show_case_meta"):
                self.param_form.show_case_meta(tc)
            else:
                self.param_form.clear_step()
