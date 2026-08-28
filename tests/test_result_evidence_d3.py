"""D3：失败证据路径写入 result.json。"""

from __future__ import annotations

from types import SimpleNamespace

import autopilot.report.result_json as result_json_mod

write_result_json = result_json_mod.write_result_json


def test_case_item_includes_evidence_paths():
    rr = SimpleNamespace(
        case_name="c1",
        passed=False,
        duration_ms=10,
        source_path="",
        results=[
            SimpleNamespace(
                comment="fail step",
                keyword_id="intent_act",
                status="FAIL",
                intent_id="s1",
                binding_hit="failed",
                heal_applied=False,
                resolved_keyword_id="",
                fail_reason="timeout",
                fail_reason_label="超时",
                rolled_back=False,
                message="boom",
                resolve_strategy="heuristic",
                candidate_count=1,
                perception_platform="web",
                perception_element_count=0,
                perception_used_screenshot=False,
                latency_ms=50,
                vision_tokens=0,
                verification_status="skipped",
                screenshot_path="reports/evidence/c1/s1/screenshot.png",
                dom_path="reports/evidence/c1/s1/page_source.xml",
            )
        ],
    )
    item = getattr(result_json_mod, "_case_item_from_result")(rr, root="")
    assert item["steps"][0]["screenshot_path"].endswith("screenshot.png")
    assert item["steps"][0]["dom_path"].endswith("page_source.xml")


def test_attachments_aggregated(tmp_path):
    cases = [
        {
            "name": "c1",
            "steps": [
                {
                    "intent_id": "s1",
                    "screenshot_path": "reports/evidence/a.png",
                    "dom_path": "reports/evidence/a.xml",
                }
            ],
        }
    ]
    atts = getattr(result_json_mod, "_attachments_from_cases")(cases)
    assert len(atts) == 2
    kinds = {a["kind"] for a in atts}
    assert kinds == {"screenshot", "dom"}
    # AUD-2026-14：canonical case + 兼容别名 case_name 须同时写出
    for a in atts:
        assert a.get("case") == "c1"
        assert a.get("case_name") == "c1"
    path = tmp_path / "result.json"
    write_result_json(
        str(path),
        job_id="j1",
        status="failed",
        suite_name="s",
        passed=0,
        failed=1,
        total=1,
        duration_ms=1,
        cases=cases,
    )
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["attachments"]
