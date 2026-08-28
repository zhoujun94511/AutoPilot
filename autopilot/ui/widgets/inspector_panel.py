"""控件检视器面板：设备截图(画框+点选) + 控件树 + 属性表 + 候选定位符。

render_snapshot(png, xml, platform) 为核心入口（离线可测）：解析快照→渲染截图与控件框、
填充控件树；点截图或点树节点互相联动并刷新右侧属性/候选定位符。
选中定位符可「复制 / 填入当前步骤 / 写入对象库」（通过信号交主窗口处理）。
"""

from __future__ import annotations

import threading
from typing import Optional, Callable

from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QRect, QThread, QBuffer, QPoint, QSize
from PyQt6.QtGui import QPixmap, QPen, QColor, QBrush, QImage
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem, QListWidget,
    QListWidgetItem, QRubberBand,
    QGraphicsView, QGraphicsScene, QGraphicsRectItem, QHeaderView, QApplication,
    QAbstractItemView, QSizePolicy, QStyledItemDelegate, QStyleOptionViewItem,
    QStackedWidget,
)

from .grip_splitter import GripSplitter
from .empty_state import EmptyState

# noinspection PyPep8Naming
from ...inspector import tree as T

_ROLE_NODE = Qt.ItemDataRole.UserRole
_ROLE_LOC = Qt.ItemDataRole.UserRole       # 候选定位符列表项里存放完整 loc 串

# 工作区空态：无快照时整区单一主空态；有快照未选中时仅右侧紧凑提示
_WORKSPACE_IDLE = "未取快照\n点「刷新快照」选择平台（Android / iOS / Web）"
_WORKSPACE_LOADING = "正在取快照…\n首次连接可能需初始化驱动，请稍候"
_DETAIL_NO_SEL = "点选控件查看属性\n可在截图或控件树中选择"


class _TreeNoElideDelegate(QStyledItemDelegate):
    """树节点不省略文本，配合横向滚动查看完整 resource-id。"""

    def initStyleOption(self, option: QStyleOptionViewItem, index) -> None:
        super().initStyleOption(option, index)
        option.textElideMode = Qt.TextElideMode.ElideNone


class SnapshotWorker(QThread):
    """后台取快照：避免首次连接新设备（如 Appium 装 uiautomator2）阻塞 GUI 假死。

    provider 在 worker 线程执行，故其内部日志须走线程安全的 logger 桥接，勿直接碰控件。"""
    done = pyqtSignal(object)        # 快照数据元组 (png, xml, platform, backend) 或 None

    def __init__(self, provider, parent=None) -> None:
        super().__init__(parent)
        self._provider = provider

    def run(self) -> None:
        # noinspection PyBroadException
        try:
            data = self._provider()
        except Exception:
            data = None
        # noinspection PyUnresolvedReferences
        self.done.emit(data)


