"""B2：risk_level 元数据与 resolve 候选过滤。"""

from __future__ import annotations

from autopilot.intent.risk import filter_safe_candidates, risk_level
from autopilot.intent.resolve import resolve_candidates
from autopilot.metadata.keyword_meta import load_catalog


def test_catalog_marks_http_delete_irreversible():
    cat = load_catalog()
    meta = cat.get("http_delete")
    assert meta is not None
    assert meta.risk_level == "irreversible"
    assert risk_level("http_delete") == "irreversible"


def test_hardcode_not_downgraded_by_registry_write(monkeypatch):
    """AUD-P2-010：硬编码 irreversible 不可被 REGISTRY 误标 write 降级。"""
    from autopilot.keywords.registry import KeywordDef, REGISTRY

    kid = "mobile_app_uninstall"
    monkeypatch.setitem(
        REGISTRY,
        kid,
        KeywordDef(keyword_id=kid, func=lambda: None, name=kid, risk_level="write"),
    )
    assert risk_level(kid) == "irreversible"


def test_filter_safe_candidates_drops_irreversible(monkeypatch):
    monkeypatch.delenv("AUTOPILOT_INTENT_ALLOW_IRREVERSIBLE", raising=False)
    out = filter_safe_candidates(
        [
            {"keyword_id": "http_get", "score": 0.9},
            {"keyword_id": "http_delete", "score": 0.8},
        ]
    )
    assert [c["keyword_id"] for c in out] == ["http_get"]


def test_resolve_http_delete_filtered(monkeypatch):
    monkeypatch.delenv("AUTOPILOT_INTENT_ALLOW_IRREVERSIBLE", raising=False)
    cands = resolve_candidates(
        action="delete",
        target="/api/v1/users/1",
        value="",
        platform="web",
        channel="http",
        text="DELETE /api/v1/users/1",
        include_vision=False,
    )
    kids = {c.get("keyword_id") for c in cands}
    assert "http_delete" not in kids


def test_resolve_http_delete_allowed_when_env(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_INTENT_ALLOW_IRREVERSIBLE", "1")
    cands = resolve_candidates(
        action="delete",
        target="/api/v1/users/1",
        value="",
        platform="web",
        channel="http",
        text="DELETE /api/v1/users/1",
        include_vision=False,
    )
    kids = {c.get("keyword_id") for c in cands}
    assert "http_delete" in kids


def test_aud2026_09_ssh_and_destructive_mobile_irreversible():
    """AUD-2026-09：SSH 远程命令/SFTP、force-stop 重启、Monkey 须 irreversible。"""
    cat = load_catalog()
    kids = [
        "linux_ssh_runCmd_WithResult",
        "linux_ssh_runCmd_WithoutResult",
        "linux_ssh_sftp_fileUpload",
        "linux_ssh_sftp_fileDownload",
        "mobile_app_reset_saveinfo",
        "mobile_monkey",
    ]
    for kid in kids:
        meta = cat.get(kid)
        assert meta is not None, kid
        assert meta.risk_level == "irreversible", kid
        assert risk_level(kid) == "irreversible", kid
    # 连接本身仍为 write（非远程命令）
    assert risk_level("linux_ssh_connect") != "irreversible"
    assert risk_level("linux_ssh_close") != "irreversible"


def test_aud2026_09_filter_blocks_ssh_run(monkeypatch):
    monkeypatch.delenv("AUTOPILOT_INTENT_ALLOW_IRREVERSIBLE", raising=False)
    out = filter_safe_candidates(
        [
            {"keyword_id": "linux_ssh_connect", "score": 0.9},
            {"keyword_id": "linux_ssh_runCmd_WithResult", "score": 0.8},
        ]
    )
    assert [c["keyword_id"] for c in out] == ["linux_ssh_connect"]
