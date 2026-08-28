"""链路 3 Authoring：假 LLM + 假 UI → 落盘 / 门禁。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autopilot.authoring.codegen import parse_llm_draft, save_draft_tc
from autopilot.authoring.contract import AuthoringError, AuthoringRequest
from autopilot.authoring.gate import assert_local_dry_run_passed, upload_blocked_reason
from autopilot.authoring.pipeline import generate_traditional_case


def _fake_chat_click(_prompt: str) -> str:
    return json.dumps(
        {
            "title": "点击蓝牙",
            "steps": [
                {
                    "keyword_id": "mobile_element_click",
                    "params": {"locator": "id=com.android.settings:id/bluetooth"},
                    "comment": "点击蓝牙",
                }
            ],
            "notes": "ok",
        },
        ensure_ascii=False,
    )


def test_parse_rejects_intent_act():
    with pytest.raises(AuthoringError, match="无合法步骤"):
        parse_llm_draft(
            {
                "title": "x",
                "steps": [
                    {"keyword_id": "intent_act", "params": {}, "comment": "bad"},
                ],
            },
            platform="android",
            max_steps=5,
        )


def test_generate_and_save_draft(tmp_path: Path, monkeypatch):
    # 缩小白名单依赖：若 catalog 无 mobile_element_click，用 monkeypatch
    from autopilot.authoring import codegen as cg

    monkeypatch.setattr(
        cg,
        "allowed_keyword_ids",
        lambda _p: frozenset({"mobile_element_click", "web_element_click"}),
    )

    result = generate_traditional_case(
        AuthoringRequest(
            natural_language="点击蓝牙",
            platform="android",
            draft_only=True,
            mode="plan_only",
        ),
        elements_text='[{"tx":"蓝牙","rid":"bluetooth"}]',
        project_dir=tmp_path,
        chat=_fake_chat_click,
        save=True,
    )
    assert result.path is not None
    assert result.path.is_file()
    assert result.gate is not None
    assert result.gate.allow_upload is False
    text = result.path.read_text(encoding="utf-8")
    assert "mobile_element_click" in text
    assert "intent_act" not in text


def test_gate_blocks_upload_until_pass(tmp_path: Path):
    path = tmp_path / "a.tc.yaml"
    path.write_text("type: testcase\n", encoding="utf-8")
    g1 = assert_local_dry_run_passed(path, draft_only=True)
    assert g1.allow_upload is False
    assert upload_blocked_reason(gate=g1, authoring_meta={"chain": "3"})

    g2 = assert_local_dry_run_passed(path, draft_only=False, runner=lambda _p: True)
    assert g2.allow_upload is True
    assert upload_blocked_reason(gate=g2, authoring_meta={"chain": "3"}) == ""


def test_save_draft_tc_writes_yaml(tmp_path: Path, monkeypatch):
    from autopilot.authoring import codegen as cg
    from autopilot.model.serializer import load, testcase_to_dict

    monkeypatch.setattr(
        cg,
        "allowed_keyword_ids",
        lambda _p: frozenset({"web_element_click", "mobile_element_click"}),
    )
    draft = parse_llm_draft(
        {
            "title": "打开菜单",
            "steps": [
                {
                    "keyword_id": "web_element_click",
                    "params": {"locator": "css::#menu"},
                    "comment": "点菜单",
                }
            ],
        },
        platform="web",
        max_steps=8,
    )
    path = save_draft_tc(draft, tmp_path)
    assert path.suffixes == [".tc", ".yaml"]
    text = path.read_text(encoding="utf-8")
    assert "web_element_click" in text
    assert "name: 打开菜单" in text
    assert "is_execute: true" in text
    assert "datapool:" in text
    assert "desc.name" not in text
    assert "description: AI 辅助编写" in text

    tc = load(str(path))
    assert tc.name == "打开菜单"
    roundtrip = testcase_to_dict(tc)
    assert roundtrip["name"] == "打开菜单"


def test_save_draft_normalizes_mobile_click_params(tmp_path: Path, monkeypatch):
    from autopilot.authoring import codegen as cg
    from autopilot.authoring.contract import AuthoringDraft, GeneratedStep
    from autopilot.model.serializer import load
    import yaml

    monkeypatch.setattr(
        cg,
        "allowed_keyword_ids",
        lambda _p: frozenset({"mobile_element_click", "mobile_app_start"}),
    )
    draft = AuthoringDraft(
        title="进入无线局域网",
        platform="ios",
        steps=[
            GeneratedStep(
                keyword_id="mobile_app_start",
                params={"packageName": "com.apple.Preferences"},
                comment="启动设置",
            ),
            GeneratedStep(
                keyword_id="mobile_element_click",
                params={
                    "locator": "name::com.apple.settings.wifi",
                    "target": "WLAN 设置入口",
                },
                comment="点 WLAN",
            ),
        ],
    )
    path = save_draft_tc(draft, tmp_path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["name"] == "进入无线局域网"
    assert raw["platform"] == "ios"
    assert raw["tag"] == "MOBILE"
    steps = raw["shells"]["case"]
    start = steps[0]["params"]
    assert start["type"] == "ios"
    assert start["packageName"] == "com.apple.Preferences"
    assert "activityName" in start
    click = steps[1]["params"]
    assert click["locator"] == "name::com.apple.settings.wifi"
    assert click.get("timeout") == "30000"
    assert "target" not in click
    assert "WLAN" in steps[1].get("remark", "")

    tc = load(str(path))
    assert tc.name == "进入无线局域网"
    assert tc.case.steps[1].param("timeout") == "30000"
    assert tc.case.steps[1].param("target") is None
