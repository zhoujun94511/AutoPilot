"""IDE 项目上下文：禁止目录名回退；无成员明确报错。"""

from __future__ import annotations

import os
import sys
from typing import cast

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest

from autopilot.mgmt.client import MgmtClient, MgmtClientError
from autopilot.mgmt.project_context import (
    assert_project_membership,
    ensure_project_selected,
    project_id_from_label,
    project_labels,
    require_cached_project_id,
)


class _FakeClient:
    def __init__(self, projects):
        self._projects = projects

    def list_projects(self):
        return list(self._projects)


def test_ensure_project_selected_empty(monkeypatch):
    monkeypatch.setattr("autopilot.runtime.settings.mc_project_id", lambda: "")
    cleared = {"v": None}

    def _set(v):
        cleared["v"] = v

    monkeypatch.setattr("autopilot.runtime.settings.set_mc_project_id", _set)
    with pytest.raises(MgmtClientError, match="没有任何可见项目"):
        ensure_project_selected(cast(MgmtClient, _FakeClient([])))
    assert cleared["v"] == ""


def test_resolve_login_allows_empty_projects(monkeypatch):
    from autopilot.mgmt.project_context import resolve_login_project

    monkeypatch.setattr("autopilot.runtime.settings.mc_project_id", lambda: "x")
    monkeypatch.setattr("autopilot.runtime.settings.set_mc_project_id", lambda _v: None)
    pid, need = resolve_login_project([])
    assert pid is None and need is False


def test_require_cached_project_id_empty(monkeypatch):
    monkeypatch.setattr("autopilot.runtime.settings.mc_project_id", lambda: "")
    with pytest.raises(MgmtClientError, match="未绑定项目空间"):
        require_cached_project_id()


def test_local_project_platform_binding_roundtrip(tmp_path, monkeypatch):
    from autopilot.runtime import settings

    monkeypatch.setenv("AUTOPILOT_CONFIG_DIR", str(tmp_path))
    local = str(tmp_path / "workspace")
    assert settings.mc_bound_project_id(local) == ""
    settings.set_mc_bound_project_id(local, "p1")
    assert settings.mc_bound_project_id(local) == "p1"
    settings.set_mc_bound_project_id(local, "p2")
    assert settings.mc_bound_project_id(local) == "p2"
    settings.set_mc_bound_project_id(local, "")
    assert settings.mc_bound_project_id(local) == ""


def test_ensure_project_selected_single(monkeypatch):
    monkeypatch.setattr("autopilot.runtime.settings.mc_project_id", lambda: "")
    saved = {"v": ""}

    def _set(v):
        saved["v"] = v

    monkeypatch.setattr("autopilot.runtime.settings.set_mc_project_id", _set)
    pid = ensure_project_selected(cast(MgmtClient, _FakeClient([{"id": "only", "name": "Only"}])))
    assert pid == "only"
    assert saved["v"] == "only"


def test_ensure_project_selected_choose(monkeypatch):
    monkeypatch.setattr("autopilot.runtime.settings.mc_project_id", lambda: "gone")
    saved = {"v": ""}

    def _set(v):
        saved["v"] = v

    monkeypatch.setattr("autopilot.runtime.settings.set_mc_project_id", _set)
    projects = [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}]
    pid = ensure_project_selected(
        cast(MgmtClient, _FakeClient(projects)),
        choose=lambda _ps: "b",
    )
    assert pid == "b"
    assert saved["v"] == "b"


def test_assert_project_membership_denied():
    with pytest.raises(MgmtClientError) as ei:
        assert_project_membership(cast(MgmtClient, _FakeClient([{"id": "a"}])), "b")
    assert ei.value.status_code == 403


def test_project_labels_and_parse():
    projects = [{"id": "team-core", "name": "核心"}]
    labels = project_labels(projects)
    assert labels == ["核心 (team-core)"]
    assert project_id_from_label(labels[0], projects) == "team-core"


def test_mgmt_client_error_keeps_status():
    err = MgmtClientError("无权访问", status_code=403)
    from autopilot.mgmt.client import mgmt_error_message

    assert "无权" in mgmt_error_message(err)
    assert err.status_code == 403
