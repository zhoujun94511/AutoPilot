"""自愈归因 / Binding 回滚 / 质量分桶单测。"""

from __future__ import annotations

from pathlib import Path

from autopilot.intent.bindings import (
    confirm_step_binding,
    load_binding,
    rollback_step_binding,
    upsert_step_binding,
)
from autopilot.intent.heal_attr import classify_intent_failure
from autopilot.intent.runtime import IntentRuntime


def test_classify_no_candidate():
    a = classify_intent_failure(had_candidates=False, message="无法解析意图")
    assert a["code"] == "no_candidate"


def test_classify_not_found():
    a = classify_intent_failure(
        ["mobile_element_click: 未找到元素: NoSuchElementError"],
        had_candidates=True,
    )
    assert a["code"] == "element_not_found"


def test_classify_verify_mismatch():
    a = classify_intent_failure(
        ["mobile_verify_element_existed: 校验控件存在性失败：实际值是[false],期望值是[true]"],
        had_candidates=True,
    )
    assert a["code"] == "element_not_found"


def test_binding_previous_and_rollback(tmp_path: Path):
    upsert_step_binding(
        tmp_path,
        "lc1",
        "s1",
        platform="android",
        keyword_id="mobile_element_click",
        params={"locator": "xpath:://*[@text='A']"},
        candidates=[],
        resolver="heuristic",
    )
    upsert_step_binding(
        tmp_path,
        "lc1",
        "s1",
        platform="android",
        keyword_id="mobile_element_click",
        params={"locator": "xpath:://*[@text='B']"},
        candidates=[],
        resolver="heuristic",
        provisional=True,
    )
    doc = load_binding(tmp_path, "lc1")
    step = doc["steps"]["s1"]
    assert step["provisional"] is True
    assert step["previous"]["params"]["locator"].endswith("'A']")

    rolled = rollback_step_binding(tmp_path, "lc1", "s1", reason="mis-heal")
    assert rolled is not None
    assert rolled["params"]["locator"].endswith("'A']")
    assert "rolled_back_at" in rolled


def test_confirm_clears_provisional(tmp_path: Path):
    upsert_step_binding(
        tmp_path,
        "lc2",
        "s1",
        platform="web",
        keyword_id="web_element_click",
        params={"locator": "xpath:://*"},
        provisional=True,
    )
    confirm_step_binding(tmp_path, "lc2", "s1")
    step = load_binding(tmp_path, "lc2")["steps"]["s1"]
    assert "provisional" not in step
    assert "confirmed_at" in step


def test_runtime_rollback_on_provisional_cache_fail(tmp_path, monkeypatch):
    ctx_vars: dict = {
        "__project_path__": str(tmp_path),
        "__run_platform__": "android",
        "__logical_case_id__": "lc-rb",
    }

    class Ctx:
        @staticmethod
        def get_var(name, default=None):
            return ctx_vars.get(name, default)

        @staticmethod
        def set_var(name, value):
            ctx_vars[name] = value

        @staticmethod
        def resolve(v):
            return v

    upsert_step_binding(
        tmp_path,
        "lc-rb",
        "s1",
        platform="android",
        keyword_id="mobile_verify_element_existed",
        params={"locator": "xpath:://*[@text='OLD']", "timeout": "100"},
        provisional=False,
    )
    upsert_step_binding(
        tmp_path,
        "lc-rb",
        "s1",
        platform="android",
        keyword_id="mobile_verify_element_existed",
        params={"locator": "xpath:://*[@text='BAD']", "timeout": "100"},
        provisional=True,
    )

    calls: list[str] = []

    def fake_invoke(_self, keyword_id, params):
        loc = str(params.get("locator") or "")
        calls.append(loc)
        if "BAD" in loc:
            raise RuntimeError("bad")
        if "OLD" in loc:
            return
        raise RuntimeError("unexpected")

    monkeypatch.setattr(IntentRuntime, "_invoke", fake_invoke)
    monkeypatch.setattr("autopilot.intent.runtime.detect_platform", lambda _c: "android")
    # 回滚成功后不应再进 resolve
    monkeypatch.setattr(
        "autopilot.intent.runtime.resolve_candidates",
        lambda **_k: (_ for _ in ()).throw(AssertionError("should not resolve")),
    )

    out = IntentRuntime(Ctx()).run(
        intent_id="s1",
        action="assert",
        target="x",
        logical_case_id="lc-rb",
    )
    assert out.binding_hit == "rolled_back"
    assert out.rolled_back is True
    assert any("BAD" in c for c in calls)
    assert any("OLD" in c for c in calls)
