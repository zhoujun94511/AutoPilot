"""Platform HTTP 客户端（仅 X-API-Token；不 import 服务端包）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from autopilot.runtime.safe_zip import safe_extractall

from .contract import (
    API_V1_PREFIX,
    DEFAULT_API_TOKEN,
    DeviceInfo,
    HeartbeatIn,
    JobOut,
    JobResultIn,
    RunnerRegister,
)


def _httpx():
    try:
        import httpx
    except ImportError as exc:
        raise RuntimeError(
            "TestRunner 需要 httpx：pip install httpx 或 pip install -e \".[http]\""
        ) from exc
    return httpx


def _raise_for_status(r) -> None:  # noqa: ANN001
    """优先抛出后端错误信封中的 message（中文用户文案）。"""
    if r.is_success:
        return
    httpx = _httpx()
    detail = ""
    try:
        body = r.json()
        if isinstance(body, dict):
            detail = str(body.get("message") or body.get("detail") or "").strip()
    except (ValueError, TypeError):
        detail = (r.text or "").strip()
    if detail:
        raise httpx.HTTPStatusError(
            detail,
            request=r.request,
            response=r,
        )
    r.raise_for_status()


class PlatformClient:
    def __init__(
        self,
        base_url: str,
        token: str = DEFAULT_API_TOKEN,
        *,
        timeout: float = 30.0,
    ) -> None:
        httpx = _httpx()
        self.base_url = base_url.rstrip("/")
        from autopilot.runtime.http_ssl import httpx_verify

        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"X-API-Token": token},
            timeout=timeout,
            verify=httpx_verify(),
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PlatformClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @staticmethod
    def _url(path: str) -> str:
        return f"{API_V1_PREFIX}{path}"

    def register(self, body: RunnerRegister) -> dict[str, Any]:
        r = self._client.post(self._url("/runners/register"), json=body.to_dict())
        _raise_for_status(r)
        return r.json()

    def heartbeat(self, body: HeartbeatIn) -> dict[str, Any]:
        r = self._client.post(self._url("/runners/heartbeat"), json=body.to_dict())
        _raise_for_status(r)
        return r.json()

    def claim(self, runner_id: str, *, wait_sec: int = 0) -> Optional[JobOut]:
        """领取任务。``wait_sec>0`` 启用服务端长轮询（B1-T；需 timeout ≥ wait_sec）。"""
        params: dict[str, Any] = {"runner_id": runner_id}
        sec = max(0, min(30, int(wait_sec or 0)))
        kwargs: dict[str, Any] = {"params": params}
        if sec > 0:
            params["wait_sec"] = sec
            kwargs["timeout"] = float(sec) + 10.0
        r = self._client.post(self._url("/jobs/claim"), **kwargs)
        _raise_for_status(r)
        if r.status_code == 204 or not r.content or r.text in ("", "null"):
            return None
        data = r.json()
        if data is None:
            return None
        return JobOut.from_dict(data)

    def get_job(self, job_id: str) -> JobOut:
        r = self._client.get(self._url(f"/jobs/{job_id}"))
        _raise_for_status(r)
        return JobOut.from_dict(r.json())

    def mark_running(self, job_id: str, runner_id: str) -> JobOut:
        r = self._client.post(
            self._url(f"/jobs/{job_id}/running"),
            params={"runner_id": runner_id},
        )
        _raise_for_status(r)
        return JobOut.from_dict(r.json())

    def nack(self, job_id: str, runner_id: str, *, reason: str = "") -> JobOut:
        params: dict[str, Any] = {"runner_id": runner_id}
        note = (reason or "").strip()
        if note:
            params["reason"] = note
        r = self._client.post(self._url(f"/jobs/{job_id}/nack"), params=params)
        _raise_for_status(r)
        return JobOut.from_dict(r.json())

    def complete(self, job_id: str, runner_id: str, body: JobResultIn) -> JobOut:
        r = self._client.post(
            self._url(f"/jobs/{job_id}/complete"),
            params={"runner_id": runner_id},
            json=body.to_dict(),
        )
        _raise_for_status(r)
        return JobOut.from_dict(r.json())

    def upload_report(self, job_id: str, runner_id: str, html_path: str) -> dict[str, Any]:
        p = Path(html_path)
        files = {"file": (p.name or "report.html", p.read_bytes(), "text/html")}
        r = self._client.post(
            self._url(f"/jobs/{job_id}/report"),
            params={"runner_id": runner_id},
            files=files,
        )
        _raise_for_status(r)
        return r.json()

    def upload_result_json(self, job_id: str, runner_id: str, json_path: str) -> dict[str, Any]:
        p = Path(json_path)
        files = {"file": ("result.json", p.read_bytes(), "application/json")}
        r = self._client.post(
            self._url(f"/jobs/{job_id}/report"),
            params={"runner_id": runner_id},
            files=files,
        )
        _raise_for_status(r)
        return r.json()

    def upload_evidence_zip(self, job_id: str, runner_id: str, zip_path: str) -> dict[str, Any]:
        """上传 D3 evidence.zip（内含 reports/evidence/**）。"""
        p = Path(zip_path)
        files = {"file": ("evidence.zip", p.read_bytes(), "application/zip")}
        r = self._client.post(
            self._url(f"/jobs/{job_id}/report"),
            params={"runner_id": runner_id},
            files=files,
        )
        _raise_for_status(r)
        return r.json()

    def download_artifact(self, artifact_id: str, dest_dir: str) -> str:
        import zipfile
        r = self._client.get(self._url(f"/artifacts/{artifact_id}/download"))
        _raise_for_status(r)
        root = Path(dest_dir)
        root.mkdir(parents=True, exist_ok=True)
        zip_path = root / "project.zip"
        zip_path.write_bytes(r.content)
        extract = root / "project"
        extract.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            safe_extractall(zf, extract)
        children = [p for p in extract.iterdir() if not p.name.startswith(".")]
        if len(children) == 1 and children[0].is_dir():
            return str(children[0].resolve())
        return str(extract.resolve())

    def download_app_build(self, build_id: str, dest_dir: str) -> str:
        from urllib.parse import unquote

        r = self._client.get(self._url(f"/app-builds/{build_id}/download"))
        _raise_for_status(r)
        root = Path(dest_dir)
        root.mkdir(parents=True, exist_ok=True)
        name = "app.bin"
        cd = r.headers.get("content-disposition") or ""
        if "filename=" in cd:
            part = cd.split("filename=", 1)[1].strip().strip("\"'")
            if part:
                name = Path(unquote(part)).name or name
        path = root / name
        path.write_bytes(r.content)
        return str(path.resolve())


def devices_to_payload(devices: list[DeviceInfo]) -> list[dict[str, Any]]:
    return [d.to_dict() for d in devices]
