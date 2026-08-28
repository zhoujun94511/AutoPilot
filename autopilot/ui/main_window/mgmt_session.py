"""主窗口·管理台登录与会话 UI（AUD-2026-17 Wave 2）。

混入链：MainWindow → MgmtMixin → MgmtSessionMixin → MgmtRunnerWebMixin → …
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from PyQt6.QtCore import QEventLoop
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from ..actions import ACTIONS, action_allowed_for_role
from ..mgmt_http_worker import MgmtHttpWorker
from ..mgmt_role import is_platform_admin_role
from .mgmt_errors import SESSION_ERRS as _SESSION_ERRS
from .mgmt_runner_web import MgmtRunnerWebMixin
from ...mgmt import (
    ensure_user_session,
    login_and_persist,
    logout_and_clear,
    mgmt_error_message,
)
from ...runtime import settings

# 上传/入队等写入：必须登录且已绑定项目。打开管理台网页不在此列。
_MGMT_WRITE_ACTION_IDS = (
    "mgmt.upload",
    "mgmt.upload_app",
    "mgmt.submit",
    "mgmt.enqueue_approved",
    "mgmt.import_logical",
)


def mgmt_write_enabled(*, logged_in: bool, has_project: bool) -> bool:
    return bool(logged_in and has_project)


def mgmt_open_web_enabled(*, logged_in: bool) -> bool:
    """打开管理台只需已登录；不要求绑定项目。"""
    return bool(logged_in)

if TYPE_CHECKING:
    from .window import MainWindow
    _Base = MainWindow
else:
    _Base = MgmtRunnerWebMixin


class MgmtSessionMixin(_Base):
    """登录门禁、会话校验与状态栏/菜单刷新。"""

    # 类属性声明，避免「仅在方法内赋值」的实例特性告警（MainWindow.__init__ 也会置 None）
    _mgmt_http_worker = None

    def ensure_ide_login(self, *, force_dialog: bool = False) -> bool:
        """IDE 使用前门禁。成功返回 True；取消登录返回 False（调用方应退出）。"""

        # 单测 / 离屏构建主窗口不走 GUI 门禁；正式 run() 默认必须登录
        if os.environ.get("AUTOPILOT_SKIP_LOGIN", "").strip() in ("1", "true", "yes"):
            return True
        if (
            not force_dialog
            and os.environ.get("QT_QPA_PLATFORM", "").strip().lower() == "offscreen"
        ):
            return True

        if not force_dialog and settings.mc_is_logged_in():
            try:
                client, jwt = ensure_user_session(require=True)
                try:
                    if jwt:
                        client.me()
                        self._mgmt_refresh_session_ui()
                        return True
                finally:
                    client.close()
            except _SESSION_ERRS:
                settings.clear_mc_session()

        from ..widgets.mgmt_login_gate_dialog import MgmtLoginGateDialog  # 延迟：仅登录门禁弹窗

        while True:
            dlg = MgmtLoginGateDialog(self)
            code = dlg.exec()
            if code == QDialog.DialogCode.Accepted and dlg.logged_in:
                user = settings.mc_username()
                role = settings.mc_user_role()
                pid = settings.mc_project_id()
                if hasattr(self, "console"):
                    suffix = f"（{role}）" if role else ""
                    if pid:
                        self.console.log(f"已登录：{user}{suffix} · 项目 {pid}", "管理台")
                    else:
                        self.console.log(
                            f"已登录：{user}{suffix} · 未绑定项目空间"
                            "（本地可用；上传/投递需管理员将你加入项目）",
                            "管理台",
                        )
                self._mgmt_refresh_session_ui()
                return True
            # 取消 = 不使用 IDE
            return False

    def mgmt_connect_settings(self) -> None:
        from ..widgets.mgmt_connect_dialog import MgmtConnectDialog  # 延迟：仅连接设置弹窗

        prev_server = settings.mc_server_url()
        prev_token = settings.mc_api_token()
        dlg = MgmtConnectDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        # 连接设置会清 JWT：必须重新登录或回门禁，禁止主界面滞留未登录态
        if dlg.login_after_save:
            if not self.mgmt_login(quiet_if_fail=False, announce=True):
                if not self.ensure_ide_login(force_dialog=True):
                    self._mgmt_quit_app()
        else:
            if not self.ensure_ide_login(force_dialog=True):
                self._mgmt_quit_app()
        self._mgmt_refresh_session_ui()
        proc = getattr(self, "_local_runner", None)
        conn_changed = (
            settings.mc_server_url() != prev_server
            or settings.mc_api_token() != prev_token
        )
        if proc is not None and proc.running and conn_changed:
            ans = QMessageBox.question(
                self,
                "本机 Runner",
                "服务器或 API Token 已变更。旧 Runner 仍使用旧连接参数。\n\n"
                "是否立即停止本机 Runner？（可之后再重新启动）",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if ans == QMessageBox.StandardButton.Yes:
                self.mgmt_stop_local_runner()

    def mgmt_login(self, *, quiet_if_fail: bool = False, announce: bool = True) -> bool:
        """菜单「登录」：POST /api/v1/auth/login 刷新会话（后台 HTTP，不堵 UI）。"""

        if not (settings.mc_username() and settings.mc_password()):
            return self.ensure_ide_login(force_dialog=True)

        settings.clear_mc_session()
        self._mgmt_refresh_session_ui()

        def work():
            return login_and_persist()

        worker = MgmtHttpWorker(work, self)
        self._mgmt_http_worker = worker
        loop = QEventLoop(self)
        box: dict = {}

        def on_done(payload) -> None:
            box["out"] = payload
            loop.quit()

        # noinspection PyUnresolvedReferences
        worker.done.connect(on_done)
        worker.start()
        loop.exec()
        worker.wait(2000)

        out = box.get("out")
        if isinstance(out, Exception):
            if not quiet_if_fail:

                QMessageBox.warning(self, "登录", mgmt_error_message(out))
            self._mgmt_refresh_session_ui()
            return False
        try:
            u = out.get("user") if isinstance(out, dict) and isinstance(out.get("user"), dict) else {}
            user = u.get("username") or settings.mc_username()
            role = u.get("role") or settings.mc_user_role()
            self.console.log(
                f"已登录：{user}" + (f"（{role}）" if role else ""),
                "管理台",
            )
            if announce:
                QMessageBox.information(
                    self,
                    "登录",
                    f"已登录：{user}" + (f"（{role}）" if role else ""),
                )
            self._mgmt_refresh_session_ui()
            return True
        except Exception as exc:  # noqa: BLE001
            if not quiet_if_fail:

                QMessageBox.warning(self, "登录", mgmt_error_message(exc))
            self._mgmt_refresh_session_ui()
            return False

    def mgmt_logout(self) -> None:
        """退出登录后必须重新登录，否则退出应用。"""
        user = settings.mc_username() or "当前用户"
        # 登出后旧 Runner token 会话失效，一并停下避免幽灵心跳
        proc = getattr(self, "_local_runner", None)
        if proc is not None and proc.running:
            rid = proc.runner_id or "本机"
            proc.stop()
            self.console.log(f"已随退出登录停止本机 Runner：{rid}", "管理台")
        logout_and_clear()
        self.console.log(f"已退出登录：{user}", "管理台")
        self._mgmt_refresh_session_ui()
        self.hide()
        if not self.ensure_ide_login(force_dialog=True):
            self._mgmt_quit_app()
            return
        self.show()
        self.raise_()
        self.activateWindow()

    @staticmethod
    def _mgmt_quit_app() -> None:
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _mgmt_require_user_session(self, *, purpose: str) -> bool:
        if settings.mc_is_logged_in():
            return True
        QMessageBox.information(
            self,
            "需要登录",
            f"「{purpose}」需要已登录会话。请重新登录。",
        )
        if not self.ensure_ide_login(force_dialog=True):
            self._mgmt_quit_app()
            return False
        return settings.mc_is_logged_in()

    @staticmethod
    def _mgmt_is_platform_admin() -> bool:

        return is_platform_admin_role()

    def _mgmt_apply_action_roles(self) -> None:

        role = settings.mc_user_role()
        actions = getattr(self, "_actions", None) or {}
        for spec in ACTIONS:
            act = actions.get(spec.id)
            if act is None:
                continue
            act.setVisible(action_allowed_for_role(spec, role))

    def _mgmt_refresh_session_ui(self) -> None:
        actions = getattr(self, "_actions", None) or {}
        logged_in = settings.mc_is_logged_in()
        has_project = bool(settings.mc_project_id())

        if "mgmt.logout" in actions:
            actions["mgmt.logout"].setEnabled(logged_in)

        # 写入依赖项目空间；打开网页只需登录（未绑项目也能进管理台选项目）
        write_enabled = mgmt_write_enabled(logged_in=logged_in, has_project=has_project)
        for aid in _MGMT_WRITE_ACTION_IDS:
            if aid in actions:
                actions[aid].setEnabled(write_enabled)
                if logged_in and not has_project:
                    actions[aid].setToolTip(
                        "未绑定项目空间：请在「连接设置」选择项目，"
                        "或联系管理员将你加入项目成员"
                    )
        if "mgmt.open" in actions:
            actions["mgmt.open"].setEnabled(mgmt_open_web_enabled(logged_in=logged_in))
            if logged_in:
                actions["mgmt.open"].setToolTip("浏览器打开管理台（已登录可免二次登录）")

        proc = getattr(self, "_local_runner", None)
        running = bool(proc is not None and proc.running)
        if "mgmt.runner_start" in actions:
            actions["mgmt.runner_start"].setEnabled(not running and logged_in)
            act = actions["mgmt.runner_start"]
            if not logged_in:
                act.setToolTip("请先登录管理台")
            elif self._mgmt_is_platform_admin():
                act.setToolTip(
                    "把本机 USB 设备心跳上报到管理台组织设备池"
                    "（可自动签发组织作用域 Token；不必先选项目）"
                )
            else:
                act.setToolTip(
                    "使用连接设置中预配的 Runner Token 启动；Token 须由平台管理员签发"
                )
        if "mgmt.runner_stop" in actions:
            actions["mgmt.runner_stop"].setEnabled(running)

        self._mgmt_apply_action_roles()

        label = getattr(self, "_sb_mc_session", None)
        if label is not None:
            disp = settings.mc_session_display()
            pid = settings.mc_project_id()
            if disp:
                if pid:
                    label.setText(f"{disp} · {pid}")
                    label.setToolTip(
                        f"已登录 AutoPilot\n项目空间：{pid}\n与 Web 管理台同一账号"
                    )
                else:
                    label.setText(f"{disp} · 未绑定项目")
                    label.setToolTip(
                        "已登录，但当前账号无可见项目空间。\n"
                        "本地编辑与执行可用；上传/远程批跑需加入项目成员。\n"
                        "可在「Platform 连接」中切换项目。"
                    )
            else:
                label.setText("未登录")
                label.setToolTip("必须登录后才能使用 IDE")

        runner_lbl = getattr(self, "_sb_mc_runner", None)
        if runner_lbl is not None:
            if running and proc is not None:
                runner_lbl.setText(f"Runner {proc.runner_id}")
                runner_lbl.setToolTip(
                    f"本机 TestRunner 运行中 → {proc.server}\n"
                    "有 USB 设备时出现在管理台「设备」页；无设备时节点仍在线、设备列表为空"
                )
            else:
                runner_lbl.setText("Runner 未启动")
                runner_lbl.setToolTip(
                    "管理台 → 启动本机 Runner，可将本机 USB 设备注册到 TR 池"
                )
