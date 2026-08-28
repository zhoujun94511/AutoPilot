"""mgmt_connect_dialog — Operator / platform admin 差异化 UI。"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..mgmt_role import (
    connect_settings_banner,
    connect_token_placeholder,
    is_platform_admin_role,
)


class MgmtConnectDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Platform 连接（高级）")
        self.setMinimumWidth(480)
        self.login_after_save = False
        self._projects: list[dict] = []

        from ...runtime import settings
        from ...runtime.platform_deploy import platform_url_locked

        self.url = QLineEdit(settings.mc_server_url())
        locked = platform_url_locked()
        if locked:
            self.url.setReadOnly(True)
            self.url.setToolTip("管理台地址由 IT 部署配置，此处不可修改")
        else:
            self.url.setPlaceholderText("默认本机 http://127.0.0.1:8000；连远程时填写地址")
        self.username = QLineEdit(settings.mc_username())
        self.password = QLineEdit(settings.mc_password())
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.project_id = QComboBox()
        self.project_id.setEditable(True)
        self.project_id.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.project_id.lineEdit().setPlaceholderText(
            "可选；不选仍可登录、闲聊、启动本机 Runner；上传/回写须选择"
        )
        if settings.mc_project_id():
            self.project_id.setEditText(settings.mc_project_id())
        self.org_id = QLineEdit(settings.mc_org_id() if hasattr(settings, "mc_org_id") else "")
        self.org_id.setPlaceholderText("可选；多组织时填写当前组织")
        self.token = QLineEdit(settings.mc_api_token())
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.web_url = QLineEdit(settings.mc_web_url() if hasattr(settings, "mc_web_url") else "")
        self.web_url.setPlaceholderText(
            "可选；留空则与服务器地址相同"
        )
        self.chk_login = QCheckBox("保存后立即登录")
        self.chk_login.setChecked(True)
        self._role_hint = QLabel()
        self._role_hint.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Platform 地址", self.url)
        form.addRow("前端 URL", self.web_url)
        form.addRow("用户名", self.username)
        form.addRow("密码", self.password)
        form.addRow("默认项目空间", self.project_id)
        form.addRow("组织 ID", self.org_id)
        form.addRow("API Token", self.token)
        form.addRow("", self.chk_login)

        test_btn = QPushButton("测试登录")
        # noinspection PyUnresolvedReferences
        test_btn.clicked.connect(self._test)
        row = QHBoxLayout()
        row.addWidget(test_btn)
        row.addStretch(1)

        buttons = QDialogButtonBox(self)
        buttons.addButton("保存", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        # noinspection PyUnresolvedReferences
        buttons.accepted.connect(self._save)
        # noinspection PyUnresolvedReferences
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._role_hint)
        layout.addLayout(form)
        layout.addLayout(row)
        layout.addWidget(buttons)

        self._apply_role_ui()

    def _apply_role_ui(self, role: str | None = None) -> None:
        admin = is_platform_admin_role(role)
        self._role_hint.setText(connect_settings_banner(admin))
        self.token.setPlaceholderText(connect_token_placeholder(admin))
        self.token.setToolTip(self.token.placeholderText())

    def _selected_project_id(self) -> str:
        from ...mgmt.project_context import project_id_from_label

        text = self.project_id.currentText().strip()
        if self._projects:
            return project_id_from_label(text, self._projects)
        return text

    def _fill_projects(self, projects: list[dict]) -> None:
        from ...mgmt.project_context import project_labels
        from ...runtime import settings

        self._projects = list(projects or [])
        cur = self._selected_project_id() or settings.mc_project_id()
        self.project_id.blockSignals(True)
        self.project_id.clear()
        labels = project_labels(self._projects)
        if labels:
            self.project_id.addItems(labels)
            for i, p in enumerate(self._projects):
                if str((p or {}).get("id") or "").strip() == cur:
                    self.project_id.setCurrentIndex(i)
                    break
            else:
                if cur:
                    self.project_id.setEditText(cur)
        elif cur:
            self.project_id.setEditText(cur)
        self.project_id.blockSignals(False)

    def _persist_form(self, *, clear_session: bool) -> None:
        from ...runtime import settings
        from ...runtime.platform_deploy import platform_url_locked

        if not platform_url_locked():
            settings.set_mc_server_url(self.url.text())
        if hasattr(settings, "set_mc_web_url"):
            settings.set_mc_web_url(self.web_url.text())
        settings.set_mc_username(self.username.text())
        settings.set_mc_password(self.password.text())
        settings.set_mc_project_id(self._selected_project_id())
        if hasattr(settings, "set_mc_org_id"):
            settings.set_mc_org_id(self.org_id.text())
        settings.set_mc_api_token(self.token.text())
        if clear_session:
            settings.clear_mc_session()

    def _save(self) -> None:
        if not is_platform_admin_role() and not self.token.text().strip():
            answer = QMessageBox.question(
                self,
                "连接设置",
                "未填写 API Token：Operator 无法启动本机 Runner，"
                "上传/批跑仍可用。\n\n仍要保存吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._persist_form(clear_session=True)
        self.login_after_save = self.chk_login.isChecked()
        self.accept()

    def _test(self) -> None:
        from ...mgmt import MgmtClient, MgmtClientError, ensure_user_session, login_and_persist, mgmt_error_message
        from ...runtime import settings

        self._persist_form(clear_session=False)
        url = self.url.text().strip().rstrip("/")
        try:
            with MgmtClient(url) as c:
                h = c.health()
            login_and_persist(
                base_url=url,
                username=self.username.text().strip(),
                password=self.password.text(),
            )
            client, jwt = ensure_user_session(require=True)
            try:
                if jwt:
                    me = client.me()
                    role = str(me.get("role") or settings.mc_user_role() or "operator")
                    self._apply_role_ui(role)
                    projects = client.list_projects()
                    self._fill_projects(projects)
                    tip = (
                        f"健康检查：{h.get('status', h)}\n"
                        f"API 登录成功：{me.get('username')}（{role}）\n"
                        f"可见项目：{len(projects)} 个"
                    )
                    if not projects:
                        tip += "\n\n当前账号无可见项目，无法使用上传/回写。"
                    if role.strip().lower() != "admin" and not self.token.text().strip():
                        tip += "\n\n提示：Operator 启动本机 Runner 前须填写 API Token。"
                    QMessageBox.information(self, "测试登录", tip)
                else:
                    QMessageBox.information(
                        self,
                        "测试登录",
                        f"健康检查：{h.get('status', h)}\n"
                        "未获得用户 JWT。",
                    )
            finally:
                client.close()
        except (MgmtClientError, OSError, ConnectionError, TimeoutError) as exc:
            QMessageBox.warning(self, "测试登录", mgmt_error_message(exc))
        except Exception as exc:
            QMessageBox.warning(self, "测试登录", mgmt_error_message(exc))
