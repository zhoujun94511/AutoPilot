from __future__ import annotations

from typing import cast

from autopilot.runner import agent as agent_module
from autopilot.runner.agent import RunnerAgent
from autopilot.runner.client import PlatformClient
from autopilot.runner.contract import JobOut, JobResultIn, JobStatus, ReportIndex


class _ReportClient:
    def __init__(self, job: JobOut, *, fail_upload: bool = False) -> None:
        self.job = job
        self.fail_upload = fail_upload
        self.calls: list[str] = []

    @staticmethod
    def heartbeat(_body) -> dict:
        return {}

    def claim(self, _runner_id: str) -> JobOut:
        return self.job

    def mark_running(self, _job_id: str, _runner_id: str) -> JobOut:
        self.calls.append("running")
        return self.job

    def upload_report(self, _job_id: str, _runner_id: str, _path: str) -> dict:
        self.calls.append("report")
        if self.fail_upload:
            raise OSError("network down")
        return {}

    def upload_result_json(self, _job_id: str, _runner_id: str, _path: str) -> dict:
        self.calls.append("result")
        return {}

    def complete(self, _job_id: str, _runner_id: str, _result: JobResultIn) -> JobOut:
        self.calls.append("complete")
        return self.job


def _run_with_report(tmp_path, monkeypatch, *, fail_upload: bool):
    report_dir = tmp_path / "mc-report-delivery"
    report_dir.mkdir()
    report_path = report_dir / "report.html"
    report_path.write_text("<html>ok</html>", encoding="utf-8")
    (report_dir / "result.json").write_text("{}", encoding="utf-8")
    job = JobOut(id="job-1", name="job", status=JobStatus.CLAIMED)
    result = JobResultIn(
        status=JobStatus.SUCCEEDED,
        report=ReportIndex(report_path=str(report_path)),
    )
    monkeypatch.setattr(agent_module, "execute_job", lambda *_a, **_kw: result)
    runner = RunnerAgent("http://platform", runner_id="runner-1")
    monkeypatch.setattr(runner, "_start_exec_heartbeat", lambda _client: None)
    monkeypatch.setattr(runner, "_stop_exec_heartbeat", lambda: None)
    report_stub = _ReportClient(job, fail_upload=fail_upload)
    client = cast(PlatformClient, report_stub)

    assert runner.run_once(client) is True
    return report_stub, report_dir


def test_runner_uploads_report_before_complete_and_cleans_success(tmp_path, monkeypatch):
    client, report_dir = _run_with_report(tmp_path, monkeypatch, fail_upload=False)
    assert client.calls == ["running", "report", "result", "complete"]
    assert not report_dir.exists()


def test_runner_retains_local_report_when_upload_fails(tmp_path, monkeypatch):
    client, report_dir = _run_with_report(tmp_path, monkeypatch, fail_upload=True)
    assert client.calls == ["running", "report", "complete"]
    assert report_dir.exists()
