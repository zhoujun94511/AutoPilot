"""失败分类：断言 / 超时 / 环境 / 定位。"""

from __future__ import annotations

from autopilot.engine.executor import RunResult, StepResult
from autopilot.engine.suite import SuiteResult
from autopilot.report.fail_class import classify_attribution, classify_failure, classify_step
from autopilot.report.html_report import ReportMeta, render_report
from autopilot.report.result_json import cases_from_suite


def test_classify_by_reason_and_keyword():
    assert classify_failure(fail_reason="element_not_found", status="FAIL")["fail_class"] == "locator"
    assert classify_failure(fail_reason="timeout", status="FAIL")["fail_class"] == "timeout"
    assert classify_failure(keyword_id="http_assert_status", message="期望 200 实际 500", status="FAIL")[
        "fail_class"
    ] == "assertion"
    assert classify_failure(
        keyword_id="http_get",
        message="Connection refused",
        status="FAIL",
    )["fail_class"] == "environment"
    assert classify_attribution(fail_class="assertion", status="FAIL")["attribution"] == "product_bug"
    assert classify_attribution(fail_class="timeout", status="FAIL")["attribution"] == "env_issue"
    assert classify_attribution(
        fail_class="locator",
        fail_reason="no_candidate",
        resolve_strategy="vision",
        status="FAIL",
    )["attribution"] == "inner_agent_bug"
    assert classify_attribution(
        fail_class="locator",
        fail_reason="element_not_found",
        binding_hit="cache",
        status="FAIL",
    )["attribution"] == "product_bug"
    assert classify_attribution(fail_class="other", status="FAIL")["attribution"] == "tooling_gap"
    assert classify_attribution(
        fail_reason="app_crash",
        fail_class="locator",
        status="FAIL",
    )["attribution"] == "product_bug"
    assert classify_attribution(
        fail_reason="evidence_missing",
        status="FAIL",
    )["attribution"] == "uncertain"
    assert classify_attribution(
        message="证据不足，无法判断",
        status="FAIL",
    )["attribution"] == "uncertain"
    from autopilot.report.fail_class import scan_attributions
    from collections import Counter

    counter: Counter[str] = Counter()
    scan_attributions(
        {
            "cases": [
                {
                    "steps": [
                        {
                            "status": "FAIL",
                            "attribution": "product_bug",
                            "fail_class": "locator",
                            "fail_reason": "element_not_found",
                        },
                        {
                            "status": "FAIL",
                            "attribution": "product_bug",
                            "fail_class": "locator",
                            "fail_reason": "element_not_found",
                        },
                    ]
                }
            ]
        },
        counter,
    )
    assert counter["product_bug"] == 1


def test_result_json_and_html_include_http_and_class():
    rr = RunResult(case_name="api-login", source_path="/x/api.tc.yaml")
    rr.results = [
        StepResult(
            "http_get",
            "拉用户",
            "PASS",
            "GET http://127.0.0.1/users → 200 (12ms)",
            duration_ms=12,
            http_status=200,
            http_url="http://127.0.0.1/users",
            http_elapsed_ms=12,
        ),
        StepResult(
            "http_assert_status",
            "断言状态",
            "FAIL",
            "期望 201 实际 200",
            duration_ms=1,
        ),
    ]
    cases = cases_from_suite(SuiteResult(name="s", results=[rr]), project_dir="")
    assert cases[0]["fail_class"] == "assertion"
    http_step = cases[0]["steps"][0]
    assert http_step["http_status"] == 200
    assert http_step["http_url"].endswith("/users")
    assert cases[0]["steps"][1]["fail_class"] == "assertion"
    assert cases[0]["attribution"] == "product_bug"
    assert cases[0]["steps"][1]["attribution"] == "product_bug"
    assert cases[0]["status"] == "failed"
    assert cases[0]["qa_review"]["changed_status"] is False
    assert cases[0]["root_causes"]

    html = render_report(
        SuiteResult(name="s", results=[rr]),
        generated_at="t",
        meta=ReportMeta(suite_name="s"),
    )
    assert "搜索用例 / 关键字" in html
    assert "applyFilter" in html
    assert "http://127.0.0.1/users" in html
    assert "200" in html
    assert "断言" in html
    assert "产品缺陷" in html
    assert "事后二审" in html
    assert classify_step(rr.results[1])["fail_class"] == "assertion"
    assert classify_step(rr.results[1])["attribution"] == "product_bug"


def test_fail_shots_keep_pre_and_post_separate():
    from autopilot.engine.executor import Executor, RunResult
    from autopilot.keywords.context import ExecutionContext

    ex = Executor(ExecutionContext())
    names: list[str] = []

    def fake_cap(_result, *, _step=None, _intent_id="", filename="screenshot.png"):
        names.append(filename)
        if "before" in filename:
            return "PRE", "reports/pre.png", ""
        return "POST", "reports/post.png", "reports/dom.xml"

    ex._capture_evidence = fake_cap  # type: ignore[method-assign]

    class _Step:
        keyword_id = "mobile_element_click"

    rr = RunResult("demo")
    ex._stash_pre_action_shot(rr, _Step())
    meta: dict = {"intent_id": "i1"}
    ex._attach_fail_shots(meta, rr, _Step())
    assert meta["screenshot"] == "POST"
    assert meta["screenshot_before"] == "PRE"
    assert meta["screenshot_path"] == "reports/post.png"
    assert meta["screenshot_before_path"] == "reports/pre.png"
    assert meta["screenshot_before"] != meta["screenshot"]
    assert names == ["screenshot_before.png", "screenshot.png"]
