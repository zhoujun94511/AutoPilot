"""失败用例事后二审：只加注，不改 PASS/FAIL。"""

from __future__ import annotations

from autopilot.report.fail_review import review_failed_case, unique_root_causes


def test_review_does_not_change_status():
    case = {
        "status": "failed",
        "steps": [
            {
                "status": "FAIL",
                "attribution": "inner_agent_bug",
                "fail_class": "locator",
                "fail_reason": "no_candidate",
                "error_message": "no candidate",
            }
        ],
    }
    review = review_failed_case(case)
    assert case["status"] == "failed"
    assert review["changed_status"] is False
    assert any("定位偏差" in text for text in review["issues"])


def test_review_crash_stays_product_bug():
    case = {
        "status": "failed",
        "steps": [
            {
                "status": "FAIL",
                "attribution": "product_bug",
                "fail_class": "other",
                "fail_reason": "app_crash",
                "error_message": "目标应用已离开前台（疑似崩溃）",
            }
        ],
    }
    review = review_failed_case(case)
    assert review["changed_status"] is False
    assert any("崩溃" in text for text in review["issues"])


def test_unique_root_causes_dedup():
    steps = [
        {
            "attribution": "product_bug",
            "fail_class": "locator",
            "fail_reason": "element_not_found",
        },
        {
            "attribution": "product_bug",
            "fail_class": "locator",
            "fail_reason": "element_not_found",
        },
        {
            "attribution": "env_issue",
            "fail_class": "timeout",
            "fail_reason": "timeout",
        },
    ]
    roots = unique_root_causes(steps)
    assert len(roots) == 2
    assert roots[0]["attribution"] == "product_bug"
    assert roots[1]["attribution"] == "env_issue"


def test_passed_case_has_no_review():
    assert review_failed_case({"status": "passed", "steps": []}) == {}
