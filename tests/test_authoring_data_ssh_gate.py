"""AUD-2026-15：链路 3 禁止 Data/SSH 进入 catalog / 解析 / 执行。"""

from __future__ import annotations

import pytest

from autopilot.authoring.codegen import parse_llm_draft
from autopilot.authoring.contract import (
    AUTHORING_BLOCKED_PREFIXES,
    AuthoringError,
    GeneratedStep,
    is_authoring_blocked_keyword,
)
from autopilot.authoring.registry_catalog import allowed_keyword_ids
from autopilot.authoring.step_runner import execute_keyword_step
from autopilot.keywords.registry import KeywordDef, REGISTRY


@pytest.mark.parametrize(
    "kid",
    [
        "linux_ssh_runCmd_WithResult",
        "linux_ssh_sftp_fileUpload",
        "redis_del_RedisKey",
        "jdbc_query",
        "ssh_run",
        "intent_act",
        "http_delete",
    ],
)
def test_is_authoring_blocked_keyword(kid: str):
    assert is_authoring_blocked_keyword(kid) is True


def test_mobile_click_not_blocked():
    assert is_authoring_blocked_keyword("mobile_element_click") is False


def test_catalog_excludes_ssh_and_redis():
    for plat in ("android", "ios", "web"):
        ids = allowed_keyword_ids(plat)
        assert not any(k.startswith(AUTHORING_BLOCKED_PREFIXES) for k in ids)
        assert "linux_ssh_runCmd_WithResult" not in ids
        assert "redis_del_RedisKey" not in ids
        assert "intent_act" not in ids


def test_parse_llm_draft_rejects_ssh():
    with pytest.raises(AuthoringError, match="无合法步骤|拒绝"):
        parse_llm_draft(
            {
                "title": "x",
                "steps": [
                    {
                        "keyword_id": "linux_ssh_runCmd_WithResult",
                        "params": {"cmd": "id"},
                    }
                ],
            },
            platform="android",
            max_steps=5,
        )


def test_execute_blocks_blocked_prefix_before_registry(monkeypatch):
    monkeypatch.delenv("AUTOPILOT_INTENT_ALLOW_IRREVERSIBLE", raising=False)
    called = {"n": 0}

    def _boom(_ctx, **_kwargs):
        called["n"] += 1

    monkeypatch.setitem(
        REGISTRY,
        "jdbc_query",
        KeywordDef(keyword_id="jdbc_query", func=_boom, name="jdbc", category="data"),
    )
    with pytest.raises(AuthoringError, match="AUD-2026-15|Data/SSH|拒绝"):
        execute_keyword_step(
            GeneratedStep(keyword_id="jdbc_query", params={}, comment=""),
            object(),
        )
    assert called["n"] == 0
