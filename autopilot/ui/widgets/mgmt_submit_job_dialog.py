"""提交远程批跑对话框：选用例 → 应用资源 → 设备（与 Web 编排对齐）。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ..theme import apply_dialog_theme


class MgmtSubmitJobDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        default_name: str = "Suite",
        default_project_id: str = "",
        default_app_build_id: str = "",
        app_builds: list[dict] | None = None,
        devices: list[dict] | None = None,
        entries: list[dict] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("form_dialog")
        self.setWindowTitle("提交远程批跑")
        self.setMinimumWidth(520)
        self._app_builds = list(app_builds or [])
        self._devices = list(devices or [])
        self._entries = list(entries or [])

        self.name = QLineEdit(default_name or "Suite")
        self.project_id = QLineEdit(default_project_id)
        self.project_id.setReadOnly(True)
        self.project_id.setToolTip(
            "任务归属当前连接设置中的 Platform 项目；如需切换，请先返回连接设置。"
        )
        self.platform = QComboBox()
        self.platform.addItems(["android", "ios", "web", "http"])
        self.entry_list = QListWidget()
        self.entry_list.setMinimumHeight(140)
        self.entry_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.app_build = QComboBox()
        self.app_build.setMinimumWidth(280)
        self.device_list = QListWidget()
        self.device_list.setMinimumHeight(140)
        self.device_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.udids = QLineEdit()
        self.udids.setPlaceholderText("可选；勾选设备后会自动填充，也可手填逗号分隔")
        self.runner = QLineEdit()
        self.runner.setPlaceholderText("可选 preferred_runner_id")
        self.parallel = QCheckBox("并行执行")
        self.workers = QSpinBox()
        self.workers.setRange(0, 64)
        self.workers.setValue(0)
        self.workers.setToolTip("0=按设备数全开；仅并行时生效")
        self.webhook = QLineEdit()
        self.webhook.setPlaceholderText("可选；覆盖默认 Webhook")
        self.backend_mode = QComboBox()
        self.backend_mode.addItems(["auto", "uia2", "wda", "appium"])
        self.web_engine = QComboBox()
        self.web_engine.addItems(["selenium", "playwright"])
        self.web_engine.setToolTip("仅 platform=web：Selenium 主力 / Playwright 可选")
        self.wda_bundle = QLineEdit()
        self.wda_bundle.setPlaceholderText("iOS WDA bundle（可选）")
        self.reupload = QCheckBox("先重新打包上传工程")
        self.reupload.setChecked(True)

        form = QFormLayout()
        form.addRow("1. 任务名", self.name)
        form.addRow("项目空间", self.project_id)
        form.addRow("平台", self.platform)

        entry_box = QGroupBox("2. 勾选要执行的用例")
        entry_lay = QVBoxLayout(entry_box)
        entry_btns = QHBoxLayout()
        btn_all = QPushButton("全选")
        btn_none = QPushButton("清空")
        # noinspection PyUnresolvedReferences
        btn_all.clicked.connect(self._select_all_entries)
        # noinspection PyUnresolvedReferences
        btn_none.clicked.connect(self._clear_entries)
        entry_btns.addWidget(btn_all)
        entry_btns.addWidget(btn_none)
        entry_btns.addStretch(1)
        entry_lay.addLayout(entry_btns)
        entry_lay.addWidget(self.entry_list)
        entry_hint = QLabel("仅展示用例/套件/计划，不会提交整棵工程目录树。")
        entry_hint.setObjectName("dialog_hint")
        entry_hint.setWordWrap(True)
        entry_lay.addWidget(entry_hint)

        app_box = QGroupBox("3. 选应用资源（推荐）")
        app_lay = QVBoxLayout(app_box)
        app_lay.addWidget(self.app_build)
        hint = QLabel(
            "安装包与工程制品分离。指定后 Runner 下载该版本并安装（覆盖用例 appFile）。"
            "可不选——仅当设备已装目标应用且用例不执行安装。"
        )
        hint.setObjectName("dialog_hint")
        hint.setWordWrap(True)
        app_lay.addWidget(hint)

        self._dev_box = QGroupBox("4. 选设备（TR 池）")
        dev_lay = QVBoxLayout(self._dev_box)
        dev_lay.addWidget(self.device_list)
        row = QHBoxLayout()
        row.addWidget(QLabel("UDID"))
        row.addWidget(self.udids, 1)
        dev_lay.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Runner"))
        row2.addWidget(self.runner, 1)
        row2.addWidget(self.parallel)
        row2.addWidget(QLabel("并发"))
        row2.addWidget(self.workers)
        dev_lay.addLayout(row2)

        opt_box = QGroupBox("5. 工程制品、通知与后端")
        opt_lay = QVBoxLayout(opt_box)
        opt_lay.addWidget(self.reupload)
        wh = QHBoxLayout()
        wh.addWidget(QLabel("Webhook"))
        wh.addWidget(self.webhook, 1)
        opt_lay.addLayout(wh)
        adv = QHBoxLayout()
        self._backend_label = QLabel("backend")
        adv.addWidget(self._backend_label)
        adv.addWidget(self.backend_mode)
        self._web_engine_label = QLabel("引擎")
        adv.addWidget(self._web_engine_label)
        adv.addWidget(self.web_engine)
        adv.addWidget(QLabel("WDA"))
        adv.addWidget(self.wda_bundle, 1)
        opt_lay.addLayout(adv)
        opt_hint = QLabel(
            "勾选则重新 zip 上传；否则复用上次 artifact_id。"
            "backend/WDA 一般保持 auto；web 平台可选引擎 Selenium/Playwright。"
        )
        opt_hint.setObjectName("dialog_hint")
        opt_hint.setWordWrap(True)
        opt_lay.addWidget(opt_hint)

        buttons = QDialogButtonBox(self)
        buttons.addButton("确定", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        # noinspection PyUnresolvedReferences
        buttons.accepted.connect(self.accept)
        # noinspection PyUnresolvedReferences
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(entry_box)
        layout.addWidget(app_box)
        layout.addWidget(self._dev_box)
        layout.addWidget(opt_box)
        layout.addWidget(buttons)

        # noinspection PyUnresolvedReferences
        self.platform.currentTextChanged.connect(self._reload_filtered)
        # noinspection PyUnresolvedReferences
        self.device_list.itemChanged.connect(self._sync_udids_from_checks)

        self._fill_entries()
        self._reload_filtered()
        if default_app_build_id:
            for i in range(self.app_build.count()):
                if self.app_build.itemData(i) == default_app_build_id:
                    self.app_build.setCurrentIndex(i)
                    break
        self._ui_theme = apply_dialog_theme(self, "dialog_form")

    def _fill_entries(self) -> None:
        self.entry_list.clear()
        if not self._entries:
            empty = QListWidgetItem(
                "本工程未发现 .tc / .ts / .tp（提交后将按空过滤跑全量发现）"
            )
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.entry_list.addItem(empty)
            return
        self.entry_list.blockSignals(True)
        for e in self._entries:
            path = str(e.get("path") or "")
            kind = str(e.get("kind") or "case")
            name = str(e.get("name") or path)
            item = QListWidgetItem(f"[{kind}] {name}  ·  {path}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.entry_list.addItem(item)
        self.entry_list.blockSignals(False)

    def _select_all_entries(self) -> None:
        for i in range(self.entry_list.count()):
            item = self.entry_list.item(i)
            if item and item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(Qt.CheckState.Checked)

    def _clear_entries(self) -> None:
        for i in range(self.entry_list.count()):
            item = self.entry_list.item(i)
            if item and item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(Qt.CheckState.Unchecked)

    def _selected_entry_paths(self) -> list[str]:
        paths: list[str] = []
        for i in range(self.entry_list.count()):
            item = self.entry_list.item(i)
            if item is None:
                continue
            path = item.data(Qt.ItemDataRole.UserRole)
            if not path:
                continue
            if item.checkState() == Qt.CheckState.Checked:
                paths.append(str(path))
        return paths

    def _reload_filtered(self) -> None:
        from ...runtime.job_platforms import (
            HTTP_BUILTIN_PROFILES,
            coerce_backend_mode,
            is_deviceless_platform,
            is_http_platform,
            is_web_platform,
        )

        plat = self.platform.currentText().strip().lower()
        is_web = is_web_platform(plat)
        is_http = is_http_platform(plat)
        is_deviceless = is_deviceless_platform(plat)
        # backend_mode：web 承载浏览器类型；http 承载 api_env profile；移动为设备后端
        cur_be = coerce_backend_mode(plat, self.backend_mode.currentText())
        self.backend_mode.blockSignals(True)
        self.backend_mode.clear()
        if is_http:
            self.backend_mode.setEditable(True)
            self.backend_mode.addItems(list(HTTP_BUILTIN_PROFILES))
        elif is_web:
            self.backend_mode.setEditable(False)
            self.backend_mode.addItems(["auto", "chrome", "edge", "firefox", "headless"])
        else:
            self.backend_mode.setEditable(False)
            self.backend_mode.addItems(["auto", "uia2", "wda", "appium"])
        _be_idx = self.backend_mode.findText(cur_be)
        if _be_idx >= 0:
            self.backend_mode.setCurrentIndex(_be_idx)
        elif is_http and cur_be and cur_be != "auto":
            self.backend_mode.setEditText(cur_be)
        self.backend_mode.blockSignals(False)
        self._dev_box.setTitle(
            "4. 指定执行节点" if is_deviceless else "4. 选设备（TR 池）"
        )
        self._backend_label.setText("API环境" if is_http else ("浏览器" if is_web else "backend"))
        self._web_engine_label.setVisible(is_web)
        self.web_engine.setVisible(is_web)
        self.web_engine.setEnabled(is_web)
        # web / http 无移动设备 / apk / 并行概念：禁用相关控件，仅保留「指定 Runner」
        self.device_list.setEnabled(not is_deviceless)
        self.udids.setEnabled(not is_deviceless)
        self.parallel.setEnabled(not is_deviceless)
        self.workers.setEnabled(not is_deviceless)
        self.wda_bundle.setEnabled(not is_deviceless)
        self.app_build.setEnabled(not is_deviceless)
        cur = self.app_build.currentData()
        self.app_build.blockSignals(True)
        self.app_build.clear()
        self.app_build.addItem("— 不指定 —", "")
        for b in self._app_builds:
            bplat = str(b.get("platform") or "").lower()
            if plat and bplat and bplat != plat:
                continue
            label = (
                f"{b.get('name') or b.get('filename') or b.get('id')}"
                f"{(' v' + str(b.get('version_name'))) if b.get('version_name') else ''}"
                f"{(' (' + str(b.get('version_code')) + ')') if b.get('version_code') else ''}"
                f"{(' · ' + str(b.get('package_id'))) if b.get('package_id') else ''}"
                f" ({str(b.get('id') or '')[:8]}…)"
            )
            self.app_build.addItem(label, b.get("id") or "")
        if cur:
            for i in range(self.app_build.count()):
                if self.app_build.itemData(i) == cur:
                    self.app_build.setCurrentIndex(i)
                    break
        self.app_build.blockSignals(False)

        selected_udids = {
            x.strip() for x in self.udids.text().split(",") if x.strip()
        }
        self.device_list.blockSignals(True)
        self.device_list.clear()
        matched = 0
        for d in self._devices:
            dplat = str(d.get("platform") or "").lower()
            if plat and dplat and dplat != plat:
                continue
            udid = str(d.get("udid") or "")
            if not udid:
                continue
            busy = bool(d.get("busy"))
            state = str(d.get("state") or "ready").strip().lower() or "ready"
            backends = d.get("backends") or []
            be = ",".join(str(x) for x in backends) if backends else "-"
            os_ver = str(d.get("os_version") or "").strip()
            label = (
                f"{d.get('name') or d.get('model') or udid}  [{dplat or '?'}]  "
                f"os={os_ver or '-'}  backends={be}  "
                f"{udid}  @ {d.get('runner_id') or '?'}"
            )
            if busy:
                label += "  (占用中)"
            elif state != "ready":
                label += f"  ({state})"
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            if busy or state != "ready":
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            item.setData(Qt.ItemDataRole.UserRole, udid)
            item.setData(Qt.ItemDataRole.UserRole + 1, d.get("runner_id") or "")
            item.setCheckState(
                Qt.CheckState.Checked
                if udid in selected_udids
                else Qt.CheckState.Unchecked
            )
            self.device_list.addItem(item)
            matched += 1
        self.device_list.blockSignals(False)
        if matched == 0:
            empty = QListWidgetItem("当前无匹配平台的在线设备（可手填 UDID）")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.device_list.addItem(empty)

    def _sync_udids_from_checks(self, *_args) -> None:
        udids: list[str] = []
        runners: list[str] = []
        for i in range(self.device_list.count()):
            item = self.device_list.item(i)
            if item is None:
                continue
            udid = item.data(Qt.ItemDataRole.UserRole)
            if not udid:
                continue
            if item.checkState() == Qt.CheckState.Checked:
                udids.append(str(udid))
                rid = item.data(Qt.ItemDataRole.UserRole + 1)
                if rid:
                    runners.append(str(rid))
        self.udids.blockSignals(True)
        self.udids.setText(", ".join(udids))
        self.udids.blockSignals(False)
        uniq = list(dict.fromkeys(runners))
        self.runner.blockSignals(True)
        if len(uniq) == 1:
            self.runner.setText(uniq[0])
        elif len(uniq) > 1:
            self.runner.setText("")
            self.runner.setPlaceholderText(
                "已选跨节点设备，请手动指定 preferred_runner_id 或只勾选同一 Runner"
            )
        self.runner.blockSignals(False)

    def values(self) -> dict:
        plat = self.platform.currentText().strip().lower()
        is_deviceless = plat in ("web", "http")
        is_web = plat == "web"
        udids = (
            []
            if is_deviceless
            else [x.strip() for x in self.udids.text().split(",") if x.strip()]
        )
        app_id = "" if is_deviceless else self.app_build.currentData()
        parallel = False if is_deviceless else self.parallel.isChecked()
        if len(udids) > 1 and not parallel:
            raise ValueError("多台设备须勾选「并行执行」，或只选一台设备")
        entry_paths = self._selected_entry_paths()
        if self._entries and not entry_paths:
            raise ValueError("请至少勾选一个用例/套件/计划")
        return {
            "name": self.name.text().strip() or "Suite",
            "project_id": self.project_id.text().strip(),
            "platform": self.platform.currentText(),
            "app_build_id": str(app_id or "").strip(),
            "device_udids": udids,
            "preferred_runner_id": self.runner.text().strip() or None,
            "parallel": parallel,
            "parallel_workers": int(self.workers.value()),
            "webhook_url": self.webhook.text().strip(),
            "backend_mode": self.backend_mode.currentText().strip() or "auto",
            "web_engine": (
                (self.web_engine.currentText().strip() or "selenium")
                if is_web
                else "selenium"
            ),
            "wda_bundle": "" if is_deviceless else self.wda_bundle.text().strip(),
            "reupload": self.reupload.isChecked(),
            "entry_paths": entry_paths,
        }
