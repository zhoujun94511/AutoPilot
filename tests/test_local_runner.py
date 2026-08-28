"""本机 Runner 进程管理单测（不真起 autopilot.runner）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from autopilot.mgmt.local_runner import LocalRunnerProcess, default_local_runner_id


def test_default_local_runner_id_stable_shape():
    rid = default_local_runner_id()
    assert "-" in rid
    assert len(rid) > 4


def test_start_requires_server_and_token():
    p = LocalRunnerProcess()
    with pytest.raises(ValueError, match="服务器"):
        p.start("", "tok")
    with pytest.raises(ValueError, match="Token"):
        p.start("http://127.0.0.1:8000", "")


def test_start_stop_subprocess(monkeypatch):
    p = LocalRunnerProcess()
    fake = MagicMock()
    fake.poll.return_value = None
    with patch("builtins.__import__", return_value=MagicMock()):
        with patch("autopilot.mgmt.local_runner.subprocess.Popen", return_value=fake) as popen:
            rid = p.start("http://127.0.0.1:8000", "dev-mc-token", runner_id="ide-test-1")
    assert rid == "ide-test-1"
    assert p.running
    args = popen.call_args[0][0]
    kwargs = popen.call_args[1]
    assert "-m" in args and "autopilot.runner" in args
    assert "--runner-id" in args and "ide-test-1" in args
    assert "--token" not in args
    assert "--token-env" in args and "MC_API_TOKEN" in args
    assert kwargs["env"]["MC_API_TOKEN"] == "dev-mc-token"

    fake.poll.return_value = None
    fake.wait.return_value = 0
    assert p.stop() is True
    fake.terminate.assert_called_once()
    assert not p.running


def test_start_missing_runner_module_friendly_error():
    p = LocalRunnerProcess()
    with patch("builtins.__import__", side_effect=ImportError("nope")):
        with pytest.raises(RuntimeError, match="autopilot.runner"):
            p.start("http://127.0.0.1:8000", "tok")
