"""IDE 启动/退出后的强制登录门禁（登录 → 可选项目空间）。

交互参考：
- VS Code / JetBrains：账号登录后即可进入 IDE；云端 workspace 可后选
- Postman：登录 ≠ 必须已有 workspace；无 workspace 时本地能力可用
- Slack：多 workspace 时同屏选择；有效缓存则跳过

项目空间仅约束管理台写入（上传/投递）；无可见项目时仍允许进入 IDE。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from PyQt6.QtCore import Qt, QEventLoop
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .list_pick_dialog import _PickRow


def _qt_connect(signal: Any, slot: Callable[..., Any]) -> None:
    """PyQt6 信号连接（静态检查无法识别 pyqtSignal.connect）。"""
    # noinspection PyUnresolvedReferences
    signal.connect(slot)  # type: ignore[attr-defined]


class MgmtLoginGateDialog(QDialog):
    """未登录不可进入 IDE。多项目时在**同一对话框**内选项目，不用系统原生弹窗。"""

    _STEP_LOGIN = 0
    _STEP_PROJECT = 1
    _SEARCH_MIN_PROJECTS = 4
    # 一屏最多展示的项目行数，超出滚动（对齐 Slack/JetBrains 的工作区选择）
    _VISIBLE_PROJECT_ROWS = 5
    _ROW_GAP_PX = 4  # QSS 中 item margin 上下各 2px
    _LIST_PAD_PX = 8  # QSS 中 list padding 上下各 4px
    _FALLBACK_ROW_H = 52

    def __init__(self, parent=None, *, title: str = "登录") -> None:
        super().__init__(parent)
        self.setObjectName("login_gate_dialog")
        self.setWindowTitle(title)
        self.setFixedWidth(440)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        # 保留标题栏关闭按钮：Windows 即使去掉该 hint 也照样把 X 画出来，
        # 只是点不动，看着像坏了。关闭走 QDialog.reject()，与「退出应用」同义。
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)

        from ...runtime import settings
        from ...runtime.platform_deploy import platform_url_locked
        from ..branding import APP_NAME, APP_TAGLINE, app_icon
        from ..theme import apply_dialog_theme

        apply_dialog_theme(self, "login_gate")
        self.setWindowIcon(app_icon())
        self._app_name = APP_NAME

        self._ok = False
        self._busy = False
        self._locked = platform_url_locked()
        self._effective_url = settings.mc_server_url()
        self._url_visible = False
        self._logged_in_user = ""
        self._projects: list[dict[str, Any]] = []
        self._project_rows: list[_PickRow] = []
        self._centered_once = False
        self._freeze_depth = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 20)
        root.setSpacing(0)

        card = QFrame()
        card.setObjectName("login_card")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(28, 28, 28, 24)
        card_lay.setSpacing(0)

        # —— 品牌（两步共用）——
        brand_row = QHBoxLayout()
        brand_row.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(app_icon(52).pixmap(52, 52))
        logo.setFixedSize(52, 52)
        brand_row.addWidget(logo)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self._title_lbl = QLabel(APP_NAME)
        self._title_lbl.setObjectName("login_title")
        tagline_lbl = QLabel(APP_TAGLINE)
        tagline_lbl.setObjectName("login_tagline")
        title_col.addWidget(self._title_lbl)
        title_col.addWidget(tagline_lbl)
        brand_row.addLayout(title_col, 1)
        card_lay.addLayout(brand_row)
        card_lay.addSpacing(14)

        self._step_indicator = self._build_step_indicator()
        card_lay.addWidget(self._step_indicator)
        card_lay.addSpacing(12)

        self._session_strip = self._build_session_strip()
        card_lay.addWidget(self._session_strip)
        card_lay.addSpacing(8)

        self._stack = QStackedWidget()
        card_lay.addWidget(self._stack, 1)

        self._stack.addWidget(self._build_login_page(settings))
        self._stack.addWidget(self._build_project_page(settings))
        card_lay.addSpacing(12)

        self._error = QLabel("")
        self._error.setObjectName("login_error")
        self._error.setWordWrap(True)
        self._error.setVisible(False)
        card_lay.addWidget(self._error)
        card_lay.addSpacing(10)

        self._primary_btn = QPushButton("登录")
        self._primary_btn.setObjectName("login_primary_btn")
        self._primary_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _qt_connect(self._primary_btn.clicked, self._on_primary)
        card_lay.addWidget(self._primary_btn)
        card_lay.addSpacing(6)

        self._secondary_btn = QPushButton("退出应用")
        self._secondary_btn.setObjectName("login_exit_btn")
        self._secondary_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _qt_connect(self._secondary_btn.clicked, self._on_secondary)
        card_lay.addWidget(self._secondary_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        root.addWidget(card)
        self._show_step(self._STEP_LOGIN)

        if settings.mc_username():
            self.password.setFocus()
        else:
            self.username.setFocus()

        _qt_connect(self.username.textChanged, self._on_credentials_changed)
        _qt_connect(self.password.textChanged, self._on_credentials_changed)

    def _build_step_indicator(self) -> QWidget:
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self._step_login_lbl = QLabel("1  登录")
        self._step_login_lbl.setObjectName("step_crumb")
        self._step_sep = QLabel("›")
        self._step_sep.setObjectName("step_sep")
        self._step_project_lbl = QLabel("2  项目空间")
        self._step_project_lbl.setObjectName("step_crumb")
        lay.addWidget(self._step_login_lbl)
        lay.addWidget(self._step_sep)
        lay.addWidget(self._step_project_lbl)
        lay.addStretch(1)
        return wrap

    def _build_session_strip(self) -> QFrame:
        strip = QFrame()
        strip.setObjectName("session_strip")
        lay = QHBoxLayout(strip)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)
        self._session_user = QLabel("")
        self._session_user.setObjectName("session_user")
        self._session_platform = QLabel("")
        self._session_platform.setObjectName("session_platform")
        self._session_platform.setWordWrap(True)
        lay.addWidget(self._session_user)
        lay.addWidget(self._session_platform, 1)
        strip.setVisible(False)
        return strip

    def _build_login_page(self, settings) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._platform_chip = QFrame()
        self._platform_chip.setObjectName("platform_chip")
        chip_lay = QHBoxLayout(self._platform_chip)
        chip_lay.setContentsMargins(12, 10, 12, 10)
        chip_lay.setSpacing(8)
        chip_prefix = "企业 Platform" if self._locked else "Platform"
        self._chip_label = QLabel(chip_prefix)
        self._chip_label.setObjectName("platform_chip_label")
        self._chip_url = QLabel(self._effective_url)
        self._chip_url.setObjectName("platform_chip_url")
        self._chip_url.setWordWrap(True)
        chip_lay.addWidget(self._chip_label)
        chip_lay.addWidget(self._chip_url, 1)
        self._url_toggle = None
        if not self._locked:
            self._url_toggle = QPushButton("更改")
            self._url_toggle.setObjectName("link_btn")
            self._url_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
            _qt_connect(self._url_toggle.clicked, self._toggle_url_field)
            chip_lay.addWidget(self._url_toggle)
        lay.addWidget(self._platform_chip)
        lay.addSpacing(12)

        self._url_section = QWidget()
        url_sec_lay = QVBoxLayout(self._url_section)
        url_sec_lay.setContentsMargins(0, 0, 0, 0)
        url_sec_lay.setSpacing(6)
        url_lbl = QLabel("Platform 地址")
        url_lbl.setObjectName("field_label")
        stored = settings.mc_server_url_stored()
        self.url = QLineEdit(stored or self._effective_url)
        self.url.setPlaceholderText("http://127.0.0.1:8000")
        self._url_section.setVisible(False)
        url_sec_lay.addWidget(url_lbl)
        url_sec_lay.addWidget(self.url)
        lay.addWidget(self._url_section)
        if stored:
            self._show_url_field(initial=True)
        lay.addSpacing(4)

        user_lbl = QLabel("用户名")
        user_lbl.setObjectName("field_label")
        self.username = QLineEdit(settings.mc_username())
        self.username.setPlaceholderText("请输入用户名")
        _qt_connect(self.username.returnPressed, self._focus_password)
        lay.addWidget(user_lbl)
        lay.addWidget(self.username)
        lay.addSpacing(10)

        pwd_lbl = QLabel("密码")
        pwd_lbl.setObjectName("field_label")
        self.password = QLineEdit(settings.mc_password())
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("请输入密码")
        _qt_connect(self.password.returnPressed, self._on_primary)
        lay.addWidget(pwd_lbl)
        lay.addWidget(self.password)
        # 项目页更高：登录页多出的空间留在底部，避免输入框被拉伸变形
        lay.addStretch(1)
        return page

    def _build_project_page(self, settings) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        hint = QLabel("选择本次要使用的项目空间（可随时在「Platform 连接」中切换）：")
        hint.setObjectName("step_hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self._project_search = QLineEdit()
        self._project_search.setObjectName("project_search")
        self._project_search.setPlaceholderText("搜索项目名称或 ID…")
        self._project_search.setClearButtonEnabled(True)
        self._project_search.setVisible(False)
        _qt_connect(self._project_search.textChanged, self._filter_project_list)
        lay.addWidget(self._project_search)

        frame = QFrame()
        frame.setObjectName("list_pick_frame")
        frame_lay = QVBoxLayout(frame)
        frame_lay.setContentsMargins(0, 0, 0, 0)
        self._project_list = QListWidget()
        self._project_list.setObjectName("list_pick_list")
        self._project_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._project_list.setUniformItemSizes(False)
        self._project_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._project_list.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        # 逐像素滚动：长列表拖动/滚轮不再整行跳
        self._project_list.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self._project_list.setMinimumHeight(
            self._project_list_height(1)
        )
        _qt_connect(self._project_list.itemDoubleClicked, self._on_primary)
        _qt_connect(self._project_list.currentRowChanged, self._sync_project_rows)
        frame_lay.addWidget(self._project_list)
        lay.addWidget(frame, 1)

        self._project_count = QLabel("")
        self._project_count.setObjectName("project_count")
        self._project_count.setVisible(False)
        lay.addWidget(self._project_count)

        self._project_empty_hint = QLabel("没有匹配的项目")
        self._project_empty_hint.setObjectName("login_tagline")
        self._project_empty_hint.setVisible(False)
        lay.addWidget(self._project_empty_hint)
        _ = settings  # 构建时预读 settings，保持与旧接口一致
        return page

    def _project_list_height(self, rows: int) -> int:
        """列表可视高度：最多 ``_VISIBLE_PROJECT_ROWS`` 行，多出来的滚动查看。"""
        shown = max(1, min(int(rows or 1), self._VISIBLE_PROJECT_ROWS))
        row_h = self._FALLBACK_ROW_H
        if self._project_rows:
            row_h = self._project_rows[0].row_size_hint().height()
        return shown * (row_h + self._ROW_GAP_PX) + self._LIST_PAD_PX

    def _update_project_count(self, matched: int | None = None) -> None:
        total = len(self._project_rows)
        if total <= 1:
            self._project_count.setVisible(False)
            return
        if matched is None or matched == total:
            text = f"共 {total} 个项目空间"
            if total > self._VISIBLE_PROJECT_ROWS:
                text += " · 滚动或搜索查看更多"
        else:
            text = f"匹配 {matched} / {total} 个项目空间"
        self._project_count.setText(text)
        self._project_count.setVisible(True)

    def _populate_project_list(self, projects: list[dict[str, Any]]) -> None:
        from ...runtime import settings

        self._projects = list(projects or [])
        self._project_list.clear()
        self._project_rows.clear()
        self._project_search.clear()
        self._project_search.setVisible(
            len(self._projects) >= self._SEARCH_MIN_PROJECTS
        )

        current = settings.mc_project_id()
        pick_row = 0
        for i, p in enumerate(self._projects):
            pid = str((p or {}).get("id") or "").strip()
            if not pid:
                continue
            if pid == current:
                pick_row = len(self._project_rows)
            name = str((p or {}).get("name") or "").strip()
            subtitle = pid if name else ""
            if pid == current and len(self._projects) > 1:
                subtitle = f"上次使用 · {subtitle or pid}"
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, pid)
            row = _PickRow(name or pid, subtitle)
            item.setSizeHint(row.row_size_hint())
            self._project_list.addItem(item)
            self._project_list.setItemWidget(item, row)
            self._project_rows.append(row)
        self._project_list.setFixedHeight(
            self._project_list_height(len(self._project_rows))
        )
        if self._project_rows:
            self._project_list.setCurrentRow(pick_row)
            self._sync_project_rows(pick_row)
            item = self._project_list.item(pick_row)
            if item is not None:
                self._project_list.scrollToItem(
                    item, QAbstractItemView.ScrollHint.EnsureVisible
                )
        self._project_empty_hint.setVisible(False)
        self._update_project_count()

    def _filter_project_list(self, text: str) -> None:
        q = (text or "").strip().lower()
        visible = 0
        for i in range(self._project_list.count()):
            item = self._project_list.item(i)
            if item is None:
                continue
            pid = str(item.data(Qt.ItemDataRole.UserRole) or "").lower()
            row = self._project_rows[i] if i < len(self._project_rows) else None
            show = not q or q in pid or (row.matches_query(q) if row else False)
            item.setHidden(not show)
            if show:
                visible += 1
        self._project_empty_hint.setVisible(bool(q) and visible == 0)
        self._update_project_count(visible if q else None)
        if q and visible:
            cur = self._project_list.currentRow()
            cur_item = self._project_list.item(cur) if cur >= 0 else None
            if cur_item is None or cur_item.isHidden():
                for i in range(self._project_list.count()):
                    it = self._project_list.item(i)
                    if it is not None and not it.isHidden():
                        self._project_list.setCurrentRow(i)
                        break

    def _sync_project_rows(self, row: int) -> None:
        for i, w in enumerate(self._project_rows):
            w.set_selected(i == row)

    def _update_step_indicator(self, step: int) -> None:
        login_active = step == self._STEP_LOGIN
        for lbl, active in (
            (self._step_login_lbl, login_active),
            (self._step_project_lbl, not login_active),
        ):
            lbl.setProperty("active", "true" if active else "false")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)

    def _reference_center(self):
        """居中参考点：父窗口可见时用其中心，否则用当前屏幕中心。

        「退出登录」会先隐藏主窗口再弹门禁，此时必须回落到屏幕，
        否则窗口可能落在屏幕边角并在重定位时闪现。
        """
        parent = self.parentWidget()
        if parent is not None and parent.isVisible():
            return parent.frameGeometry().center()
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return None
        return screen.availableGeometry().center()

    def _center_dialog(self) -> None:
        """把窗口摆到参考中心并夹回可用区域内。"""
        center = self._reference_center()
        if center is None:
            return
        geo = self.frameGeometry()
        geo.moveCenter(center)
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            if geo.height() >= avail.height():
                geo.moveTop(avail.top())
            else:
                geo.moveTop(
                    max(avail.top(), min(geo.top(), avail.bottom() - geo.height()))
                )
            geo.moveLeft(
                max(avail.left(), min(geo.left(), avail.right() - geo.width()))
            )
        self.move(geo.topLeft())

    def _settle_geometry(self) -> None:
        """按当前内容定尺寸并摆到参考中心（不看冻结状态，供首帧与换步复用）。"""
        self.ensurePolished()
        lay = self.layout()
        if lay is not None:
            # 先重算布局：换页刚改过子控件尺寸约束时 sizeHint 仍是旧值，
            # 据此 resize 会被 Windows 以「小于窗口最小尺寸」拒绝并刷 setGeometry 警告。
            lay.activate()
        self.adjustSize()
        self._center_dialog()

    def setVisible(self, visible: bool) -> None:  # noqa: N802 — Qt 命名
        """首帧即就位。

        Windows 的 ``QWidget::show()`` 会先把原生窗口映射到屏幕，之后才派发 Show
        事件；若等到 ``showEvent`` 再定尺寸/居中，用户会先看到一个尚未布局的小窗口
        在屏幕左上角 (0,0) 闪一下。故必须在 ``super()`` 之前把几何算好。
        """
        if visible and not self._centered_once:
            self._centered_once = True
            self._settle_geometry()
        super().setVisible(visible)

    def showEvent(self, event) -> None:  # noqa: N802 — 兜底：非 setVisible 的显示路径
        super().showEvent(event)
        if not self._centered_once:
            self._centered_once = True
            self._settle_geometry()

    @contextmanager
    def _frozen_paint(self) -> Iterator[None]:
        """抑制中间帧重绘；可嵌套。

        最外层退出时先定几何再恢复重绘：无论嵌套多深都只重排一次、只上屏最终帧。
        """
        self._freeze_depth += 1
        if self._freeze_depth == 1:
            self.setUpdatesEnabled(False)
        try:
            yield
        finally:
            self._freeze_depth -= 1
            if self._freeze_depth <= 0:
                self._freeze_depth = 0
                if self.isVisible():
                    self._settle_geometry()
                self.setUpdatesEnabled(True)

    def _resettle(self) -> None:
        if self._freeze_depth or not self.isVisible():
            return
        self._settle_geometry()

    def _show_step(self, step: int) -> None:
        # 两步高度不同：冻结期改完，退出冻结时统一定位并重绘最终帧
        with self._frozen_paint():
            self._apply_step(step)

    def _apply_step(self, step: int) -> None:
        self._stack.setCurrentIndex(step)
        self._update_step_indicator(step)
        on_login = step == self._STEP_LOGIN
        self._session_strip.setVisible(not on_login)
        self._platform_chip.setVisible(on_login and not self._url_visible)
        self._url_section.setVisible(on_login and self._url_visible)

        if on_login:
            self.setWindowTitle(f"登录 · {self._app_name}")
            self._title_lbl.setText("登录到 Platform")
            self._primary_btn.setText("登录中…" if self._busy else "登录")
            self._secondary_btn.setText("退出应用")
        else:
            self.setWindowTitle(f"选择项目 · {self._app_name}")
            self._title_lbl.setText("选择项目空间")
            self._primary_btn.setText("进入 IDE")
            self._secondary_btn.setText("切换账号")
            user = self._logged_in_user or "—"
            self._session_user.setText(user)
            self._session_platform.setText(self._effective_url)

    def _on_secondary(self) -> None:
        from ...runtime import settings

        if self._stack.currentIndex() == self._STEP_PROJECT:
            settings.clear_mc_session()
            self._logged_in_user = ""
            self._clear_error()
            self._show_step(self._STEP_LOGIN)
            self.password.selectAll()
            self.password.setFocus()
            return
        self.reject()

    def _on_primary(self) -> None:
        if self._stack.currentIndex() == self._STEP_PROJECT:
            self._confirm_project()
        else:
            self._do_login()

    def _on_credentials_changed(self, _text: str = "") -> None:
        self._clear_error()

    def _focus_password(self) -> None:
        self.password.setFocus()

    def _show_url_field(self, *, initial: bool = False) -> None:
        self._url_visible = True
        if self._stack.currentIndex() == self._STEP_LOGIN:
            self._platform_chip.setVisible(False)
            self._url_section.setVisible(True)
        if self._url_toggle is not None:
            self._url_toggle.setText("收起")
        if not initial:
            self.url.setFocus()

    def _hide_url_field(self) -> None:
        self._url_visible = False
        if self._stack.currentIndex() == self._STEP_LOGIN:
            self._platform_chip.setVisible(True)
            self._url_section.setVisible(False)
        if self._url_toggle is not None:
            self._url_toggle.setText("更改")

    def _toggle_url_field(self) -> None:
        if self._url_visible:
            self._hide_url_field()
        else:
            self._show_url_field()

    def _clear_error(self) -> None:
        self._error.clear()
        self._error.setVisible(False)

    def _show_error(self, message: str) -> None:
        self._error.setText(message)
        self._error.setVisible(bool(message))

    @property
    def logged_in(self) -> bool:
        return self._ok

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        on_login = self._stack.currentIndex() == self._STEP_LOGIN
        self._primary_btn.setEnabled(not busy)
        if on_login:
            self._primary_btn.setText("登录中…" if busy else "登录")
        if self._url_toggle is not None:
            self._url_toggle.setEnabled(not busy)
        self.url.setEnabled(not busy)
        self.username.setEnabled(not busy)
        self.password.setEnabled(not busy)
        self.setCursor(
            Qt.CursorShape.WaitCursor if busy else Qt.CursorShape.ArrowCursor
        )

    def _finish_login(self, project_id: str = "") -> None:
        from ...runtime import settings

        settings.set_mc_project_id((project_id or "").strip())
        self._ok = True
        self.accept()

    def _confirm_project(self) -> None:
        row = self._project_list.currentRow()
        while row >= 0:
            item = self._project_list.item(row)
            if item is not None and not item.isHidden():
                break
            row -= 1
        if row < 0:
            for i in range(self._project_list.count()):
                item = self._project_list.item(i)
                if item is not None and not item.isHidden():
                    row = i
                    self._project_list.setCurrentRow(row)
                    break
        if row < 0:
            self._show_error("请选择一个项目空间")
            return
        item = self._project_list.item(row)
        pid = str(item.data(Qt.ItemDataRole.UserRole) or "").strip() if item else ""
        if not pid:
            self._show_error("项目无效，请重试")
            return
        self._finish_login(pid)

    def _do_login(self) -> None:
        if self._busy:
            return
        from ...mgmt import login_and_persist, mgmt_error_message
        from ...mgmt.client import MgmtClient
        from ...mgmt.project_context import fetch_visible_projects, resolve_login_project
        from ...runtime import settings
        from ..mgmt_http_worker import MgmtHttpWorker

        username = self.username.text().strip()
        password = self.password.text()
        if not username or not password:
            self._show_error("请填写用户名和密码")
            return

        self._clear_error()
        settings.clear_mc_session()
        persist_url = ""
        if not self._locked and self._url_visible:
            persist_url = self.url.text().strip()
        url = persist_url or self._effective_url
        self._effective_url = url
        self._set_busy(True)

        def work():
            login_and_persist(
                base_url=persist_url,
                username=username,
                password=password,
            )
            client = MgmtClient(url, jwt=settings.mc_jwt())
            try:
                return fetch_visible_projects(client)
            finally:
                client.close()

        worker = MgmtHttpWorker(work, self)
        loop = QEventLoop(self)
        box: dict = {}

        def on_done(payload) -> None:
            box["out"] = payload
            loop.quit()

        _qt_connect(worker.done, on_done)
        worker.start()
        loop.exec()
        worker.wait(2000)
        self._set_busy(False)

        out = box.get("out")
        if isinstance(out, Exception):
            self._show_error(mgmt_error_message(out))
            settings.clear_mc_session()
            self.password.selectAll()
            self.password.setFocus()
            return

        projects = list(out or [])
        self._logged_in_user = username
        try:
            project_id, need_picker = resolve_login_project(projects)
        except Exception as exc:
            self._show_error(mgmt_error_message(exc))
            settings.clear_mc_session()
            return

        if not need_picker:
            # 有唯一/缓存项目，或无可见项目：均可进入 IDE（后者管理台写入再拦截）
            self._finish_login(project_id or "")
            return

        with self._frozen_paint():
            self._populate_project_list(projects)
            self._show_step(self._STEP_PROJECT)
            self._clear_error()
        self._project_list.setFocus()
