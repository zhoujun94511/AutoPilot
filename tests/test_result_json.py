"""result.json 写出与 cases 提取。"""

from __future__ import annotations

import json

from autopilot.engine.executor import RunResult, StepResult
from autopilot.engine.suite import SuiteResult
from autopilot.report import cases_from_suite, write_result_json


def test_write_result_json_roundtrip(tmp_path):
    path = tmp_path / "result.json"
    write_result_json(
        str(path),
        job_id="local-1",
        status="succeeded",
        suite_name="s",
        passed=1,
        failed=0,
        total=1,
        duration_ms=12,
        summary="ok",
        project_id="p1",
        cases=[{"name": "a", "status": "passed", "duration_ms": 12}],
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0"
    assert data["job_id"] == "local-1"
    assert data["suite"]["passed"] == 1
    assert data["cases"][0]["name"] == "a"


def test_cases_from_suite_reads_trace(tmp_path):
    tc = tmp_path / "login.tc.yaml"
    tc.write_text(
        "type: testcase\n"
        "name: login\n"
        "logical_case_id: lc-1\n"
        "automation_case_id: ac-1\n"
        "case_key: K1\n"
        "shells: {before: [], case: [], after: [], fault: []}\n",
        encoding="utf-8",
    )
    rr = RunResult(case_name="login", source_path=str(tc), duration_ms=5)
    rr.results = [StepResult("web_common_sleep", "", "PASS")]
    suite = SuiteResult(name="s", results=[rr], duration_ms=5)
    cases = cases_from_suite(suite, project_dir=str(tmp_path))
    assert cases[0]["logical_case_id"] == "lc-1"
    assert cases[0]["automation_case_id"] == "ac-1"
    assert cases[0]["case_key"] == "K1"
    assert cases[0]["relative_path"] == "login.tc.yaml"
    assert cases[0]["status"] == "passed"
