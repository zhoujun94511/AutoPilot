"""测试套(.ts)编辑器组件：编辑 TestSuite 的 before/after/fault 步骤序列。

复用用例编辑器的步骤树渲染与增删改逻辑，仅把「无选中时的默认插入目标」
改为 before shell（测试套没有 case shell）。
"""

from __future__ import annotations

from typing import Optional

from ...model.testcase import TestSuite
from .case_editor import CaseEditor


class SuiteEditor(CaseEditor):
    def show_suite(self, ts: TestSuite) -> None:
        # noinspection PyTypeChecker
        self.show_case(ts)  # 渲染走 .shells，对 TestSuite 同样适用（结构兼容）

    @property
    def suite(self) -> Optional[TestSuite]:
        return self._case  # type: ignore[return-value]

    def _default_parent_list(self) -> list:
        # 测试套无 case shell，新步骤默认进 before
        return self._case.before.steps
