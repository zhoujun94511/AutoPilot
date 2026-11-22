from __future__ import annotations

from typing import cast

from autopilot.runner import agent as agent_module
from autopilot.runner.agent import RunnerAgent
from autopilot.runner.client import PlatformClient
from autopilot.runner.contract import JobOut, JobResultIn, JobStatus, ReportIndex


class _ReportClient:
    def __init__(
        self, job: JobOut, *, fail_upload: bool = False, fail_complete: bool = False
    ) -> None:
        self.job = job
        self.fail_upload = fail_upload
        self.fail_complete = fail_complete
        self.calls: list[str] = []
        self.result: JobResultIn | None = None
        self.claims: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    @staticmethod
    def heartbeat(_body) -> dict:
        return {}

    def claim(self, _runner_id: str, *, wait_sec: int = 0) -> JobOut:
        return self.job

    def mark_running(self, _job_id: str, _runner_id: str, *, claimed_at: str = "") -> JobOut:
        self.calls.append("running")
        self.claims.append(claimed_at)
        return self.job

    def upload_report(
        self, _job_id: str, _runner_id: str, _path: str, *, claimed_at: str = ""
    ) -> dict:
        self.calls.append("report")
        self.claims.append(claimed_at)
        if self.fail_upload:
            raise OSError("network down")
        return {}

    def upload_result_json(
        self, _job_id: str, _runner_id: str, _path: str, *, claimed_at: str = ""
    ) -> dict:
        self.calls.append("result")
        self.claims.append(claimed_at)
        return {}

    def upload_evidence_zip(
        self, _job_id: str, _runner_id: str, _path: str, *, claimed_at: str = ""
    ) -> dict:
        self.calls.append("evidence")
        self.claims.append(claimed_at)
        return {}

    def complete(
        self, _job_id: str, _runner_id: str, _result: JobResultIn, *, claimed_at: str = ""
    ) -> JobOut:
        self.calls.append("complete")
        self.claims.append(claimed_at)
        if self.fail_complete:
            raise OSError("temporarily unavailable")
        self.result = _result
        return self.job


def _run_with_report(tmp_path, monkeypatch, *, fail_upload: bool, fail_complete: bool = False):
    report_dir = tmp_path / "mc-report-delivery"
    report_dir.mkdir()
    report_path = report_dir / "report.html"
    report_path.write_text("<html>ok</html>", encoding="utf-8")
    (report_dir / "result.json").write_text("{}", encoding="utf-8")
    (report_dir / "evidence.zip").touch()
    job = JobOut(id="job-1", name="job", status=JobStatus.CLAIMED, claimed_at="2026-11-22T08:00:00Z")
    result = JobResultIn(
        status=JobStatus.SUCCEEDED,
        report=ReportIndex(report_path=str(report_path)),
    )
    monkeypatch.setattr(agent_module, "execute_job", lambda *_a, **_kw: result)
    monkeypatch.setenv("MC_RUNNER_STATE_DIR", str(tmp_path / "runner-state"))
    monkeypatch.setattr(agent_module.tempfile, "gettempdir", lambda: str(tmp_path))
    runner = RunnerAgent("http://platform", runner_id="runner-1")
    monkeypatch.setattr(runner, "_heartbeat_once", lambda _client: None)
    monkeypatch.setattr(runner, "_ensure_exec_heartbeat", lambda _client: None)
    report_stub = _ReportClient(job, fail_upload=fail_upload, fail_complete=fail_complete)
    # Each claimed job now owns a client in its worker thread.  Keep both
    # claim and delivery requests on this local stub, with no device/network IO.
    monkeypatch.setattr(agent_module, "PlatformClient", lambda *_a, **_kw: report_stub)
    client = cast(PlatformClient, report_stub)

    assert runner.run_once(client) is True
    worker = runner._job_threads[job.id]
    worker.join(timeout=5)
    assert not worker.is_alive(), "report delivery worker did not finish"
    assert not runner._slots.has_any()
    return report_stub, report_dir


def test_runner_uploads_report_before_complete_and_cleans_success(tmp_path, monkeypatch):
    client, report_dir = _run_with_report(tmp_path, monkeypatch, fail_upload=False)
    assert client.calls == ["running", "report", "result", "evidence", "complete"]
    assert client.result is not None
    assert client.result.status == JobStatus.SUCCEEDED
    assert client.claims == [client.job.claimed_at] * 5
    assert not report_dir.exists()


def test_runner_retains_local_report_when_upload_fails(tmp_path, monkeypatch):
    client, report_dir = _run_with_report(tmp_path, monkeypatch, fail_upload=True)
    assert client.calls == ["running", "report", "report", "report", "complete"]
    assert client.result is not None
    assert client.result.status == JobStatus.FAILED
    assert "本地文件已保留" in client.result.error
    assert report_dir.exists()


def test_runner_replays_unacknowledged_result_after_restart(tmp_path, monkeypatch):
    client, report_dir = _run_with_report(
        tmp_path, monkeypatch, fail_upload=False, fail_complete=True
    )
    assert report_dir.exists()
    restarted = RunnerAgent("http://platform", runner_id="runner-1")
    assert len(list(restarted._result_directory.glob("*.json"))) == 1

    client.fail_complete = False
    restarted._retry_pending_results(cast(PlatformClient, client))
    assert client.calls == ["running", "report", "result", "evidence", "complete", "complete"]
    assert client.claims[-1] == client.job.claimed_at
    assert client.result is not None and client.result.status == JobStatus.SUCCEEDED
    assert not list(restarted._result_directory.glob("*.json"))
    assert not report_dir.exists()
