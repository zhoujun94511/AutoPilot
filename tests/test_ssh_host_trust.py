"""AUD-2026-04：SSH 主机信任默认 RejectPolicy，未知主机须显式放行。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from autopilot.keywords.context import ExecutionContext
from autopilot.keywords.data import ssh as ssh_mod
from autopilot.keywords.registry import KeywordError


class _RejectPolicy:
    pass


class _AutoAddPolicy:
    pass


class _BadHostKey(Exception):
    pass


class _SSHExc(Exception):
    pass


def _install_fake_paramiko(monkeypatch, *, client_cls):
    fake_mod = MagicMock()
    fake_mod.SSHClient = client_cls
    fake_mod.RejectPolicy = _RejectPolicy
    fake_mod.AutoAddPolicy = _AutoAddPolicy
    fake_mod.BadHostKeyException = _BadHostKey
    fake_mod.SSHException = _SSHExc
    monkeypatch.setitem(__import__("sys").modules, "paramiko", fake_mod)
    return fake_mod


def test_default_factory_uses_reject_policy_when_unknown_disallowed(monkeypatch):
    created = []

    class _FakeSSHClient:
        def __init__(self):
            self.policy = None
            created.append(self)

        @staticmethod
        def load_system_host_keys():
            return None

        def set_missing_host_key_policy(self, policy):
            self.policy = policy

        @staticmethod
        def connect(*_a, **_k):
            return None

    monkeypatch.delenv("AUTOPILOT_SSH_ALLOW_UNKNOWN_HOST", raising=False)
    _install_fake_paramiko(monkeypatch, client_cls=_FakeSSHClient)
    ssh_mod.default_ssh_factory("10.0.0.1", 22, "u", "p", allow_unknown_host=False)
    assert created
    assert isinstance(created[0].policy, _RejectPolicy)


def test_default_factory_autoadd_when_allow_unknown(monkeypatch):
    created = []

    class _FakeSSHClient:
        def __init__(self):
            self.policy = None
            created.append(self)

        @staticmethod
        def load_system_host_keys():
            return None

        def set_missing_host_key_policy(self, policy):
            self.policy = policy

        @staticmethod
        def connect(*_a, **_k):
            return None

    monkeypatch.delenv("AUTOPILOT_SSH_ALLOW_UNKNOWN_HOST", raising=False)
    _install_fake_paramiko(monkeypatch, client_cls=_FakeSSHClient)
    ssh_mod.default_ssh_factory("10.0.0.1", 22, "u", "p", allow_unknown_host=True)
    assert isinstance(created[0].policy, _AutoAddPolicy)


def test_env_allow_unknown_enables_autoadd(monkeypatch):
    created = []

    class _FakeSSHClient:
        def __init__(self):
            self.policy = None
            created.append(self)

        @staticmethod
        def load_system_host_keys():
            return None

        def set_missing_host_key_policy(self, policy):
            self.policy = policy

        @staticmethod
        def connect(*_a, **_k):
            return None

    monkeypatch.setenv("AUTOPILOT_SSH_ALLOW_UNKNOWN_HOST", "1")
    _install_fake_paramiko(monkeypatch, client_cls=_FakeSSHClient)
    ssh_mod.default_ssh_factory("10.0.0.1", 22, "u", "p", allow_unknown_host=False)
    assert isinstance(created[0].policy, _AutoAddPolicy)


def test_connect_keyword_passes_allow_flag_to_factory():
    ctx = ExecutionContext()
    seen = {}

    def _factory(ip, port, user, passwd, **kw):
        seen["args"] = (ip, port, user, passwd)
        seen["kw"] = kw
        return MagicMock()

    ctx.ssh_factory = _factory
    ssh_mod.connect_ssh(
        ctx,
        alias="s1",
        IP="1.2.3.4",
        port="22",
        user="root",
        passwd="x",
        allow_unknown_host="true",
        known_hosts="/tmp/kh",
    )
    assert seen["args"][0] == "1.2.3.4"
    assert seen["kw"]["allow_unknown_host"] is True
    assert seen["kw"]["known_hosts"] == "/tmp/kh"


def test_connect_keyword_compat_with_four_arg_factory():
    """既有测试注入的 4 参 factory 不得因新 kwargs 破坏。"""
    ctx = ExecutionContext()
    ctx.ssh_factory = lambda ip, port, user, pwd: MagicMock(close=MagicMock())
    ssh_mod.connect_ssh(ctx, alias="s", IP="10.0.0.1", port="22", user="u", passwd="p")
    assert "s" in ctx.ssh


def test_missing_known_hosts_file_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("AUTOPILOT_SSH_ALLOW_UNKNOWN_HOST", raising=False)

    class _FakeSSHClient:
        @staticmethod
        def load_system_host_keys():
            return None

        @staticmethod
        def set_missing_host_key_policy(_policy):
            return None

        @staticmethod
        def connect(*_a, **_k):
            return None

    _install_fake_paramiko(monkeypatch, client_cls=_FakeSSHClient)
    missing = tmp_path / "no-such-known-hosts"
    with pytest.raises(KeywordError, match="known_hosts"):
        ssh_mod.default_ssh_factory(
            "10.0.0.1",
            22,
            "u",
            "p",
            allow_unknown_host=False,
            known_hosts=str(missing),
        )


def test_source_no_longer_defaults_to_autoadd():
    """源码级回归：默认工厂不得无条件 AutoAddPolicy。"""
    from pathlib import Path

    src = Path(ssh_mod.__file__).read_text(encoding="utf-8")
    assert "RejectPolicy" in src
    assert "allow_unknown_host" in src
    # 默认分支应设置 Reject；AutoAdd 仅在 allow 为真时
    assert "set_missing_host_key_policy(paramiko.RejectPolicy())" in src
    assert "if allow:" in src
    assert "AutoAddPolicy()" in src
