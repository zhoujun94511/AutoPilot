"""AUD-P2-001：Authoring 执行层必须二次拦截 irreversible 关键字。"""

from __future__ import annotations

import pytest

from autopilot.authoring.contract import AuthoringError, GeneratedStep
from autopilot.authoring.step_runner import execute_keyword_step
from autopilot.keywords.registry import KeywordDef, REGISTRY


class _Ctx:
    @staticmethod
    def resolve(value: str) -> str:
        return value


def _install(monkeypatch, kid: str, func) -> None:
    monkeypatch.setitem(
        REGISTRY,
        kid,
        KeywordDef(keyword_id=kid, func=func, name=kid, category="test"),
    )


def test_execute_blocks_irreversible_keyword(monkeypatch):
    monkeypatch.delenv("AUTOPILOT_INTENT_ALLOW_IRREVERSIBLE", raising=False)
    called = {"n": 0}

    def _boom(_ctx, **_kwargs):
        called["n"] += 1

    # 即便 REGISTRY 有实现，执行前也应被 risk 闸门拦住
    _install(monkeypatch, "mobile_app_uninstall", _boom)

    step = GeneratedStep(
        keyword_id="mobile_app_uninstall",
        params={"package": "com.example.app"},
        comment="危险",
    )
    with pytest.raises(AuthoringError, match="高风险|irreversible|拒绝"):
        execute_keyword_step(step, _Ctx())
    assert called["n"] == 0


def test_execute_allows_irreversible_when_flag_on(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_INTENT_ALLOW_IRREVERSIBLE", "1")
    called = {"n": 0}

    def _ok(_ctx, **_kwargs):
        called["n"] += 1

    _install(monkeypatch, "mobile_app_uninstall", _ok)
    step = GeneratedStep(keyword_id="mobile_app_uninstall", params={}, comment="")
    execute_keyword_step(step, _Ctx())
    assert called["n"] == 1


def test_execute_allows_normal_keyword(monkeypatch):
    monkeypatch.delenv("AUTOPILOT_INTENT_ALLOW_IRREVERSIBLE", raising=False)
    called = {"n": 0}

    def _ok(_ctx, **_kwargs):
        called["n"] += 1

    _install(monkeypatch, "mobile_element_click", _ok)
    step = GeneratedStep(
        keyword_id="mobile_element_click",
        params={"locator": "name::ok"},
        comment="",
    )
    execute_keyword_step(step, _Ctx())
    assert called["n"] == 1


def test_execute_blocks_ssh_run_cmd(monkeypatch):
    """AUD-2026-09：Authoring 执行层拦截 SSH 远程命令。"""
    monkeypatch.delenv("AUTOPILOT_INTENT_ALLOW_IRREVERSIBLE", raising=False)
    called = {"n": 0}

    def _boom(_ctx, **_kwargs):
        called["n"] += 1

    _install(monkeypatch, "linux_ssh_runCmd_WithResult", _boom)
    step = GeneratedStep(
        keyword_id="linux_ssh_runCmd_WithResult",
        params={"alias": "s", "cmd": "id"},
        comment="",
    )
    with pytest.raises(AuthoringError, match="高风险|irreversible|拒绝"):
        execute_keyword_step(step, _Ctx())
    assert called["n"] == 0
