"""用例级报告对比（公共组件）。"""

from __future__ import annotations

from autopilot.report.compare import compare_case_lists, refine_verdict


def test_compare_new_fail_fixed_still_fail():
    left = [
        {"logical_case_id": "a", "name": "login", "status": "passed"},
        {"logical_case_id": "b", "name": "pay", "status": "failed", "fail_class": "assertion"},
        {"logical_case_id": "c", "name": "search", "status": "failed"},
    ]
    right = [
        {"logical_case_id": "a", "name": "login", "status": "failed", "fail_class": "timeout"},
        {"logical_case_id": "b", "name": "pay", "status": "passed"},
        {"logical_case_id": "c", "name": "search", "status": "failed"},
        {"name": "new-only", "status": "failed"},
    ]
    diff = compare_case_lists(left, right)
    assert diff["counts"]["new_fail"] == 2
    assert diff["counts"]["fixed"] == 1
    assert diff["counts"]["still_fail"] == 1
    names_new = {x["name"] for x in diff["new_fail"]}
    assert names_new == {"login", "new-only"}
    assert diff["fixed"][0]["name"] == "pay"
    assert refine_verdict("same", diff) == "mixed"


def test_compare_identity_prefers_logical_id():
    left = [{"logical_case_id": "lc-1", "name": "old-name", "status": "failed"}]
    right = [{"logical_case_id": "lc-1", "name": "new-name", "status": "passed"}]
    diff = compare_case_lists(left, right)
    assert diff["counts"]["fixed"] == 1
    assert diff["fixed"][0]["name"] == "new-name"


def test_refine_verdict_without_cases_keeps_summary():
    assert refine_verdict("regressed", None) == "regressed"
    assert refine_verdict("improved", {"counts": {"new_fail": 0, "fixed": 0}}) == "improved"
