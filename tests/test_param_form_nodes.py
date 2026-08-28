"""参数面板对 StepVerbs / StepSet / StepInnerCase 的编辑支持回归。"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_APP = None  # 持有 QApplication，防止被 GC 导致离屏崩溃


def _ensure_app():
    global _APP
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication([])
    return _APP


def test_param_form_stepverbs() -> None:
    _ensure_app()
    from autopilot.model.keyworddef import KeywordDef, LocalParam
    from autopilot.model.testcase import StepVerbs, ParamValue
    from autopilot.ui.widgets.param_form import ParamForm

    sv = StepVerbs(ks_id="login_flow", params=[ParamValue("user", "alice")])
    kd = KeywordDef(
        ks_id="login_flow",
        params=[
            LocalParam("user", name="用户名", default="guest"),
            LocalParam("pwd", name="密码", required=True),
        ],
    )
    pf = ParamForm()
    pf.show_stepverbs(sv, kd)
    assert pf._node is sv
    assert "pwd" in pf._param_rows
    pf._write_back("pwd", "secret")
    assert sv.param("pwd") == "secret"


def test_param_form_stepset() -> None:
    _ensure_app()
    from autopilot.model.testcase import StepSet
    from autopilot.ui.widgets.param_form import ParamForm

    group = StepSet(name="数据驱动组", datapool="DATATABLE(users,false)", comment="批量登录")
    pf = ParamForm()
    pf.show_stepset(group)
    assert pf._node is group
    pf._write_stepset_field(group, "name", "登录组")
    assert group.name == "登录组"


def test_param_form_innercase() -> None:
    _ensure_app()
    from autopilot.model.testcase import StepInnerCase
    from autopilot.ui.widgets.param_form import ParamForm

    inner = StepInnerCase(relative_path="cases/sub.tc.yaml", comment="子流程")
    pf = ParamForm()
    pf.show_innercase(inner)
    pf._write_innercase_field(inner, "relative_path", "flows/sub.tc.yaml")
    assert inner.relative_path == "flows/sub.tc.yaml"
