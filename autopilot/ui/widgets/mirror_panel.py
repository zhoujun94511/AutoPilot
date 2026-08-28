"""实时交互镜像面板：看真机画面 + 直接操作（点/拖/长按/双击/输入/系统键/剪贴板）。

与控件检视器(InspectorPanel)职责隔离：这里点屏幕=操作设备；Inspector 点屏幕=选控件。

按钮**组件化、按平台能力数据驱动**：面板按 `control.capabilities()` 只显示该平台能做的
系统键/面板/旋转/电源/剪贴板按钮（Android 与 iOS 能力不同，按钮自然不同）。

控制调用走后台分发线程（顺序队列，不丢动作），避免 WDA(~0.8s 串行)阻塞 GUI。

主窗口注入 session_provider() -> (platform, opts, control_sink|None)。
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QTimer
from PyQt6.QtGui import QPixmap, QBrush, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QToolButton, QLabel, QLineEdit,
    QGraphicsView, QGraphicsScene,
)

from ..actions import qicon
from ..theme import icon_color

_DRAG_THRESH = 12.0     # 场景像素：超过判为滑动
_LONG_PRESS_MS = 450    # 按住不放达此时长 → 长按


def _pretty_stream_tag(src_name: str) -> str:
    """把内部帧源名转成用户可读文案。"""
    if src_name.startswith("avf"):
        return "AVFoundation 高帧" + ("（截图兜底）" if "fallback" in src_name else "")
    if src_name.startswith("mjpeg"):
        return "MJPEG 9100" + ("（截图兜底）" if "fallback" in src_name else "")
    if src_name == "polling" or src_name == "polling-fallback":
        return "截图轮询"
    return src_name

# 系统键/面板按钮注册表：能力键 → (qtawesome 图标, 提示, 传给 control.key 的名)
_BUTTONS = [
    ("back", "mdi6.arrow-left", "返回"),
    ("home", "mdi6.circle-outline", "主屏"),
    ("recents", "mdi6.square-outline", "最近任务"),
    ("notifications", "mdi6.bell-outline", "通知栏"),
    ("settings", "mdi6.cog-outline", "快捷设置"),
    ("collapse", "mdi6.chevron-up", "收起面板"),
    ("rotate", "mdi6.screen-rotation", "旋转"),
    ("volume_up", "mdi6.volume-plus", "音量+"),
    ("volume_down", "mdi6.volume-minus", "音量-"),
    ("power", "mdi6.power", "电源/唤醒"),
    ("lock", "mdi6.lock-outline", "锁屏"),
    ("screenshot", "mdi6.camera-outline", "设备截图"),
]

# 超过此秒数无新帧 → 视为「静默断流」（画面冻在最后一帧但控制/WDA 仍可用）
_STALE_FRAME_SEC = 12.0
_STALE_CHECK_MS = 4000


class _Dispatcher:
    """后台顺序执行控制动作（不丢、不阻塞 GUI）。"""

    def __init__(self, on_error=None) -> None:
        self._q: "queue.Queue" = queue.Queue()
        self._on_error = on_error
        self._t = threading.Thread(target=self._run, daemon=True)
        self._alive = True
        self._t.start()

    def submit(self, fn) -> None:
        self._q.put(fn)

    def _run(self) -> None:
        while self._alive:
            fn = self._q.get()
            if fn is None:
                break
            # noinspection PyBroadException
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                logging.getLogger("autopilot.mirror").warning("镜像控制失败：%s", e)
                if self._on_error is not None:
                    self._on_error(str(e))

    def stop(self) -> None:
        self._alive = False
        self._q.put(None)
        t = self._t
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=2.0)


class _MirrorView(QGraphicsView):
    """显示实时帧并把鼠标手势以「帧像素坐标」发出。"""
    pressed = pyqtSignal(QPointF)
    released = pyqtSignal(QPointF)
    doubleClicked = pyqtSignal(QPointF)
    scrolled = pyqtSignal(QPointF, float, float)
    textInput = pyqtSignal(str)        # 输入法提交的文本（中文等，经 inputMethodEvent）

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setMinimumWidth(220)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)  # 接收 IME（中文）
        self._scene_bg = {"light": "#f3f3f3", "dark": "#2d2d2d"}
        self.scene().setBackgroundBrush(QBrush(QColor(self._scene_bg["light"])))
        from .empty_state import EmptyState
        self._ph = EmptyState("mdi6.cellphone-play", self)
        self.set_hint("未开始\n点「▶ 开始」镜像并操作真机")

    def inputMethodEvent(self, e) -> None:
        """输入法提交的文本（中文/emoji 等）——keyPressEvent 收不到，须在此接。"""
        s = e.commitString()
        if s:
            # noinspection PyUnresolvedReferences
            self.textInput.emit(s)
        e.accept()

    def apply_scene_theme(self, theme: str) -> None:
        from ..theme import THEME_DARK

        key = "dark" if theme == THEME_DARK else "light"
        self.scene().setBackgroundBrush(QBrush(QColor(self._scene_bg[key])))

    def set_hint(self, text) -> None:
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

    def placeholder_visible(self) -> bool:
        return not self._ph.isHidden()

    def apply_placeholder_theme(self, theme: str) -> None:
        self._ph.apply_theme(theme)

    def _scene(self, pos) -> QPointF:
        return self.mapToScene(pos)

    def mousePressEvent(self, e) -> None:
        # noinspection PyUnresolvedReferences
        self.pressed.emit(self._scene(e.pos()))

    def mouseReleaseEvent(self, e) -> None:
        # noinspection PyUnresolvedReferences
        self.released.emit(self._scene(e.pos()))

    def mouseDoubleClickEvent(self, e) -> None:
        # noinspection PyUnresolvedReferences
        self.doubleClicked.emit(self._scene(e.pos()))

    def wheelEvent(self, e) -> None:
        d = e.angleDelta()
        # noinspection PyUnresolvedReferences
        self.scrolled.emit(self._scene(e.position().toPoint()), d.x(), d.y())


class MirrorPanel(QWidget):
    sessionEnded = pyqtSignal()
    videoFirstFrame = pyqtSignal()   # 高帧画面首帧 → 启 WDA（ws-scrcpy 顺序）

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("mirror_panel")
        self.session_provider = None
        self.before_start = None           # 主窗口注入：开始前(GUI 线程)确认真机；返回 False 则中止
        self.video_fallback = None   # (reason) -> bool；高帧画面失败时重试/回退 MJPEG，返回 True 则不整镜停止
        self._mobile_available = False
        self._platform = "android"
        self._source = None
        self._control = None
        self._disp: Optional[_Dispatcher] = None
        self._pixmap_item = None
        self._frame_size = (0, 0)
        self._last_frame = None          # 最近一帧 QImage，供「设备截图」保存
        self._stream_tag = ""
        self._wait_first_frame = False
        self._first_frame_emitted = False
        self._got_real_frame = False
        self._stopping = False
        self._first_frame_timer = QTimer(self)
        self._first_frame_timer.setSingleShot(True)
        # noinspection PyUnresolvedReferences
        self._first_frame_timer.timeout.connect(self._on_first_frame_deadline)
        self._press_pt: Optional[QPointF] = None
        self._pressed = False
        self._lp_fired = False
        self._lp_timer = QTimer(self)
        self._lp_timer.setSingleShot(True)
        # noinspection PyUnresolvedReferences
        self._lp_timer.timeout.connect(self._on_long_press)
        self._last_frame_at = 0.0
        self._stale_recovering = False
        self._stale_frame_timer = QTimer(self)
        # noinspection PyUnresolvedReferences
        self._stale_frame_timer.timeout.connect(self._on_stale_frame_check)

        root = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.btn_live = QPushButton("▶ 开始")
        self.btn_live.setCheckable(True)
        self.btn_live.setEnabled(False)
        self.btn_live.setToolTip("未检测到真机，插入并授权后再试")
        # noinspection PyUnresolvedReferences
        self.btn_live.toggled.connect(self._toggle)
        self.lbl = QLabel("未连接（点▶开始）")
        bar.addWidget(self.btn_live)
        bar.addWidget(self.lbl, 1)
        root.addLayout(bar)

        # 设备控制按钮条（按能力数据驱动填充）
        self.btn_bar = QHBoxLayout()
        self.btn_bar.setSpacing(4)
        root.addLayout(self.btn_bar)

        # 剪贴板行
        self.clip_row = QHBoxLayout()
        self.clip_edit = QLineEdit()
        self.clip_edit.setPlaceholderText("输入文本，点「发送」写入设备剪贴板并粘贴")
        self.btn_clip_set = QPushButton("发送")
        self.btn_clip_get = QPushButton("读取")
        # noinspection PyUnresolvedReferences
        self.btn_clip_set.clicked.connect(self._send_clipboard)
        # noinspection PyUnresolvedReferences
        self.btn_clip_get.clicked.connect(self._read_clipboard)
        self.clip_row.addWidget(self.clip_edit, 1)
        self.clip_row.addWidget(self.btn_clip_set)
        self.clip_row.addWidget(self.btn_clip_get)
        root.addLayout(self.clip_row)

        self.view = _MirrorView()
        # noinspection PyUnresolvedReferences
        self.view.pressed.connect(self._on_press)
        # noinspection PyUnresolvedReferences
        self.view.released.connect(self._on_release)
        # noinspection PyUnresolvedReferences
        self.view.doubleClicked.connect(self._on_double)
        # noinspection PyUnresolvedReferences
        self.view.scrolled.connect(self._on_scroll)
        # noinspection PyUnresolvedReferences
        self.view.textInput.connect(self._on_text_input)
        root.addWidget(self.view, 1)
        self._clear_buttons()
        self._fail_is_handoff = lambda: False

        from ..theme import init_panel_style

        self._ui_theme = init_panel_style(self, "mirror_panel")

    def _sync_idle_label(self, *, stopped: bool = False) -> None:
        """非运行态状态栏：停止后勿残留「实时操作中」。"""
        if self.active():
            return
        if not self._mobile_available:
            self.lbl.setText("未连接（无可用真机）")
        elif stopped:
            self.lbl.setText("已停止")
        else:
            self.lbl.setText("点 ▶ 开始实时镜像")

    # ---- 对外（供主窗口查询/控制，避免外部访问私有属性）----
    def active(self) -> bool:
        return self._source is not None

    def platform_name(self) -> str:
        return self._platform

    def request_start(self) -> None:
        """程序化开始镜像（已连接设备枢纽等入口）；已在跑则忽略。"""
        if self.active():
            return
        self.btn_live.blockSignals(True)
        self.btn_live.setChecked(True)
        self.btn_live.blockSignals(False)
        self._start()

    def stop(self) -> None:
        self._stop()

    def attach_control(self, control) -> None:
        """控制会话晚于画面就绪时注入（如高帧画面先开播、WDA 后建）。"""
        if control is None:
            return
        self._control = control
        self._wait_first_frame = False
        if self._disp is None:
            self._disp = _Dispatcher(on_error=self._on_control_error)
        tag = self._stream_tag or "镜像"
        self.lbl.setText(
            f"实时操作中（{tag}·可控制）｜点=轻触 拖=滑动 双击 长按 滚轮=滚动 键盘=输入")
        self._populate_buttons()
        if self._pixmap_item is not None or (
                getattr(self, "_last_frame", None) is not None
                and not getattr(self._last_frame, "isNull", lambda: True)()):
            self.view.set_hint(None)

    def swap_video(self, platform: str, opts: dict, control=None) -> bool:
        """切换帧源（如高帧→MJPEG），不触发 sessionEnded、不关 WDA。"""
        from ...inspector.stream.factory import make_source, describe_source
        new_src = make_source(platform, opts)
        if new_src is None:
            return False
        old = self._source
        if old is not None:
            # noinspection PyBroadException
            try:
                old.frame.disconnect(self._on_frame)
                old.failed.disconnect(self._on_failed)
                if hasattr(old, "mode_changed"):
                    old.mode_changed.disconnect(self._on_stream_mode)
            except Exception:
                pass
            # noinspection PyBroadException
            try:
                old.stop()
            except Exception:
                pass
        self._source = new_src
        # noinspection PyUnresolvedReferences
        new_src.frame.connect(self._on_frame)
        # noinspection PyUnresolvedReferences
        new_src.failed.connect(self._on_failed)
        # noinspection PyUnresolvedReferences
        if hasattr(new_src, "mode_changed"):
            new_src.mode_changed.connect(self._on_stream_mode)
        new_src.start()
        self._stream_tag = _pretty_stream_tag(describe_source(platform, opts))
        if opts.get("avf_capture"):
            self._got_real_frame = False
            self._first_frame_emitted = False
            self._wait_first_frame = True
            self._first_frame_timer.start(60000)
        if control is not None:
            self.attach_control(control)
        else:
            ctrl = "可控制" if self._control is not None else "仅观看"
            self.lbl.setText(f"实时操作中（{self._stream_tag}·{ctrl}）")
        self._start_stale_watch()
        return True

    def set_mobile_available(self, available: bool, *, hint: str = "") -> None:
        """主窗口按设备监控同步：无真机时禁用「开始」并更新占位。"""
        self._mobile_available = available
        self.btn_live.setEnabled(available)
        self.btn_live.setToolTip(
            "开始实时镜像并操作真机" if available else "未检测到真机，插入并授权后再试")
        if not available:
            if self.active():
                self.stop()
            if not self.active():
                self.view.set_hint(
                    hint or "未检测到设备\n请插入并授权（USB 调试 / 信任此电脑）后点 ▶ 开始")
                self._sync_idle_label()
        elif not self.active():
            self._sync_idle_label()

    # ---- 生命周期 ----
    def _toggle(self, on: bool) -> None:
        self._start() if on else self._stop()

    def _start(self) -> None:
        self._stopping = False
        if not self._mobile_available:
            self._fail_start("未检测到可用真机", hint=(
                "未检测到设备\n请插入并授权（USB 调试 / 信任此电脑）后点 ▶ 开始"))
            return
        if self.before_start is not None and self.before_start() is False:
            self._fail_start("未选择镜像目标或设备不可用")
            return
        if self.session_provider is None:
            self._fail_start("无会话来源")
            return
        data = self.session_provider()
        if not data:
            self._fail_start("无可用会话（先连接设备）")
            return
        platform, opts, control = data
        self._platform = (platform or "android").lower()
        from ...inspector.stream.factory import make_source, describe_source
        src = make_source(self._platform, opts)
        if src is None:
            self._fail_start("无可用帧源")
            return
        self._source = src
        # noinspection PyUnresolvedReferences
        src.frame.connect(self._on_frame)
        # noinspection PyUnresolvedReferences
        src.failed.connect(self._on_failed)
        # noinspection PyUnresolvedReferences
        if hasattr(src, "mode_changed"):
            src.mode_changed.connect(self._on_stream_mode)
        src.start()
        if control is None and hasattr(src, "control_sink"):
            control = src.control_sink()
        src_name = describe_source(self._platform, opts)
        self._control = control
        self._stream_tag = _pretty_stream_tag(src_name)
        _avf = bool(opts.get("avf_capture"))
        if control is None and self._platform == "ios" and _avf:
            self._wait_first_frame = True
            self._first_frame_emitted = False
            self._got_real_frame = False
            self._first_frame_timer.start(60000)
        else:
            self._wait_first_frame = False
        self._disp = _Dispatcher(on_error=self._on_control_error)
        self.btn_live.setText("⏸ 停止")
        if control is not None:
            self.lbl.setText(
                f"实时操作中（{self._stream_tag}·可控制）｜点=轻触 拖=滑动 双击 长按 滚轮=滚动 键盘=输入")
        else:
            self.lbl.setText(
                f"实时操作中（{self._stream_tag}·仅观看）"
                + ("｜等待画面首帧…" if self._wait_first_frame else "——未取到控制通道"))
        if self._wait_first_frame:
            self.view.set_hint("等待 iPhone 画面\n正在启用系统采集（CoreMediaIO）…")
        else:
            # 清掉上轮 stop() / 枢纽「先停再开」残留的「已停止」占位
            self.view.set_hint(None)
        self._populate_buttons()
        self._start_stale_watch()

    def _start_stale_watch(self) -> None:
        self._last_frame_at = time.monotonic()
        self._stale_recovering = False
        self._stale_frame_timer.start(_STALE_CHECK_MS)

    def _stop_stale_watch(self) -> None:
        self._stale_frame_timer.stop()

    def _on_stale_frame_check(self) -> None:
        """采集线程静默挂起时不会 emit failed；用「无新帧」检测并触发上层重启/回退。"""
        if self._stopping or self._source is None or self._stale_recovering:
            return
        if not self._got_real_frame:
            return
        if time.monotonic() - self._last_frame_at < _STALE_FRAME_SEC:
            return
        fb = self.video_fallback
        if not callable(fb):
            return
        self._stale_recovering = True
        # noinspection PyBroadException
        try:
            fb(f"画面已超过 {int(_STALE_FRAME_SEC)}s 无新帧（采集源可能已静默挂起）")
        except Exception:
            pass
        finally:
            self._stale_recovering = False
            # 给恢复动作留出时间，避免每 4s 连发
            self._last_frame_at = time.monotonic()

    def _fail_start(self, msg: str, *, hint: str = "") -> None:
        self.lbl.setText(msg)
        if hint:
            self.view.set_hint(hint)
        if self.btn_live.isChecked():
            # 复位按钮时必须屏蔽 toggled，否则会经 _toggle→_stop 发 sessionEnded。
            # iOS WDA-direct 镜像里 session_provider 会「先异步起 WDA 会话再 return
            # None」，_start 据此走本函数；若此刻误发 sessionEnded，会经
            # _on_mirror_stopped 置位 _mirror_cancel，反手取消刚启动的设备准备
            # （日志现象：正在建立 WDA 控制会话… → iOS 设备准备已取消）。启动失败
            # 时尚未建立真正会话，UI 已在本函数复位，无需再走 _stop 清理。
            self.btn_live.blockSignals(True)
            self.btn_live.setChecked(False)
            self.btn_live.blockSignals(False)

    def _disconnect_source(self, src) -> None:
        if src is None:
            return
        # noinspection PyBroadException
        try:
            src.frame.disconnect(self._on_frame)
            src.failed.disconnect(self._on_failed)
            if hasattr(src, "mode_changed"):
                src.mode_changed.disconnect(self._on_stream_mode)
        except Exception:
            pass

    def _on_first_frame_deadline(self) -> None:
        """首帧等待超时：交由上层重启采集/回退（不直接启 WDA）。"""
        if self._stopping or not self._wait_first_frame or self._got_real_frame:
            return
        self.lbl.setText("画面首帧超时，正在重启采集…")
        fb = self.video_fallback
        if callable(fb):
            # noinspection PyBroadException
            try:
                fb("画面首帧超时（采集源未推送可解码帧）")
            except Exception:
                pass
        self._first_frame_timer.start(60000)

    def _stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        self._first_frame_timer.stop()
        self._stop_stale_watch()
        self._lp_timer.stop()
        src = self._source
        self._source = None
        if src is not None:
            self._disconnect_source(src)
            # 帧源 stop 可能 wait 数秒：放到后台，避免卡住 GUI
            def _bg_stop(s=src) -> None:
                # noinspection PyBroadException
                try:
                    s.stop()
                except Exception:
                    pass

            threading.Thread(target=_bg_stop, name="mirror-src-stop", daemon=True).start()
        if self._disp is not None:
            self._disp.stop()
            self._disp = None
        self._control = None
        self._wait_first_frame = False
        self._clear_buttons()
        self.view.scene().clear()
        self._pixmap_item = None
        self.view.set_hint("已停止\n点 ▶ 开始 实时镜像")
        self.btn_live.setText("▶ 开始")
        self._sync_idle_label(stopped=True)
        if self.btn_live.isChecked():
            self.btn_live.setChecked(False)
        # noinspection PyUnresolvedReferences
        self.sessionEnded.emit()
        self._stopping = False

    # ---- 按钮条（能力数据驱动）----
    def _clear_buttons(self) -> None:
        while self.btn_bar.count():
            it = self.btn_bar.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        caps = self._control.capabilities() if self._control is not None else set()
        from ...inspector.stream.control import CAP_CLIPBOARD_GET, CAP_CLIPBOARD_SET
        has_set = CAP_CLIPBOARD_SET in caps
        has_get = CAP_CLIPBOARD_GET in caps
        for w in (self.clip_edit, self.btn_clip_set):
            w.setEnabled(has_set)
        self.btn_clip_get.setEnabled(has_get)

    def _populate_buttons(self) -> None:
        self._clear_buttons()
        caps = self._control.capabilities() if self._control is not None else set()
        for cap, icon, tip in _BUTTONS:
            if cap not in caps:
                continue
            b = QToolButton()
            ic = qicon(icon, color=icon_color("tool", self._ui_theme))
            if ic is not None:
                b.setIcon(ic)
            else:
                b.setText(tip)
            b.setToolTip(tip)
            b.setAutoRaise(True)
            # 截图是面板级动作（保存当前帧），其余走控制汇系统键
            slot = (self._save_screenshot if cap == "screenshot"
                    else (lambda _c=False, n=cap: self._key(n)))
            # noinspection PyUnresolvedReferences
            b.clicked.connect(slot)
            self.btn_bar.addWidget(b)
        self.btn_bar.addStretch(1)

    def _save_screenshot(self, _checked: bool = False) -> None:
        """保存当前镜像帧为 PNG（平台无关，scrcpy / WDA 都适用）。由用户选择保存位置。"""
        img = getattr(self, "_last_frame", None)
        if img is None or img.isNull():
            self.lbl.setText("还没有可保存的画面（等首帧到达后再截图）")
            return
        import os  # 延迟：仅用户点「保存截图」
        from datetime import datetime
        from PyQt6.QtWidgets import QFileDialog
        default = os.path.join(os.path.expanduser("~"),
                               f"mirror_{datetime.now():%Y%m%d_%H%M%S}.png")
        path, _ = QFileDialog.getSaveFileName(self, "保存截图", default, "图片 (*.png)")
        if not path:
            return
        # noinspection PyBroadException
        try:
            ok = img.save(path, "PNG")
            self.lbl.setText(f"已保存截图：{path}" if ok else "保存截图失败")
        except Exception as e:  # noqa: BLE001
            self.lbl.setText(f"保存截图失败：{e}")

    # ---- 帧渲染 ----
    def _on_frame(self, img) -> None:
        if self._stopping:
            return
        pm = QPixmap.fromImage(img)
        if pm.isNull():
            return
        self._last_frame = img              # 缓存最后一帧，供「设备截图」保存
        self._last_frame_at = time.monotonic()
        size_changed = (pm.width(), pm.height()) != self._frame_size
        self._frame_size = (pm.width(), pm.height())
        self._got_real_frame = True
        if self._wait_first_frame and not self._first_frame_emitted:
            self._first_frame_emitted = True
            self._first_frame_timer.stop()
            # noinspection PyUnresolvedReferences
            self.videoFirstFrame.emit()
        scene = self.view.scene()
        if self._pixmap_item is None:
            scene.clear()
            self._pixmap_item = scene.addPixmap(pm)
            scene.setSceneRect(0, 0, pm.width(), pm.height())
            self.view.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
        else:
            self._pixmap_item.setPixmap(pm)
            # 采集分辨率/方向变化（如占位 1920x1080 → 真机竖屏）时重置场景并重新贴合
            if size_changed:
                scene.setSceneRect(0, 0, pm.width(), pm.height())
                self.view.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
        # 隐占位层——仅在其仍可见时 hide，避免每帧无谓往返
        if self.view.placeholder_visible():
            self.view.set_hint(None)

    def _on_failed(self, msg: str) -> None:
        if self._stopping:
            return
        if self._fail_is_handoff():
            self.lbl.setText("正在建立 WDA 控制会话…")
            return
        fb = self.video_fallback
        if callable(fb):
            # noinspection PyBroadException
            try:
                if fb(msg):
                    self.lbl.setText("画面恢复中…")
                    return
            except Exception:
                pass
        self.lbl.setText(f"实时失败：{msg}")
        self._stop()

    def _on_stream_mode(self, mode: str) -> None:
        """MJPEG 断流切截图轮询时更新状态条。"""
        self._stream_tag = _pretty_stream_tag(mode)
        ctrl = "可控制" if self._control is not None else "仅观看"
        self.lbl.setText(f"实时操作中（{self._stream_tag}·{ctrl}）｜MJPEG 断流，已切截图轮询")

    def _on_control_error(self, msg: str) -> None:
        from PyQt6.QtCore import QTimer
        short = (msg or "").strip().splitlines()[0][:100]
        hint = "会话已断开，请停止镜像后重新开启" if "session" in short.lower() else short
        QTimer.singleShot(0, lambda: self.lbl.setText(f"控制失败：{hint}"))

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if self._pixmap_item is not None:
            self.view.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    # ---- 坐标映射：帧像素 → 设备坐标（含越界钳制，处理 letterbox 点击）----
    def _to_device(self, pt: QPointF) -> tuple:
        fw, fh = self._frame_size
        x = min(max(pt.x(), 0), fw) if fw else pt.x()
        y = min(max(pt.y(), 0), fh) if fh else pt.y()
        res = self._control.resolution() if self._control is not None else None
        if res and fw and fh and res[0] and res[1]:
            return x * res[0] / fw, y * res[1] / fh
        return x, y

    def _dispatch(self, fn) -> None:
        if self._disp is not None:
            self._disp.submit(fn)
        else:
            fn()   # 未起会话（如测试）时同步执行

    # ---- 手势 → 控制 ----
    def _on_press(self, pt: QPointF) -> None:
        self._press_pt = pt
        self._pressed = True
        self._lp_fired = False
        if self._control is not None:
            self._lp_timer.start(_LONG_PRESS_MS)

    def _on_long_press(self) -> None:
        if self._pressed and self._control is not None and self._press_pt is not None:
            self._lp_fired = True
            x, y = self._to_device(self._press_pt)
            self._dispatch(lambda: self._control.long_press(x, y))

    def _on_release(self, pt: QPointF) -> None:
        self._lp_timer.stop()
        self._pressed = False
        start = self._press_pt
        if self._control is None or start is None or self._lp_fired:
            return
        dx, dy = pt.x() - start.x(), pt.y() - start.y()
        if (dx * dx + dy * dy) ** 0.5 < _DRAG_THRESH:
            x, y = self._to_device(start)
            self._dispatch(lambda: self._control.tap(x, y))
        else:
            x1, y1 = self._to_device(start)
            x2, y2 = self._to_device(pt)
            self._dispatch(lambda: self._control.swipe(x1, y1, x2, y2, 200))

    def _on_double(self, pt: QPointF) -> None:
        self._lp_timer.stop()
        self._lp_fired = True       # 抑制随后的 release 单击
        if self._control is not None:
            x, y = self._to_device(pt)
            self._dispatch(lambda: self._control.double_tap(x, y))

    def _on_scroll(self, pt: QPointF, dx: float, dy: float) -> None:
        if self._control is None:
            return
        x, y = self._to_device(pt)
        self._dispatch(lambda: self._control.scroll(x, y, dx, dy))

    def _key(self, name: str) -> None:
        if self._control is not None:
            self._dispatch(lambda: self._control.key(name))

    # ---- 剪贴板 ----
    def _send_clipboard(self) -> None:
        if self._control is not None:
            text = self.clip_edit.text()
            self._dispatch(lambda: self._control.set_clipboard(text))

    def _read_clipboard(self) -> None:
        if self._control is not None:
            self._dispatch(self._do_read_clipboard)

    def _do_read_clipboard(self) -> None:
        text = self._control.get_clipboard()
        # iOS 限制：仅 WDA 前台时可读剪贴板，镜像被测 App 时常返回空（非 bug）
        hint = ("（iOS 限制：仅 WDA 前台时可读剪贴板）"
                if not text and self._platform == "ios" else "")

        def _apply():
            self.clip_edit.setText(text or "")
            if hint:
                self.clip_edit.setPlaceholderText(hint)
        QTimer.singleShot(0, _apply)

    def _on_text_input(self, s: str) -> None:
        """输入法提交文本（中文等）→ 注入设备（Android 非 ASCII 走剪贴板粘贴，iOS 走 /wda/keys）。"""
        if self._control is not None and s:
            self._dispatch(lambda t=s: self._control.text(t))

    # 键盘输入：可见字符→text；回车/退格/Esc→系统键
    def keyPressEvent(self, e) -> None:
        if self._control is None:
            super().keyPressEvent(e)
            return
        key = e.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._key("enter")
        elif key == Qt.Key.Key_Backspace:
            self._key("delete")
        elif key == Qt.Key.Key_Escape:
            self._key("back")
        else:
            txt = e.text()
            if txt:
                self._dispatch(lambda t=txt: self._control.text(t))
            else:
                super().keyPressEvent(e)

    def apply_theme(self, theme: str) -> None:
        from ..theme import apply_panel_theme, resolve_theme

        self._ui_theme = resolve_theme(theme)
        apply_panel_theme(self, "mirror_panel", self._ui_theme)
        self.view.apply_scene_theme(self._ui_theme)
        self.view.apply_placeholder_theme(self._ui_theme)
        if self._control is not None:
            self._populate_buttons()
        self.view.viewport().update()
