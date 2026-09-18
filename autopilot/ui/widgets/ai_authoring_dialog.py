"""AI 辅助编写对话框（链路 3：自动设备/应用/会话）。"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import QObject, QSize, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...authoring.app_resolve import InstalledApp
from ...authoring.codegen import save_draft_tc
from ...authoring.contract import (
    DEFAULT_MAX_STEPS,
    HARD_MAX_STEPS,
    AuthoringDraft,
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
from ...authoring.pipeline import AuthoringResult, generate_traditional_case
from ...authoring.agent import try_page_nl
from ...authoring.session_bootstrap import (
    authoring_unattended,
    preferred_authoring_udid,
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
from .empty_state import EmptyState

log = get_logger("authoring.ui")


class _AuthoringWorker(QThread):
    """后台执行编写/当前页理解，避免对话框假死。"""

    progress = pyqtSignal(str)
    finished_with = pyqtSignal(object)

    def __init__(self, fn: Callable[[], Any], parent=None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            # noinspection PyUnresolvedReferences
            self.finished_with.emit(self._fn())
        except Exception as exc:  # noqa: BLE001
            # noinspection PyUnresolvedReferences
            self.finished_with.emit(exc)


_JOB_CANCELLED = object()


class _WriteJobPayload:
    """后台编写结果：草稿 + 解析后的请求（回填包名/URL 必须在 UI 线程）。"""

    __slots__ = ("result", "request")

    def __init__(self, result: AuthoringResult, request: AuthoringRequest) -> None:
        self.result = result
        self.request = request


class _UiCallGate(QObject):
    """工作线程里要弹选择框 / 启 Appium 时，阻塞切回界面线程。"""

    _run = pyqtSignal()

    def __init__(self, host: QObject) -> None:
        super().__init__(host)
        self._fn: Callable[[], Any] | None = None
        self._result: Any = None
        self._error: BaseException | None = None
        # noinspection PyUnresolvedReferences
        self._run.connect(self._on_run, Qt.ConnectionType.BlockingQueuedConnection)

    def invoke(self, fn: Callable[[], Any]) -> Any:
        app = QApplication.instance()
        if app is None or QThread.currentThread() == app.thread():
            return fn()
        self._fn = fn
        self._result = None
        self._error = None
        # noinspection PyUnresolvedReferences
        self._run.emit()
        if self._error is not None:
            raise self._error
        return self._result

    def _on_run(self) -> None:
        try:
            self._result = self._fn() if self._fn is not None else None
        except BaseException as exc:  # noqa: BLE001
            self._error = exc
        finally:
            self._fn = None


class _UnshrinkableScrollArea(QScrollArea):
    """视口可以变矮并出滚动条，内部表单保持自身高度，避免一行挤一行。"""

    def __init__(self, inner: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("authoring_advanced_scroll")
        self.setWidget(inner)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)

    def sizeHint(self) -> QSize:
        inner = self.widget()
        if inner is None:
            return super().sizeHint()
        hint = inner.sizeHint()
        return QSize(max(hint.width(), 200), hint.height())

    def minimumSizeHint(self) -> QSize:
        hint = self.sizeHint()
        return QSize(hint.width(), min(hint.height(), 72))


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
        self._committed_draft = None
        self._previewing_page = False
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
        self._cancel_event = threading.Event()
        self._worker: _AuthoringWorker | None = None
        self._close_after_job = False
        self._busy_action = "write"
        self._active_llm_mode = ""
        self._ui_gate = _UiCallGate(self)

        lay = QVBoxLayout(self)
        self._root_lay = lay
        self.lbl_hint = QLabel(
            "用一句话描述要测的操作，设备和应用会自动准备。"
            "在设备上编写才会驱动真机；当前页理解只预览、不保存。"
        )
        self.lbl_hint.setObjectName("dialog_hint")
        self.lbl_hint.setWordWrap(True)
        lay.addWidget(self.lbl_hint)

        self.ed_nl = QPlainTextEdit()
        self.ed_nl.setPlaceholderText(
            "例如：打开设置应用，进入无线局域网并打开开关\n"
            "或：打开 https://example.com ，点击登录并输入账号"
        )
        self.ed_nl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        if default_nl:
            self.ed_nl.setPlainText(default_nl)
        lay.addWidget(self.ed_nl, 0)

        top = QFormLayout()
        self.cmb_platform = QComboBox()
        self.cmb_platform.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.cmb_platform.setMinimumContentsLength(12)
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
        top.addRow("平台", self.cmb_platform)

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
        top.addRow("工程", proj_row)
        lay.addLayout(top)

        self.btn_advanced = QToolButton()
        self.btn_advanced.setObjectName("authoring_advanced")
        self.btn_advanced.setText("高级选项")
        self.btn_advanced.setCheckable(True)
        self.btn_advanced.setAutoRaise(True)
        self.btn_advanced.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        # noinspection PyUnresolvedReferences
        self.btn_advanced.toggled.connect(self._toggle_advanced)
        lay.addWidget(self.btn_advanced, 0, Qt.AlignmentFlag.AlignLeft)

        self.adv_panel = QWidget()
        self.adv_panel.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        form = QFormLayout(self.adv_panel)
        self._adv_form = form
        form.setContentsMargins(0, 8, 0, 8)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.cmb_mode = QComboBox()
        self.cmb_mode.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.cmb_mode.setMinimumContentsLength(20)
        self.cmb_mode.addItem("在设备上编写（推荐）", "session")
        self.cmb_mode.addItem("高级：仅规划草稿（不执行、不可上传）", "plan_only")
        self.cmb_mode.setToolTip(
            "正式路径会在设备或浏览器上逐步执行后再落盘。"
            "仅规划草稿不连接会话，也不能直接上传批跑。"
        )
        # noinspection PyUnresolvedReferences
        self.cmb_mode.currentIndexChanged.connect(self._sync_mode_fields)
        form.addRow("模式", self.cmb_mode)

        self.ed_package = QLineEdit()
        self.ed_package.setPlaceholderText("留空即按描述里的应用名自动识别（移动端）")
        self._lbl_package = QLabel("应用包名（可选）")
        form.addRow(self._lbl_package, self.ed_package)

        self.chk_current_app = QCheckBox("使用当前前台应用（不自动启动，适用于已开检视器）")
        self.chk_current_app.setToolTip(
            "勾选后跳过应用名解析与 mobile_app_start；请在设备上手动打开目标 App 后再编写"
        )
        # noinspection PyUnresolvedReferences
        self.chk_current_app.toggled.connect(self._sync_platform_fields)
        form.addRow(self.chk_current_app)

        self.ed_url = QLineEdit()
        self._lbl_url = QLabel("起始 URL")
        self.ed_url.setPlaceholderText("可写在描述里，或在此填写")
        form.addRow(self._lbl_url, self.ed_url)

        self.spn_steps = QSpinBox()
        self.spn_steps.setRange(1, HARD_MAX_STEPS)
        self.spn_steps.setValue(DEFAULT_MAX_STEPS)
        self.spn_steps.setToolTip("这条用例最多生成多少步；更长的流程建议拆成多条用例。")
        form.addRow("步数上限", self.spn_steps)

        self.chk_draft = QCheckBox("只存草稿，不做本机验证（之后不能直接提交批量执行）")
        self.chk_draft.setChecked(False)
        form.addRow(self.chk_draft)
        self._adv_scroll = _UnshrinkableScrollArea(self.adv_panel)
        self._adv_scroll.setVisible(False)
        lay.addWidget(self._adv_scroll)

        btn_row = QHBoxLayout()
        self.btn_gen = QPushButton("在设备上编写")
        self.btn_gen.setObjectName("primary_action")
        self.btn_gen.setToolTip("连接会话并逐步执行，生成可保存的用例。Ctrl+Enter")
        # noinspection PyUnresolvedReferences
        self.btn_gen.clicked.connect(self._on_generate)
        self.btn_try = QPushButton("只理解当前页")
        self.btn_try.setToolTip(
            "在已连接的检视器会话上预览理解是否正确；不写入工程，也不替换已编写结果"
        )
        # noinspection PyUnresolvedReferences
        self.btn_try.clicked.connect(self._on_try_page)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setObjectName("authoring_stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setToolTip("在当前回合结束后停止编写或理解")
        # noinspection PyUnresolvedReferences
        self.btn_stop.clicked.connect(self._request_stop)
        btn_row.addWidget(self.btn_gen)
        btn_row.addWidget(self.btn_try)
        btn_row.addWidget(self.btn_stop)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)
        self._sync_platform_fields()
        self._sync_mode_fields()

        gen_sc = QShortcut(QKeySequence("Ctrl+Return"), self)
        # noinspection PyUnresolvedReferences
        gen_sc.activated.connect(self._on_generate)
        gen_sc2 = QShortcut(QKeySequence("Ctrl+Enter"), self)
        # noinspection PyUnresolvedReferences
        gen_sc2.activated.connect(self._on_generate)

        self.tbl = QTableWidget(0, 3)
        self.tbl.setObjectName("authoring_steps")
        self.tbl.setAlternatingRowColors(True)
        self.tbl.setHorizontalHeaderLabels(["说明", "关键字", "参数"])
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # noinspection PyUnresolvedReferences
        self.tbl.customContextMenuRequested.connect(self._on_steps_menu)
        copy_sc = QShortcut(QKeySequence.StandardKey.Copy, self.tbl)
        # noinspection PyUnresolvedReferences
        copy_sc.activated.connect(self._copy_selected_steps)

        self._empty = EmptyState("mdi6.robot-outline", compact=True)
        self._empty.show_state("还没有步骤", "编写完成后，步骤会显示在这里")
        self._steps_stack = QStackedWidget()
        self._steps_stack.addWidget(self._empty)
        self._steps_stack.addWidget(self.tbl)
        lay.addWidget(self._steps_stack, 1)

        status_row = QHBoxLayout()
        self.lbl_badge = QLabel("")
        self.lbl_badge.setObjectName("authoring_badge")
        self.lbl_badge.setVisible(False)
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("authoring_status")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.lbl_status.setCursor(Qt.CursorShape.IBeamCursor)
        self.lbl_status.setToolTip("可选中后 Ctrl+C 复制")
        status_row.addWidget(self.lbl_badge, 0, Qt.AlignmentFlag.AlignTop)
        status_row.addWidget(self.lbl_status, 1)
        lay.addLayout(status_row)

        self.lbl_llm = QLabel("")
        self.lbl_llm.setObjectName("authoring_llm")
        self.lbl_llm.setWordWrap(True)
        lay.addWidget(self.lbl_llm)

        buttons = QDialogButtonBox()
        self.btn_save = buttons.addButton("写入工程", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("关闭", QDialogButtonBox.ButtonRole.RejectRole)
        self.btn_save.setEnabled(False)
        self.btn_save.setAutoDefault(False)
        self.btn_save.setDefault(False)
        for box_btn in buttons.buttons():
            box_btn.setAutoDefault(False)
            box_btn.setDefault(False)
        self.btn_gen.setDefault(True)
        self.btn_gen.setAutoDefault(True)
        # noinspection PyUnresolvedReferences
        buttons.accepted.connect(self._on_save)
        # noinspection PyUnresolvedReferences
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self._ui_theme = apply_dialog_theme(self, "ai_authoring_dialog")
        self._empty.apply_theme(self._ui_theme)
        self._apply_advanced_field_metrics()
        self._sync_steps_stretch()
        self._form_lock_widgets = [
            self.ed_nl,
            self.cmb_platform,
            self.ed_project,
            btn_open,
            btn_new,
            self.btn_advanced,
            self.cmb_mode,
            self.ed_package,
            self.chk_current_app,
            self.ed_url,
            self.spn_steps,
            self.chk_draft,
        ]

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

    def _toggle_advanced(self, checked: bool) -> None:
        self._adv_scroll.setVisible(bool(checked))
        self.btn_advanced.setText("收起高级选项" if checked else "高级选项")
        if checked:
            self._relayout_advanced()
        else:
            self._sync_steps_stretch()
            host = self.layout()
            if host is not None:
                host.invalidate()
                host.activate()

    def _field_min_height(self) -> int:
        return max(28, self.fontMetrics().height() + 12)

    def _apply_advanced_field_metrics(self) -> None:
        """隐藏面板里的控件在首次展开前可能未 polish，sizeHint 会偏矮。"""
        min_h = self._field_min_height()
        expanding_fixed = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for widget in (
            self.cmb_platform,
            self.cmb_mode,
            self.ed_package,
            self.ed_url,
            self.ed_project,
        ):
            widget.setMinimumHeight(min_h)
            widget.setSizePolicy(expanding_fixed)
        check_h = max(22, self.fontMetrics().height() + 8)
        preferred_fixed = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        for widget in (self.chk_current_app, self.chk_draft):
            widget.setMinimumHeight(check_h)
            widget.setSizePolicy(preferred_fixed)
        # 步数框只加控件最小高度，不加 QSS padding，以免箭头消失
        self.spn_steps.setMinimumHeight(min_h)
        self._apply_nl_field_metrics()
        self._lock_advanced_form_height()

    def _nl_min_height(self) -> int:
        """两行示例提示 + 一行输入；避免被 QSS 单行 min-height 盖掉。"""
        fm = self.ed_nl.fontMetrics()
        placeholder = self.ed_nl.placeholderText() or ""
        lines = max(2, placeholder.count("\n") + 1) + 1
        return max(88, fm.lineSpacing() * lines + 20)

    def _apply_nl_field_metrics(self) -> None:
        min_h = self._nl_min_height()
        self.ed_nl.setMinimumHeight(min_h)
        self.ed_nl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.ed_nl.updateGeometry()

    def _lock_advanced_form_height(self) -> None:
        """表单按内容撑开；窗口不够高时由滚动区出条，而不是压扁某一行。"""
        self.adv_panel.ensurePolished()
        for child in self.adv_panel.findChildren(QWidget):
            child.ensurePolished()
            child.updateGeometry()
        self.adv_panel.setMinimumHeight(0)
        self.adv_panel.adjustSize()
        hint_h = max(
            self.adv_panel.sizeHint().height(),
            self.adv_panel.minimumSizeHint().height(),
        )
        self.adv_panel.setMinimumHeight(hint_h)
        self._adv_scroll.updateGeometry()

    def _relayout_advanced(self) -> None:
        self._apply_advanced_field_metrics()
        self._sync_steps_stretch()
        self._adv_scroll.updateGeometry()
        host = self.layout()
        if host is not None:
            host.invalidate()
            host.activate()

    def _set_form_row_visible(self, widget: QWidget, visible: bool) -> None:
        """隐藏时连 QFormLayout 的行一起收掉，避免切平台留下空白缝。"""
        widget.setVisible(visible)
        form = getattr(self, "_adv_form", None)
        if form is not None and hasattr(form, "setRowVisible"):
            form.setRowVisible(widget, visible)

    def _sync_steps_stretch(self) -> None:
        lay = getattr(self, "_root_lay", None)
        if lay is None:
            return
        empty = self._steps_stack.currentWidget() is self._empty
        adv = not self._adv_scroll.isHidden()
        lay.setStretchFactor(self.ed_nl, 0 if adv else 1)
        lay.setStretchFactor(self._steps_stack, 1 if empty else 2)

    def _apply_resolved_request(self, req: AuthoringRequest) -> None:
        if req.package_name:
            self.ed_package.setText(req.package_name)
        if req.start_url:
            self.ed_url.setText(req.start_url)
        idx = self.cmb_platform.findData(req.platform)
        if idx >= 0:
            self.cmb_platform.setCurrentIndex(idx)

    def _refresh_llm_caption(self) -> None:
        if getattr(self, "_active_llm_mode", "") != "platform":
            return
        caps = last_platform_llm_capabilities()
        if not caps:
            return
        log.info(
            "AI 编写使用 %s/%s（图片=%s，预算=%s）",
            caps.get("provider"),
            caps.get("model"),
            caps.get("accepts_images"),
            caps.get("token_budget"),
        )
        img = "支持图像" if caps.get("accepts_images") else "文本"
        self.lbl_llm.setText(
            f"AI：{caps.get('provider')} / {caps.get('model')} · {img}"
        )

    def _ensure_appium_safe(self) -> bool:
        fn = self._ensure_appium
        if fn is None:
            return True
        return bool(self._ui_gate.invoke(fn))

    def _is_http_platform(self) -> bool:
        return str(self.cmb_platform.currentData() or "") == "http"

    def _session_write_label(self) -> str:
        plat = str(self.cmb_platform.currentData() or "")
        if plat == "http":
            return "编写接口用例"
        if plat == "web":
            return "在浏览器上编写"
        return "在设备上编写"

    def _is_plan_only(self) -> bool:
        return str(self.cmb_mode.currentData() or "") == "plan_only"

    def _sync_mode_fields(self) -> None:
        plan = self._is_plan_only()
        if plan:
            self.chk_draft.setChecked(True)
            self.chk_draft.setEnabled(False)
            self.btn_gen.setText("生成规划草稿")
        else:
            self.chk_draft.setEnabled(not self._generating)
            self.btn_gen.setText(
                self._session_write_label() if not self._generating else "正在编写…"
            )

    def _sync_save_cta(self) -> None:
        draft = self._committed_draft
        if draft is None or self._generating:
            self.btn_save.setEnabled(False)
            return
        self.btn_save.setEnabled(True)
        incomplete = not bool(getattr(draft, "goal_completed", False))
        if self._is_plan_only() or self.chk_draft.isChecked() or incomplete:
            self.btn_save.setText("写入待核对草稿")
        else:
            self.btn_save.setText("写入工程")

    def _set_badge(self, kind: str) -> None:
        labels = {
            "done": "已完成",
            "review": "需核对",
            "plan": "仅规划",
            "preview": "当前页预览",
            "": "",
        }
        self.lbl_badge.setText(labels.get(kind, ""))
        self.lbl_badge.setProperty("badge_kind", kind)
        self.lbl_badge.style().unpolish(self.lbl_badge)
        self.lbl_badge.style().polish(self.lbl_badge)
        self.lbl_badge.setVisible(bool(kind))

    def _set_busy(self, busy: bool, *, action: str = "write") -> None:
        self._generating = busy
        self._busy_action = action
        for w in self._form_lock_widgets:
            if w is self.chk_draft and self._is_plan_only():
                w.setEnabled(False)
                continue
            w.setEnabled(not busy)
        self.btn_gen.setEnabled(not busy)
        self.btn_try.setEnabled(not busy and not self._is_http_platform())
        self.btn_stop.setEnabled(busy)
        if busy:
            if action == "try":
                self.btn_gen.setText("正在理解…")
            elif self._is_plan_only():
                self.btn_gen.setText("正在规划…")
            else:
                self.btn_gen.setText("正在编写…")
        else:
            self._sync_mode_fields()
        self._sync_save_cta()

    def _emit_progress(self, msg: str) -> None:
        worker = self._worker
        if worker is None:
            return
        # noinspection PyUnresolvedReferences
        worker.progress.emit(msg)

    def _request_stop(self) -> None:
        if not self._generating:
            return
        self._cancel_event.set()
        self.lbl_status.setText("正在停止…")
        self.btn_stop.setEnabled(False)

    def reject(self) -> None:
        if self._generating:
            self._close_after_job = True
            self._request_stop()
            return
        super().reject()

    def _sync_platform_fields(self) -> None:
        """按平台切换包名 / URL 的标签与显隐。"""
        plat = str(self.cmb_platform.currentData() or "auto")
        mobile = plat in ("ios", "android")
        web = plat == "web"
        http = plat == "http"
        auto = plat == "auto"
        show_pkg = mobile or auto
        show_url = web or http or auto
        self._set_form_row_visible(self.ed_package, show_pkg)
        self._lbl_package.setVisible(show_pkg)
        self._set_form_row_visible(self.chk_current_app, show_pkg)
        self._set_form_row_visible(self.ed_url, show_url)
        self._lbl_url.setVisible(show_url)
        if http:
            self._lbl_url.setText("接口 Base URL")
            self.ed_url.setPlaceholderText("API 根地址，也可写在描述里")
            self.lbl_hint.setText(
                "用一句话描述要测的接口。编写时会真实发 HTTP 请求并固化断言，不占用手机或浏览器。"
            )
            self.ed_nl.setPlaceholderText(
                "例如：GET /api/v1/health，断言状态码 200\n"
                "或：用 Bearer 登录后创建订单并校验返回 id"
            )
            self.cmb_mode.setItemText(0, "编写接口用例（推荐）")
            self.cmb_mode.setToolTip(
                "正式路径会真实调用接口后再落盘。仅规划草稿不发请求，也不能直接上传批跑。"
            )
            self.btn_try.setVisible(False)
        elif web:
            self._lbl_url.setText("起始页 URL")
            self.ed_url.setPlaceholderText("浏览器打开的地址，也可写在描述里")
            self.lbl_hint.setText(
                "用一句话描述要测的操作。在浏览器上编写才会打开页面；当前页理解只预览、不保存。"
            )
            self.ed_nl.setPlaceholderText(
                "例如：打开 https://example.com ，点击登录并输入账号"
            )
            self.cmb_mode.setItemText(0, "在浏览器上编写（推荐）")
            self.cmb_mode.setToolTip(
                "正式路径会在浏览器上逐步执行后再落盘。"
                "仅规划草稿不连接会话，也不能直接上传批跑。"
            )
            self.btn_try.setVisible(True)
        else:
            self._lbl_url.setText("起始 URL")
            self.ed_url.setPlaceholderText("可写在描述里，或在此填写")
            self.lbl_hint.setText(
                "用一句话描述要测的操作，设备和应用会自动准备。"
                "在设备上编写才会驱动真机；当前页理解只预览、不保存。"
            )
            self.ed_nl.setPlaceholderText(
                "例如：打开设置应用，进入无线局域网并打开开关\n"
                "或：打开 https://example.com ，点击登录并输入账号"
            )
            self.cmb_mode.setItemText(0, "在设备上编写（推荐）")
            self.cmb_mode.setToolTip(
                "正式路径会在设备或浏览器上逐步执行后再落盘。"
                "仅规划草稿不连接会话，也不能直接上传批跑。"
            )
            self.btn_try.setVisible(True)
        if not self._generating:
            self._sync_mode_fields()
        if show_pkg:
            self.ed_package.setEnabled(
                not self._generating and not self.chk_current_app.isChecked()
            )
            self.chk_current_app.setEnabled(not self._generating)
        if show_url:
            self.ed_url.setEnabled(not self._generating)
        if not self._adv_scroll.isHidden():
            self._relayout_advanced()
        else:
            self._apply_nl_field_metrics()

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
        """当前会话理解一句：不要求工程目录，不落盘，不替换已编写草稿。"""
        if self._generating:
            return
        nl = self.ed_nl.toPlainText().strip()
        if not nl:
            QMessageBox.warning(self, "无法理解当前页", "请先输入场景描述")
            return
        existing = self._get_ctx() if self._get_ctx else None
        if existing is None:
            QMessageBox.warning(
                self,
                "无法理解当前页",
                "需要先连接检视器或设备会话。",
            )
            return
        if self._chat_fn is None:
            try:
                assert_llm_ready()
            except AuthoringError as exc:
                QMessageBox.warning(self, "无法理解当前页", str(exc))
                return

        plat_data = str(self.cmb_platform.currentData() or "auto")
        package_name = self.ed_package.text().strip()
        start_url = self.ed_url.text().strip()
        project_dir = self._target_project_dir()
        self._cancel_event = threading.Event()
        self._close_after_job = False

        def work():
            return self._try_page_job(
                nl=nl,
                plat_data=plat_data,
                package_name=package_name,
                start_url=start_url,
                existing=existing,
                project_dir=project_dir,
            )

        self._start_job(work, action="try")

    def _try_page_job(
        self,
        *,
        nl: str,
        plat_data: str,
        package_name: str,
        start_url: str,
        existing: Any,
        project_dir: str,
    ) -> Any:
        cancel = self._cancel_event
        if cancel.is_set():
            return _JOB_CANCELLED
        hints, _notes = resolve_nl_hints(
            nl,
            platform="" if plat_data == "auto" else plat_data,
            package_name=package_name,
            start_url=start_url,
            chat=self._chat_fn,
            allow_llm=True,
        )
        if cancel.is_set():
            return _JOB_CANCELLED
        resolved_url = hints.start_url or start_url
        platform = self._resolve_authoring_platform(
            plat_data=plat_data,
            hints_platform=hints.platform,
            start_url=resolved_url,
            existing=existing,
        )
        req = AuthoringRequest(
            natural_language=nl,
            platform=platform,
            mode="session",
            package_name=hints.package_name or package_name,
            start_url=hints.start_url or start_url,
            draft_only=True,
            max_steps=4,
            app_label=hints.app_name,
            input_texts=hints.input_texts,
            project_dir=project_dir,
        )
        return try_page_nl(
            req,
            ctx=existing,
            chat=self._chat_fn,
            on_progress=self._emit_progress,
            cancel_event=cancel,
        )

    def _on_generate(self) -> None:
        if self._generating:
            return
        nl = self.ed_nl.toPlainText().strip()
        if not nl:
            QMessageBox.warning(self, "无法编写", "请先输入场景描述")
            return
        project_dir = self._target_project_dir()
        if not project_dir:
            QMessageBox.warning(
                self,
                "无法编写",
                "请先选择草稿写入的工程目录（或打开一个工程）",
            )
            return
        if not Path(project_dir).is_dir():
            QMessageBox.warning(self, "无法编写", f"工程目录不存在：{project_dir}")
            return
        if self._chat_fn is None:
            try:
                active_llm_mode = assert_llm_ready()
            except AuthoringError as exc:
                QMessageBox.warning(self, "无法编写", str(exc))
                self.lbl_status.setText(str(exc))
                return
        else:
            active_llm_mode = "custom"
        plat_data = str(self.cmb_platform.currentData() or "auto")
        mode = str(self.cmb_mode.currentData() or "session")
        if mode == "plan_only":
            self.chk_draft.setChecked(True)
        package_name = self.ed_package.text().strip()
        start_url = self.ed_url.text().strip()
        use_current = self.chk_current_app.isChecked()
        draft_only = self.chk_draft.isChecked()
        max_steps = clamp_max_steps(self.spn_steps.value())
        existing = self._get_ctx() if self._get_ctx else None
        inspector_udid = ""
        if existing is not None and hasattr(existing, "get_var"):
            inspector_udid = str(existing.get_var("__device_udid__") or "")
        self._active_llm_mode = active_llm_mode
        self._cancel_event = threading.Event()
        self._close_after_job = False
        if mode == "session":
            self._release_session_resources()

        def work():
            return self._write_job(
                nl=nl,
                plat_data=plat_data,
                mode=mode,
                package_name=package_name,
                start_url=start_url,
                use_current=use_current,
                draft_only=draft_only,
                max_steps=max_steps,
                existing=existing,
                preferred_udid=preferred_authoring_udid(inspector_udid),
                unattended=authoring_unattended(),
                project_dir=project_dir,
            )

        self._start_job(work, action="write")

    def _write_job(
        self,
        *,
        nl: str,
        plat_data: str,
        mode: str,
        package_name: str,
        start_url: str,
        use_current: bool,
        draft_only: bool,
        max_steps: int,
        existing: Any,
        preferred_udid: str,
        unattended: bool,
        project_dir: str,
    ) -> Any:
        cancel = self._cancel_event
        if cancel.is_set():
            return _JOB_CANCELLED
        self._emit_progress("正在解析描述…")
        hints, nl_notes = resolve_nl_hints(
            nl,
            platform="" if plat_data == "auto" else plat_data,
            package_name=package_name,
            start_url=start_url,
            chat=self._chat_fn,
            allow_llm=True,
        )
        if cancel.is_set():
            return _JOB_CANCELLED
        resolved_pkg = hints.package_name or package_name
        resolved_url = hints.start_url or start_url
        platform = self._resolve_authoring_platform(
            plat_data=plat_data,
            hints_platform=hints.platform,
            start_url=resolved_url,
            existing=existing,
        )
        log.info("AI 编写解析线索：mode=%s notes=%s", self._active_llm_mode, nl_notes)
        req = AuthoringRequest(
            natural_language=nl,
            platform=platform,
            mode=mode,  # type: ignore[arg-type]
            package_name=resolved_pkg,
            start_url=resolved_url,
            draft_only=draft_only,
            max_steps=max_steps,
            app_label=hints.app_name,
            input_texts=hints.input_texts,
            project_dir=project_dir,
            use_current_app=use_current,
        )
        ctx = None
        if mode == "session":
            if cancel.is_set():
                return _JOB_CANCELLED
            self._emit_progress("正在准备设备与应用…")
            boot = prepare_authoring_session(
                req,
                preferred_udid=preferred_udid,
                ensure_appium=(
                    self._ensure_appium_safe if self._ensure_appium is not None else None
                ),
                existing_ctx=existing,
                pick_device=None if unattended else self._pick_device,
                pick_app=None if unattended else self._pick_app,
                chat=self._chat_fn,
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
                self._emit_progress("；".join(status_bits))
            if cancel.is_set():
                return _JOB_CANCELLED
        if cancel.is_set():
            return _JOB_CANCELLED
        result = generate_traditional_case(
            req,
            ctx=ctx,
            project_dir=None,
            chat=self._chat_fn,
            on_progress=self._emit_progress,
            save=False,
            cancel_event=cancel,
        )
        return _WriteJobPayload(result, req)

    def _start_job(
        self,
        fn: Callable[[], Any],
        *,
        action: str,
    ) -> None:
        self._set_busy(True, action=action)
        if action == "try":
            self.lbl_status.setText("正在理解当前页…")
        else:
            self.lbl_status.setText("正在解析描述…")
        worker = _AuthoringWorker(fn, self)
        self._worker = worker
        # noinspection PyUnresolvedReferences
        worker.progress.connect(self.lbl_status.setText)
        # noinspection PyUnresolvedReferences
        worker.finished_with.connect(
            lambda payload: self._on_job_finished(payload, action)
        )
        worker.start()
        if not self.isVisible() and self._worker is not None:
            running = self._worker
            for _ in range(2400):
                if not running.isRunning():
                    break
                QApplication.processEvents()
                running.wait(50)
            QApplication.processEvents()

    def _on_job_finished(self, payload: object, action: str) -> None:
        self._worker = None
        self._set_busy(False)
        close_after = self._close_after_job
        self._close_after_job = False
        if action != "try":
            self._release_session_resources()
        if payload is _JOB_CANCELLED:
            self.lbl_status.setText("已停止")
            if close_after:
                super().reject()
            return
        if isinstance(payload, _WriteJobPayload):
            self._apply_resolved_request(payload.request)
            self._refresh_llm_caption()
            payload = payload.result
        if isinstance(payload, Exception):
            title = "无法理解当前页" if action == "try" else (
                "无法编写" if isinstance(payload, AuthoringError) else "编写失败"
            )
            if isinstance(payload, AuthoringError):
                QMessageBox.warning(self, title, str(payload))
            else:
                QMessageBox.critical(self, title, str(payload))
            self.lbl_status.setText(str(payload))
            if close_after:
                super().reject()
            return
        if action == "try":
            if not isinstance(payload, AuthoringDraft):
                QMessageBox.critical(self, "无法理解当前页", "当前页理解未返回草稿")
                self.lbl_status.setText("当前页理解未返回草稿")
                if close_after:
                    super().reject()
                return
            draft = payload
            self._draft = draft
            self._previewing_page = True
            self._fill_table()
            self._set_badge("preview")
            keep = (
                "；上一份编写结果仍可写入"
                if self._committed_draft is not None
                else ""
            )
            warns = "；".join(list(draft.warnings)[:3])
            self.lbl_status.setText(
                f"当前页理解 {len(draft.steps or [])} 步（未保存）{keep}"
                + (f"：{warns}" if warns else "")
            )
            self._sync_save_cta()
            if close_after:
                super().reject()
            return

        if not isinstance(payload, AuthoringResult):
            QMessageBox.critical(self, "编写失败", "编写未返回结果")
            self.lbl_status.setText("编写未返回结果")
            if close_after:
                super().reject()
            return
        draft = payload.draft
        self._committed_draft = draft
        self._draft = draft
        self._previewing_page = False
        self._fill_table()
        if self._is_plan_only() or draft.mode == "plan_only":
            self._set_badge("plan")
        elif draft.goal_completed:
            self._set_badge("done")
        else:
            self._set_badge("review")
        warns = "；".join(draft.warnings[:4])
        incomplete = "" if draft.goal_completed else "未确认完成需求，请人工核对步骤。"
        self.lbl_status.setText(
            f"已生成 {len(draft.steps)} 步。{incomplete}"
            + (f" {warns}" if warns else "")
        )
        self._sync_save_cta()
        if close_after:
            super().reject()

    def _fill_table(self) -> None:
        draft = self._draft
        self.tbl.setRowCount(0)
        steps = list(getattr(draft, "steps", []) or []) if draft is not None else []
        if not steps:
            self._steps_stack.setCurrentWidget(self._empty)
            self._sync_steps_stretch()
            return
        self._steps_stack.setCurrentWidget(self.tbl)
        self._sync_steps_stretch()
        for s in steps:
            r = self.tbl.rowCount()
            self.tbl.insertRow(r)
            comment = (s.comment or "").strip() or s.keyword_id
            params = ", ".join(f"{k}={v}" for k, v in (s.params or {}).items())
            for col, text in ((0, comment), (1, s.keyword_id), (2, params)):
                item = QTableWidgetItem(text)
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

    def _draft_to_save(self):
        if self._committed_draft is not None:
            return self._committed_draft
        if getattr(self, "_previewing_page", False):
            return None
        return self._draft

    def _on_save(self) -> None:
        draft = self._draft_to_save()
        if draft is None:
            return
        project_dir = self._target_project_dir()
        if not project_dir:
            QMessageBox.warning(
                self, "无法写入", "请先选择工程目录（或打开一个工程）"
            )
            return
        draft_only = self.chk_draft.isChecked() or self._is_plan_only()
        try:
            path = save_draft_tc(draft, project_dir)
            gate = assert_local_dry_run_passed(
                path,
                draft_only=draft_only,
                runner=None if draft_only else self._runner_fn,
                session_verified=bool(getattr(draft, "session_verified", False)),
                goal_completed=bool(getattr(draft, "goal_completed", False)),
            )
            record_gate_result(path, gate)
            self._gate = gate
            self._saved_path = str(path)
        except AuthoringError as exc:
            QMessageBox.warning(self, "无法写入", str(exc))
            return
        self.lbl_status.setText(f"已写入：{path}\n{gate.message}")
        if gate.allow_upload or draft_only or self._on_request_run is None:
            return
        ans = QMessageBox.question(
            self,
            "已写入草稿",
            f"已写入：{path}\n{gate.message}\n\n现在打开并用本机运行验证吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if ans == QMessageBox.StandardButton.Yes:
            self._on_request_run(str(path))

    def gate_result(self):
        """最近一次写入的门禁结论（未写入时为 None）。"""
        return self._gate

    def _pick_device(self, platform: str, udids: list[str]) -> str:
        """多台设备在线时问一次，别静默跑到别人的机器上。"""
        return self._ui_gate.invoke(lambda: self._pick_device_on_ui(platform, udids))

    def _pick_device_on_ui(self, platform: str, udids: list[str]) -> str:
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

    def _pick_app(self, hint: str, candidates: list[InstalledApp]) -> InstalledApp | None:
        """应用歧义或未命中时让用户择一。"""
        return self._ui_gate.invoke(lambda: self._pick_app_on_ui(hint, candidates))

    def _pick_app_on_ui(
        self, hint: str, candidates: list[InstalledApp]
    ) -> InstalledApp | None:
        from .list_pick_dialog import pick_list_item

        if not candidates:
            return None
        items = [
            f"{a.app_label or a.package_name} ({a.package_name})"
            for a in candidates
        ]
        pkgs = [a.package_name for a in candidates]
        title = "选择目标应用"
        if hint:
            prompt = f"「{hint}」需要确认目标应用，请选择本次编写使用的应用："
        else:
            prompt = "请从设备已装应用中选择本次编写使用的应用："
        choice, ok = pick_list_item(
            self,
            title,
            prompt,
            items,
            0,
            values=pkgs,
        )
        if not ok:
            return None
        for app in candidates:
            if app.package_name == choice:
                return app
        return None

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
        if self._generating:
            event.ignore()
            self._close_after_job = True
            self._request_stop()
            return
        self._release_session_resources()
        super().closeEvent(event)
