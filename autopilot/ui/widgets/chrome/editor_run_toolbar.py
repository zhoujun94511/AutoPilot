"""当前用例运行控件：贴编辑器标签栏，F5 / 暂停 / 停止。"""

from __future__ import annotations

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QToolButton

_RUN_ACTION_IDS = ("run.case", "run.pause", "run.stop")


class EditorRunToolbar:
    """标签栏右侧紧凑运行条（绑定全局 QAction，与菜单/快捷键一致）。"""

    def __init__(self, actions: dict[str, QAction], parent: QWidget | None = None) -> None:
        self.widget = QWidget(parent)
        self.widget.setObjectName("editor_run_toolbar")
        lay = QHBoxLayout(self.widget)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(2)
        for aid in _RUN_ACTION_IDS:
            btn = QToolButton(self.widget)
            btn.setDefaultAction(actions[aid])
            btn.setAutoRaise(True)
            lay.addWidget(btn)
