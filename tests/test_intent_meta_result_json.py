"""intent meta → StepResult → result_json 贯通。"""

from __future__ import annotations

from types import SimpleNamespace

from autopilot.engine.executor import Executor, StepResult
from autopilot.keywords.context import ExecutionContext
from autopilot.report.result_json import cases_from_suite


def test_resolved_keyword_id_flows_to_result_json():
    ex = Executor(ExecutionContext())
    ex.ctx.set_var(
        "__last_intent_meta__",
        {
            "intent_id": "i-login",
            "binding_hit": "healed",
            "heal_applied": True,
            "keyword_id": "mobile_tap",
            "fail_reason": "",
            "fail_reason_label": "",
            "rolled_back": False,
        },
    )
    meta = ex._consume_intent_meta()
    assert meta["resolved_keyword_id"] == "mobile_tap"
    sr = StepResult("intent_act", "点登录", "PASS", **meta)
    rows = cases_from_suite(
        SimpleNamespace(
            results=[
                SimpleNamespace(
                    case_name="login",
                    passed=True,
                    duration_ms=1,
                    source_path="",
                    results=[sr],
                )
            ]
        ),
        project_dir="",
    )
    steps = rows[0]["steps"]
    assert steps[0]["resolved_keyword_id"] == "mobile_tap"
    assert steps[0]["intent_id"] == "i-login"
    assert steps[0]["binding_hit"] == "healed"
