"""右侧辅区：编辑区与设备区分栏，各用 ViewTabStack 切换视图。

对标 Eclipse/VS Code「视图在固定容器内切换」：
  - 上区（编辑）：关键字库 | 参数
  - 下区（设备）：控件检视器 | 实时镜像
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt, QByteArray
from PyQt6.QtGui import QShowEvent
from PyQt6.QtWidgets import QWidget, QVBoxLayout

from .grip_splitter import GripSplitter
from .chrome.view_tab_stack import ViewTabStack
from .chrome.auxiliary_toolbar import AuxiliaryRegionToolbar

_VIEW_KEYWORD = "keyword"
_VIEW_PARAM = "param"
_VIEW_INSPECTOR = "inspector"
_VIEW_MIRROR = "mirror"

_DEFAULT_SPLIT = (360, 440)
_EXPAND_DEVICE_RATIO = 0.28
_MIN_PANE_PX = 40


class RightAuxiliaryRegion(QWidget):
    """右侧辅区容器：顶栏 chrome + 上下 Splitter + 两组 Tab。"""

    def __init__(
        self,
        keyword_panel: QWidget,
        param_form: QWidget,
        inspector: QWidget,
        mirror: QWidget,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("right_auxiliary_region")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._toolbar = AuxiliaryRegionToolbar()
        self._toolbar.expandDeviceRequested.connect(self.expand_device_area)
        self._toolbar.resetSplitRequested.connect(self.reset_split)
        root.addWidget(self._toolbar)

        self._splitter = GripSplitter(
            Qt.Orientation.Vertical,
            tooltip="拖动此处调整「编辑区 / 设备区」高度",
        )

        self._edit_stack = ViewTabStack((
            (_VIEW_KEYWORD, "关键字库", keyword_panel),
            (_VIEW_PARAM, "参数", param_form),
        ))
        self._device_stack = ViewTabStack((
            (_VIEW_INSPECTOR, "控件检视器", inspector),
            (_VIEW_MIRROR, "实时镜像", mirror),
        ))

        self._splitter.addWidget(self._edit_stack)
        self._splitter.addWidget(self._device_stack)
        self._splitter.setStretchFactor(0, 4)
        self._splitter.setStretchFactor(1, 6)
        root.addWidget(self._splitter, 1)

    def activate_view(self, view_id: str) -> None:
        if view_id in (_VIEW_KEYWORD, _VIEW_PARAM):
            self._edit_stack.activate(view_id)
        elif view_id in (_VIEW_INSPECTOR, _VIEW_MIRROR):
            self._device_stack.activate(view_id)

    def current_device_view(self) -> str:
        vid = self._device_stack.current_view_id()
        return vid if vid else _VIEW_INSPECTOR

    def device_tab_index(self) -> int:
        return self._device_stack.tab_index()

    def reset_split(self) -> None:
        self._splitter.setSizes(list(_DEFAULT_SPLIT))

    def expand_device_area(self) -> None:
        total = max(self._splitter.height(), sum(_DEFAULT_SPLIT))
        top = max(120, int(total * _EXPAND_DEVICE_RATIO))
        self._splitter.setSizes([top, max(160, total - top)])

    def save_split(self) -> list[int]:
        return list(self._splitter.sizes())

    def restore_split(self, sizes: list[int]) -> None:
        if sizes and len(sizes) >= 2 and sizes[0] > 40 and sizes[1] > 40:
            self._splitter.setSizes(sizes[:2])
        else:
            self.reset_split()

    def save_state(self) -> QByteArray:
        return self._splitter.saveState()

    def restore_state(self, data: Optional[QByteArray]) -> None:
        if data is not None and not data.isEmpty():
            self._splitter.restoreState(data)
        else:
            self.reset_split()
        self._ensure_valid_split()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._ensure_valid_split()

    def _ensure_valid_split(self) -> None:
        """分割条在控件尚未布局时 restore/setSizes 可能失效，显示后再校验一次。"""
        sizes = self._splitter.sizes()
        if len(sizes) < 2 or sizes[0] < _MIN_PANE_PX or sizes[1] < _MIN_PANE_PX:
            self.reset_split()

    def apply_theme(self, theme: str) -> None:
        from ..theme import apply_panel_theme, resolve_theme

        resolved = resolve_theme(theme)
        apply_panel_theme(self, "auxiliary_region", resolved)
        self._toolbar.apply_theme(theme)
        self._splitter.update()
