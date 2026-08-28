"""欢迎与占位组件：当未打开任何工程时，提供优雅且功能丰富的仪表盘。

提供最近工程快捷打开、创建/打开工程快捷链接，采用专业、扁平的现代 IDE 风格。
"""

from __future__ import annotations

import os
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QListWidget, QListWidgetItem, QSizePolicy
)

from ..branding import APP_NAME, APP_TAGLINE, app_icon
from ..theme import apply_panel_theme, icon_color, init_panel_style
from ..actions import qicon
from ...runtime import settings


class WelcomePanel(QWidget):
    open_project_requested = pyqtSignal(str)
    open_project_dialog_requested = pyqtSignal()
    new_project_dialog_requested = pyqtSignal()
    new_case_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("welcome_panel")
        self._theme = "light"

        # 主布局
        main_lay = QVBoxLayout(self)
        main_lay.setContentsMargins(40, 40, 40, 40)
        main_lay.setSpacing(20)
        main_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 顶部弹性
        main_lay.addStretch(2)

        # 1. 顶部横幅 (Logo + 标题 + 副标题)
        header_widget = QWidget()
        header_lay = QHBoxLayout(header_widget)
        header_lay.setContentsMargins(0, 0, 0, 0)
        header_lay.setSpacing(16)
        header_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.logo_lbl = QLabel()
        self.logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_lay.addWidget(self.logo_lbl)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        title_col.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        title_lbl = QLabel(APP_NAME)
        title_lbl.setObjectName("welcome_title")
        sub_lbl = QLabel(APP_TAGLINE)
        sub_lbl.setObjectName("welcome_subtitle")

        title_col.addWidget(title_lbl)
        title_col.addWidget(sub_lbl)
        header_lay.addLayout(title_col)

        main_lay.addWidget(header_widget)

        # 间隔弹性
        main_lay.addStretch(1)

        # 2. 中间卡片区域 (开始 vs 最近打开)
        cards_widget = QWidget()
        cards_widget.setMaximumWidth(760)
        cards_widget.setMinimumWidth(500)
        cards_lay = QHBoxLayout(cards_widget)
        cards_lay.setContentsMargins(0, 0, 0, 0)
        cards_lay.setSpacing(24)

        # 左卡片: 开始
        self.left_card = QFrame()
        self.left_card.setObjectName("welcome_card")
        self.left_card.setFrameShape(QFrame.Shape.StyledPanel)
        left_lay = QVBoxLayout(self.left_card)
        left_lay.setContentsMargins(20, 20, 20, 20)
        left_lay.setSpacing(10)
        left_lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        start_title = QLabel("开始")
        start_title.setObjectName("section_title")
        left_lay.addWidget(start_title)

        self.btn_open = QPushButton("打开工程…")
        self.btn_open.setObjectName("action_btn")
        self.btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        # noinspection PyUnresolvedReferences
        self.btn_open.clicked.connect(self.open_project_dialog_requested.emit)

        self.btn_new = QPushButton("新建工程…")
        self.btn_new.setObjectName("action_btn")
        self.btn_new.setCursor(Qt.CursorShape.PointingHandCursor)
        # noinspection PyUnresolvedReferences
        self.btn_new.clicked.connect(self.new_project_dialog_requested.emit)

        self.btn_draft = QPushButton("新建草稿用例")
        self.btn_draft.setObjectName("action_btn")
        self.btn_draft.setCursor(Qt.CursorShape.PointingHandCursor)
        # noinspection PyUnresolvedReferences
        self.btn_draft.clicked.connect(self.new_case_requested.emit)

        left_lay.addWidget(self.btn_open)
        left_lay.addWidget(self.btn_new)
        left_lay.addWidget(self.btn_draft)
        left_lay.addStretch(1)

        # 右卡片: 最近打开
        self.right_card = QFrame()
        self.right_card.setObjectName("welcome_card")
        self.right_card.setFrameShape(QFrame.Shape.StyledPanel)
        right_lay = QVBoxLayout(self.right_card)
        right_lay.setContentsMargins(20, 20, 20, 16)
        right_lay.setSpacing(10)
        right_lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        recent_title = QLabel("最近打开")
        recent_title.setObjectName("section_title")
        right_lay.addWidget(recent_title)

        self.recent_list = QListWidget()
        self.recent_list.setObjectName("recent_list")
        self.recent_list.setCursor(Qt.CursorShape.PointingHandCursor)
        self.recent_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # noinspection PyUnresolvedReferences
        self.recent_list.itemClicked.connect(self._on_recent_clicked)
        right_lay.addWidget(self.recent_list, 1)

        self.clear_btn = QPushButton("清除历史")
        self.clear_btn.setObjectName("clear_btn")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # noinspection PyUnresolvedReferences
        self.clear_btn.clicked.connect(self._clear_recent_history)
        right_lay.addWidget(self.clear_btn, 0, Qt.AlignmentFlag.AlignRight)

        cards_lay.addWidget(self.left_card, 1)
        cards_lay.addWidget(self.right_card, 1)

        main_lay.addWidget(cards_widget, 0, Qt.AlignmentFlag.AlignCenter)

        # 底部弹性
        main_lay.addStretch(3)

        # 初始化主题样式
        self._theme = init_panel_style(self, "welcome_panel")
        self._refresh_icons()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh_recents()

    def refresh_recents(self) -> None:
        """刷新最近工程列表。"""
        self.recent_list.clear()
        recents = [p for p in settings.recent_projects() if os.path.isdir(p)]
        col = icon_color("tree_folder", self._theme)
        icon_folder = qicon("mdi6.folder-outline", color=col)

        if not recents:
            empty_item = QListWidgetItem("暂无最近打开的工程")
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            empty_item.setData(Qt.ItemDataRole.UserRole, "")
            self.recent_list.addItem(empty_item)
            self.clear_btn.hide()
            return

        self.clear_btn.show()
        for p in recents:
            name = os.path.basename(p) or p
            item = QListWidgetItem(icon_folder, name)
            item.setToolTip(p)
            item.setStatusTip(p)
            item.setData(Qt.ItemDataRole.UserRole, p)
            self.recent_list.addItem(item)

    def _on_recent_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and os.path.isdir(path):
            # noinspection PyUnresolvedReferences
            self.open_project_requested.emit(path)

    def _clear_recent_history(self) -> None:
        from ..confirm import confirm  # 延迟：仅点「清除历史」
        if not confirm(self, "确定要清除所有最近打开的工程记录吗？", "清除历史"):
            return
        settings.set_value("recent_projects", [])
        self.refresh_recents()

    def _refresh_icons(self) -> None:
        """根据当前主题刷新各组件图标。"""
        # 顶部大 Logo
        self.logo_lbl.setPixmap(app_icon(72).pixmap(72, 72))

        # 开始按钮图标
        col = icon_color("tool", self._theme)
        icon_open = qicon("mdi6.folder-open", color=col)
        icon_new = qicon("mdi6.folder-plus", color=col)
        icon_draft = qicon("mdi6.file-plus", color=col)

        if icon_open:
            self.btn_open.setIcon(icon_open)
            self.btn_open.setIconSize(QSize(16, 16))
        if icon_new:
            self.btn_new.setIcon(icon_new)
            self.btn_new.setIconSize(QSize(16, 16))
        if icon_draft:
            self.btn_draft.setIcon(icon_draft)
            self.btn_draft.setIconSize(QSize(16, 16))

        # 最近打开列表项图标
        self.refresh_recents()

    def apply_theme(self, theme: str) -> None:
        """响应主题切换；样式统一由 theme/qss_*.py 维护。"""
        self._theme = apply_panel_theme(self, "welcome_panel", theme)
        self._refresh_icons()
