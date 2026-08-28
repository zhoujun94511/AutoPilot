"""Intent 导入 / Binding / 失败审阅冒烟。"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from autopilot.intent.bindings import ensure_empty_binding, load_binding, upsert_step_binding
from autopilot.intent.normalize import logical_texts_to_intent_steps
from autopilot.intent.review import failed_intent_steps_from_result
from autopilot.mgmt.logical_import import logical_case_to_tc_dict, write_logical_cases_as_drafts


def test_normalize_click_and_assert():
    steps = logical_texts_to_intent_steps(
        ["点击登录按钮", "输入用户名 admin"],
        ["页面显示欢迎"],
    )
    assert steps[0]["action"] == "click"
    assert "登录" in (steps[0].get("target") or steps[0].get("text") or "")
    assert any(s["action"] == "type" for s in steps)
    assert any(s["action"] == "assert" for s in steps)


def test_logical_import_emits_intent_act(tmp_path: Path):
    case = {
        "logical_case_id": "lc-1",
        "case_key": "LC-1",
        "title": "登录",
        "revision_id": "rev1",
        "intent_steps": [
            {
                "id": "s1",
                "action": "click",
                "target": "登录",
                "value": "",
                "platform_hint": "any",
                "text": "点击登录",
            }
        ],
        "logical_steps": ["点击登录"],
        "expected_results": ["成功"],
    }
    data = logical_case_to_tc_dict(case, project_id="p1")
    assert data["schema_version"] == "2.0"
    assert data["logical_case_id"] == "lc-1"
    case_steps = data["shells"]["case"]
    assert case_steps
    assert all(s.get("step") == "intent_act" for s in case_steps)
    assert all(s.get("is_run") is True for s in case_steps)
    blob = yaml.safe_dump(data)
    assert "mapping_required" not in blob
    assert "web_common_sleep" not in blob
    assert data["shells"]["before"] == []

    paths = write_logical_cases_as_drafts(tmp_path, [case], project_id="p1")
    assert len(paths) == 1
    assert paths[0].is_file()
    bind = load_binding(tmp_path, "lc-1")
    assert bind["logical_case_id"] == "lc-1"
    assert bind["steps"] == {}


def test_logical_import_session_bootstrap(tmp_path: Path):
    case = {
        "logical_case_id": "lc-boot",
        "case_key": "LC-BOOT",
        "title": "Settings",
        "revision_id": "rev-b",
        "intent_steps": [
            {
                "id": "s1",
                "action": "assert",
                "target": "Wi-Fi",
                "value": "",
                "text": "断言 Wi-Fi",
            }
        ],
    }
    data = logical_case_to_tc_dict(
        case,
        project_id="p1",
        session={
            "platform": "android",
            "package_name": "com.android.settings",
        },
    )
    assert data["platform"] == "android"
    before = data["shells"]["before"]
    assert before[0]["step"] == "appium_start"
    assert before[1]["step"] == "mobile_app_start"
    assert before[1]["params"]["packageName"] == "com.android.settings"
    assert data["shells"]["after"][0]["step"] == "mobile_app_close"

    paths = write_logical_cases_as_drafts(
        tmp_path,
        [case],
        project_id="p1",
        session={"platform": "android", "package_name": "com.android.settings"},
    )
    assert paths and paths[0].is_file()
    loaded = yaml.safe_load(paths[0].read_text(encoding="utf-8"))
    assert loaded["shells"]["before"][1]["params"]["packageName"] == "com.android.settings"


def test_binding_upsert_and_heal_count(tmp_path: Path):
    ensure_empty_binding(tmp_path, "lc-x", revision_id="r1")
    upsert_step_binding(
        tmp_path,
        "lc-x",
        "s1",
        platform="web",
        keyword_id="web_element_click",
        params={"locator": "text=登录"},
        candidates=[{"locator": "text=登录", "score": 0.9}],
        resolver="heuristic",
        heal_count=2,
    )
    doc = load_binding(tmp_path, "lc-x")
    step = doc["steps"]["s1"]
    assert step["keyword_id"] == "web_element_click"
    assert step["heal_count"] == 2
    assert step["platform"] == "web"


def test_failed_intent_filter_from_result():
    result = {
        "cases": [
            {
                "name": "登录",
                "logical_case_id": "lc-1",
                "steps": [
                    {
                        "name": "点击登录",
                        "intent_id": "s1",
                        "binding_hit": "cache",
                        "status": "PASS",
                    },
                    {
                        "name": "断言欢迎",
                        "intent_id": "s2",
                        "binding_hit": "failed",
                        "status": "FAIL",
                        "error_message": "no candidate",
                    },
                ],
            }
        ]
    }
    failed = failed_intent_steps_from_result(result)
    assert len(failed) == 1
    assert failed[0]["intent_id"] == "s2"
    assert failed[0]["binding_hit"] == "failed"


def test_resolve_candidates_tag_resolver():
    from autopilot.intent.resolve import resolve_candidates

    cands = resolve_candidates(action="click", target="登录", value="", platform="web")
    assert cands
    assert all(c.get("resolver") for c in cands)


def test_resolve_xpath_escapes_quotes():
    from autopilot.intent.resolve import _xpath_string_literal, resolve_candidates

    assert _xpath_string_literal("ok") == "'ok'"
    assert _xpath_string_literal("it's") == '"it\'s"'
    lit = _xpath_string_literal("it's \"ok\"")
    assert "concat(" in lit
    assert '"\'"' in lit
    cands = resolve_candidates(
        action="click", target="it's \"ok\"", value="", platform="web"
    )
    assert cands
    assert "concat(" in (cands[0].get("locator") or "")


def test_resolve_android_assert_uses_verify():
    from autopilot.intent.resolve import resolve_candidates

    cands = resolve_candidates(
        action="assert", target="Wi-Fi", value="", platform="android"
    )
    assert cands
    assert cands[0]["keyword_id"] == "mobile_verify_element_existed"
    loc = str(cands[0].get("locator") or "").lower()
    assert "wifi" in loc or "wlan" in loc or "无线" in loc


def test_apply_manual_binding(tmp_path: Path):
    from autopilot.intent.manual_bind import apply_manual_binding
    from autopilot.intent.bindings import load_binding

    entry = apply_manual_binding(
        str(tmp_path),
        "lc-m",
        "s1",
        locator="xpath:://*[@text='登录']",
        platform="android",
        action="click",
    )
    assert entry["keyword_id"] == "mobile_element_click"
    assert entry["resolver"] == "manual"
    assert entry["params"]["locator"].startswith("xpath::")
    doc = load_binding(tmp_path, "lc-m")
    assert doc["steps"]["s1"]["candidates"][0]["resolver"] == "manual"


def test_watch_filter_and_seen(tmp_path: Path):
    from autopilot.intent.watch import filter_new_cases, load_seen_ids, save_seen_ids

    save_seen_ids(tmp_path, {"lc-old"})
    cases = [
        {"logical_case_id": "lc-old", "title": "旧"},
        {"logical_case_id": "lc-new", "title": "新"},
    ]
    new = filter_new_cases(cases, load_seen_ids(tmp_path))
    assert len(new) == 1
    assert new[0]["logical_case_id"] == "lc-new"


def test_vision_hook_disabled_by_default():
    from autopilot.intent.vision import vision_candidates, vision_enabled

    assert vision_enabled() is False
    assert vision_candidates(action="click", target="x", value="", platform="web") == []


def test_cli_bind(tmp_path: Path):
    from autopilot.intent.cli import main
    from autopilot.intent.bindings import load_binding

    rc = main(
        [
            "bind",
            "--project",
            str(tmp_path),
            "--logical-case-id",
            "lc-b",
            "--intent-id",
            "s1",
            "--locator",
            "id=login",
            "--platform",
            "web",
            "--action",
            "click",
        ]
    )
    assert rc == 0
    assert load_binding(tmp_path, "lc-b")["steps"]["s1"]["params"]["locator"] == "id=login"


def test_cli_import_from_file(tmp_path: Path):
    bundle = {
        "schema_version": "2.0",
        "project_id": "p1",
        "cases": [
            {
                "logical_case_id": "lc-cli",
                "case_key": "LC-CLI",
                "title": "CLI导入",
                "intent_steps": [
                    {
                        "id": "s1",
                        "action": "open",
                        "target": "https://example.com",
                        "text": "打开首页",
                        "platform_hint": "web",
                        "value": "",
                    }
                ],
                "logical_steps": ["打开首页"],
                "expected_results": ["页面打开"],
            }
        ],
    }
    src = tmp_path / "bundle.json"
    src.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    proj = tmp_path / "proj"
    proj.mkdir()
    from autopilot.intent.cli import main

    rc = main(
        [
            "import",
            "--project",
            str(proj),
            "--from-file",
            str(src),
            "--subdir",
            "imported_logical",
        ]
    )
    assert rc == 0
    written = list((proj / "imported_logical").glob("*.yaml"))
    assert written
    text = written[0].read_text(encoding="utf-8")
    assert "intent_act" in text
    assert "mapping_required" not in text
    assert (proj / "bindings" / "lc-cli.json").is_file()
