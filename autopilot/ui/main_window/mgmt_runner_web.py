"""主窗口·管理台本机 Runner / 打开网页（AUD-2026-17 Wave 2）。

混入链：… → MgmtSessionMixin → MgmtRunnerWebMixin → MgmtDeliveryMixin。
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QMessageBox

from autopilot import __version__ as runtime_version

from .mgmt_delivery import MgmtDeliveryMixin
from .mgmt_errors import SESSION_ERRS as _SESSION_ERRS
from ...mgmt import mgmt_error_message
from ...mgmt.local_runner import LocalRunnerProcess
from ...mgmt.web_frontend import resolve_web_frontend_url
from ...runtime import settings

if TYPE_CHECKING:
    from .window import MainWindow
    _Base = MainWindow
else:
    _Base = MgmtDeliveryMixin


class MgmtRunnerWebMixin(_Base):
    """本机 Runner 与打开管理台网页。"""

    def _mgmt_resolve_runner_token_platform_admin(
        self, runner_id: str, org_id: str, project_ids: list[str]
    ) -> str:
        try:
            from ...mgmt import ensure_user_session

            client, _ = ensure_user_session(require=True)
            try:

                client.register_runner(
                    {
                        "runner_id": runner_id,
                        "hostname": os.environ.get("COMPUTERNAME", ""),
                        "version": str(runtime_version),
                        "capabilities": [],
                        "registration_source": "ide",
                    }
                )
                issued = client.issue_scoped_runner_token(
                    runner_id,
                    org_id=org_id,
                    project_ids=list(project_ids or []),
                )
                return str(issued.get("api_token") or "")
            finally:
                client.close()
        except Exception as exc:  # noqa: BLE001
            allow_dev_global = os.environ.get(
                "AUTOPILOT_DEV_RUNNER_GLOBAL_TOKEN", ""
            ).strip().lower() in ("1", "true", "yes")
            if not allow_dev_global:

                QMessageBox.warning(
                    self,
                    "本机 Runner",
                    "无法签发当前组织作用域的独立 Runner Token：\n"
                    f"{mgmt_error_message(exc)}",
                )
                return ""
            token = settings.mc_api_token().strip()
            if not token:
                QMessageBox.warning(
                    self,
                    "本机 Runner",
                    "开发兼容模式需要在「连接设置」中填写非空 API Token；"
                    "已禁止回落默认 dev-mc-token。",
                )
                return ""
            if token == "dev-mc-token":
                self.console.log(
                    "警告：正在使用弱默认 Token dev-mc-token；生产 Platform 应拒绝",
                    "管理台",
                    "WARNING",
                )
            self.console.log(
                "开发兼容模式：使用连接设置中的 Runner Token；"
                "生产 Platform 将拒绝未拆分的弱令牌",
                "管理台",
                "WARNING",
            )
            return token

    def _mgmt_resolve_runner_token_operator(
        self, runner_id: str
    ) -> str:
        token = settings.mc_api_token().strip()
        if not token:
            QMessageBox.information(
                self,
                "本机 Runner",
                "当前账号为 Operator，不能自动签发 Runner Token。\n\n"
                "请让平台管理员在 Web「设备与执行 → 执行节点」签发 Token，"
                "并填入「管理台 → 连接设置 → API Token」。",
            )
            return ""
        try:
            from ...mgmt import ensure_user_session

            client, _ = ensure_user_session(require=True)
            try:

                client.register_runner(
                    {
                        "runner_id": runner_id,
                        "hostname": os.environ.get("COMPUTERNAME", ""),
                        "version": str(runtime_version),
                        "capabilities": [],
                        "registration_source": "ide",
                    }
                )
            finally:
                client.close()
        except Exception as exc:  # noqa: BLE001

            QMessageBox.warning(
                self,
                "本机 Runner",
                f"注册 Runner 失败：{mgmt_error_message(exc)}",
            )
            return ""
        self.console.log(
            "Operator 模式：使用连接设置中的预配 Runner Token",
            "管理台",
        )
        return token

    def _mgmt_local_runner(self):

        proc = getattr(self, "_local_runner", None)
        if proc is None:
            proc = LocalRunnerProcess()
            self._local_runner = proc
        return proc

    def _mgmt_confirm_local_runner_vs_inspect(self, runner_id: str) -> bool:
        """已绑检视/镜像真机时确认；多机默认从上报摘除该 UDID。"""
        from ...mgmt.local_runner_guard import (
            ACTION_CANCEL,
            ACTION_EXCLUDE,
            bound_mobile_udid,
            collect_local_udids,
            inspect_kind,
            start_runner_prompt,
        )
        from ...runner.device_policy import add_exclude_udids
        from ..confirm import ask_local_runner_prompt

        udid = bound_mobile_udid(
            platform=getattr(self, "_inspect_platform", "") or "",
            udid=getattr(self, "_inspect_udid", "") or "",
        )
        mirror = getattr(self, "mirror", None)
        kind = inspect_kind(
            inspect_ctx=getattr(self, "_inspect_ctx", None),
            mirror_active=bool(
                mirror is not None and getattr(mirror, "active", lambda: False)()
            ),
            inspect_chosen=bool(getattr(self, "_inspect_chosen", False)),
            udid=udid,
        )
        if not kind or not udid:
            return True
        android, ios = getattr(self, "_devices", ([], []))
        try:
            from ...mgmt.local_devices import list_local_devices

            extra = list_local_devices()
        except (ImportError, OSError, RuntimeError, TypeError, ValueError):
            extra = []
        prompt = start_runner_prompt(
            inspect_udid=udid,
            inspect_kind_label=kind,
            local_udids=collect_local_udids(android, ios, extra),
        )
        if prompt is None:
            return True
        action = ask_local_runner_prompt(self, prompt)
        if action == ACTION_CANCEL:
            return False
        if action == ACTION_EXCLUDE:
            add_exclude_udids(runner_id, {udid})
            self.console.log(
                f"已从本机 Runner 上报摘除 {udid}，避免与{kind}抢会话",
                "管理台",
            )
        return True

    def mgmt_start_local_runner(self) -> None:
        """启动本机 Runner：本机 USB 设备心跳进 TR 池（与 IDE 本地池隔离）。"""
        server = settings.mc_server_url()
        org_id = (settings.mc_org_id() or "").strip()
        project_id = (settings.mc_project_id() or "").strip()
        project_ids = [project_id] if project_id else []
        if self._mgmt_is_platform_admin() and not org_id and not project_ids:
            QMessageBox.information(
                self,
                "本机 Runner",
                "请先在「连接设置」填写组织 ID，或选择默认项目空间，"
                "以便签发组织（或项目）作用域 Runner Token。",
            )
            return
        from ...mgmt.local_runner import default_local_runner_id

        runner_id = default_local_runner_id()
        if self._mgmt_is_platform_admin():
            token = self._mgmt_resolve_runner_token_platform_admin(
                runner_id, org_id, project_ids
            )
        else:
            token = self._mgmt_resolve_runner_token_operator(runner_id)
        if not token:
            return
        if not self._mgmt_confirm_local_runner_vs_inspect(runner_id):
            return
        proc = self._mgmt_local_runner()
        try:
            rid = proc.start(server, token, runner_id=runner_id)
        except (RuntimeError, ValueError, OSError) as exc:

            QMessageBox.warning(self, "本机 Runner", mgmt_error_message(exc))
            self._mgmt_refresh_session_ui()
            return
        try:
            from ...mgmt.local_devices import list_local_devices  # 延迟：仅本机 Runner 探活

            n_dev = len(list_local_devices())
        except (ImportError, OSError, RuntimeError, TypeError, ValueError):
            n_dev = 0
        if n_dev:
            self.console.log(
                f"已启动本机 Runner：{rid} → {server}；当前探测到 {n_dev} 台设备，将心跳上报 TR 池",
                "管理台",
            )
        else:
            self.console.log(
                f"已启动本机 Runner：{rid} → {server}；当前无 USB 设备"
                "（节点仍会心跳在线，插上并授权后下一拍心跳才会出现在「设备」页）",
                "管理台",
                "WARNING",
            )
        self._mgmt_refresh_session_ui()

    def mgmt_stop_local_runner(self) -> None:
        proc = getattr(self, "_local_runner", None)
        if proc is None or not proc.running:
            self._mgmt_refresh_session_ui()
            return
        rid = proc.runner_id or "本机"
        proc.stop()
        self.console.log(f"已停止本机 Runner：{rid}", "管理台")
        self._mgmt_refresh_session_ui()

    def mgmt_stop_local_runner_quiet(self) -> None:
        """关窗时静默停止，避免弹框。"""
        proc = getattr(self, "_local_runner", None)
        if proc is not None:
            proc.stop()

    @staticmethod
    def _mgmt_web_base_url() -> str:
        """打开管理台前端：与 ``start_dev`` / 浏览器同一套（Vite 优先）。"""
        configured = ""
        if hasattr(settings, "mc_web_url"):
            configured = (settings.mc_web_url() or "").strip()
        return resolve_web_frontend_url(
            api_url=settings.mc_server_url() or "http://127.0.0.1:8000",
            configured_web=configured,
        )

    def mgmt_open_web(self) -> None:
        """打开管理台网页：用一次性短码交接登录，不把 JWT 写进地址栏。"""

        if not self._mgmt_require_user_session(purpose="打开管理台网页"):
            return
        base = self._mgmt_web_base_url()
        dest = base
        try:
            from ...mgmt import ensure_user_session

            client, _jwt = ensure_user_session(require=True)
            try:
                code = client.create_ide_handoff()
            finally:
                client.close()
            self._mgmt_refresh_session_ui()
            if code:
                dest = f"{base}/#{urlencode({'ide': '1', 'code': code})}"
        except _SESSION_ERRS as exc:

            ans = QMessageBox.question(
                self,
                "打开管理台",
                f"无法刷新登录会话（{mgmt_error_message(exc)}）。\n\n"
                "将打开未登录页面，需在浏览器中重新登录。是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
            dest = base
        try:
            opened = QDesktopServices.openUrl(QUrl(dest))
        except OSError as exc:

            QMessageBox.warning(self, "打开管理台", mgmt_error_message(exc))
            return
        if not opened:
            QMessageBox.warning(
                self,
                "打开管理台",
                f"系统未能打开浏览器。\n请手动访问：\n{base}",
            )
            return
        if hasattr(self, "console") and self.console is not None:
            self.console.log(f"已打开管理台：{base}", "管理台")
