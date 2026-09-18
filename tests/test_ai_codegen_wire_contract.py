"""链路 3 双仓 wire v1：请求版本、能力兼容与结构化错误。"""

from __future__ import annotations

import json as jsonlib
from pathlib import Path

import pytest

from autopilot.authoring.contract import AuthoringError
from autopilot.authoring.llm_client import validate_platform_wire_contract
from autopilot.mgmt.client import (
    AI_CODEGEN_WIRE_VERSION,
    MgmtClient,
    MgmtClientError,
)


class _Response:
    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code = status_code
        self._body = body
        self.text = jsonlib.dumps(body, ensure_ascii=False)
        self.content = self.text.encode()

    def json(self) -> dict:
        return self._body


def test_codegen_request_declares_wire_version() -> None:
    captured: dict = {}

    class _Http:
        @staticmethod
        def post(path: str, *, json: dict) -> _Response:
            captured.update({"path": path, "json": json})
            return _Response(200, {"ok": True})

    client = object.__new__(MgmtClient)
    client._client = _Http()
    client.ai_codegen("打开设置", purpose="authoring")
    assert captured["json"]["wire_contract_version"] == AI_CODEGEN_WIRE_VERSION


def test_structured_platform_error_uses_human_message() -> None:
    response = _Response(
        503,
        {"detail": {"error": "ai_unavailable", "message": "AI 尚未开通"}},
    )
    with pytest.raises(MgmtClientError, match="AI 尚未开通"):
        MgmtClient._check(response)


def test_wire_major_validation_is_backward_compatible() -> None:
    validate_platform_wire_contract({"enabled": True})
    validate_platform_wire_contract({"wire_contract_version": "1.3"})
    with pytest.raises(AuthoringError, match="协议不兼容"):
        validate_platform_wire_contract({"wire_contract_version": "2.0"})


def test_ai_codegen_schema_is_mirrored_from_platform() -> None:
    ide_root = Path(__file__).resolve().parents[1]
    ide_schema = ide_root / "contracts/jsonschema/ai_codegen_wire.v1.json"
    platform_schema = (
        ide_root.parent
        / "Autopilot-Platform/contracts/jsonschema/ai_codegen_wire.v1.json"
    )
    assert jsonlib.loads(ide_schema.read_text(encoding="utf-8"))["$defs"]["request"]
    if platform_schema.is_file():
        assert ide_schema.read_bytes() == platform_schema.read_bytes()
