"""AI 辅助编写对话框（链路 3：自动设备/应用/会话）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...authoring.codegen import save_draft_tc
from ...authoring.contract import (
    DEFAULT_MAX_STEPS,
    HARD_MAX_STEPS,
    AuthoringError,
    AuthoringRequest,
    clamp_max_steps,
    user_facing_notes,
)
from ...authoring.gate import assert_local_dry_run_passed, record_gate_result
from ...authoring.llm_client import (
    assert_llm_ready,
    last_platform_llm_capabilities,
)
from ...authoring.nl_bootstrap import resolve_nl_hints
from ...authoring.pipeline import generate_traditional_case
from ...authoring.agent import try_page_nl
from ...authoring.session_bootstrap import (
    prepare_authoring_session,
    release_authoring_session,
)
from ...authoring.platform_resolve import (
    inspect_platform_from_ctx,
    resolve_authoring_platform,
)
from ...runtime import settings
from ...runtime.log import get_logger
from ..platform_labels import normalize_ui_platform, platform_label
from ..theme import apply_dialog_theme

log = get_logger("authoring.ui")


class AiAuthoringDialog(QDialog):
    """NL → 自动选设备/解析应用/建会话 → 固化传统用例。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        project_dir: str = "",
        default_platform: str = "auto",
        get_ctx: Callable[[], Any] | None = None,
        ensure_appium: Callable[[], bool] | None = None,
        chat_fn: Callable[[str], str] | None = None,
        runner_fn: Callable[[str], bool] | None = None,
        on_request_run: Callable[[str], None] | None = None,
        open_project_fn: Callable[[str], None] | None = None,
        create_project_fn: Callable[[], str] | None = None,
        default_nl: str = "",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ai_authoring_dialog")
        self.setWindowTitle("AI 辅助编写")
        # 步骤/状态文案会变长：允许缩放与最大化，便于核对
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setMinimumSize(640, 480)
        self.resize(760, 620)
        self.setSizeGripEnabled(True)
        self._project_dir = project_dir or ""
        self._get_ctx = get_ctx
        self._ensure_appium = ensure_appium
        self._chat_fn = chat_fn
        self._runner_fn = runner_fn
        self._on_request_run = on_request_run
        self._open_project_fn = open_project_fn
        self._create_project_fn = create_project_fn
        self._draft = None
        self._saved_path = ""
        #: 本轮编写自建的会话（非检视器复用）；关闭对话框时必须回收
        self._owned_ctx = None
        #: 复用检视器会话时保留引用，仅做软清理（不关 driver）
        self._reused_ctx = None
        self._generating = False
        self._gate = None
        self._released = False
        #: 若在对话框内打开/新建了工程，主窗口应同步刷新
        self._project_changed = False

        lay = QVBoxLayout(self)
        hint = QLabel(
            "用一句话描述要测的操作，设备和应用会自动准备。"
            "生成的是普通用例，之后照常编辑和运行。"
        )
        hint.setObjectName("dialog_hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        form = QFormLayout()
        self.cmb_platform = QComboBox()
        self.cmb_platform.addItem("自动（从描述识别）", "auto")
        self.cmb_platform.addItem("iOS", "ios")
        self.cmb_platform.addItem("Android", "android")
        self.cmb_platform.addItem("Web", "web")
        self.cmb_platform.addItem("HTTP / API", "http")

        raw_plat = (default_platform or "auto").strip().lower()
        plat = "auto" if raw_plat in ("", "auto") else (normalize_ui_platform(raw_plat) or "auto")
        idx = self.cmb_platform.findData(plat)
        self.cmb_platform.setCurrentIndex(max(0, idx))
        # noinspection PyUnresolvedReferences
        self.cmb_platform.currentIndexChanged.connect(self._sync_platform_fields)
        form.addRow("平台", self.cmb_platform)

        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem("会话驱动编写（推荐）", "session")
        self.cmb_mode.addItem("仅规划草稿（不执行）", "plan_only")
        form.addRow("模式", self.cmb_mode)

        self.ed_package = QLineEdit()
        self.ed_package.setPlaceholderText("留空即按描述里的应用名自动识别（移动端）")
        form.addRow("应用包名（可选）", self.ed_package)

        self.ed_url = QLineEdit()
        self.ed_url.setPlaceholderText("Web 起始页或 API base URL（可写在描述里）")
        form.addRow("起始 URL", self.ed_url)

        self.ed_project = QLineEdit(self._project_dir)
        self.ed_project.setReadOnly(True)
        self.ed_project.setPlaceholderText("请打开或新建工程后再编写")
        btn_open = QPushButton("打开…")
        btn_new = QPushButton("新建…")
        # noinspection PyUnresolvedReferences
        btn_open.clicked.connect(self._on_open_project)
        # noinspection PyUnresolvedReferences
        btn_new.clicked.connect(self._on_new_project)
        proj_row = QWidget()
        proj_lay = QHBoxLayout(proj_row)
        proj_lay.setContentsMargins(0, 0, 0, 0)
        proj_lay.addWidget(self.ed_project, 1)
        proj_lay.addWidget(btn_open)
        proj_lay.addWidget(btn_new)
        form.addRow("工程", proj_row)

        self.spn_steps = QSpinBox()
        self.spn_steps.setRange(1, HARD_MAX_STEPS)
        self.spn_steps.setValue(DEFAULT_MAX_STEPS)
        self.spn_steps.setToolTip("这条用例最多生成多少步；更长的流程建议拆成多条用例。")
        form.addRow("步数上限", self.spn_steps)

        self.ed_nl = QPlainTextEdit()
        self.ed_nl.setPlaceholderText(
            "例如：打开设置应用，进入无线局域网并打开开关\n"
            "或：打开 https://example.com ，点击登录并输入账号"
        )
        self.ed_nl.setFixedHeight(110)
        if default_nl:
            self.ed_nl.setPlainText(default_nl)
        form.addRow("场景描述", self.ed_nl)

        self.chk_draft = QCheckBox("只存草稿，不做试跑（之后不能直接提交批量执行）")
        self.chk_draft.setChecked(False)
        form.addRow("", self.chk_draft)
        lay.addLayout(form)
        self._sync_platform_fields()

        btn_row = QHBoxLayout()
        self.btn_gen = QPushButton("开始编写")
        self.btn_gen.setObjectName("primary_action")
        # noinspection PyUnresolvedReferences
        self.btn_gen.clicked.connect(self._on_generate)
        self.btn_try = QPushButton("试跑当前页")
        self.btn_try.setToolTip(
            "在当前已连接会话上只跑一小步，用于确认理解是否正确；不写入工程"
        )
        # noinspection PyUnresolvedReferences
        self.btn_try.clicked.connect(self._on_try_page)
        btn_row.addWidget(self.btn_gen)
        btn_row.addWidget(self.btn_try)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        self.tbl = QTableWidget(0, 3)
        self.tbl.setObjectName("authoring_steps")
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setHorizontalHeaderLabels(["关键字", "参数", "说明"])
        self.tbl.horizontalHeader().setStretchLastSection(True)
        # 只读；Qt 默认不会把多格选区写入剪贴板，需自管复制
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # noinspection PyUnresolvedReferences
        self.tbl.customContextMenuRequested.connect(self._on_steps_menu)
        copy_sc = QShortcut(QKeySequence.StandardKey.Copy, self.tbl)
        # noinspection PyUnresolvedReferences
        copy_sc.activated.connect(self._copy_selected_steps)
        lay.addWidget(self.tbl, 1)

        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("authoring_status")
        self.lbl_status.setWordWrap(True)
        # 默认 QLabel 不可选中；状态/告警文案经常要复制排查
        # 仅鼠标可选（与 about_dialog / sidebar_header 一致；避免 Flag | 触发类型检查误报）
        self.lbl_status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.lbl_status.setCursor(Qt.CursorShape.IBeamCursor)
        self.lbl_status.setToolTip("可选中后 Ctrl+C 复制")
        lay.addWidget(self.lbl_status)

        buttons = QDialogButtonBox()
        self.btn_save = buttons.addButton("写入工程", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("关闭", QDialogButtonBox.ButtonRole.RejectRole)
        self.btn_save.setEnabled(False)
        # noinspection PyUnresolvedReferences
        buttons.accepted.connect(self._on_save)
        # noinspection PyUnresolvedReferences
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self._ui_theme = apply_dialog_theme(self, "ai_authoring_dialog")

    def saved_path(self) -> str:
        return self._saved_path

    def project_dir(self) -> str:
        return self._target_project_dir()

    def project_changed(self) -> bool:
        return self._project_changed

    def _on_open_project(self) -> None:
        """走正式「打开工程」链路，不是随便选个目录就写 authored/。"""
        start = self.ed_project.text().strip() or self._project_dir or ""
        chosen = QFileDialog.getExistingDirectory(self, "打开工程目录", start)
        if not chosen:
            return
        self._bind_project(chosen, notify_host=True)

    def _on_new_project(self) -> None:
        """复用主窗口新建工程对话框；无回调时本地建骨架。"""
        if self._create_project_fn is not None:
            path = (self._create_project_fn() or "").strip()
            if path:
                self._bind_project(path, notify_host=False)
            return
        from .new_project_dialog import NewProjectDialog  # 延迟：仅点「新建工程」时弹窗

        base = self.ed_project.text().strip() or self._project_dir or ""
        dlg = NewProjectDialog(self, base)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        parent, name = dlg.parent_dir(), dlg.project_name()
        if not parent or not name:
            return
        path = str(Path(parent) / name)
        if not Path(path).is_dir():
            Path(path).mkdir(parents=True, exist_ok=True)
            cfg = Path(path) / "config"
            cfg.mkdir(parents=True, exist_ok=True)
            props = cfg / "DataConfig.properties"
            if not props.exists():
                props.write_text("", encoding="utf-8")
        self._bind_project(path, notify_host=True)

    def _bind_project(self, path: str, *, notify_host: bool) -> None:
        self._project_dir = path
        self.ed_project.setText(path)
        self._project_changed = True
        if notify_host and self._open_project_fn is not None:
            self._open_project_fn(path)

    def _target_project_dir(self) -> str:
        """草稿落盘目录：对话框绑定的工程（打开/新建/当前）。"""
        return self.ed_project.text().strip() or self._project_dir

    def _sync_platform_fields(self) -> None:
        """按平台高亮包名 / URL 提示（自动时两者都可用）。"""
        plat = str(self.cmb_platform.currentData() or "auto")
        if plat == "web":
            self.ed_package.setEnabled(False)
            self.ed_url.setEnabled(True)
        elif plat == "http":
            self.ed_package.setEnabled(False)
            self.ed_url.setEnabled(True)
        elif plat in ("ios", "android"):
            self.ed_package.setEnabled(True)
            self.ed_url.setEnabled(False)
        else:
            self.ed_package.setEnabled(True)
            self.ed_url.setEnabled(True)

    def _resolve_authoring_platform(
        self,
        *,
        plat_data: str,
        hints_platform: str,
        start_url: str,
        existing: Any = None,
    ) -> str:
        """显式选择 → NL 线索 → URL 推断 → 检视器 → 工程默认；仍空则报错。"""
        proj_plat = ""
        proj = self._target_project_dir()
        if proj:
            try:
                proj_plat = normalize_ui_platform(settings.project_platform(proj) or "")
            except (ImportError, OSError, AttributeError, TypeError, RuntimeError):
                proj_plat = ""
        return resolve_authoring_platform(
            explicit=plat_data,
            hints_platform=hints_platform,
            start_url=start_url,
            inspect_platform=inspect_platform_from_ctx(existing),
            project_platform=proj_plat,
        )

    def _on_try_page(self) -> None:
        """当前会话试一句：不要求工程目录，不落盘。"""
        if self._generating:
            return
        nl = self.ed_nl.toPlainText().strip()
        if not nl:
            QMessageBox.warning(self, "AI 辅助编写", "请先输入场景描述")
            return
        existing = self._get_ctx() if self._get_ctx else None
        if existing is None:
            QMessageBox.warning(
                self,
                "AI 辅助编写",
                "试跑当前页需要先连接检视器或设备会话。",
            )
            return
        if self._chat_fn is None:
            try:
                assert_llm_ready()
            except AuthoringError as exc:
                QMessageBox.warning(self, "AI 辅助编写", str(exc))
                return

        plat_data = str(self.cmb_platform.currentData() or "auto")
        hints, _notes = resolve_nl_hints(
            nl,
            platform="" if plat_data == "auto" else plat_data,
            package_name=self.ed_package.text().strip(),
            start_url=self.ed_url.text().strip(),
            chat=self._chat_fn,
            allow_llm=True,
        )
        start_url = hints.start_url or self.ed_url.text().strip()
        try:
            platform = self._resolve_authoring_platform(
                plat_data=plat_data,
                hints_platform=hints.platform,
                start_url=start_url,
                existing=existing,
            )
        except AuthoringError as exc:
            QMessageBox.warning(self, "AI 辅助编写", str(exc))
            return

        self._generating = True
        self.btn_gen.setEnabled(False)
        self.btn_try.setEnabled(False)
        self.lbl_status.setText("试跑当前页…")

        def on_progress(msg: str) -> None:
            self.lbl_status.setText(msg)

        try:
            req = AuthoringRequest(
                natural_language=nl,
                platform=platform,
                mode="session",
                package_name=hints.package_name or self.ed_package.text().strip(),
                start_url=hints.start_url or self.ed_url.text().strip(),
                draft_only=True,
                max_steps=4,
                app_label=hints.app_name,
                input_texts=hints.input_texts,
                project_dir=self._target_project_dir(),
            )
            draft = try_page_nl(
                req,
                ctx=existing,
                chat=self._chat_fn,
                on_progress=on_progress,
            )
            self._draft = draft
            self._fill_table()
            self.btn_save.setEnabled(False)
            warns = "；".join(draft.warnings[:3])
            self.lbl_status.setText(
                f"试跑完成 {len(draft.steps)} 步（未写入）"
                + (f"：{warns}" if warns else "")
            )
        except AuthoringError as exc:
            QMessageBox.warning(self, "AI 辅助编写", str(exc))
            self.lbl_status.setText(str(exc))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "AI 辅助编写", f"试跑失败：{exc}")
            self.lbl_status.setText(str(exc))
        finally:
            self._generating = False
            self.btn_gen.setEnabled(True)
            self.btn_try.setEnabled(True)

    def _on_generate(self) -> None:
        if self._generating:
            # 弹窗/进度更新会重入事件循环，仅靠按钮禁用不足以防重复触发一整轮 AI 调用
            return
        nl = self.ed_nl.toPlainText().strip()
        if not nl:
            QMessageBox.warning(self, "AI 辅助编写", "请先输入场景描述")
            return
        # 落盘目录先校验：编写要占真机并消耗 token，不能等跑完才发现没处可写
        project_dir = self._target_project_dir()
        if not project_dir:
            QMessageBox.warning(
                self,
                "AI 辅助编写",
                "请先选择草稿写入的工程目录（或打开一个工程）",
            )
            return
        if not Path(project_dir).is_dir():
            QMessageBox.warning(self, "AI 辅助编写", f"工程目录不存在：{project_dir}")
            return
        if self._chat_fn is None:
            try:
                active_llm_mode = assert_llm_ready()
            except AuthoringError as exc:
                QMessageBox.warning(self, "AI 辅助编写", str(exc))
                self.lbl_status.setText(str(exc))
                return
        else:
            active_llm_mode = "custom"
        plat_data = str(self.cmb_platform.currentData() or "auto")
        hints, nl_notes = resolve_nl_hints(
            nl,
            platform="" if plat_data == "auto" else plat_data,
            package_name=self.ed_package.text().strip(),
            start_url=self.ed_url.text().strip(),
            chat=self._chat_fn,
            allow_llm=True,
        )
        package_name = hints.package_name or self.ed_package.text().strip()
        start_url = hints.start_url or self.ed_url.text().strip()
        existing = self._get_ctx() if self._get_ctx else None
        try:
            platform = self._resolve_authoring_platform(
                plat_data=plat_data,
                hints_platform=hints.platform,
                start_url=start_url,
                existing=existing,
            )
        except AuthoringError as exc:
            QMessageBox.warning(self, "AI 辅助编写", str(exc))
            self.lbl_status.setText(str(exc))
            return
        mode = str(self.cmb_mode.currentData() or "session")
        if package_name and not self.ed_package.text().strip():
            self.ed_package.setText(package_name)
        if start_url and not self.ed_url.text().strip():
            self.ed_url.setText(start_url)

        self._generating = True
        self.btn_gen.setEnabled(False)
        caps = last_platform_llm_capabilities() if active_llm_mode == "platform" else {}
        # AI 供应商、图片能力、预算这些属于运维信息：写日志与悬浮提示，不占状态行
        if caps:
            log.info(
                "AI 编写使用 %s/%s（图片=%s，预算=%s）",
                caps.get("provider"),
                caps.get("model"),
                caps.get("accepts_images"),
                caps.get("token_budget"),
            )
            self.lbl_status.setToolTip(
                f"AI 服务：{caps.get('provider')} / {caps.get('model')}"
            )
        log.info("AI 编写解析线索：mode=%s notes=%s", active_llm_mode, nl_notes)
        self.lbl_status.setText("正在准备设备与应用…")

        def on_progress(msg: str) -> None:
            self.lbl_status.setText(msg)

        try:
            req = AuthoringRequest(
                natural_language=nl,
                platform=platform,
                mode=mode,  # type: ignore[arg-type]
                package_name=package_name,
                start_url=start_url,
                draft_only=self.chk_draft.isChecked(),
                max_steps=clamp_max_steps(self.spn_steps.value()),
                app_label=hints.app_name,
                input_texts=hints.input_texts,
                project_dir=self._target_project_dir(),
            )
            ctx = None
            if mode == "session":
                # 重新编写前先回收上一轮自建会话，避免 Appium/浏览器叠层占端口
                self._release_session_resources()
                existing = self._get_ctx() if self._get_ctx else None
                preferred = ""
                if existing is not None and hasattr(existing, "get_var"):
                    preferred = str(existing.get_var("__device_udid__") or "")
                boot = prepare_authoring_session(
                    req,
                    preferred_udid=preferred,
                    ensure_appium=self._ensure_appium,
                    existing_ctx=existing,
                    pick_device=self._pick_device,
                    chat=self._chat_fn,
                    # 对话框已做过一次 NL resolve，避免 bootstrap 再打一轮
                    allow_nl_llm=False,
                )
                req = boot.request
                ctx = boot.ctx
                if boot.reused_ctx:
                    self._reused_ctx = ctx
                    self._owned_ctx = None
                else:
                    self._owned_ctx = ctx
                    self._reused_ctx = None
                self._released = False
                log.info("AI 编写会话就绪：%s", "；".join(boot.notes))
                status_bits = user_facing_notes(list(nl_notes) + list(boot.notes))
                if status_bits:
                    self.lbl_status.setText("；".join(status_bits))
                # 回填自动解析结果，便于确认
                if req.package_name:
                    self.ed_package.setText(req.package_name)
                if req.start_url:
                    self.ed_url.setText(req.start_url)
                idx = self.cmb_platform.findData(req.platform)
                if idx >= 0:
                    self.cmb_platform.setCurrentIndex(idx)

            result = generate_traditional_case(
                req,
                ctx=ctx,
                project_dir=None,
                chat=self._chat_fn,
                on_progress=on_progress,
                save=False,
            )
            self._draft = result.draft
            self._fill_table()
            warns = "；".join(result.draft.warnings[:4])
            incomplete = (
                "" if result.draft.goal_completed
                else " · 未确认完成需求，请人工核对步骤"
            )
            self.lbl_status.setText(
                f"已生成 {len(result.draft.steps)} 步"
                f"（{req.app_label or req.package_name}）{incomplete}"
                + (f"：{warns}" if warns else "")
            )
            self.btn_save.setEnabled(True)
            # 步骤已固化进草稿：立刻回收自建会话，预览/保存阶段不再占设备端口
            self._release_session_resources()
        except AuthoringError as exc:
            self._release_session_resources()
            QMessageBox.warning(self, "AI 辅助编写", str(exc))
            self.lbl_status.setText(str(exc))
        except Exception as exc:  # noqa: BLE001
            self._release_session_resources()
            QMessageBox.critical(self, "AI 辅助编写", f"编写失败：{exc}")
            self.lbl_status.setText(str(exc))
        finally:
            self._generating = False
            self.btn_gen.setEnabled(True)

    def _fill_table(self) -> None:
        draft = self._draft
        self.tbl.setRowCount(0)
        if draft is None:
            return
        for s in draft.steps:
            r = self.tbl.rowCount()
            self.tbl.insertRow(r)
            for col, text in (
                (0, s.keyword_id),
                (1, ", ".join(f"{k}={v}" for k, v in (s.params or {}).items())),
                (2, s.comment or ""),
            ):
                item = QTableWidgetItem(text)
                # 编辑由表格 NoEditTriggers 禁止；默认 flags 已含可选中
                item.setToolTip(text)
                self.tbl.setItem(r, col, item)

    def _selected_step_rows(self) -> list[int]:
        rows = sorted({idx.row() for idx in self.tbl.selectionModel().selectedRows()})
        if not rows:
            rows = sorted({i.row() for i in self.tbl.selectedItems()})
        return rows

    def _row_step_text(self, row: int) -> str:
        cells = [
            self.tbl.item(row, c).text() if self.tbl.item(row, c) else ""
            for c in range(self.tbl.columnCount())
        ]
        return "\t".join(cells)

    def _copy_selected_steps(self) -> None:
        rows = self._selected_step_rows()
        if not rows:
            return
        QApplication.clipboard().setText(
            "\n".join(self._row_step_text(r) for r in rows)
        )

    def _copy_all_steps(self) -> None:
        if self.tbl.rowCount() <= 0:
            return
        QApplication.clipboard().setText(
            "\n".join(
                self._row_step_text(r) for r in range(self.tbl.rowCount())
            )
        )

    def _on_steps_menu(self, pos) -> None:
        menu = QMenu(self)
        has_sel = bool(self._selected_step_rows())
        has_any = self.tbl.rowCount() > 0
        act_copy = menu.addAction("复制选中行\tCtrl+C", self._copy_selected_steps)
        act_copy.setEnabled(has_sel)
        act_all = menu.addAction("复制全部步骤", self._copy_all_steps)
        act_all.setEnabled(has_any)
        menu.addSeparator()
        act_sel = menu.addAction("全选", self.tbl.selectAll)
        act_sel.setEnabled(has_any)
        menu.exec(self.tbl.viewport().mapToGlobal(pos))

    def _on_save(self) -> None:
        if self._draft is None:
            return
        project_dir = self._target_project_dir()
        if not project_dir:
            QMessageBox.warning(
                self, "AI 辅助编写", "请先选择工程目录（或打开一个工程）"
            )
            return
        draft_only = self.chk_draft.isChecked()
        try:
            path = save_draft_tc(self._draft, project_dir)
            gate = assert_local_dry_run_passed(
                path,
                draft_only=draft_only,
                runner=None if draft_only else self._runner_fn,
                session_verified=bool(getattr(self._draft, "session_verified", False)),
                goal_completed=bool(getattr(self._draft, "goal_completed", True)),
            )
            record_gate_result(path, gate)
            self._gate = gate
            self._saved_path = str(path)
        except AuthoringError as exc:
            QMessageBox.warning(self, "AI 辅助编写", str(exc))
            return
        if gate.allow_upload or draft_only or self._on_request_run is None:
            QMessageBox.information(self, "AI 辅助编写", f"已写入：{path}\n{gate.message}")
            self.accept()
            return
        ans = QMessageBox.question(
            self,
            "AI 辅助编写",
            f"已写入：{path}\n{gate.message}\n\n现在打开并用本机运行验证吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        self.accept()
        if ans == QMessageBox.StandardButton.Yes:
            self._on_request_run(str(path))

    def gate_result(self):
        """最近一次写入的门禁结论（未写入时为 None）。"""
        return self._gate

    def _pick_device(self, platform: str, udids: list[str]) -> str:
        """多台设备在线时问一次，别静默跑到别人的机器上。"""
        from .list_pick_dialog import pick_list_item  # 延迟：仅多设备时弹选择框
        from ..main_window.device_select import friendly_pick_labels

        if platform == "web" or not udids:
            return ""
        label = platform_label(platform)
        items = friendly_pick_labels(platform, list(udids))
        choice, ok = pick_list_item(
            self,
            "选择编写目标设备",
            f"{label} 有多台设备在线，选择本次 AI 编写使用的设备：",
            items,
            0,
            values=list(udids),
        )
        return choice if ok else ""

    def _release_session_resources(self) -> None:
        """回收本对话框持有的编写会话；幂等，可安全重复调用。"""
        if self._released and self._owned_ctx is None and self._reused_ctx is None:
            return
        owned = self._owned_ctx
        reused = self._reused_ctx
        self._owned_ctx = None
        self._reused_ctx = None
        self._released = True
        if owned is not None:
            release_authoring_session(owned, reused=False)
        if reused is not None:
            release_authoring_session(reused, reused=True)

    def done(self, result: int) -> None:  # noqa: A003 — Qt API
        # accept / reject / Esc 都会走这里；保证关窗必回收，不挡住后续 F5/检视
        self._release_session_resources()
        super().done(result)

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt API
        self._release_session_resources()
        super().closeEvent(event)
