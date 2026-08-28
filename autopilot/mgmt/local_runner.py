"""本机 TestRunner 子进程：把 USB 设备心跳上报到 Platform TR 池。

通过 ``python -m <module>`` 拉起 Agent（HTTP 客户端），
不 import Platform 服务端鉴权实现。

模块名默认 ``autopilot.runner``，可用环境变量 ``MC_RUNNER_MODULE`` 覆盖。
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Optional

DEFAULT_RUNNER_MODULE = "autopilot.runner"


def runner_module_name() -> str:
    """Runner 可执行模块（``python -m`` 目标）。"""
    return (os.environ.get("MC_RUNNER_MODULE") or DEFAULT_RUNNER_MODULE).strip() or DEFAULT_RUNNER_MODULE


def default_local_runner_id() -> str:
    """IDE 本机 Runner ID：加 ``-ide-`` 前缀，避免与 CLI 默认 ID 同构抢注册。"""
    host = socket.gethostname() or "host"
    return f"{host}-ide-{uuid.getnode():x}"


class LocalRunnerProcess:
    """IDE 托管的本机 Runner 生命周期。"""

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self.runner_id: str = ""
        self.server: str = ""
        self._log_path: Optional[Path] = None

    @property
    def running(self) -> bool:
        proc = self._proc
        if proc is None:
            return False
        if proc.poll() is not None:
            # 进程已退出：清句柄，避免 Start 一直灰掉
            self._proc = None
            return False
        return True

    @property
    def last_log_path(self) -> Optional[Path]:
        return self._log_path

    def start(
        self,
        server: str,
        token: str,
        *,
        runner_id: str | None = None,
        poll_interval: float = 3.0,
    ) -> str:
        if self.running:
            raise RuntimeError("本机 Runner 已在运行")
        url = (server or "").strip().rstrip("/")
        if not url:
            raise ValueError("未配置管理台服务器 URL")
        tok = (token or "").strip()
        if not tok:
            raise ValueError(
                "未配置 API Token（连接设置中的 API Token；禁止空值回落默认弱令牌）"
            )

        mod = runner_module_name()
        try:
            __import__(mod)
        except ImportError as exc:
            raise RuntimeError(
                f"未找到 Runner 模块 {mod!r}。默认入口为 autopilot.runner（本仓）。"
                f"若使用 Platform Agent：先 pip install -e \".[runner]\"（Autopilot-Platform），"
                f"再设 MC_RUNNER_MODULE=autopilot_platform.runner。"
                f"原始错误: {exc}"
            ) from exc

        rid = (runner_id or "").strip() or default_local_runner_id()
        cmd = [
            sys.executable,
            "-m",
            mod,
            "--server",
            url,
            "--token-env",
            "MC_API_TOKEN",
            "--runner-id",
            rid,
            "--poll-interval",
            str(poll_interval),
        ]
        log_dir = Path(tempfile.gettempdir()) / "autopilot_local_runner"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = log_dir / f"{rid}.log"
        log_f = open(self._log_path, "ab", buffering=0)
        kwargs: dict = {
            "stdout": log_f,
            "stderr": subprocess.STDOUT,
            "stdin": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            kwargs["creationflags"] = flags
        else:
            kwargs["start_new_session"] = True

        env = os.environ.copy()
        env["MC_SERVER"] = url
        env["MC_API_TOKEN"] = tok
        env["MC_RUNNER_ID"] = rid
        try:
            self._proc = subprocess.Popen(cmd, env=env, **kwargs)
        finally:
            # 子进程已继承 fd；父进程可关闭写入端句柄引用计数
            try:
                log_f.close()
            except OSError:
                pass
        self.runner_id = rid
        self.server = url
        return rid

    def stop(self, *, timeout: float = 5.0) -> bool:
        """停止本机 Runner；未在运行返回 False。"""
        proc = self._proc
        if proc is None:
            return False
        if proc.poll() is not None:
            self._proc = None
            return False
        try:
            proc.terminate()
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2.0)
        finally:
            self._proc = None
        return True
