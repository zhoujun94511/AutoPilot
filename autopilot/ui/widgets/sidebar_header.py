"""侧栏上下文条：显示当前工程文件夹名。"""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel

from ..theme import init_panel_style


class SidebarContextBar(QWidget):
    """工程视图下的一行上下文（工程文件夹名）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar_context")
        init_panel_style(self, "sidebar_context")
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 2, 8, 6)
        root.setSpacing(0)
        self._label = QLabel("未打开工程")
        self._label.setObjectName("sidebar_context_label")
        self._label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self._label, 1)

    def set_project(self, project_dir: str = "") -> None:
        self.show()
        if project_dir and os.path.isdir(project_dir):
            name = os.path.basename(project_dir.rstrip("/\\")) or project_dir
            self._label.setText(name)
            self._label.setToolTip(project_dir)
        else:
            self._label.setText("未打开工程")
            self._label.setToolTip("")

    def apply_theme(self, theme: str) -> None:
        from ..theme import apply_panel_theme

        apply_panel_theme(self, "sidebar_context", theme)


# 兼容旧引用
SidebarHeader = SidebarContextBar
