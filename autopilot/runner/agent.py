"""Runner 主循环。"""

from __future__ import annotations

import json
import os
import shutil
import socket
import tempfile
import threading
import time
import uuid
from dataclasses import replace as dc_replace
from pathlib import Path
from typing import Optional

from .client import PlatformClient
from .contract import (
    DEFAULT_API_TOKEN,
    JOB_CLAIM_GENERATION_CAPABILITY,
    JOB_LEASE_HEARTBEAT_CAPABILITY,
    HeartbeatIn,
    JobResultIn,
    JobStatus,
    RunnerRegister,
)
from .devices import list_local_devices, probe_host_capabilities
from .device_policy import (
    load_device_policy,
    sync_exclude_udids,
    update_device_policy,
)
from .execute import DEVICE_OFFLINE_ERROR, execute_job
from .instance_lock import RunnerInstanceBusyError, RunnerInstanceLock
from .job_slots import JobSlotTracker
from .pending_results import result_directory, stage_result

_RUNNER_PROTOCOLS = (JOB_CLAIM_GENERATION_CAPABILITY, JOB_LEASE_HEARTBEAT_CAPABILITY)
_RESULT_REJECTION_CODES = (400, 403, 404, 409, 422)

_HTTP_ERRS: tuple[type[BaseException], ...] = (
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    AttributeError,
)


def _http_error_types() -> tuple[type[BaseException], ...]:
    try:
        import httpx

        return *_HTTP_ERRS, httpx.HTTPError
    except ImportError:
        return _HTTP_ERRS


def _package_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:
        return "0.1.0"
    try:
        return version("autopilot")
    except PackageNotFoundError:
        return "0.1.0"


def default_runner_id() -> str:
    host = socket.gethostname() or "host"
    return f"{host}-{uuid.getnode():x}"


def _upload_report_bundle(
    client: PlatformClient, job_id: str, runner_id: str, report_path: str, *, claimed_at: str
) -> bool:
    report = Path(report_path)
    if not report.is_file():
        return False
    uploads = (
        (report, client.upload_report),
        (report.with_name("result.json"), client.upload_result_json),
        (report.with_name("evidence.zip"), client.upload_evidence_zip),
    )
    claim = {"claimed_at": claimed_at} if claimed_at else {}
    errors = _http_error_types()
    for path, upload in uploads:
        if not path.is_file():
            continue
        for attempt in range(1, 4):
            try:
                upload(job_id, runner_id, str(path), **claim)
                break
            except errors as exc:
                print(f"[runner] {path.name} upload failed attempt={attempt}: {exc}", flush=True)
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if attempt == 3 or status in _RESULT_REJECTION_CODES:
                    return False
                time.sleep(0.35 * attempt)
    return True


