"""GripSplitter 手柄宽度与握把渲染（离屏）。"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_APP = None


def test_grip_splitter_handle_width() -> None:
    global _APP
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QWidget
    from autopilot.ui.widgets.grip_splitter import GripSplitter

    _APP = QApplication.instance() or QApplication([])
    h = GripSplitter(Qt.Orientation.Horizontal)
    h.addWidget(QWidget())
    h.addWidget(QWidget())
    h.show()
    _APP.processEvents()
    assert h.handleWidth() >= 8
    assert h.count() == 2
