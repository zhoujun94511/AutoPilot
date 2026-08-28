"""Runner 按互斥设备并发领任务。"""

from __future__ import annotations

from unittest.mock import MagicMock

from autopilot.runner.agent import RunnerAgent
from autopilot.runner.contract import JobOut, JobStatus
from autopilot.runner.job_slots import JobSlotTracker


def _job(jid: str, udids: list[str]) -> JobOut:
    return JobOut(id=jid, name=jid, status=JobStatus.CLAIMED, device_udids=udids)


def test_run_once_starts_second_job_when_devices_disjoint(monkeypatch):
    agent = RunnerAgent("http://127.0.0.1:9", runner_id="r1", poll_interval=0.5)
    jobs = [_job("j-android", ["a1"]), _job("j-ios", ["i1"])]
    client = MagicMock()
    client.heartbeat.return_value = None
    client.claim.side_effect = jobs

    started: list[str] = []

    def _fake_run(job, _cancel_ev):  # noqa: ARG001
        started.append(job.id)

    monkeypatch.setattr(agent, "_run_claimed_job", _fake_run)
    monkeypatch.setattr(agent, "_heartbeat_once", lambda *_a, **_k: None)
    monkeypatch.setattr(agent, "_ensure_exec_heartbeat", lambda *_a, **_k: None)

    assert agent.run_once(client) is True
    assert agent.run_once(client) is True
    assert started == ["j-android", "j-ios"]
    assert agent._slots.busy_udids() == {"a1", "i1"}


def test_tracker_used_by_agent_rejects_overlap():
    t = JobSlotTracker()
    assert t.try_reserve("j1", ["x"]) == ""
    agent = RunnerAgent("http://127.0.0.1:9", runner_id="r1")
    agent._slots = t
    client = MagicMock()
    client.heartbeat.return_value = None
    client.claim.return_value = _job("j2", ["x"])
    client.complete.return_value = None
    agent._heartbeat_once = lambda *_a, **_k: None  # type: ignore[method-assign]
    assert agent.run_once(client) is True
    assert client.nack.called
    assert not client.complete.called
    assert client.nack.call_args.args[0] == "j2"
    assert "槽位冲突" in str(client.nack.call_args.kwargs.get("reason") or "")


def test_run_once_nacks_second_web_job(monkeypatch):
    agent = RunnerAgent("http://127.0.0.1:9", runner_id="r1")
    assert agent._slots.try_reserve("web1", []) == ""
    client = MagicMock()
    client.claim.return_value = _job("web2", [])
    client.nack.return_value = None
    monkeypatch.setattr(agent, "_heartbeat_once", lambda *_a, **_k: None)
    assert agent.run_once(client) is True
    assert client.nack.called
    assert not client.complete.called
    assert client.nack.call_args.args[0] == "web2"


def test_run_once_claims_device_job_while_web_running(monkeypatch):
    agent = RunnerAgent("http://127.0.0.1:9", runner_id="r1")
    assert agent._slots.try_reserve("web1", []) == ""
    client = MagicMock()
    client.claim.return_value = _job("j-android", ["a1"])
    started: list[str] = []
    monkeypatch.setattr(agent, "_run_claimed_job", lambda job, _ev: started.append(job.id))
    monkeypatch.setattr(agent, "_heartbeat_once", lambda *_a, **_k: None)
    monkeypatch.setattr(agent, "_ensure_exec_heartbeat", lambda *_a, **_k: None)
    assert agent.run_once(client) is True
    client.claim.assert_called_once()
    assert started == ["j-android"]


def test_run_once_claims_web_while_device_job_running(monkeypatch):
    agent = RunnerAgent("http://127.0.0.1:9", runner_id="r1")
    assert agent._slots.try_reserve("and1", ["a1"]) == ""
    client = MagicMock()
    client.claim.return_value = _job("web1", [])
    started: list[str] = []
    monkeypatch.setattr(agent, "_run_claimed_job", lambda job, _ev: started.append(job.id))
    monkeypatch.setattr(agent, "_heartbeat_once", lambda *_a, **_k: None)
    monkeypatch.setattr(agent, "_ensure_exec_heartbeat", lambda *_a, **_k: None)
    assert agent.run_once(client) is True
    assert started == ["web1"]
    assert agent._slots.has_web()
    assert agent._slots.busy_udids() == {"a1"}


def test_agent_recycles_udid_slot_after_job_thread_exits(monkeypatch):
    agent = RunnerAgent("http://127.0.0.1:9", runner_id="r1")
    client = MagicMock()
    client.claim.side_effect = [_job("j1", ["a1"]), _job("j2", ["a1"])]
    started: list[str] = []

    def _run(job, _ev):  # noqa: ARG001
        started.append(job.id)
        agent._slots.release(job.id)

    monkeypatch.setattr(agent, "_run_claimed_job", _run)
    monkeypatch.setattr(agent, "_heartbeat_once", lambda *_a, **_k: None)
    monkeypatch.setattr(agent, "_ensure_exec_heartbeat", lambda *_a, **_k: None)
    monkeypatch.setattr(agent, "_maybe_stop_exec_heartbeat", lambda *_a, **_k: None)
    assert agent.run_once(client) is True
    agent._job_threads["j1"].join(timeout=2)
    agent._reap_job_threads()
    assert started == ["j1"]
    assert "a1" not in agent._slots.busy_udids()
    assert agent.run_once(client) is True
    agent._job_threads["j2"].join(timeout=2)
    assert started == ["j1", "j2"]
    assert not client.nack.called
    assert not client.complete.called


def test_run_once_claims_with_wait_zero_when_device_job_active(monkeypatch):
    agent = RunnerAgent("http://127.0.0.1:9", runner_id="r1", poll_interval=3.0)
    agent._slots.try_reserve("j-android", ["a1"])
    client = MagicMock()
    client.claim.return_value = None
    monkeypatch.setattr(agent, "_heartbeat_once", lambda *_a, **_k: None)
    assert agent.run_once(client) is True
    client.claim.assert_called_once()
    assert client.claim.call_args.kwargs["wait_sec"] == 0
