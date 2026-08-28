"""本地跑完后回写 EXECUTABLE / DEBUGGING / MAPPING_REQUIRED。"""

from __future__ import annotations

from autopilot.engine.executor import RunResult, StepResult
from autopilot.engine.suite import SuiteResult
from autopilot.mgmt.case_trace import has_mapping_required
from autopilot.mgmt.executable_sync import collect_passed_logical_ids, sync_executable_after_run
from autopilot.mgmt.run_status_sync import (
    collect_failed_logical_ids,
    collect_logical_ids_by_outcome,
    collect_status_targets,
    sync_statuses_after_run,
)


def _write_tc(path, *, logical_id: str, mapping: bool):
    remark = "mapping_required" if mapping else "mapped"
    path.write_text(
        "type: testcase\n"
        f"name: {logical_id}\n"
        f"logical_case_id: {logical_id}\n"
        "shells:\n"
        "  before: []\n"
        "  case:\n"
        "  - step: web_common_sleep\n"
        f"    remark: {remark}\n"
        "    is_run: false\n"
        "    params: {millis: '0'}\n"
        "  after: []\n"
        "  fault: []\n",
        encoding="utf-8",
    )


def _rr(path, passed: bool) -> RunResult:
    rr = RunResult(case_name=path.stem, source_path=str(path))
    if passed:
        rr.results = [StepResult("x", "", "PASS")]
    else:
        rr.results = [StepResult("x", "", "FAIL", "boom")]
    return rr


def test_has_mapping_required(tmp_path):
    p = tmp_path / "a.tc.yaml"
    _write_tc(p, logical_id="lc-a", mapping=True)
    assert has_mapping_required(str(p)) is True
    _write_tc(p, logical_id="lc-a", mapping=False)
    assert has_mapping_required(str(p)) is False


def test_collect_status_targets_splits_mapping(tmp_path):
    ok = tmp_path / "ok.tc.yaml"
    bad_map = tmp_path / "bad_map.tc.yaml"
    bad_dbg = tmp_path / "bad_dbg.tc.yaml"
    _write_tc(ok, logical_id="lc-ok", mapping=False)
    _write_tc(bad_map, logical_id="lc-map", mapping=True)
    _write_tc(bad_dbg, logical_id="lc-dbg", mapping=False)

    suite = SuiteResult(
        name="s",
        results=[_rr(ok, True), _rr(bad_map, False), _rr(bad_dbg, False)],
    )
    targets = collect_status_targets(suite)
    assert targets["EXECUTABLE"] == ["lc-ok"]
    assert targets["MAPPING_REQUIRED"] == ["lc-map"]
    assert targets["DEBUGGING"] == ["lc-dbg"]
    assert collect_passed_logical_ids(suite) == ["lc-ok"]
    assert set(collect_failed_logical_ids(suite)) == {"lc-map", "lc-dbg"}
    assert collect_logical_ids_by_outcome(suite)[0] == ["lc-ok"]


def test_collect_status_targets_binding_partial(tmp_path):
    """通过但 Binding 未覆盖全部 intent → BINDING_PARTIAL。"""
    ok = tmp_path / "imported_logical"
    ok.mkdir()
    tc = ok / "partial.tc.yaml"
    tc.write_text(
        "type: testcase\n"
        "name: partial\n"
        "logical_case_id: lc-partial\n"
        "shells:\n"
        "  case:\n"
        "  - step: intent_act\n"
        "    remark: intent:s1|click\n"
        "    is_run: true\n"
        "    params: {intent_id: s1, action: click, target: 登录}\n"
        "  - step: intent_act\n"
        "    remark: intent:s2|assert\n"
        "    is_run: true\n"
        "    params: {intent_id: s2, action: assert, target: 欢迎}\n",
        encoding="utf-8",
    )
    from autopilot.intent.bindings import upsert_step_binding

    upsert_step_binding(
        tmp_path,
        "lc-partial",
        "s1",
        platform="web",
        keyword_id="web_element_click",
        params={"locator": "x"},
    )
    suite = SuiteResult(name="s", results=[_rr(tc, True)])
    targets = collect_status_targets(suite, project_dir=str(tmp_path))
    assert targets["BINDING_PARTIAL"] == ["lc-partial"]
    assert targets["EXECUTABLE"] == []


def test_sync_executable_no_ids():
    class _C:
        def __init__(self):
            self.calls = []

        def set_automation_status(self, cid, status):
            self.calls.append((cid, status))

    suite = SuiteResult(name="s", results=[RunResult(case_name="x")])
    client = _C()
    assert sync_executable_after_run(suite, client=client) == (0, 0)
    assert client.calls == []


def test_sync_statuses_after_run_patches_three_ways(tmp_path):
    class _C:
        def __init__(self):
            self.calls = []

        def set_automation_status(self, cid, status):
            self.calls.append((cid, status))

    ok = tmp_path / "ok.tc.yaml"
    bad_map = tmp_path / "bad_map.tc.yaml"
    bad_dbg = tmp_path / "bad_dbg.tc.yaml"
    _write_tc(ok, logical_id="lc-ok", mapping=False)
    _write_tc(bad_map, logical_id="lc-map", mapping=True)
    _write_tc(bad_dbg, logical_id="lc-dbg", mapping=False)
    suite = SuiteResult(
        name="s",
        results=[_rr(ok, True), _rr(bad_map, False), _rr(bad_dbg, False)],
    )
    client = _C()
    out = sync_statuses_after_run(suite, client=client)
    assert out == {
        "EXECUTABLE": (1, 0),
        "BINDING_PARTIAL": (0, 0),
        "PENDING_VERIFY": (0, 0),
        "DEBUGGING": (1, 0),
        "MAPPING_REQUIRED": (1, 0),
    }
    assert ("lc-ok", "EXECUTABLE") in client.calls
    assert ("lc-map", "MAPPING_REQUIRED") in client.calls
    assert ("lc-dbg", "DEBUGGING") in client.calls
