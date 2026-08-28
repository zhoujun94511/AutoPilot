"""D2：Intent 步固化为确定性关键字。"""

from __future__ import annotations

from pathlib import Path

# noinspection PyUnresolvedReferences
import yaml

from autopilot.intent.bindings import upsert_step_binding
from autopilot.intent.solidify import solidify_intent_step


def test_solidify_replaces_intent_act(tmp_path: Path):
    lid = "lc-solid"
    cases = tmp_path / "cases"
    cases.mkdir()
    tc = {
        "schema_version": "2.0",
        "logical_case_id": lid,
        "name": "solid-demo",
        "shells": {
            "case": [
                {
                    "step": "intent_act",
                    "comment": "点登录",
                    "remark": "intent:s1|click",
                    "is_run": True,
                    "params": {
                        "intent_id": "s1",
                        "action": "click",
                        "target": "登录",
                        "text": "点登录",
                        "logical_case_id": lid,
                    },
                }
            ]
        },
    }
    path = cases / "demo.tc.yaml"
    path.write_text(yaml.safe_dump(tc, allow_unicode=True), encoding="utf-8")
    upsert_step_binding(
        tmp_path,
        lid,
        "s1",
        platform="web",
        keyword_id="web_element_click",
        params={"locator": "xpath:://*[@id='login']"},
        resolver="manual",
        channel="ui",
    )
    out = solidify_intent_step(tmp_path, lid, "s1")
    assert out["ok"] is True
    assert out["keyword_id"] == "web_element_click"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    step = data["shells"]["case"][0]
    assert step["step"] == "web_element_click"
    assert step["params"]["locator"] == "xpath:://*[@id='login']"
    assert "solidified:intent:s1" in step["remark"]


def test_solidify_requires_binding(tmp_path: Path):
    out = solidify_intent_step(tmp_path, "missing", "s1")
    assert out["ok"] is False


def test_solidify_stable_by_streak(tmp_path: Path):
    from autopilot.intent.bindings import note_step_run
    from autopilot.intent.solidify import solidify_stable

    lid = "lc-stable"
    cases = tmp_path / "cases"
    cases.mkdir()
    tc = {
        "schema_version": "2.0",
        "logical_case_id": lid,
        "name": "stable-demo",
        "shells": {
            "case": [
                {
                    "step": "intent_act",
                    "params": {
                        "intent_id": "s1",
                        "action": "click",
                        "logical_case_id": lid,
                    },
                }
            ]
        },
    }
    path = cases / "stable.tc.yaml"
    path.write_text(yaml.safe_dump(tc, allow_unicode=True), encoding="utf-8")
    upsert_step_binding(
        tmp_path,
        lid,
        "s1",
        platform="web",
        keyword_id="web_element_click",
        params={"locator": "id::ok"},
        resolver="cache",
    )
    for _ in range(3):
        note_step_run(tmp_path, lid, "s1", success=True, healed=False)
    dry = solidify_stable(tmp_path, min_streak=3, dry_run=True)
    assert dry["candidates"] == 1
    out = solidify_stable(tmp_path, min_streak=3, dry_run=False)
    assert out["solidified"] == 1
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["shells"]["case"][0]["step"] == "web_element_click"
