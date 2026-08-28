"""右侧辅区组件回归（离屏）。"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_APP = None


def test_auxiliary_region_split_views() -> None:
    from PyQt6.QtWidgets import QApplication, QWidget
    global _APP
    _APP = QApplication.instance() or QApplication([])
    from autopilot.ui.widgets.auxiliary_region import RightAuxiliaryRegion

    kw, param, insp, mir = QWidget(), QWidget(), QWidget(), QWidget()
    aux = RightAuxiliaryRegion(kw, param, insp, mir)
    aux.activate_view("mirror")
    assert aux.device_tab_index() == 1
    aux.activate_view("param")
    assert aux.device_tab_index() == 1
    aux.activate_view("inspector")
    assert aux.device_tab_index() == 0


def test_auxiliary_region_restores_both_panes_after_show() -> None:
    from PyQt6.QtWidgets import QApplication, QWidget
    global _APP
    _APP = QApplication.instance() or QApplication([])
    from autopilot.ui.widgets.auxiliary_region import RightAuxiliaryRegion

    kw, param, insp, mir = QWidget(), QWidget(), QWidget(), QWidget()
    aux = RightAuxiliaryRegion(kw, param, insp, mir)
    aux.resize(400, 800)
    aux.show()
    _APP.processEvents()
    sizes = aux._splitter.sizes()
    assert len(sizes) == 2
    assert sizes[0] >= 40 and sizes[1] >= 40
