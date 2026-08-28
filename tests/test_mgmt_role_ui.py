"""IDE 管理台 role 门禁与连接设置文案。"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from autopilot.ui.actions import ACTIONS, ActionSpec, action_allowed_for_role
from autopilot.ui.main_window import mgmt_session as mgmt_session_mod
from autopilot.ui.mgmt_role import (
    connect_settings_banner,
    connect_token_placeholder,
    is_platform_admin_role,
    role_meets_min,
)

_MGMT_WRITE_ACTION_IDS = getattr(mgmt_session_mod, "_MGMT_WRITE_ACTION_IDS")
mgmt_open_web_enabled = mgmt_session_mod.mgmt_open_web_enabled
mgmt_write_enabled = mgmt_session_mod.mgmt_write_enabled


def test_role_meets_min():
    assert role_meets_min("admin", "operator") is True
    assert role_meets_min("operator", "operator") is True
    assert role_meets_min("operator", "admin") is False
    assert role_meets_min("admin", "admin") is True


def test_connect_settings_copy_differs_by_role():
    admin_banner = connect_settings_banner(True)
    op_banner = connect_settings_banner(False)
    assert "自动签发" in admin_banner
    assert "不能自行签发" in op_banner
    assert connect_token_placeholder(False) != connect_token_placeholder(True)
    assert "必填" in connect_token_placeholder(False)


def test_mgmt_actions_default_operator_visible():
    role = "operator"
    mgmt_specs = [s for s in ACTIONS if s.id.startswith("mgmt.")]
    assert mgmt_specs, "expected mgmt menu actions"
    assert all(action_allowed_for_role(s, role) for s in mgmt_specs)


def test_admin_only_action_hidden_for_operator():
    spec = ActionSpec(
        id="mgmt.test_admin_only",
        text="t",
        slot="noop",
        min_role="admin",
    )
    assert action_allowed_for_role(spec, "admin") is True
    assert action_allowed_for_role(spec, "operator") is False


def test_open_mgmt_web_does_not_require_project():
    assert mgmt_open_web_enabled(logged_in=True) is True
    assert mgmt_open_web_enabled(logged_in=False) is False
    assert mgmt_write_enabled(logged_in=True, has_project=False) is False
    assert mgmt_write_enabled(logged_in=True, has_project=True) is True
    assert "mgmt.open" not in _MGMT_WRITE_ACTION_IDS
    assert "mgmt.import_logical" in _MGMT_WRITE_ACTION_IDS


def test_is_platform_admin_role_from_settings(monkeypatch):
    store = {"mc_user_role": "operator"}

    import autopilot.runtime.settings as settings

    monkeypatch.setattr(settings, "load", lambda: dict(store))
    monkeypatch.setattr(settings, "mc_user_role", lambda: store.get("mc_user_role", ""))
    assert is_platform_admin_role() is False
    store["mc_user_role"] = "admin"
    assert is_platform_admin_role() is True