class RunnerAgent:
    def __init__(
        self,
        server: str,
        token: str = DEFAULT_API_TOKEN,
        *,
        runner_id: Optional[str] = None,
        poll_interval: float = 3.0,
        hostname: Optional[str] = None,
    ) -> None:
        self.server = server
        self.token = token
        self.runner_id = runner_id or default_runner_id()
        self.poll_interval = max(0.5, float(poll_interval))
        self.hostname = hostname or socket.gethostname()
        self._result_directory = result_directory(self.server, self.runner_id)
        self._slots = JobSlotTracker()
        self._cancel: dict[str, threading.Event] = {}
        self._claim_generations: dict[str, str] = {}
        self._job_udids: dict[str, list[str]] = {}
        self._offline_jobs: set[str] = set()
        self._job_threads: dict[str, threading.Thread] = {}
        self._hb_guard = threading.Lock()
        self._state_lock = threading.RLock()
        self._hb_stop = threading.Event()
        self._hb_thread: Optional[threading.Thread] = None
        self._hb_client: Optional[PlatformClient] = None
        self._device_policy = load_device_policy(self.runner_id)

    def _heartbeat_once(self, client: PlatformClient) -> None:
        with self._state_lock:
            policy = sync_exclude_udids(self.runner_id, self._device_policy)
            self._device_policy = policy
        inventory = list_local_devices()
        devices = policy.filter(inventory)
        caps, host_backends = probe_host_capabilities()
        body = HeartbeatIn(
            runner_id=self.runner_id,
            devices=devices,
            inventory=inventory,
            policy_revision=policy.revision,
            capabilities=[*caps, *_RUNNER_PROTOCOLS],
            host_backends=host_backends,
            active_job_ids=self._slots.job_ids(),
        )
        try:
            response = client.heartbeat(body)
            with self._state_lock:
                self._device_policy = update_device_policy(
                    self.runner_id, self._device_policy, response
                )
        except Exception as exc:
            # 兜底：未注册 / 404 时补注册再心跳一次
            status = getattr(getattr(exc, "response", None), "status_code", None)
            msg = str(exc).lower()
            if status == 404 or "not registered" in msg or "404" in msg:
                self.register(client)
                response = client.heartbeat(body)
                with self._state_lock:
                    self._device_policy = update_device_policy(
                        self.runner_id, self._device_policy, response
                    )
                return
            raise

    def _signal_missing_devices(self) -> None:
        present = {d.udid for d in list_local_devices()}
        with self._state_lock:
            items = [(jid, ev, list(self._job_udids.get(jid, []))) for jid, ev in self._cancel.items()]
        for jid, ev, udids in items:
            if ev.is_set():
                continue
            missing = [uid for uid in udids if uid not in present]
            if not missing:
                continue
            self._offline_jobs.add(jid)
            ev.set()
            print(f"[runner] job {jid} device offline: {','.join(missing)}", flush=True)

    def _poll_cancel(self, client: PlatformClient) -> None:
        items = list(self._cancel.items())
        if not items:
            return
        errs = _http_error_types()
        for jid, ev in items:
            if ev is None or ev.is_set():
                continue
            generation = self._claim_generations.get(jid)
            try:
                job = client.get_job(jid)
            except errs as exc:
                print(f"[runner] cancel-poll: {exc}", flush=True)
                continue
            if self._cancel.get(jid) is not ev:
                continue
            st = job.status
            val = st.value if isinstance(st, JobStatus) else str(st)
            if val == JobStatus.CANCELLED.value:
                ev.set()
                print(f"[runner] job {jid} cancelled remotely; signaling stop", flush=True)
            elif generation and (
                job.runner_id != self.runner_id
                or job.claimed_at != generation
                or val not in (JobStatus.CLAIMED.value, JobStatus.RUNNING.value)
            ):
                ev.set()
                print(f"[runner] job {jid} claim no longer current; signaling stop", flush=True)

    def _ensure_exec_heartbeat(self) -> None:
        with self._hb_guard:
            if self._hb_thread is not None and self._hb_thread.is_alive():
                return
            # 心跳线程使用独立的 PlatformClient（底层 httpx.Client 非线程安全，禁止跨线程共享）
            hb_client = PlatformClient(self.server, self.token)
            self._hb_client = hb_client
            self._hb_stop.clear()

            def _loop() -> None:
                try:
                    while not self._hb_stop.wait(self.poll_interval):
                        try:
                            self._heartbeat_once(hb_client)
                            self._signal_missing_devices()
                            self._poll_cancel(hb_client)
                        except _http_error_types() as exc:
                            print(f"[runner] exec-heartbeat: {exc}", flush=True)
                finally:
                    try:
                        hb_client.close()
                    except (OSError, RuntimeError):
                        pass

            self._hb_thread = threading.Thread(
                target=_loop, name=f"runner-hb-{self.runner_id}", daemon=True
            )
            self._hb_thread.start()

    def _maybe_stop_exec_heartbeat(self) -> None:
        with self._hb_guard:
            if self._slots.has_any():
                return
            self._hb_stop.set()
            t = self._hb_thread
            self._hb_thread = None
            self._hb_client = None
        if t is not None and t.is_alive():
            t.join(timeout=2.0)

    def _reap_job_threads(self) -> None:
        done = [jid for jid, th in list(self._job_threads.items()) if not th.is_alive()]
        for jid in done:
            th = self._job_threads.pop(jid, None)
            if th is not None:
                th.join(timeout=0.1)

    def _fail_claimed(
        self, client: PlatformClient, job_id: str, error: str, *, claimed_at: str = ""
    ) -> None:
        errs = _http_error_types()
        try:
            self._submit_result(
                client,
                job_id,
                JobResultIn(status=JobStatus.FAILED, error=error, log=f"[runner] {error}\n"),
                claimed_at=claimed_at,
            )
        except errs as exc:
            print(f"[runner] complete failed for {job_id}: {exc}", flush=True)

    def _nack_claimed(
        self, client: PlatformClient, job_id: str, reason: str, *, claimed_at: str = ""
    ) -> None:
        errs = _http_error_types()
        try:
            claim = {"claimed_at": claimed_at} if claimed_at else {}
            client.nack(job_id, self.runner_id, reason=reason, **claim)
        except errs as exc:
            print(f"[runner] nack failed for {job_id}: {exc}", flush=True)

    def _submit_result(
        self, client: PlatformClient, job_id: str, result: JobResultIn, *,
        claimed_at: str, cleanup_report: str = "",
    ) -> None:
        try:
            pending = stage_result(self._result_directory, job_id, claimed_at, {
                "job_id": job_id,
                "claimed_at": claimed_at,
                "result": result.to_dict(),
                "cleanup_report": cleanup_report,
            })
        except OSError as exc:
            print(f"[runner] could not persist result for {job_id}: {exc}", flush=True)
            claim = {"claimed_at": claimed_at} if claimed_at else {}
            client.complete(job_id, self.runner_id, result, **claim)
            self._cleanup_uploaded_report(cleanup_report)
            return
        self._deliver_result(client, pending, result, job_id, claimed_at, cleanup_report)

    @staticmethod
    def _cleanup_uploaded_report(report_path: str) -> None:
        if report_path:
            parent = Path(report_path).resolve().parent
            if parent.parent == Path(tempfile.gettempdir()).resolve() and parent.name.startswith("mc-report-"):
                shutil.rmtree(parent, ignore_errors=True)

    def _deliver_result(
        self, client: PlatformClient, path: Path, result: JobResultIn, job_id: str,
        claimed_at: str, cleanup_report: str,
    ) -> None:
        claim = {"claimed_at": claimed_at} if claimed_at else {}
        try:
            client.complete(job_id, self.runner_id, result, **claim)
        except _http_error_types() as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in _RESULT_REJECTION_CODES:
                path.replace(path.with_suffix(".rejected"))
                print(f"[runner] result rejected for {job_id}: {exc}", flush=True)
            else:
                print(f"[runner] result pending for {job_id}: {exc}", flush=True)
            return
        path.unlink(missing_ok=True)
        self._cleanup_uploaded_report(cleanup_report)

    def _retry_pending_results(self, client: PlatformClient) -> None:
        active = set(self._slots.job_ids())
        for path in self._result_directory.glob("*.json"):
            try:
                pending = json.loads(path.read_text(encoding="utf-8"))
                job_id = str(pending["job_id"])
                result = JobResultIn.from_dict(pending["result"])
                claimed_at = str(pending.get("claimed_at") or "")
                cleanup_report = str(pending.get("cleanup_report") or "")
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                print(f"[runner] invalid pending result {path.name}: {exc}", flush=True)
                continue
            if job_id not in active:
                self._deliver_result(client, path, result, job_id, claimed_at, cleanup_report)

    def _run_claimed_job(self, job, cancel_ev: threading.Event) -> None:
        errs = _http_error_types()
        claimed_at = getattr(job, "claimed_at", "")
        claim = {"claimed_at": claimed_at} if claimed_at else {}
        with PlatformClient(self.server, self.token) as client:
            try:
                try:
                    client.mark_running(job.id, self.runner_id, **claim)
                except (*errs, PermissionError) as exc:
                    print(f"[runner] skip job {job.id}: {exc}", flush=True)
                    self._fail_claimed(client, job.id, f"标记运行失败：{exc}", claimed_at=claimed_at)
                    return
                t_exec = time.monotonic()
                try:
                    result = execute_job(job, client, cancel_event=cancel_ev)
                except errs as exc:
                    self._fail_claimed(client, job.id, f"任务执行失败：{exc}", claimed_at=claimed_at)
                    return
                print(
                    f"[runner] execute job={job.id} status={result.status} "
                    f"({time.monotonic() - t_exec:.2f}s)",
                    flush=True,
                )
                status_val = (
                    result.status.value if hasattr(result.status, "value") else str(result.status)
                )
                if job.id in self._offline_jobs and status_val != JobStatus.SUCCEEDED.value:
                    result = result.with_error(DEVICE_OFFLINE_ERROR)
                elif cancel_ev.is_set() and not (result.error or "").strip():
                    result = result.with_error("任务执行中被取消")
                report_path = (
                    (result.report.report_path if result.report else "") or ""
                )
                report_uploaded = False
                try:
                    if report_path and os.path.isfile(report_path):
                        report_uploaded = _upload_report_bundle(
                            client, job.id, self.runner_id, report_path, claimed_at=claimed_at
                        )
                except errs as exc:
                    print(
                        f"[runner] report upload failed; local files retained: {exc}",
                        flush=True,
                    )
                if report_path and not report_uploaded:
                    note = "报告文件未全部上传到平台（本地文件已保留）"
                    err = (result.error or "").strip()
                    merged = f"{err}; {note}" if err else note
                    st_val = result.status.value if hasattr(result.status, "value") else str(result.status)
                    new_status = result.status
                    if st_val != JobStatus.FAILED.value:
                        new_status = JobStatus.FAILED
                    result = dc_replace(
                        result,
                        status=new_status,
                        error=merged,
                        log=(result.log or "") + f"\n[runner] {note}\n",
                    )
                self._submit_result(
                    client, job.id, result, claimed_at=claimed_at,
                    cleanup_report=report_path if report_uploaded else "",
                )
            finally:
                self._cancel.pop(job.id, None)
                self._claim_generations.pop(job.id, None)
                self._job_udids.pop(job.id, None)
                self._offline_jobs.discard(job.id)
                self._slots.release(job.id)
                self._maybe_stop_exec_heartbeat()

    def run_once(self, client: PlatformClient) -> bool:
        self._heartbeat_once(client)
        self._retry_pending_results(client)
        self._reap_job_threads()

        t_claim = time.monotonic()
        wait_sec = 0 if self._slots.has_any() else min(25, max(0, int(self.poll_interval * 8)))
        job = client.claim(self.runner_id, wait_sec=wait_sec)
        if job is None:
            return self._slots.has_any()
        print(
            f"[runner] claim job={job.id} name={job.name!r} "
            f"({time.monotonic() - t_claim:.2f}s)",
            flush=True,
        )
        reason = self._slots.try_reserve(job.id, list(getattr(job, "device_udids", None) or []))
        if reason:
            print(f"[runner] reject job={job.id}: {reason}", flush=True)
            self._nack_claimed(
                client, job.id, f"本机设备槽位冲突：{reason}",
                claimed_at=getattr(job, "claimed_at", ""),
            )
            return True
        cancel_ev = threading.Event()
        with self._state_lock:
            self._claim_generations[job.id] = getattr(job, "claimed_at", "")
            self._cancel[job.id] = cancel_ev
            self._job_udids[job.id] = [
                str(u).strip() for u in (getattr(job, "device_udids", None) or []) if str(u).strip()
            ]
        self._ensure_exec_heartbeat()
        th = threading.Thread(
            target=self._run_claimed_job,
            args=(job, cancel_ev),
            name=f"runner-job-{job.id[:8]}",
            daemon=True,
        )
        self._job_threads[job.id] = th
        th.start()
        return True

    def register(self, client: PlatformClient) -> None:
        caps, host_backends = probe_host_capabilities()
        ver = _package_version()
        print(
            f"[runner] register capabilities={caps} host_backends={host_backends} version={ver}",
            flush=True,
        )
        client.register(
            RunnerRegister(
                runner_id=self.runner_id,
                hostname=self.hostname,
                version=ver,
                capabilities=[*caps, *_RUNNER_PROTOCOLS],
                host_backends=host_backends,
            )
        )


def run_forever(
    server: str,
    token: str = DEFAULT_API_TOKEN,
    *,
    runner_id: Optional[str] = None,
    poll_interval: float = 3.0,
    lock_dir: Optional[str] = None,
) -> None:
    agent = RunnerAgent(
        server, token, runner_id=runner_id, poll_interval=poll_interval
    )
    try:
        lock = RunnerInstanceLock(agent.runner_id, lock_dir=lock_dir)
        lock.acquire()
    except RunnerInstanceBusyError as exc:
        print(f"[runner] abort: {exc}", flush=True)
        raise SystemExit(2) from exc
    try:
        with PlatformClient(server, token) as client:
            agent.register(client)
            print(f"[runner] id={agent.runner_id} server={server}", flush=True)
            while True:
                try:
                    did = agent.run_once(client)
                    if not did:
                        time.sleep(min(0.5, agent.poll_interval))
                except KeyboardInterrupt:
                    print("[runner] stopped", flush=True)
                    break
                except Exception as exc:
                    print(f"[runner] error: {exc}", flush=True)
                    time.sleep(agent.poll_interval)
    finally:
        lock.release()
