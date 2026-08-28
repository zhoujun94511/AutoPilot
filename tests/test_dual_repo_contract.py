"""IDE→Platform 跨仓公开契约：端点、manifest、状态证据与 Runner scope。"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from autopilot.mgmt.client import MgmtClient
from autopilot.mgmt.pack import zip_project_dir
from autopilot.mgmt.runtime_contract import (
    validate_artifact_runtime,
    validate_platform_runtime,
)
from autopilot.report.result_json import cases_from_suite


class _Response:
    status_code = 200
    content = b"{}"
    text = "{}"

    @staticmethod
    def json():
        return {}


class _Http:
    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []

    def post(self, path, **kwargs):
        self.calls.append(("POST", path, kwargs.get("json") or {}))
        return _Response()

    def get(self, path, **kwargs):
        self.calls.append(("GET", path, kwargs.get("params") or {}))
        return _Response()


def _client() -> tuple[MgmtClient, _Http]:
    client = object.__new__(MgmtClient)
    http = _Http()
    client._client = http
    return client, http


def test_client_endpoint_schema_and_runner_scope():
    client, http = _client()
    client.enqueue_approved_cases_job(
        {
            "project_id": "p1",
            "artifact_id": "a1",
            "logical_case_ids": ["lc1"],
            "app_build_id": "app1",
            "device_udids": ["u1"],
        }
    )
    client.runtime_version()
    client.issue_scoped_runner_token("r1", org_id="o1", project_ids=["p1"])
    assert http.calls[0] == (
        "POST",
        "/api/v1/design/logical-cases/enqueue-job",
        {
            "project_id": "p1",
            "artifact_id": "a1",
            "logical_case_ids": ["lc1"],
            "app_build_id": "app1",
            "device_udids": ["u1"],
        },
    )
    assert http.calls[1][1] == "/api/v1/ops/runtime-version"
    assert http.calls[2][1] == "/api/v1/runners/r1/scoped-token"
    assert http.calls[2][2] == {"org_id": "o1", "project_ids": ["p1"]}


def test_manifest_project_and_runtime(tmp_path):
    (tmp_path / "a.tc.yaml").write_text("name: a\n", encoding="utf-8")
    data = zip_project_dir(
        str(tmp_path),
        project_id="p1",
        required_runtime_version="0.1.0-vendored",
    )
    with zipfile.ZipFile(BytesIO(data)) as archive:
        manifest_name = next(n for n in archive.namelist() if n.endswith("/manifest.json"))
        manifest = json.loads(archive.read(manifest_name))
    assert manifest["project_id"] == "p1"
    assert manifest["required_runtime_version"] == "0.1.0-vendored"
    assert (
        validate_platform_runtime(
            {"ap_version": "0.1.0-vendored", "runtime_pin": "0.1.0-vendored"}
        )
        == "0.1.0-vendored"
    )
    validate_artifact_runtime(
        {"required_runtime_version": "0.1.3"},
        "0.1.0-vendored",
    )


def test_result_status_mapping_evidence(tmp_path):
    tc = tmp_path / "mapping.tc.yaml"
    tc.write_text(
        "logical_case_id: lc-map\n"
        "shells:\n"
        "  case:\n"
        "    - step: click\n"
        "      remark: mapping_required\n",
        encoding="utf-8",
    )
    rr = SimpleNamespace(
        case_name="mapping",
        passed=False,
        duration_ms=1,
        source_path=str(tc),
        results=[],
    )
    rows = cases_from_suite(SimpleNamespace(results=[rr]), project_dir=str(tmp_path))
    assert rows[0]["mapping_required"] is True
    assert rows[0]["automation_status_evidence"] == "MAPPING_REQUIRED"


def test_runtime_public_capability_contract_matches_platform():
    ide_root = Path(__file__).resolve().parents[1]
    platform_root = ide_root.parent / "Autopilot-Platform"
    ide = json.loads(
        (ide_root / "contracts" / "runtime_contract.json").read_text(encoding="utf-8")
    )
    platform = json.loads(
        (platform_root / "contracts" / "runtime_contract.json").read_text(
            encoding="utf-8"
        )
    )
    assert ide["schema_version"] == platform["schema_version"]
    assert set(ide["capabilities"]) == set(platform["capabilities"])
    # 公开契约须同一 canonical semver（-vendored 只允许出现在 ap/RUNTIME_PIN）
    assert ide["runtime_version"] == platform["runtime_version"]
    assert "-" not in str(ide["runtime_version"])
    assert "-" not in str(platform["runtime_version"])


def test_jsonschema_mirrors_platform_byte_identical():
    """AUD-P2-002：IDE 须镜像 Platform 权威 jsonschema 全集。"""
    ide_root = Path(__file__).resolve().parents[1]
    platform_root = ide_root.parent / "Autopilot-Platform"
    if not (platform_root / "contracts" / "jsonschema").is_dir():
        return
    from tools.check_dual_repo_contract import check_jsonschema_sync

    check_jsonschema_sync(ide_root, platform_root)
    expected = {
        "artifact_manifest.v1.json",
        "intent_case.v2.json",
        "logical_case.v1.json",
        "result.v1.json",
        "step_binding.v1.json",
    }
    ide_names = {
        p.name
        for p in (ide_root / "contracts" / "jsonschema").glob("*.json")
    }
    assert expected <= ide_names


def test_dual_repo_contract_checker_when_platform_present():
    """门禁脚本须可执行；覆盖 engine 字节一致与 Platform ap 依赖可达。"""
    ide_root = Path(__file__).resolve().parents[1]
    platform_root = ide_root.parent / "Autopilot-Platform"
    if not (platform_root / "autopilot_platform" / "ap").is_dir():
        return
    from tools.check_dual_repo_contract import check_contracts

    check_contracts(ide_root, platform_root)


def test_main_ui_really_calls_enqueue_endpoint():
    # AUD-2026-17：投递面在 mgmt_delivery.py；入口仍经 MgmtMixin
    mw = (
        Path(__file__).resolve().parents[1]
        / "autopilot"
        / "ui"
        / "main_window"
    )
    delivery = (mw / "mgmt_delivery.py").read_text(encoding="utf-8")
    facade = (mw / "mgmt.py").read_text(encoding="utf-8")
    assert "def mgmt_enqueue_approved_cases" in delivery
    assert "client.enqueue_approved_cases_job(body)" in delivery
    enqueue_chunk = delivery.split("client.enqueue_approved_cases_job(body)", 1)[0][-900:]
    assert "backend_mode" in enqueue_chunk
    assert "wda_bundle" in enqueue_chunk
    assert "MgmtSessionMixin" in facade
    assert "MgmtRunnerWebMixin" in (mw / "mgmt_session.py").read_text(encoding="utf-8")
    assert "MgmtDeliveryMixin" in (mw / "mgmt_runner_web.py").read_text(encoding="utf-8")
