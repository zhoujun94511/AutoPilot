"""Intent 自愈语义与候选顺序。"""

from __future__ import annotations

from autopilot.intent.runtime import IntentRuntime


class _Ctx:
    def __init__(self) -> None:
        self.vars: dict = {
            "__project_path__": ".",
            "__run_platform__": "android",
            "__logical_case_id__": "lc-heal",
        }
        self.calls: list[tuple[str, dict]] = []

    def get_var(self, name: str, default=None):
        return self.vars.get(name, default)

    def set_var(self, name: str, value) -> None:
        self.vars[name] = value

    @staticmethod
    def resolve(v: str) -> str:
        return v


def test_heal_prefers_fresh_candidates(tmp_path, monkeypatch):
    ctx = _Ctx()
    ctx.vars["__project_path__"] = str(tmp_path)
    project = tmp_path

    from autopilot.intent.bindings import upsert_step_binding

    bad = "xpath:://*[@text='BAD']"
    good = "xpath:://*[@text='Wi-Fi']"
    upsert_step_binding(
        project,
        "lc-heal",
        "s1",
        platform="android",
        keyword_id="mobile_verify_element_existed",
        params={"locator": bad, "isExisted": "true", "timeout": "1000"},
        candidates=[
            {
                "keyword_id": "mobile_verify_element_existed",
                "locator": bad,
                "params": {"locator": bad, "isExisted": "true", "timeout": "1000"},
                "resolver": "heuristic",
            }
        ],
        resolver="heuristic",
    )

    def fake_resolve(**_kwargs):
        return [
            {
                "keyword_id": "mobile_verify_element_existed",
                "locator": good,
                "params": {"locator": good, "isExisted": "true", "timeout": "1000"},
                "resolver": "heuristic",
                "score": 0.7,
            }
        ]

    monkeypatch.setattr("autopilot.intent.runtime.resolve_candidates", fake_resolve)
    monkeypatch.setattr("autopilot.intent.runtime.detect_platform", lambda _c: "android")

    def fake_invoke(_self, keyword_id: str, params: dict) -> None:
        loc = params.get("locator") or ""
        if "BAD" in str(loc):
            raise RuntimeError("bad locator")
        ctx.calls.append((keyword_id, dict(params)))

    monkeypatch.setattr(IntentRuntime, "_invoke", fake_invoke)

    out = IntentRuntime(ctx).run(
        intent_id="s1",
        action="assert",
        target="Wi-Fi",
        logical_case_id="lc-heal",
    )
    assert out.binding_hit == "healed"
    assert out.heal_applied is True
    assert ctx.calls and "Wi-Fi" in str(ctx.calls[0][1].get("locator"))
