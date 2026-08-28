"""UX-P2-001：保存后 Platform 同步提示与 intent 回写。"""

from __future__ import annotations

import re
from pathlib import Path

from autopilot.mgmt.save_sync import (
    build_logical_case_patch,
    extract_intent_steps_from_testcase,
    save_sync_action_label,
    should_offer_save_sync,
)
from autopilot.model.testcase import Desc, ParamValue, Shell, Step, TestCase
from autopilot.runtime import settings

FILES_PY = Path(__file__).resolve().parents[1] / "autopilot" / "ui" / "main_window" / "files.py"
MGMT_PY = Path(__file__).resolve().parents[1] / "autopilot" / "ui" / "main_window" / "mgmt.py"


def _tc_with_intent(*, logical_case_id: str = "lc-001") -> TestCase:
    tc = TestCase(
        name="登录校验",
        logical_case_id=logical_case_id,
        desc=Desc(description="描述", precondition="已安装 App"),
    )
    tc.case = Shell(
        "case",
        steps=[
            Step(
                keyword_id="intent_act",
                comment="点击登录",
                remark="intent:s1|click",
                params=[
                    ParamValue("intent_id", "s1"),
                    ParamValue("action", "click"),
                    ParamValue("target", "登录按钮"),
                    ParamValue("text", "点击登录"),
                    ParamValue("channel", "ui"),
                ],
            ),
        ],
    )
    return tc


def test_extract_intent_steps_from_testcase():
    steps = extract_intent_steps_from_testcase(_tc_with_intent())
    assert len(steps) == 1
    assert steps[0]["id"] == "s1"
    assert steps[0]["action"] == "click"
    assert steps[0]["target"] == "登录按钮"
    assert steps[0]["platform_hint"] == "mobile"


def test_build_logical_case_patch_includes_title_and_intents():
    body = build_logical_case_patch(_tc_with_intent())
    assert body["title"] == "登录校验"
    assert body["description"] == "描述"
    assert body["preconditions"] == ["已安装 App"]
    assert len(body["intent_steps"]) == 1


def test_should_offer_save_sync_requires_platform_and_logical_or_project(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOPILOT_CONFIG_DIR", str(tmp_path))
    settings.set_mc_server_url("")
    settings.set_mc_project_id("")
    settings.set_mc_jwt("")
    tc = _tc_with_intent()
    assert should_offer_save_sync(tc) is False

    # 仅配 URL 不够：未登录时同步必然失败，不该提示
    settings.set_mc_server_url("http://127.0.0.1:8000")
    assert should_offer_save_sync(tc) is False

    settings.set_mc_jwt("jwt-test")
    assert should_offer_save_sync(tc) is True

    tc2 = TestCase(name="local")
    assert should_offer_save_sync(tc2) is False
    settings.set_mc_project_id("proj-a")
    assert should_offer_save_sync(tc2) is True

    settings.set_mc_save_sync_prompt(False)
    assert should_offer_save_sync(tc) is False


def test_save_sync_action_label():
    assert "intent" in save_sync_action_label(_tc_with_intent())
    assert "上传" in save_sync_action_label(TestCase(name="x"))


def test_save_current_case_hooks_prompt():
    text = FILES_PY.read_text(encoding="utf-8")
    block = re.search(
        r"def save_current_case\(self\)[\s\S]*?(?=\n def |\Z)",
        text,
    )
    assert block
    assert "mgmt_prompt_sync_after_save" in block.group(0)


def test_mgmt_prompt_sync_after_save_exists():
    # AUD-2026-17：实现在 mgmt_delivery；入口经 MgmtSessionMixin 链
    delivery = MGMT_PY.with_name("mgmt_delivery.py").read_text(encoding="utf-8")
    assert "def mgmt_prompt_sync_after_save" in delivery
    assert "push_logical_case_update" in delivery
    facade = MGMT_PY.read_text(encoding="utf-8")
    assert "MgmtSessionMixin" in facade
    assert "mgmt_delivery" in facade
