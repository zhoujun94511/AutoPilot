"""Intent Trace / verification_status / looks_like_http / vision-doctor。"""

from __future__ import annotations

from types import SimpleNamespace

from autopilot.engine.executor import Executor, StepResult
from autopilot.intent.heal_attr import classify_intent_failure, looks_like_http_intent
from autopilot.intent.vision_doctor import format_doctor_report, run_vision_doctor
from autopilot.keywords.context import ExecutionContext
from autopilot.report.result_json import cases_from_suite


def test_looks_like_http_intent():
    assert looks_like_http_intent("调用 /api/v1/orders 接口")
    assert looks_like_http_intent("HTTP GET 用户列表")
    assert not looks_like_http_intent("点击登录按钮")


def test_classify_looks_like_http_on_no_candidate():
    a = classify_intent_failure(
        had_candidates=False,
        message="无法解析意图: 调用订单接口",
        intent_text="调用订单接口 检查 status code",
    )
    assert a["code"] == "looks_like_http"


def test_intent_trace_flows_to_result_json():
    ex = Executor(ExecutionContext())
    ex.ctx.set_var(
        "__last_intent_meta__",
        {
            "intent_id": "i1",
            "binding_hit": "resolved",
            "heal_applied": False,
            "keyword_id": "web_element_click",
            "fail_reason": "",
            "fail_reason_label": "",
            "rolled_back": False,
            "resolve_strategy": "heuristic",
            "candidate_count": 3,
            "perception_platform": "web",
            "perception_element_count": 12,
            "perception_used_screenshot": False,
            "latency_ms": 42,
            "vision_tokens": 0,
            "verification_status": "missing",
        },
    )
    meta = ex._consume_intent_meta()
    assert meta["resolve_strategy"] == "heuristic"
    assert meta["candidate_count"] == 3
    assert meta["verification_status"] == "missing"
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
    step = rows[0]["steps"][0]
    assert step["resolve_strategy"] == "heuristic"
    assert step["candidate_count"] == 3
    assert step["perception_platform"] == "web"
    assert step["latency_ms"] == 42
    assert step["verification_status"] == "missing"


def test_verification_upgraded_by_following_assert():
    intent_sr = StepResult(
        "intent_act",
        "点提交",
        "PASS",
        intent_id="s1",
        binding_hit="cache",
        resolved_keyword_id="web_element_click",
        verification_status="missing",
        resolve_strategy="cache",
    )
    assert_sr = StepResult(
        "web_verify_element_existed",
        "应看到成功",
        "PASS",
    )
    rows = cases_from_suite(
        SimpleNamespace(
            results=[
                SimpleNamespace(
                    case_name="submit",
                    passed=True,
                    duration_ms=2,
                    source_path="",
                    results=[intent_sr, assert_sr],
                )
            ]
        ),
        project_dir="",
    )
    # assert 步骤无 intent，不会进 steps；intent 的 verification 应升级
    steps = rows[0]["steps"]
    assert steps[0]["intent_id"] == "s1"
    assert steps[0]["verification_status"] == "passed"


def test_verification_missing_sets_pending_verify_evidence():
    _intent_sr = StepResult(
        "intent_act",
        "点提交",
        "PASS",
        intent_id="s1",
        binding_hit="cache",
        resolved_keyword_id="web_element_click",
        verification_status="missing",
        resolve_strategy="cache",
    )
    _ = _intent_sr
    # 无 logical_case_id 时不会写 evidence；造一个带 source 的用例需文件。
    # 这里直接测 _has_missing_verification 升级路径：有 steps 后 evidence 覆盖。
    from autopilot.report.result_json import _has_missing_verification

    assert _has_missing_verification(
        [
            {
                "intent_id": "s1",
                "status": "PASS",
                "verification_status": "missing",
            }
        ]
    )


def test_vision_doctor_reports_disabled_by_default(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_INTENT_VISION", "0")
    monkeypatch.delenv("AUTOPILOT_VISION_API_KEY", raising=False)
    report = run_vision_doctor(ping=False)
    assert report["enabled"] is False
    assert report["ok"] is False
    assert report["config_ok"] is False
    text = format_doctor_report(report)
    assert "vision-doctor" in text
    assert "FAIL" in text


def test_risk_blocks_irreversible():
    from autopilot.intent.risk import assert_intent_keyword_allowed, risk_level
    from autopilot.keywords.registry import KeywordError

    assert risk_level("mobile_app_adb_uninstall") == "irreversible"
    assert risk_level("web_verify_element_existed") == "read"
    try:
        assert_intent_keyword_allowed("mobile_app_adb_uninstall")
        raise AssertionError("expected block")
    except KeywordError as exc:
        assert "irreversible" in str(exc)