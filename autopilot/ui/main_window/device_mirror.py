"""主窗口·实时镜像 Mixin：起停会话、AVF/MJPEG 回退、iOS 控制通道。

与 DeviceMixin 组合：检视/选机/插拔共用逻辑仍在 device.py。
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QMainWindow

from ...keywords.context import ExecutionContext
from ...keywords.mobile.platform import host_os
from ...runtime import settings
from ...runtime.log import get_logger
from ..errors import clean_driver_err
from ..widgets.inspector_panel import SnapshotWorker

# 静态检查用 QMainWindow + 显式成员注解（避免循环导入丢属性）；运行时基类为 object。
if TYPE_CHECKING:
    from ...keywords.mobile.appium_server import AppiumServer
    from ..widgets.console import Console
    from ..widgets.inspector_panel import InspectorPanel
    from ..widgets.mirror_panel import MirrorPanel

    _Base = QMainWindow
else:
    _Base = object


class DeviceMirrorMixin(_Base):
    console: Console
    inspector: InspectorPanel
    mirror: MirrorPanel
    _appium_server: AppiumServer
    _devices: tuple[list[str], list[str]]
    _inspect_ctx: ExecutionContext | None
    _inspect_platform: str
    _inspect_udid: str
    _inspect_wda: str
    _ios_backend_mode: str
    _mirror_udid: str
    _mirror_resuming: bool
    _mirror_want_live: bool         # 用户意图保持镜像开启；停止后勿因 WDA 晚到而自动重开
    _mirror_control_pending: bool   # WDA 控制建立中：帧源失败不整镜停止
    _mirror_avf_active: bool          # 当前镜像是否处于 AVFoundation 原生采集阶段
    _mirror_avf_retries: int          # AVFoundation 采集断流重试计数
    _mirror_fallback_mjpeg: bool      # 控制就绪后切 MJPEG（高帧回退路径）

    if TYPE_CHECKING:
        # 由 DeviceMixin / MainWindow 提供；仅供本文件静态解析
        def _resolve_inspect_udid(self) -> None: ...
        def _inspect_device_available(self) -> tuple[bool, str]: ...
        def _warn_no_mobile_devices(self, tag: str, *, for_mirror: bool = False) -> None: ...
        def _has_mobile_device(self) -> bool: ...
        def _guard_mobile_session_target(self, tag: str) -> bool: ...
        def _commit_mobile_target(self, *, tag: str = "检视") -> bool: ...
        @staticmethod
        def _mirror_gone(plat: str, mirror_udid: str, android: list, ios: list) -> bool: ...
        def _choose_device(self, title: str, prompt: str) -> tuple: ...
        def _ios_inspector_uses_appium(self) -> bool: ...
        def _ensure_appium_server(self, log_tag: str = "检视") -> bool: ...
        def _release_device_session(self, *, blocking: bool = False) -> None: ...
        def _ios_session_alive(self) -> bool: ...
        def _focus_right_view(self, name: str) -> None: ...

    def _on_mirror_device_gone(self) -> None:
        a, i = getattr(self, "_devices", ([], []))
        if self.mirror.active() and self._mirror_gone(
                self.mirror.platform_name(), getattr(self, "_mirror_udid", ""),
                a, i):
            self.console.log("镜像设备已断开，已自动停止实时镜像", "镜像", "WARNING")
            self.mirror.stop()

    def _prepare_mirror_start(self) -> bool:
        """实时镜像「开始」前：确认真机在线并选定目标（resume / 枢纽预选仅校验仍在线）。"""
        if getattr(self, "_mirror_resuming", False):
            self._mirror_resuming = False
            self._resolve_inspect_udid()
            ok, msg = self._inspect_device_available()
            if not ok:
                self._warn_no_mobile_devices("镜像", for_mirror=True)
                if msg:
                    self.console.log(msg.replace("\n", " "), "镜像", "WARNING")
                return False
            self._mirror_want_live = True
            return True
        # 已连接设备枢纽已指定目标：不再弹选
        if getattr(self, "_mirror_from_hub", False):
            self._resolve_inspect_udid()
            ok, msg = self._inspect_device_available()
            if not ok:
                self._warn_no_mobile_devices("镜像", for_mirror=True)
                if msg:
                    self.console.log(msg.replace("\n", " "), "镜像", "WARNING")
                return False
            self._mirror_want_live = True
            return True
        if not self._has_mobile_device():
            self._warn_no_mobile_devices("镜像", for_mirror=True)
            return False
        ok = self._select_mirror_device()
        if ok:
            self._mirror_want_live = True
        return ok

    def _on_mirror_stopped(self) -> None:
        """用户停止实时镜像：释放控制会话（AVFoundation helper 随帧源线程停）。"""
        from ...mobile.ios_mirror import set_capture_active  # 延迟：仅 iOS 镜像采集
        self._mirror_want_live = False
        cancel = getattr(self, "_mirror_cancel", None)
        if cancel is not None:
            cancel.set()
        self._mirror_control_pending = False
        self._mirror_avf_active = False
        self._mirror_avf_retries = 0
        set_capture_active(False)
        # driver/WDA 收尾放到后台，避免停止镜像时 GUI 卡数秒
        self._release_device_session(blocking=False)

    def _build_ios_mjpeg_mirror_opts(self) -> dict:
        from ...mobile.ios_mirror_bootstrap import build_mjpeg_opts  # 延迟：仅 MJPEG 镜像
        from ...keywords.mobile.driver import get_manager  # 延迟：可选 Appium
        if self._inspect_ctx is None:
            return {}
        mgr = get_manager(self._inspect_ctx)
        return build_mjpeg_opts(self._inspect_udid, mgr)

    def _activate_mjpeg_mirror(self) -> None:
        """高帧回退或显式 mjpeg 模式：WDA 会话就绪后切 MJPEG 9100 画面 + 控制。"""
        if not self.mirror.active() or self._inspect_ctx is None:
            return
        from ...keywords.mobile.driver import get_manager, mirror_control_sink
        mgr = get_manager(self._inspect_ctx)
        opts = self._build_ios_mjpeg_mirror_opts()
        control = None
        # noinspection PyBroadException
        try:
            control = mirror_control_sink(mgr, mgr.driver())
        except Exception:
            pass
        if self.mirror.swap_video("ios", opts, control):
            get_logger("镜像").info("镜像画面：WDA MJPEG 9100")
        elif control is not None:
            self.mirror.attach_control(control)

    def _handoff_to_mjpeg(self, reason: str) -> bool:
        """高帧放弃 → 改 WDA+MJPEG（生产回退；``IOS_MIRROR_STRICT=1`` 时不调用）。"""
        from ...mobile.ios_mirror import set_capture_active  # 延迟：仅 iOS 镜像采集
        log = get_logger("镜像")
        log.warning("高帧采集失败，切换 WDA MJPEG：%s", (reason or "")[:120])
        self._mirror_avf_active = False
        set_capture_active(False)
        self._mirror_control_pending = True
        # noinspection PyProtectedMember
        self.mirror._wait_first_frame = False
        # noinspection PyProtectedMember
        self.mirror._first_frame_timer.stop()
        if self._ios_session_alive():
            self._activate_mjpeg_mirror()
            self._mirror_control_pending = False
            return True
        self.console.log("高帧采集不可用，正在建立 WDA 会话（MJPEG 9100）…", "镜像")
        self._ensure_ios_session_async(fallback_mjpeg=True)
        return True

    def _on_mirror_video_failed(self, reason: str) -> bool:
        """画面断流/静默挂起 → 重启采集或回退 MJPEG（控制/WDA 与画面正交，可仍可用）。

        返回 True 表示已接管（不整镜停止）。
        """
        if getattr(self.mirror, "_stopping", False):
            return False
        if not self.mirror.active():
            return False
        log = get_logger("镜像")
        if getattr(self, "_mirror_avf_active", False):
            from ...mobile.ios_mirror import build_avf_opts, allows_mjpeg_fallback
            retries = getattr(self, "_mirror_avf_retries", 0) + 1
            self._mirror_avf_retries = retries
            max_retries = 3
            if retries <= max_retries:
                log.warning("AVFoundation 断流，第 %s 次重启采集：%s", retries, (reason or "")[:120])
                self.console.log(
                    f"画面断流，正在重启原生采集（{retries}/{max_retries}）…", "镜像", "WARNING")
                grab = None
                if self._inspect_ctx is not None:
                    from ...keywords.mobile.driver import get_manager
                    # noinspection PyBroadException
                    try:
                        grab = get_manager(self._inspect_ctx).driver().get_screenshot_as_png
                    except Exception:
                        pass
                opts = build_avf_opts(self._inspect_udid, grab=grab)
                if self.mirror.swap_video("ios", opts):
                    return True
            if allows_mjpeg_fallback():
                self._mirror_avf_active = False
                return self._handoff_to_mjpeg(reason)
            log.error("AVFoundation 采集重试 %s 次仍失败（严格模式，不回退）：%s",
                      max_retries, (reason or "")[:160])
            self.console.log(
                "原生采集无法恢复（严格模式 IOS_MIRROR_STRICT=1），见 ~/.autopilot/logs/avf-capture.log",
                "镜像", "ERROR")
            return False
        # MJPEG / 其它 iOS 视频源：HTTP 半开连接等会导致线程阻塞且无 failed → 由帧停滞看门狗触发
        if (self._inspect_platform or "").strip() == "iOS" and self._ios_session_alive():
            log.warning("镜像画面静默断流，重连 MJPEG：%s", (reason or "")[:120])
            self.console.log("画面无新帧，正在重连视频流…", "镜像", "WARNING")
            opts = self._build_ios_mjpeg_mirror_opts()
            if opts.get("mjpeg_url") and self.mirror.swap_video("ios", opts):
                return True
        return False

    def _select_mirror_device(self) -> bool:
        """镜像开始前选目标设备：检测到的 Android/iOS 全列出；单台直接用、多台弹选。

        镜像面板入口不经「连接检视设备」，否则只会用默认平台→默认设备。"""
        if getattr(self, "_mirror_resuming", False):
            self._mirror_resuming = False        # iOS 建好会话后自动重开：沿用已选设备，不再弹
            return True
        status, _ = self._choose_device("选择镜像设备", "实时镜像目标：")
        if status == "empty":
            self._warn_no_mobile_devices("镜像", for_mirror=True)
            return False
        if status == "cancel":
            return False
        return self._commit_mobile_target(tag="镜像")

    def _ensure_ios_session_async(self, *, fallback_mjpeg: bool = False) -> None:
        """异步建立 iOS 镜像控制会话（仅 driver，不走检视快照）。"""
        w = getattr(self, "_ios_sess_worker", None)
        if w is not None and w.isRunning():
            return
        self._mirror_want_live = True
        self._mirror_control_pending = True
        self._mirror_fallback_mjpeg = fallback_mjpeg
        cancel = getattr(self, "_mirror_cancel", None)
        if cancel is None:
            cancel = threading.Event()
            self._mirror_cancel = cancel
        cancel.clear()
        self.console.log("正在建立 iOS WDA 控制会话…", "镜像")
        # 高帧首帧后画面已在播，勿再盖占位层（状态栏文案已足够）
        self._ios_sess_worker = SnapshotWorker(self._mirror_ios_control_session, self)
        # noinspection PyUnresolvedReferences
        self._ios_sess_worker.done.connect(self._on_ios_mirror_control_ready)
        self._ios_sess_worker.start()

    def _mirror_ios_control_session(self) -> bool:
        """镜像专用：只建 WDA/Appium 控制会话，不取 page_source/检视快照。"""
        plat = (self._inspect_platform or "").strip()
        if plat != "iOS":
            return False
        if not self._guard_mobile_session_target("镜像"):
            return False
        # 延迟：Appium/WDA 会话与 iOS 工具链仅镜像控制路径需要
        from ...keywords.mobile.driver import get_manager, ios_session_probe
        from ...mobile import ios_bootstrap as ib

        # AVFoundation 采集已激活（iPhone 进入录制 USB 配置、设备重枚举）→ 等其 settle，
        # 再由 driver 强制重建 RSD 隧道后 runwda（与 ws-scrcpy「先画面后控制」一致）
        if getattr(self, "_mirror_avf_active", False):
            get_logger("镜像").info(
                "AVFoundation 采集中 → 启动 WDA 控制（强制重建 RSD 隧道）")
            # 可中断等待：用户停止镜像时 _mirror_cancel 置位
            cancel = getattr(self, "_mirror_cancel", None)
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                if cancel is not None and cancel.is_set():
                    return False
                if not getattr(self, "_mirror_want_live", True):
                    return False
                time.sleep(0.2)

        if self._inspect_ctx is None:
            self._inspect_ctx = ExecutionContext()
            self._inspect_ctx.set_var("__device_udid__", self._inspect_udid)
            self._inspect_ctx.set_var("__inspect_platform__", "iOS")
            backend_mode = getattr(self, "_ios_backend_mode", "auto") or "auto"
            self._inspect_ctx.set_var("__mobile_backend_mode__", backend_mode)

        cancel = getattr(self, "_mirror_cancel", None)
        if cancel is not None:
            self._inspect_ctx.set_var("__inspect_cancel_event__", cancel)

        wda = (self._inspect_wda or "").strip()
        if not wda:
            # noinspection PyBroadException
            try:
                wda = ib.IosDevicePrep(self._inspect_udid, "").discover_wda()
                self._inspect_wda = wda
            except Exception as e:  # noqa: BLE001
                get_logger("镜像").error(
                    "未发现 WDA bundle（udid=%s）：%s",
                    self._inspect_udid or "?", e)
                return False

        base_vars: dict = {}
        if wda:
            base_vars["__appium_caps__"] = {"wdaBundleId": wda}
        if self._ios_inspector_uses_appium():
            # 仅镜像控制会话禁用空闲看门狗（newCommandTimeout=0）：镜像是交互式的，用户
            # 盯着画面不发指令时不能让 Appium 判超时杀 session。检视快照是一次性的，沿用
            # 默认 60s，不受此影响（改动面只限镜像）。
            ib.merge_appium_ios_caps(
                base_vars, self._inspect_udid, wda, getattr(self, "_ios_backend_mode", "auto"),
                extra={"appium:newCommandTimeout": 0})
            self._inspect_ctx.set_var(
                "__appium_server__",
                getattr(self._appium_server, "url", None) or "http://127.0.0.1:4723")
        for k, v in base_vars.items():
            self._inspect_ctx.set_var(k, v)

        if self._ios_inspector_uses_appium() and not self._ensure_appium_server("镜像"):
            return False

        mgr = get_manager(self._inspect_ctx)
        last = ""
        for attempt in range(2):
            # noinspection PyBroadException
            try:
                # noinspection PyBroadException
                try:
                    if ios_session_probe(mgr):
                        return True
                except Exception:
                    pass
                mgr.create(plat, "", "", self._inspect_udid)
                return ios_session_probe(mgr)
            except Exception as e:  # noqa: BLE001
                last = clean_driver_err(e, plat, getattr(mgr, "backend", ""))
                mgr.release_driver()
                if attempt == 0:
                    continue
                break
        get_logger("镜像").error("镜像控制会话建立失败：%s", last)
        return False

    def _on_mirror_first_frame(self) -> None:
        """真实高帧首帧后建 WDA（无首帧不启 WDA）。"""
        if not self.mirror.active():
            return
        if not getattr(self.mirror, "_got_real_frame", False):
            return
        self.console.log("画面首帧已到，启动 WDA 控制…", "镜像")
        if self._ios_session_alive():
            self._on_ios_mirror_control_ready(True)
            return
        w = getattr(self, "_ios_sess_worker", None)
        if w is not None and w.isRunning():
            return
        self._ensure_ios_session_async()

    def _on_ios_mirror_control_ready(self, ok) -> None:
        """镜像控制就绪：高帧模式 attach 控制；高帧→MJPEG 回退则切 9100 画面。"""
        self._mirror_control_pending = False
        fallback_mjpeg = getattr(self, "_mirror_fallback_mjpeg", False)
        self._mirror_fallback_mjpeg = False
        if ok and self._ios_session_alive():
            self.console.log("镜像控制通道就绪", "镜像")
            if not self.mirror.active():
                # 用户已停止：丢弃晚到的控制就绪，禁止自动重开
                if not getattr(self, "_mirror_want_live", False):
                    return
                self._mirror_resuming = True
                self.mirror.btn_live.setChecked(True)
                return
            _highfps_active = getattr(self, "_mirror_avf_active", False)
            if fallback_mjpeg or not _highfps_active:
                self._activate_mjpeg_mirror()
                return
            from ...keywords.mobile.driver import get_manager, mirror_control_sink
            mgr = get_manager(self._inspect_ctx)
            # noinspection PyBroadException
            try:
                control = mirror_control_sink(mgr, mgr.driver())
            except Exception:
                control = None
            if control is not None:
                self.mirror.attach_control(control)
            return
        self.console.log(
            "镜像控制建立失败（画面已开；调试可设 IOS_MIRROR_STRICT=1 排查）",
            "镜像", "WARNING")

    def _on_ios_session_ready(self, data) -> None:
        """兼容旧入口：转镜像控制就绪处理。"""
        self._on_ios_mirror_control_ready(bool(data) and self._ios_session_alive())

    def _mirror_session(self):
        """为实时交互镜像提供 (platform, opts, control_sink)。

        Android：scrcpy 帧 + scrcpy 控制（control 留空，由 MirrorPanel 取）。
        iOS：画面与控制正交——Mac auto 优先 AVF H.264；Win/Linux auto 走 MJPEG 9100；
        控制按 backend 选 AppiumControlSink（Mac Appium）或 WdaControlSink（WDA-direct）。

        设备选择由 MirrorPanel.before_start → _prepare_mirror_start 完成，此处不再弹选。
        """
        plat = self._inspect_platform
        if plat == "Web":
            self.console.log("Web 实时操作将在后续版本支持", "镜像", "WARNING")
            return None
        if not self._guard_mobile_session_target("镜像"):
            return None
        # iOS 镜像：Mac 优先 AVFoundation 高帧（与 WDA 控制共存）；否则先有 WDA 会话
        from ...mobile.ios_mirror import can_try_avf_mirror  # 延迟：仅 iOS 镜像源选择
        _mirror_mode = settings.ios_mirror_source()
        _try_avf = plat == "iOS" and can_try_avf_mirror(_mirror_mode, host=host_os())
        if plat == "iOS" and not self._ios_session_alive() and not _try_avf:
            self._ensure_ios_session_async()
            return None
        self._mirror_udid = self._inspect_udid   # 记住镜像的具体设备，供拔出检测
        from ...mobile.ios_bootstrap import (  # 延迟：iOS 工具链
            DEFAULT_MJPEG_PORT, ensure_mjpeg_ready, mjpeg_alive,
        )
        if plat == "Android":
            # scrcpy 自带控制通道，无需 Appium 会话；有会话则补 grab 兜底
            opts = {"serial": self._inspect_udid}
            if self._inspect_ctx is not None:
                from ...keywords.mobile.driver import get_manager
                # noinspection PyBroadException
                try:
                    opts["grab"] = get_manager(self._inspect_ctx).driver().get_screenshot_as_png
                except Exception:
                    pass
            return "android", opts, None
        # iOS：AVFoundation 高帧（Mac auto）或显式 MJPEG + WDA/Appium 控制（正交）
        from ...keywords.mobile.driver import get_manager, mirror_control_sink  # 延迟：可选 Appium
        from ...mobile.ios_mirror import MIRROR_MJPEG, resolve_mirror_source

        mgr = get_manager(self._inspect_ctx) if self._inspect_ctx is not None else None
        drv = None
        grab = None
        if mgr is not None:
            # noinspection PyBroadException
            try:
                drv = mgr.driver()
                grab = drv.get_screenshot_as_png
            except Exception:
                drv = None

        opts: dict = {}
        if grab is not None:
            opts["grab"] = grab

        _host = host_os()
        _resolved = resolve_mirror_source(_mirror_mode, host=_host)
        _use_mjpeg_video = _resolved == MIRROR_MJPEG

        if _use_mjpeg_video:
            from ...mobile.ios_mirror_bootstrap import build_mjpeg_opts
            if mgr is not None:
                opts.update(build_mjpeg_opts(self._inspect_udid, mgr))
            else:
                mjpeg_port = DEFAULT_MJPEG_PORT
                ensure_mjpeg_ready(self._inspect_udid, mjpeg_port, prep=None)
                if mjpeg_alive(mjpeg_port):
                    opts["mjpeg_url"] = f"http://127.0.0.1:{mjpeg_port}"
            if opts.get("mjpeg_url"):
                get_logger("镜像").info("MJPEG 9100 就绪（显式 mjpeg 模式）")
            elif not opts.get("grab"):
                self.console.log("iOS MJPEG 未就绪，请先建立 WDA 会话", "镜像", "WARNING")
                return None
            if drv is None:
                self.console.log("正在建立 WDA 控制会话…（MJPEG 画面）", "镜像")
                self._ensure_ios_session_async()
                return "ios", opts, None
            control = mirror_control_sink(mgr, drv)
            return "ios", opts, control

        if _try_avf:
            from ...mobile.ios_mirror import build_avf_opts, set_capture_active
            opts.update(build_avf_opts(self._inspect_udid, grab=grab))
            self._mirror_avf_active = True
            self._mirror_avf_retries = 0
            # 标记采集活跃：WDA 准备时据此强制重建 RSD 隧道（USB 因录制配置重枚举）
            set_capture_active(True)
            get_logger("镜像").info(
                "镜像走 AVFoundation 原生采集（CoreMediaIO，与 WDA 控制共存）")
            # 控制留空：首帧到达后由 _on_mirror_first_frame 建 WDA 并 attach
            return "ios", opts, None
        self._mirror_avf_active = False

        # Win/Linux auto 或高帧不可用 → MJPEG
        from ...mobile.ios_mirror_bootstrap import build_mjpeg_opts
        if mgr is not None:
            opts.update(build_mjpeg_opts(self._inspect_udid, mgr))
        else:
            mjpeg_port = DEFAULT_MJPEG_PORT
            ensure_mjpeg_ready(self._inspect_udid, mjpeg_port, prep=None)
            if mjpeg_alive(mjpeg_port):
                opts["mjpeg_url"] = f"http://127.0.0.1:{mjpeg_port}"
        if opts.get("mjpeg_url"):
            get_logger("镜像").info("MJPEG 9100 就绪，镜像走视频流")
        elif mgr is not None and getattr(mgr, "backend", "") == "appium":
            self.console.log(
                "iOS Appium 会话未暴露 MJPEG 端口，镜像使用截屏刷新模式",
                "镜像", "WARNING")
        elif not opts.get("grab"):
            self.console.log(
                "iOS MJPEG 未就绪，镜像将使用截屏轮询",
                "镜像", "WARNING")

        if drv is None:
            if opts.get("mjpeg_url") or opts.get("grab"):
                self.console.log("正在建立 WDA 控制会话…", "镜像")
                self._ensure_ios_session_async()
                return "ios", opts, None
            self.console.log("iOS 实时镜像需先连接设备或刷新检视快照", "镜像", "WARNING")
            return None

        control = mirror_control_sink(mgr, drv)
        return "ios", opts, control

    def _start_mirror_from_connected(self, device) -> None:
        """从已连接列表直接开实时镜像（切到镜像页，不再弹选设备）。"""
        plat = getattr(device, "platform", "") or ""
        udid = getattr(device, "udid", "") or ""
        if plat not in ("Android", "iOS") or not udid:
            return
        self._inspect_platform = plat
        self._inspect_udid = udid
        if not self._commit_mobile_target(tag="镜像"):
            return
        if hasattr(self, "_focus_right_view"):
            self._focus_right_view("mirror")
        mirror = getattr(self, "mirror", None)
        if mirror is None or not hasattr(mirror, "request_start"):
            self.console.log("镜像面板不可用", "镜像", "WARNING")
            return
        self._mirror_from_hub = True
        # noinspection PyBroadException
        try:
            if mirror.active():
                mirror.stop()
            self.console.log(f"开始实时镜像：{plat} {udid}", "镜像")
            mirror.request_start()
        finally:
            self._mirror_from_hub = False