class _DeviceView(QGraphicsView):
    """显示设备截图并支持点选；点中位置以「设备坐标」发出。
    框选模式下拖拽矩形，松手以「截图像素坐标」发出 regionSelected(用于图片定位裁剪)。"""
    deviceClicked = pyqtSignal(float, float)
    regionSelected = pyqtSignal(QRectF)        # 框选区域（场景=截图像素坐标系）

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self._scale = 1.0      # 截图像素 → 设备坐标 的换算（device = scene/scale）
        self._select_mode = False
        self._rubber = QRubberBand(QRubberBand.Shape.Rectangle, self.viewport())
        self._origin = QPoint()
        self.setMinimumWidth(200)
        self._scene_bg = {"light": "#f3f3f3", "dark": "#2d2d2d"}
        self.scene().setBackgroundBrush(QBrush(QColor(self._scene_bg["light"])))
        from .empty_state import EmptyState
        self._ph = EmptyState("mdi6.cellphone-screenshot", self)
        self._ph.hide()  # 检视器空态由面板整区主空态统一承载；镜像面板仍用 set_hint

    def apply_scene_theme(self, theme: str) -> None:
        from ..theme import THEME_DARK

        key = "dark" if theme == THEME_DARK else "light"
        self.scene().setBackgroundBrush(QBrush(QColor(self._scene_bg[key])))

    def set_hint(self, text) -> None:
        """空态占位：首行为标题、其余为说明；text 为空则隐藏。"""
        if text:
            title, _, hint = text.partition("\n")
            self._ph.show_state(title, hint)
            self._ph.setGeometry(self.rect())
            self._ph.show()
            self._ph.raise_()
        else:
            self._ph.hide()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if not self._ph.isHidden():
            self._ph.setGeometry(self.rect())

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._ph.setGeometry(self.rect())
        self.fit()    # 窗口缩放时重新贴合截图

    def apply_placeholder_theme(self, theme: str) -> None:
        self._ph.apply_theme(theme)

    def set_scale(self, scale: float) -> None:
        self._scale = scale or 1.0

    def set_select_mode(self, on: bool) -> None:
        """框选模式：拖拽矩形选区(供截图图片定位)，关闭则恢复点选控件。"""
        self._select_mode = bool(on)
        self.setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)

    def fit(self) -> None:
        """按比例把整张截图缩放贴合视图（KeepAspectRatio）。"""
        rect = self.scene().sceneRect()
        if not rect.isEmpty():
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def mousePressEvent(self, event) -> None:
        if self._select_mode:
            self._origin = event.pos()
            self._rubber.setGeometry(QRect(self._origin, self._origin))
            self._rubber.show()
            return
        p = self.mapToScene(event.pos())
        # noinspection PyUnresolvedReferences
        self.deviceClicked.emit(p.x() / self._scale, p.y() / self._scale)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._select_mode and self._rubber.isVisible():
            self._rubber.setGeometry(QRect(self._origin, event.pos()).normalized())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._select_mode and self._rubber.isVisible():
            self._rubber.hide()
            r = QRect(self._origin, event.pos()).normalized()
            # 视图坐标 → 场景(=截图像素)坐标
            tl = self.mapToScene(r.topLeft())
            br = self.mapToScene(r.bottomRight())
            rect = QRectF(tl, br).normalized()
            if rect.width() >= 5 and rect.height() >= 5:
                # noinspection PyUnresolvedReferences
                self.regionSelected.emit(rect)
            return
        super().mouseReleaseEvent(event)


