"""schema 2.0 追踪字段 YAML 往返。"""

from __future__ import annotations

from autopilot.model import serializer
from autopilot.model.testcase import Desc, TestCase
from autopilot.mgmt.logical_import import logical_case_to_tc_dict


def test_schema2_trace_fields_roundtrip(tmp_path):
    tc = TestCase(
        name="login",
        data_id="abc123",
        schema_version="2.0",
        project_id="proj-1",
        logical_case_id="lc-9",
        automation_case_id="ac-8",
        revision_id="rev-1",
        case_key="LOGIN-01",
        desc=Desc(description="d", precondition="已注册"),
    )
    path = tmp_path / "login.tc.yaml"
    serializer.save_testcase(tc, str(path))
    loaded = serializer.load(str(path))
    assert isinstance(loaded, TestCase)
    assert loaded.schema_version == "2.0"
    assert loaded.project_id == "proj-1"
    assert loaded.logical_case_id == "lc-9"
    assert loaded.automation_case_id == "ac-8"
    assert loaded.revision_id == "rev-1"
    assert loaded.case_key == "LOGIN-01"
    assert loaded.desc.precondition == "已注册"
    assert loaded.desc.description == "d"


def test_logical_import_dict_loads_via_serializer():
    data = logical_case_to_tc_dict(
        {
            "id": "lc-1",
            "title": "打开首页",
            "case_key": "HOME-1",
            "logical_steps": ["打开应用", "点击首页"],
            "expected_results": ["看到首页"],
            "preconditions": ["已安装"],
        },
        project_id="p1",
    )
    tc = serializer.dict_to_testcase(data)
    assert tc.schema_version == "2.0"
    assert tc.project_id == "p1"
    assert tc.logical_case_id == "lc-1"
    assert tc.case_key == "HOME-1"
    assert tc.desc.precondition == "已安装"
    assert len(tc.case.steps) >= 2
    d2 = serializer.testcase_to_dict(tc)
    assert d2["format_version"] == 2
    assert d2["logical_case_id"] == "lc-1"
