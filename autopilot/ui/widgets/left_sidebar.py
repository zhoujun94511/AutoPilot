"""左侧侧栏：工程浏览器（工程名见窗口标题，此处不再重复）。"""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget, QVBoxLayout


class LeftSidebar(QWidget):
    """工程文件树；文件名筛选见 ProjectPanel.filter。"""

    def __init__(self, project_panel: QWidget, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("left_sidebar")
        self._project_dir = ""
        self._project_panel = project_panel
        self._ui_theme = ""

        from ..theme import init_panel_style

        init_panel_style(self, "left_sidebar")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(project_panel, 1)

    def set_project_dir(self, directory: str) -> None:
        """保留接口供主窗口同步工程路径（侧栏 UI 不再展示工程名）。"""
        self._project_dir = directory or ""

    def apply_theme(self, theme: str) -> None:
        from ..theme import apply_panel_theme, resolve_theme

        self._ui_theme = resolve_theme(theme)
        apply_panel_theme(self, "left_sidebar", self._ui_theme)
        if hasattr(self._project_panel, "apply_theme"):
            self._project_panel.apply_theme(theme)