class InspectorPanel(QWidget):
    fillStep = pyqtSignal(str)    # 把定位符填入当前步骤
    addToMap = pyqtSignal(str)    # 把定位符写入对象库
    cancelled = pyqtSignal()      # 终止快照且后台已收尾 → 请主窗口释放设备会话(端口/隧道/Appium)
    cropRequested = pyqtSignal(bytes)   # 框选截图裁剪出的 PNG 字节 → 请主窗口存入工程并生成 picture:: 定位

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("inspector_panel")
        self.snapshot_provider = None      # 主窗口注入：()-> (png_bytes, xml, platform, backend) | None
        self.before_refresh = None         # 主窗口注入：取快照前(GUI 线程)确认设备；返回 False 则中止
        self.has_session: Optional[Callable[[], bool]] = None  # 主窗口注入：是否有活跃检视会话
        self._idle_lbl = "未取快照（点「刷新快照」选平台）"
        self._snap_worker = None           # 异步取快照 worker（慢设备不阻塞 GUI）
        self._snap_cancelled = False       # 本次取快照是否被用户终止（终止后丢弃结果并释放会话）
        self._cancel_event = threading.Event()  # 协作取消：传给 IosDevicePrep / provider
        self._root: Optional[T.UiNode] = None
        self._platform = "android"
        self._backend = ""
        self._scale = 1.0
        self._rects: dict = {}             # id(node) -> QGraphicsRectItem
        self._locators: list = []
        self._current_node: Optional[T.UiNode] = None
        from ..theme import init_panel_style

        self._ui_theme = init_panel_style(self, "inspector_panel")
        self._png = b""                    # 当前快照 PNG 原始字节（供框选裁剪图片定位）
        self._pixmap_item = None           # 背景截图项（静态快照；实时操作见 MirrorPanel）

        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.btn_refresh = QPushButton("🔄 刷新快照")
        # noinspection PyUnresolvedReferences
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_cancel = QPushButton("■ 终止检视")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setToolTip(
            "取快照进行中：放弃本次取快照并中断慢初始化（WDA/隧道）；\n"
            "已有快照/会话：断开检视并释放设备（WDA/隧道/Appium）")
        # noinspection PyUnresolvedReferences
        self.btn_cancel.clicked.connect(self.cancel_refresh)
        self.btn_pick_img = QPushButton("◫ 框选图片定位")
        self.btn_pick_img.setCheckable(True)
        self.btn_pick_img.setEnabled(False)      # 有快照后才可用
        self.btn_pick_img.setToolTip(
            "在截图上拖拽框选区域，弹出另存为选择路径后生成 picture:: 图片定位")
        # noinspection PyUnresolvedReferences
        self.btn_pick_img.toggled.connect(self._on_pick_img_toggled)
        self.lbl = QLabel(self._idle_lbl)
        bar.addWidget(self.btn_refresh)
        bar.addWidget(self.btn_cancel)
        bar.addWidget(self.btn_pick_img)
        bar.addWidget(self.lbl, 1)
        root.addLayout(bar)

        self._workspace_hint = _WORKSPACE_IDLE
        self._workspace_ph = EmptyState("mdi6.cellphone-screenshot")
        self._workspace_ph.setObjectName("inspector_workspace_empty")
        # 主空态需可点穿到…实际无底层；取消透传以免误以为可点选
        self._workspace_ph.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        split = GripSplitter(
            Qt.Orientation.Horizontal,
            tooltip="拖动此处调整截图 / 控件树 / 属性 列宽",
        )
        self.view = _DeviceView()
        # noinspection PyUnresolvedReferences
        self.view.deviceClicked.connect(self._on_view_click)
        # noinspection PyUnresolvedReferences
        self.view.regionSelected.connect(self._on_region_selected)
        # 设备监控等仍写 view.set_hint：无快照时改写整区主空态，有快照时忽略覆盖层
        self._view_set_hint = self.view.set_hint
        self.view.set_hint = self._on_external_hint  # type: ignore[method-assign]
        split.addWidget(self.view)

        tree_host = QWidget()
        tree_host.setObjectName("inspector_tree_host")
        tree_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        tree_layout = QVBoxLayout(tree_host)
        tree_layout.setContentsMargins(8, 8, 8, 8)
        tree_layout.setSpacing(6)
        self._tree_label = QLabel("控件树")
        self._tree_label.setObjectName("inspector_section_label")
        tree_layout.addWidget(self._tree_label)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.tree.setItemDelegate(_TreeNoElideDelegate(self.tree))
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tree.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.tree.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.tree.setUniformRowHeights(True)
        tree_hdr = self.tree.header()
        tree_hdr.setStretchLastSection(False)
        tree_hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        # noinspection PyUnresolvedReferences
        self.tree.itemClicked.connect(self._on_tree_click)
        # noinspection PyUnresolvedReferences
        self.tree.itemExpanded.connect(lambda _item: self._sync_tree_horizontal_extent())
        tree_layout.addWidget(self.tree, 1)
        split.addWidget(tree_host)

        right = QWidget()
        right.setObjectName("inspector_right_host")
        right.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 8, 8, 8)
        rv.setSpacing(6)
        self._attrs_label = QLabel("属性")
        self._attrs_label.setObjectName("inspector_section_label")
        rv.addWidget(self._attrs_label)
        self._detail_stack = QWidget()
        self._detail_stack.setObjectName("inspector_detail_stack")
        detail_lay = QVBoxLayout(self._detail_stack)
        detail_lay.setContentsMargins(0, 0, 0, 0)
        detail_lay.setSpacing(6)
        self.attrs = QTableWidget(0, 2)
        self.attrs.setAlternatingRowColors(True)
        self.attrs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.attrs.setHorizontalHeaderLabels(["属性", "值"])
        self.attrs.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.attrs.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.attrs.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.attrs.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.attrs.verticalHeader().setVisible(False)
        detail_lay.addWidget(self.attrs, 1)
        self._loc_label = QLabel("候选定位符（按稳定性排序）")
        self._loc_label.setObjectName("inspector_section_label")
        detail_lay.addWidget(self._loc_label)
        self.loc_list = QListWidget()
        self.loc_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.loc_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.loc_list.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        detail_lay.addWidget(self.loc_list, 1)
        self._detail_ph = EmptyState("mdi6.cursor-default-click-outline", compact=True)
        self._detail_pages = QStackedWidget()
        self._detail_pages.setObjectName("inspector_detail_pages")
        self._detail_pages.addWidget(self._detail_stack)  # 0 = 内容
        self._detail_pages.addWidget(self._detail_ph)     # 1 = 紧凑空态
        rv.addWidget(self._detail_pages, 1)
        br = QHBoxLayout()
        self._detail_actions = []
        for text, slot in (("复制", self._copy), ("填入步骤", self._fill), ("写入对象库", self._to_map)):
            b = QPushButton(text)
            # noinspection PyUnresolvedReferences
            b.clicked.connect(slot)
            br.addWidget(b)
            self._detail_actions.append(b)
        rv.addLayout(br)
        split.addWidget(right)
        split.setSizes([320, 300, 360])
        self._split = split
        # noinspection PyUnresolvedReferences
        self._split.splitterMoved.connect(lambda *_: self._sync_split_pane_layout())

        self._body_stack = QStackedWidget()
        self._body_stack.setObjectName("inspector_body_stack")
        self._body_stack.addWidget(self._workspace_ph)  # 0 = 整区主空态
        self._body_stack.addWidget(self._split)         # 1 = 三栏工作区
        root.addWidget(self._body_stack, 1)
        self._sync_pane_empties()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_split_pane_layout()

    def _sync_split_pane_layout(self) -> None:
        """分割条/窗口缩放后：列宽至少铺满视口，避免斑马纹右侧露白。"""
        self._sync_tree_horizontal_extent()
        self._sync_attrs_layout()
        self._sync_loc_list_width()

    def _on_external_hint(self, text) -> None:
        """主窗口/设备监控写入的提示：无快照时更新整区主空态，不在左栏再叠一套。"""
        if text:
            self._workspace_hint = str(text)
        self._view_set_hint(None)
        self._sync_pane_empties(loading=self._snap_running())

    def _show_workspace_empty(self, text: str, *, icon: str = "") -> None:
        title, _, hint = str(text).partition("\n")
        self._workspace_ph.show_state(title, hint, icon=icon or "mdi6.cellphone-screenshot")
        self._body_stack.setCurrentIndex(0)

    def _show_workspace_split(self) -> None:
        self._body_stack.setCurrentIndex(1)
        self._view_set_hint(None)

    def _sync_pane_empties(self, *, loading: bool = False) -> None:
        """无快照→整区单一主空态；有快照→三栏工作区，未选中时仅右侧紧凑提示。"""
        if loading:
            self._show_workspace_empty(_WORKSPACE_LOADING, icon="mdi6.cellphone-screenshot")
            return
        if self.tree.topLevelItemCount() == 0:
            self._show_workspace_empty(self._workspace_hint or _WORKSPACE_IDLE)
            return
        self._show_workspace_split()
        if self.attrs.rowCount() == 0:
            title, _, hint = _DETAIL_NO_SEL.partition("\n")
            self._detail_ph.show_state(title, hint)
            self._detail_pages.setCurrentIndex(1)
        else:
            self._detail_pages.setCurrentIndex(0)

    @staticmethod
    def _pretty_platform(platform: str) -> str:
        return {
            "ios": "iOS",
            "android": "Android",
            "web": "Web",
        }.get((platform or "").strip().lower(), platform or "")

    @staticmethod
    def _pretty_backend(backend: str) -> str:
        return {
            "appium": "Appium",
            "wda": "WDA-direct",
        }.get((backend or "").strip().lower(), backend or "")

    def _snap_running(self) -> bool:
        w = getattr(self, "_snap_worker", None)
        return w is not None and w.isRunning()

    def _cancel_enabled(self) -> bool:
        if self._snap_running():
            return True
        if self.has_session is not None and self.has_session():
            return True
        return False

    def sync_cancel_btn(self) -> None:
        self.btn_cancel.setEnabled(self._cancel_enabled())

    def _clear_inspector_content(self, hint: str = "") -> None:
        self._root = None
        self._current_node = None
        self._png = b""
        self._rects.clear()
        self.tree.clear()
        self.attrs.setRowCount(0)
        self.loc_list.clear()
        self.btn_pick_img.setEnabled(False)
        self.btn_pick_img.setChecked(False)
        self.view.scene().clear()
        self.view.set_select_mode(False)
        if hint:
            self.view.set_hint(hint)
        self._sync_pane_empties()

    # ---- 取快照（异步，避免慢设备阻塞 GUI）----
    def refresh(self) -> None:
        if self.snapshot_provider is None:
            self.lbl.setText("无快照来源")
            return
        # 取快照前先在 GUI 线程确认目标设备（多设备时弹选，避免默认 Android）；中止则不取
        if self.before_refresh is not None and self.before_refresh() is False:
            self._abort_refresh_precheck()
            return
        if self._snap_running():
            self.lbl.setText("上一次取快照仍在收尾，请稍候…")
            return
        self._snap_cancelled = False
        self._cancel_event.clear()
        self.btn_refresh.setEnabled(False)
        self.sync_cancel_btn()
        self.lbl.setText("正在取快照…")
        self.view.set_hint("正在取快照…\n首次链接新设备可能需安装/初始化驱动（如 uiautomator2/WDA），请稍候")
        self._sync_pane_empties(loading=True)
        self._snap_worker = SnapshotWorker(self.snapshot_provider, self)
        # noinspection PyUnresolvedReferences
        self._snap_worker.done.connect(self._on_snapshot)
        self._snap_worker.start()

    @property
    def cancel_event(self) -> threading.Event:
        return self._cancel_event

    def _abort_refresh_precheck(self) -> None:
        """前置校验未通过：恢复空闲态，不启动 worker / Appium。"""
        self.lbl.setText(self._idle_lbl)
        self.sync_cancel_btn()
        self._sync_pane_empties()

    def cancel_refresh(self) -> None:
        """终止取快照（进行中）或断开当前检视会话（快照已显示后）。"""
        if self._snap_running():
            self._snap_cancelled = True
            self._cancel_event.set()
            self.btn_cancel.setEnabled(False)
            self.lbl.setText("已终止取快照（后台调用收尾中，稍候可再刷新）")
            self.view.set_hint("已终止取快照\n后台收尾后点「🔄 刷新快照」重试")
            self._sync_pane_empties()
            return
        if self.has_session is not None and self.has_session():
            self._cancel_event.set()
            self.btn_cancel.setEnabled(False)
            self.lbl.setText("正在释放检视会话…")
            # noinspection PyUnresolvedReferences
            self.cancelled.emit()
            self._clear_inspector_content(
                "检视已终止\n点「🔄 刷新快照」重选平台与目标")
            self.lbl.setText("检视已终止")
            self.sync_cancel_btn()
            return

    def _on_snapshot(self, data) -> None:
        # 仅处理「当前」worker 的结果（终止后的孤儿结果丢弃，但仍要在它结束时恢复按钮）
        worker = self.sender()
        self.btn_refresh.setEnabled(True)
        self.sync_cancel_btn()
        if worker is not None and worker is self._snap_worker:
            self._snap_worker = None
            # noinspection PyBroadException
            try:
                worker.deleteLater()
            except Exception:
                pass
        if self._snap_cancelled:
            self._snap_cancelled = False
            # 后台调用已收尾（不再用 driver）→ 此刻释放设备会话最安全，免端口/隧道残留
            # noinspection PyUnresolvedReferences
            self.cancelled.emit()
            self.view.set_hint("已终止取快照\n点「🔄 刷新快照」重新选择平台与目标")
            self._sync_pane_empties()
            self.sync_cancel_btn()
            return                       # 丢弃这次结果
        if not data:
            self.lbl.setText("当前无可检视的会话（先启动 App/浏览器）")
            self.view.set_hint("无可检视会话\n确认已连接设备/浏览器后再「🔄 刷新快照」")
            self._sync_pane_empties()
            return
        self.lbl.setText("")
        logical_size = None
        if len(data) >= 5:
            png, xml, platform, backend, logical_size = data
        elif len(data) >= 4:
            png, xml, platform, backend = data
        else:
            png, xml, platform = data
            backend = ""
        self.render_snapshot(png, xml, platform, backend, logical_size)

    def render_snapshot(
        self,
        png: bytes,
        xml: str,
        platform: str,
        backend: str = "",
        logical_size: Optional[dict] = None,
    ) -> None:
        """核心：解析快照 + 渲染截图/控件框 + 填充树（离线可直接调用）。"""
        self._platform = platform
        self._backend = backend or ""
        self._png = png or b""          # 留存原始截图，供框选裁剪图片定位
        self._root = T.parse_snapshot(xml, platform)
        self.btn_pick_img.setEnabled(bool(self._png))
        self.view.set_hint(None)        # 有快照了，隐藏占位
        trunc_note = ""
        if platform == "web" and xml:
            # noinspection PyBroadException
            try:
                import json as _json  # 延迟：仅 Web 快照读截断标记
                meta = _json.loads(xml)
                if meta.get("truncated"):
                    trunc_note = "｜节点已截断，请缩小页面或增大上限"
            except Exception:
                pass
        # 截图
        scene = self.view.scene()
        scene.clear()
        self._rects.clear()
        self._pixmap_item = None
        pm = QPixmap()
        if png:
            img = QImage.fromData(png)
            pm = QPixmap.fromImage(img)
        if not pm.isNull():
            self._pixmap_item = scene.addPixmap(pm)
        # 换算比例：按平台/backend 分支（Android≈1；iOS Appium 点↔像素；iOS WDA 保持原逻辑）
        self._scale = (
            T.compute_render_scale(
                platform,
                pm.width(),
                pm.height(),
                self._root,
                logical_size=logical_size,
                backend=self._backend,
            )
            if not pm.isNull()
            else 1.0
        )
        self.view.set_scale(self._scale)
        # 画每个控件框
        pen = QPen(QColor("#1565c0")); pen.setWidth(1)
        for n in self._root.iter_all():
            b = n.bounds
            if not b or b[2] <= 0 or b[3] <= 0:
                continue
            rect = QGraphicsRectItem(QRectF(b[0] * self._scale, b[1] * self._scale,
                                            b[2] * self._scale, b[3] * self._scale))
            rect.setPen(pen)
            scene.addItem(rect)
            self._rects[id(n)] = rect
        # 缩放贴合视图（截图按原始分辨率，需按比例自适应，否则只显示左上角一块）
        if self._pixmap_item is not None:
            scene.setSceneRect(self._pixmap_item.boundingRect())
            self.view.fit()
        # 填充树
        self.tree.clear()
        self._fill_tree(self._root, None)
        self.tree.expandToDepth(1)
        self._sync_tree_horizontal_extent()
        cnt = sum(1 for _ in self._root.iter_all())
        plat = self._pretty_platform(platform)
        back = self._pretty_backend(backend)
        tag = f"{plat} · {back}" if back else plat
        self.lbl.setText(f"平台：{tag} | {cnt} 个控件{trunc_note}")
        self.sync_cancel_btn()
        self._current_node = None
        self.attrs.setRowCount(0)
        self.loc_list.clear()
        self._sync_pane_empties()

    def _fill_tree(self, node: T.UiNode, parent_item) -> None:
        item = QTreeWidgetItem([node.label()])
        item.setData(0, _ROLE_NODE, id(node))
        if parent_item is None:
            self.tree.addTopLevelItem(item)
        else:
            parent_item.addChild(item)
        self._node_by_id = getattr(self, "_node_by_id", {})
        self._node_by_id[id(node)] = node
        for c in node.children:
            self._fill_tree(c, item)

    def _sync_tree_horizontal_extent(self) -> None:
        """列宽 = 文本宽 + 层级缩进，避免深层节点在视口内被省略号截断。"""
        if self.tree.topLevelItemCount() == 0:
            return
        fm = self.tree.fontMetrics()
        indent = self.tree.indentation()
        branch = 28   # 展开箭头与列内边距

        best_w = [120]

        def walk(item: QTreeWidgetItem) -> None:
            depth = 0
            parent = item.parent()
            while parent is not None:
                depth += 1
                parent = parent.parent()
            text = item.text(0)
            w = fm.horizontalAdvance(text) + depth * indent + branch
            best_w[0] = max(best_w[0], w)
            for ci in range(item.childCount()):
                walk(item.child(ci))

        for ti in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(ti))
        content_w = best_w[0]
        viewport_w = self.tree.viewport().width()
        # 内容更宽时保留横向滚动；视口更宽时拉满列宽，让交替行底色铺满
        self.tree.setColumnWidth(0, max(content_w, viewport_w))

    def _sync_attrs_layout(self) -> None:
        """属性表：值列至少铺满剩余视口；内容更长时仍可横向滚动。"""
        if self.attrs.rowCount() == 0:
            return
        fm = self.attrs.fontMetrics()
        content_w = fm.horizontalAdvance("值") + 16
        for row in range(self.attrs.rowCount()):
            item = self.attrs.item(row, 1)
            if item is not None:
                content_w = max(content_w, fm.horizontalAdvance(item.text()) + 24)
        self.attrs.resizeColumnToContents(0)
        col0 = self.attrs.columnWidth(0)
        avail = self.attrs.viewport().width() - col0 - 2
        if avail > 0:
            self.attrs.setColumnWidth(1, max(content_w, avail))

    def _sync_loc_list_width(self) -> None:
        """候选定位符行控件随列表视口拉宽，避免右侧留白。"""
        vw = max(0, self.loc_list.viewport().width() - 4)
        if vw <= 0:
            return
        for i in range(self.loc_list.count()):
            item = self.loc_list.item(i)
            if item is None:
                continue
            w = self.loc_list.itemWidget(item)
            if w is None:
                continue
            h = item.sizeHint().height()
            if h <= 0:
                h = w.sizeHint().height()
            item.setSizeHint(QSize(vw, h))
            w.setMinimumWidth(vw)

    # ---- 联动 ----
    def _select_node(self, node: Optional[T.UiNode]) -> None:
        if node is None:
            return
        self._current_node = node
        # 高亮截图框
        for nid, rect in self._rects.items():
            on = nid == id(node)
            pen = QPen(QColor("#e53935") if on else QColor("#1565c0"))
            pen.setWidth(2 if on else 1)
            rect.setPen(pen)
            rect.setBrush(QBrush(QColor(229, 57, 53, 40)) if on else QBrush(Qt.BrushStyle.NoBrush))
        # 属性表
        self.attrs.setRowCount(0)
        for k, v in node.attrs.items():
            r = self.attrs.rowCount()
            self.attrs.insertRow(r)
            self.attrs.setItem(r, 0, QTableWidgetItem(k))
            self.attrs.setItem(r, 1, QTableWidgetItem(str(v)))
        self._sync_attrs_layout()
        # 候选定位符
        self._locators = T.generate_locators(self._root, node, self._platform, self._backend)
        self.loc_list.clear()
        for i, (label, loc) in enumerate(self._locators):
            item = QListWidgetItem(self.loc_list)
            # 可视完全交给 itemWidget；loc 存 data 角色（供检索/测试/复制），不设可绘制文本，
            # 否则代理会把这段文字画在自定义行控件下层，与 chip/值标签重叠成“乱码”。
            item.setData(_ROLE_LOC, loc)
            item.setToolTip(loc)
            w = self._make_loc_row(label, loc, recommended=(i == 0))
            item.setSizeHint(w.sizeHint())
            self.loc_list.addItem(item)
            self.loc_list.setItemWidget(item, w)
        if self._locators:
            self.loc_list.setCurrentRow(0)
        self._sync_loc_list_width()
        self._sync_pane_empties()

    # 稳定性配色：唯一 id/name 最稳→绿；css→蓝；属性 xpath→琥珀；绝对 xpath→灰(脆)
    _LOC_STYLE = {
        "id": ("ID", "#1b5e20", "#e8f5e9"), "name": ("NAME", "#1b5e20", "#e8f5e9"),
        "css": ("CSS", "#0d47a1", "#e3f2fd"), "xpath": ("XPATH", "#8a5a00", "#fff3e0"),
        "predicate": ("PRED", "#00695c", "#e0f2f1"),
        "linktext": ("LINK", "#4527a0", "#ede7f6"),
        "abs": ("XPATH", "#5f6368", "#eceff1"),
        "runtime": ("RT", "#5f6368", "#f5f5f5"),
    }
    _LOC_STYLE_DARK = {
        "id": ("ID", "#a5d6a7", "#1b5e20"), "name": ("NAME", "#a5d6a7", "#1b5e20"),
        "css": ("CSS", "#90caf9", "#0d47a1"), "xpath": ("XPATH", "#ffcc80", "#5d4037"),
        "predicate": ("PRED", "#80cbc4", "#004d40"),
        "linktext": ("LINK", "#ce93d8", "#4a148c"),
        "abs": ("XPATH", "#bdbdbd", "#424242"),
        "runtime": ("RT", "#9e9e9e", "#424242"),
    }
    _STAR_BADGE = {
        "light": (
            "color:#b8860b; background:#fff8e1; border-radius:4px; "
            "padding:1px 6px; font-size:11px; font-weight:600;"),
        "dark": (
            "color:#ffd54f; background:#5d4037; border-radius:4px; "
            "padding:1px 6px; font-size:11px; font-weight:600;"),
    }
    _RUNTIME_BADGE = {
        "light": (
            "color:#5f6368; background:#f5f5f5; border-radius:4px; "
            "padding:1px 6px; font-size:11px;"),
        "dark": (
            "color:#bdbdbd; background:#424242; border-radius:4px; "
            "padding:1px 6px; font-size:11px;"),
    }

    def _loc_style_map(self) -> dict:
        from ..theme import THEME_DARK
        if self._ui_theme == THEME_DARK:
            return self._LOC_STYLE_DARK
        return self._LOC_STYLE

    def _make_loc_row(self, label: str, loc: str, recommended: bool) -> QWidget:
        prefix = loc.split("::", 1)[0] if "::" in loc else "xpath"
        if "[运行时]" in label:
            key = "runtime"
        else:
            key = "abs" if label.startswith("绝对") else prefix
        tag, fg, bg = self._loc_style_map().get(key, self._LOC_STYLE["xpath"])
        value = loc.split("::", 1)[1] if "::" in loc else loc
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(6, 3, 6, 3)
        row.setSpacing(6)
        chip = QLabel(tag)
        chip.setStyleSheet(
            f"background:{bg}; color:{fg}; border-radius:4px; padding:1px 6px; font-size:11px;")
        row.addWidget(chip, 0, Qt.AlignmentFlag.AlignTop)
        if recommended:
            star = QLabel("★ 推荐")
            star.setStyleSheet(self._STAR_BADGE.get(self._ui_theme, self._STAR_BADGE["light"]))
            row.addWidget(star, 0, Qt.AlignmentFlag.AlignTop)
        elif "[运行时]" in label:
            hint = QLabel("仅运行时回退")
            hint.setStyleSheet(
                self._RUNTIME_BADGE.get(self._ui_theme, self._RUNTIME_BADGE["light"]))
            hint.setToolTip("find_element 失败时会自动尝试；不建议作为用例首选定位符")
            row.addWidget(hint, 0, Qt.AlignmentFlag.AlignTop)
        val = QLabel(value)
        val.setObjectName("inspector_loc_value")
        val.setTextFormat(Qt.TextFormat.PlainText)
        val.setWordWrap(False)
        val.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Preferred)
        val.setToolTip(loc)
        row.addWidget(val, 1)
        return w

    def _on_tree_click(self, item: QTreeWidgetItem, _col: int) -> None:
        node = getattr(self, "_node_by_id", {}).get(item.data(0, _ROLE_NODE))
        self._select_node(node)

    def _on_view_click(self, x: float, y: float) -> None:
        if self._root is None:
            return
        node = T.hit_test(self._root, int(x), int(y))
        self._select_node(node)
        # 同步选中树节点
        if node is not None:
            self._select_tree_item(id(node))

    def _select_tree_item(self, nid: int) -> None:
        it = self.tree.invisibleRootItem()

        def walk(parent):
            for i in range(parent.childCount()):
                c = parent.child(i)
                if c.data(0, _ROLE_NODE) == nid:
                    return c
                r = walk(c)
                if r:
                    return r
            return None
        found = walk(it)
        if found:
            self.tree.setCurrentItem(found)
            self.tree.scrollToItem(found, QAbstractItemView.ScrollHint.EnsureVisible)

    # ---- 选中定位符的动作 ----
    def _current_locator(self) -> str:
        r = self.loc_list.currentRow()
        if 0 <= r < len(self._locators):
            return self._locators[r][1]
        return ""

    def _copy(self) -> None:
        loc = self._current_locator()
        if loc:
            QApplication.clipboard().setText(loc)

    def _fill(self) -> None:
        loc = self._current_locator()
        if loc:
            # noinspection PyUnresolvedReferences
            self.fillStep.emit(loc)

    def _to_map(self) -> None:
        loc = self._current_locator()
        if loc:
            # noinspection PyUnresolvedReferences
            self.addToMap.emit(loc)

    # ---- 框选图片定位 ----
    def _on_pick_img_toggled(self, on: bool) -> None:
        self.view.set_select_mode(on)
        if on:
            self.lbl.setText("框选图片定位：在截图上拖拽选取目标区域")

    def crop_region(self, rect: QRectF) -> bytes:
        """按场景(=截图像素)矩形从当前 PNG 裁出子图，返回 PNG 字节（纯逻辑，可测）。"""
        if not self._png:
            return b""
        img = QImage.fromData(self._png)
        if img.isNull():
            return b""
        r = QRect(int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height()))
        r = r.intersected(img.rect())
        if r.width() < 1 or r.height() < 1:
            return b""
        buf = QBuffer()
        buf.open(QBuffer.OpenModeFlag.WriteOnly)
        img.copy(r).save(buf, "PNG")
        return bytes(buf.data())

    def _on_region_selected(self, rect: QRectF) -> None:
        self.btn_pick_img.setChecked(False)     # 选完即退出框选模式
        data = self.crop_region(rect)
        if not data:
            self.lbl.setText("框选区域无效，请重试")
            return
        # noinspection PyUnresolvedReferences
        self.cropRequested.emit(data)

    def apply_theme(self, theme: str) -> None:
        from ..theme import apply_panel_theme, resolve_theme

        self._ui_theme = resolve_theme(theme)
        apply_panel_theme(self, "inspector_panel", self._ui_theme)
        self.view.apply_scene_theme(self._ui_theme)
        self.view.apply_placeholder_theme(self._ui_theme)
        self._workspace_ph.apply_theme(self._ui_theme)
        self._detail_ph.apply_theme(self._ui_theme)
        self._split.update()
        if self._current_node is not None:
            self._select_node(self._current_node)
