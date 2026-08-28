"""Runner 主循环。"""

from __future__ import annotations

import os
import socket
import threading
import time
import uuid
from dataclasses import replace as dc_replace
from typing import Optional

from .client import PlatformClient
from .contract import (
    DEFAULT_API_TOKEN,
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
from .execute import execute_job
from .instance_lock import RunnerInstanceBusyError, RunnerInstanceLock
from .job_slots import JobSlotTracker

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
        self._slots = JobSlotTracker()
        self._cancel: dict[str, threading.Event] = {}
        self._job_threads: dict[str, threading.Thread] = {}
        self._hb_guard = threading.Lock()
        self._hb_stop = threading.Event()
        self._hb_thread: Optional[threading.Thread] = None
        self._hb_client: Optional[PlatformClient] = None
        self._device_policy = load_device_policy(self.runner_id)

    def _heartbeat_once(self, client: PlatformClient) -> None:
        self._device_policy = sync_exclude_udids(self.runner_id, self._device_policy)
        inventory = list_local_devices()
        devices = self._device_policy.filter(inventory)
        caps, host_backends = probe_host_capabilities()
        body = HeartbeatIn(
            runner_id=self.runner_id,
            devices=devices,
            inventory=inventory,
            policy_revision=self._device_policy.revision,
            capabilities=caps,
            host_backends=host_backends,
        )
        try:
            response = client.heartbeat(body)
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
                self._device_policy = update_device_policy(
                    self.runner_id, self._device_policy, response
                )
                return
            raise

    def _poll_cancel(self, client: PlatformClient) -> None:
        items = list(self._cancel.items())
        if not items:
            return
        errs = _http_error_types()
        for jid, ev in items:
            if ev is None or ev.is_set():
                continue
            try:
                job = client.get_job(jid)
            except errs as exc:
                print(f"[runner] cancel-poll: {exc}", flush=True)
                continue
            st = job.status
            val = st.value if isinstance(st, JobStatus) else str(st)
            if val == JobStatus.CANCELLED.value:
                ev.set()
                print(f"[runner] job {jid} cancelled remotely; signaling stop", flush=True)

    def _ensure_exec_heartbeat(self, client: PlatformClient) -> None:
        with self._hb_guard:
            if self._hb_thread is not None and self._hb_thread.is_alive():
                return
            self._hb_client = client
            self._hb_stop.clear()

            def _loop() -> None:
                hb_client = self._hb_client
                while not self._hb_stop.wait(self.poll_interval):
                    if hb_client is None:
                        break
                    try:
                        self._heartbeat_once(hb_client)
                        self._poll_cancel(hb_client)
                    except _http_error_types() as exc:
                        print(f"[runner] exec-heartbeat: {exc}", flush=True)

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
        self, client: PlatformClient, job_id: str, error: str, *, log: str = ""
    ) -> None:
        errs = _http_error_types()
        try:
            client.complete(
                job_id,
                self.runner_id,
                JobResultIn(status=JobStatus.FAILED, error=error, log=log or f"[runner] {error}\n"),
            )
        except errs as exc:
            print(f"[runner] complete failed for {job_id}: {exc}", flush=True)

    def _nack_claimed(self, client: PlatformClient, job_id: str, reason: str) -> None:
        errs = _http_error_types()
        try:
            client.nack(job_id, self.runner_id, reason=reason)
        except errs as exc:
            print(f"[runner] nack failed for {job_id}: {exc}", flush=True)

    def _run_claimed_job(self, job, cancel_ev: threading.Event) -> None:
        errs = _http_error_types()
        with PlatformClient(self.server, self.token) as client:
            try:
                try:
                    client.mark_running(job.id, self.runner_id)
                except (*errs, PermissionError) as exc:
                    print(f"[runner] skip job {job.id}: {exc}", flush=True)
                    self._fail_claimed(client, job.id, f"标记运行失败：{exc}")
                    return
                t_exec = time.monotonic()
                result = execute_job(job, client, cancel_event=cancel_ev)
                print(
                    f"[runner] execute job={job.id} status={result.status} "
                    f"({time.monotonic() - t_exec:.2f}s)",
                    flush=True,
                )
                if cancel_ev.is_set() and not (result.error or "").strip():
                    result = result.with_error("任务执行中被取消")
                report_path = (
                    (result.report.report_path if result.report else "") or ""
                )
                report_uploaded = False
                try:
                    if not cancel_ev.is_set():
                        if report_path and os.path.isfile(report_path):
                            t_up = time.monotonic()
                            client.upload_report(job.id, self.runner_id, report_path)
                            print(
                                f"[runner] upload report job={job.id} "
                                f"({time.monotonic() - t_up:.2f}s)",
                                flush=True,
                            )
                            result_json = os.path.join(
                                os.path.dirname(os.path.abspath(report_path)), "result.json"
                            )
                            if os.path.isfile(result_json):
                                client.upload_result_json(job.id, self.runner_id, result_json)
                                print(f"[runner] upload result.json job={job.id}", flush=True)
                            evidence_zip = os.path.join(
                                os.path.dirname(os.path.abspath(report_path)), "evidence.zip"
                            )
                            if os.path.isfile(evidence_zip):
                                client.upload_evidence_zip(
                                    job.id, self.runner_id, evidence_zip
                                )
                                print(
                                    f"[runner] upload evidence.zip job={job.id}", flush=True
                                )
                            report_uploaded = True
                except errs as exc:
                    print(
                        f"[runner] report upload failed; local files retained: {exc}",
                        flush=True,
                    )
                if report_path and os.path.isfile(report_path) and not report_uploaded:
                    note = "报告或 result.json 未能上传到平台（本地文件已保留）"
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
                t_done = time.monotonic()
                client.complete(job.id, self.runner_id, result)
                print(
                    f"[runner] complete job={job.id} ({time.monotonic() - t_done:.2f}s)",
                    flush=True,
                )
                if report_uploaded:
                    import shutil

                    parent = os.path.dirname(os.path.abspath(report_path))
                    base = os.path.basename(parent)
                    if base.startswith("mc-report-") and os.path.isdir(parent):
                        shutil.rmtree(parent, ignore_errors=True)
            finally:
                self._cancel.pop(job.id, None)
                self._slots.release(job.id)
                self._maybe_stop_exec_heartbeat()

    def run_once(self, client: PlatformClient) -> bool:
        self._heartbeat_once(client)
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
            self._nack_claimed(client, job.id, f"本机设备槽位冲突：{reason}")
            return True
        cancel_ev = threading.Event()
        self._cancel[job.id] = cancel_ev
        self._ensure_exec_heartbeat(client)
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
                capabilities=caps,
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
