"""主窗口·设备/检视 Mixin：连接检视、取源、定位符、插拔；镜像见 device_mirror。"""

from __future__ import annotations

import os
import threading
from datetime import datetime
from typing import TYPE_CHECKING

from PyQt6.QtCore import QThread, QTimer
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QFileDialog, QInputDialog, QMainWindow, QMessageBox, QStackedWidget

from ..errors import clean_driver_err
from ..confirm import ask_local_runner_prompt, confirm
from ..widgets.info_sheet_dialog import show_info_sheet
from ..widgets.list_pick_dialog import list_pick_ask, pick_list_item
from ...keywords.context import ExecutionContext
from ...runtime.log import get_logger   # 取快照在 worker 线程跑，日志须走线程安全的桥接
from ...keywords.mobile.picture_locator import (
    picture_fill_hint,
    picture_locator_for_path,
    supports_picture_locator,
    is_picture_locator,
)
from .device_mirror import DeviceMirrorMixin
from .device_readiness import (
    DeviceLists,
    default_inspect_platform_index,
    ios_install_pick_status,
    mirror_device_gone,
    no_device_info_message,
    no_device_placeholder,
    no_ios_install_message,
    no_mobile_message,
    pick_udid_unavailable_message,
    resolve_udid,
    validate_inspect_target,
)
from .device_select import (
    build_choices,
    choose_device,
    choose_device_runtime,
    device_label,
    friendly_pick_labels,
)
from ...runtime import settings
from ...keywords.mobile import platform as mp
from ...mobile.device_info import (
    collect_android_device_info,
    collect_ios_device_info,
    device_picker_line,
)
from ..device_list_menu import build_connected_devices_menu, list_connected_devices
from ..widgets.inspector_panel import SnapshotWorker

# 静态检查：基类用 QMainWindow（避免 DeviceMixin↔MainWindow 循环导致属性全丢），
# 并在类上声明本 Mixin 用到的主窗口成员。运行时基类仍是 DeviceMirrorMixin。
if TYPE_CHECKING:
    from ...keywords.mobile.appium_server import AppiumServer
    from ..widgets.case_editor import CaseEditor
    from ..widgets.console import Console
    from ..widgets.inspector_panel import InspectorPanel
    from ..widgets.map_editor import MapEditor
    from ..widgets.mirror_panel import MirrorPanel

    _Base = QMainWindow
else:
    _Base = DeviceMirrorMixin


class DeviceMixin(_Base):
    # MainWindow / 兄弟 Mixin 拥有；仅注解，运行时不在此建属性
    console: Console
    inspector: InspectorPanel
    mirror: MirrorPanel
    center: QStackedWidget
    map_editor: MapEditor
    project_dir: str
    _appium_server: AppiumServer
    _devices: tuple[list[str], list[str]]
    _inspect_ctx: ExecutionContext | None
    _ios_backend_mode: str
    _inspect_platform: str
    _inspect_chosen: bool
    _inspect_udid: str
    _inspect_wda: str
    _inspect_url: str
    _inspect_browser: str
    _ipa_install_worker: QThread         # iOS 装包后台 worker（惰性建，防被 GC）

    if TYPE_CHECKING:
        def _current_step_editor(self) -> CaseEditor: ...
        def _on_step_selected(self, node: object) -> None: ...
        # 运行时由 DeviceMirrorMixin 提供（类型检查基类是 QMainWindow，见不到）
        def _on_mirror_device_gone(self) -> None: ...
        def _start_mirror_from_connected(self, device: object) -> None: ...

    def _on_devices_changed(self, android: list, ios: list) -> None:
        self._devices = (android, ios)
        if getattr(self, "_inspect_chosen", False):
            plat = (getattr(self, "_inspect_platform", "") or "").strip()
            if plat in ("Android", "iOS"):
                self._resolve_inspect_udid()
                ok, msg = self._inspect_device_available()
                if not ok:
                    gone = (getattr(self, "_inspect_udid", "") or "").strip()
                    self._inspect_chosen = False
                    self._release_runner_exclude_if_unbound(gone)
                    self._update_device_status()
                    if hasattr(self, "inspector"):
                        self.inspector.view.set_hint(
                            f"{msg}\n点「设备 ▸ 连接检视设备」重新选择")
        elif not getattr(self, "_inspect_chosen", False):
            self._update_device_status()
        if android or ios:
            self.console.log(f"设备变化：Android {android or '无'}｜iOS {ios or '无'}", "设备")
        # 占位提示随设备在/无切换
        if not (android or ios):

            hint = no_device_placeholder()
            self.inspector.view.set_hint(hint)
            self.mirror.view.set_hint(no_device_placeholder(for_mirror=True))
            plat = (getattr(self, "_inspect_platform", "") or "").strip()
            if getattr(self, "_inspect_chosen", False) and plat in ("Android", "iOS"):
                gone = (getattr(self, "_inspect_udid", "") or "").strip()
                self._inspect_chosen = False
                self._release_runner_exclude_if_unbound(gone)
                self._update_device_status()
        self._sync_device_panel_controls()
        # 设备拔出处理（按「具体设备」判定，多台不误停）——但加去抖：设备在 uiautomator2
        # 初始化等场景会瞬时掉线再恢复，若一格没看到就拆会话，会反复打断刚建的 Appium/WDA。
        # 故缺席需「持续超过宽限期」才判真断开（其间恢复则取消），见 _watch_device_gone。
        self._watch_device_gone(
            "mirror",
            self.mirror.platform_name() if self.mirror.active() else "",
            getattr(self, "_mirror_udid", ""),
            self._on_mirror_device_gone)
        self._watch_device_gone(
            "inspect",
            (getattr(self, "_inspect_platform", "") or "").lower()
            if getattr(self, "_inspect_chosen", False) else "",
            getattr(self, "_inspect_udid", ""),
            self._on_inspect_device_gone)

    def _watch_device_gone(self, key: str, platform: str, udid: str, on_gone) -> None:
        """去抖判定设备断开：platform 为空=该会话未激活(取消计时)；缺席则起一次性计时，
        宽限期到仍缺席才回调 on_gone；其间设备恢复(再次进列表)则取消。"""
        if not hasattr(self, "_gone_timers"):
            self._gone_timers = {}
        active = platform in ("android", "ios")
        android, ios = getattr(self, "_devices", ([], []))
        gone = active and self._mirror_gone(platform, udid, android, ios)
        timer = self._gone_timers.get(key)
        if not gone:
            if timer is not None:               # 恢复/不再监视 → 取消待决计时
                timer.stop()
                self._gone_timers.pop(key, None)
            return
        if timer is not None:
            return                              # 已在计时，不重复起
        timer = QTimer(self)
        timer.setSingleShot(True)

        def _confirm_gone():
            self._gone_timers.pop(key, None)
            a, i = getattr(self, "_devices", ([], []))
            if self._mirror_gone(platform, udid, a, i):
                on_gone()                       # 宽限期满仍缺席 → 真断开
        # noinspection PyUnresolvedReferences
        timer.timeout.connect(_confirm_gone)
        timer.start(int(self._device_gone_grace_s() * 1000))
        self._gone_timers[key] = timer

    def _on_inspect_device_gone(self) -> None:
        plat = (getattr(self, "_inspect_platform", "") or "").lower()
        if not (plat in ("android", "ios") and getattr(self, "_inspect_chosen", False)):
            return
        gone = (getattr(self, "_inspect_udid", "") or "").strip()
        if self._inspect_ctx is not None:
            self._reset_inspect_session()
        self._inspect_chosen = False
        self._release_runner_exclude_if_unbound(gone)
        self._update_device_status()
        self.console.log("检视设备已断开，已释放检视会话；刷新快照将重新选择设备",
                         "检视", "WARNING")
        self.inspector.view.set_hint("检视设备已断开\n重新连接后点「🔄 刷新快照」")

    @staticmethod
    def _mirror_gone(plat: str, mirror_udid: str, android: list, ios: list) -> bool:

        return mirror_device_gone(plat, mirror_udid, DeviceLists.from_lists(android, ios))

    def _device_lists(self):

        android, ios = getattr(self, "_devices", ([], []))
        return DeviceLists.from_lists(android, ios)

    def _device_gone_grace_s(self) -> float:
        """设备拔出判定宽限（秒）；实例可覆写 _gone_grace_s，否则读用户设置。"""
        override = getattr(self, "_gone_grace_s", None)
        if override is not None:
            return float(override)
        return settings.device_gone_grace_s()

    def _connected_mobile_summary(self) -> tuple[int, int]:
        return self._device_lists().count_summary()

    def _has_mobile_device(self) -> bool:
        return self._device_lists().has_mobile()

    @staticmethod
    def _no_mobile_devices_message(*, for_mirror: bool = False) -> str:

        return no_mobile_message(for_mirror=for_mirror)

    def _default_inspect_platform_index(self) -> int:

        return default_inspect_platform_index(self._device_lists())

    def _warn_no_mobile_devices(self, tag: str, *, for_mirror: bool = False) -> None:
        msg = self._no_mobile_devices_message(for_mirror=for_mirror)
        self.console.log(msg.replace("\n", " "), tag, "WARNING")
        hint = msg + (
            "\n点「设备 ▸ 连接检视设备」重新选择"
            if not for_mirror else ""
        )
        if for_mirror and hasattr(self, "mirror"):
            self.mirror.view.set_hint(hint)
            if hasattr(self.mirror, "lbl"):
                self.mirror.lbl.setText("未检测到设备")
        elif hasattr(self, "inspector"):
            self.inspector.view.set_hint(hint)

    def _devices_for_platform(self, plat: str) -> list[str]:
        return self._device_lists().for_platform(plat)

    def _resolve_inspect_udid(self) -> None:

        plat = getattr(self, "_inspect_platform", "") or ""
        resolved = resolve_udid(plat, getattr(self, "_inspect_udid", ""), self._device_lists())
        if resolved:
            self._inspect_udid = resolved

    def _inspect_device_available(self) -> tuple[bool, str]:

        return validate_inspect_target(
            getattr(self, "_inspect_platform", "") or "",
            getattr(self, "_inspect_udid", "") or "",
            self._device_lists(),
        )

    def _warn_inspect_unavailable(self, message: str) -> None:
        self.console.log(message, "检视", "WARNING")
        if hasattr(self, "inspector"):
            self.inspector.view.set_hint(
                f"{message}\n点状态栏设备 Chip 或「设备 ▸ 已连接设备…」重新选择")

    def _commit_mobile_target(self, *, tag: str = "检视") -> bool:
        """Android/iOS 选定后统一提交：补齐 UDID、校验在线、标记 _inspect_chosen。"""
        self._resolve_inspect_udid()
        ok, msg = self._inspect_device_available()
        if not ok:
            if tag == "镜像":
                self._warn_no_mobile_devices("镜像", for_mirror=True)
                if msg:
                    self.console.log(msg.replace("\n", " "), "镜像", "WARNING")
            else:
                self._warn_inspect_unavailable(msg)
            return False
        if not self._confirm_inspect_with_local_runner(tag):
            bound_plat = getattr(self, "_runner_guard_bound_plat", None)
            bound_udid = getattr(self, "_runner_guard_bound_udid", None)
            if bound_udid is not None:
                self._inspect_platform = bound_plat or ""
                self._inspect_udid = bound_udid or ""
            return False
        # 换机/换平台：丢弃旧会话，避免画面与控制绑到不同 UDID
        if self._inspect_ctx is not None:
            bound = str(self._inspect_ctx.get_var("__device_udid__") or "")
            bound_plat = str(self._inspect_ctx.get_var("__inspect_platform__") or "")
            cur_udid = (self._inspect_udid or "").strip()
            cur_plat = (self._inspect_platform or "").strip()
            if (bound and bound != cur_udid) or (bound_plat and bound_plat != cur_plat):
                self._reset_inspect_session()
        self._inspect_chosen = True
        self._runner_guard_bound_plat = (self._inspect_platform or "").strip()
        self._runner_guard_bound_udid = (self._inspect_udid or "").strip()
        self._update_device_status()
        return True

    def _confirm_inspect_with_local_runner(self, tag: str) -> bool:
        """本机 Runner 已上报该 UDID 时确认；可摘除上报，不杀 Runner。"""
        from ...mgmt.local_runner import default_local_runner_id
        from ...mgmt.local_runner_guard import (
            ACTION_CANCEL,
            ACTION_EXCLUDE,
            bound_mobile_udid,
            open_inspect_prompt,
        )
        from ...runner.device_policy import (
            add_exclude_udids,
            load_device_policy,
            policy_would_report,
        )

        proc = getattr(self, "_local_runner", None)
        if proc is None or not getattr(proc, "running", False):
            return True
        udid = bound_mobile_udid(
            platform=getattr(self, "_inspect_platform", "") or "",
            udid=getattr(self, "_inspect_udid", "") or "",
        )
        if not udid:
            return True
        rid = (getattr(proc, "runner_id", "") or "").strip() or default_local_runner_id()
        prompt = open_inspect_prompt(
            runner_running=True,
            reports_udid=policy_would_report(load_device_policy(rid), udid),
            udid=udid,
            kind=tag or "检视",
        )
        if prompt is None:
            return True
        action = ask_local_runner_prompt(self, prompt)
        if action == ACTION_CANCEL:
            return False
        if action == ACTION_EXCLUDE:
            add_exclude_udids(rid, {udid})
            self.console.log(
                f"已从本机 Runner 上报摘除 {udid}，避免与{tag}抢会话",
                "管理台",
            )
        return True

    def _release_runner_exclude_if_unbound(self, udid: str = "") -> None:
        """检视/镜像不再占用该机时，把它放回 Runner 上报。"""
        from ...mgmt.local_runner import default_local_runner_id
        from ...mgmt.local_runner_guard import bound_mobile_udid
        from ...runner.device_policy import remove_exclude_udids

        uid = (udid or "").strip()
        if not uid:
            return
        current = bound_mobile_udid(
            platform=getattr(self, "_inspect_platform", "") or "",
            udid=getattr(self, "_inspect_udid", "") or "",
        )
        mirror = getattr(self, "mirror", None)
        mirror_on = bool(
            mirror is not None and getattr(mirror, "active", lambda: False)()
        )
        still_bound = (current == uid) and (
            bool(getattr(self, "_inspect_chosen", False)) or mirror_on
        )
        if still_bound:
            return
        proc = getattr(self, "_local_runner", None)
        rid = (getattr(proc, "runner_id", "") or "").strip() or default_local_runner_id()
        remove_exclude_udids(rid, {uid})

    def _guard_mobile_session_target(self, tag: str) -> bool:
        """镜像/检视建会话前的二次校验（与 _inspector_snapshot 对齐）。"""
        plat = (getattr(self, "_inspect_platform", "") or "").strip()
        if plat not in ("Android", "iOS"):
            return plat == "Web"
        self._resolve_inspect_udid()
        ok, msg = self._inspect_device_available()
        if ok:
            return True
        get_logger(tag).warning(msg)
        if tag == "镜像":
            self.console.log(msg.replace("\n", " "), "镜像", "WARNING")
        else:
            self._warn_inspect_unavailable(msg)
        return False

    # ---- 控件检视器 ----
    def _pick_inspect_platform(self, title: str = "选择检视目标") -> str | None:
        """检视向导第一步：Android / iOS / Web。"""
        default_idx = self._default_inspect_platform_index()
        plat, ok = QInputDialog.getItem(
            self, title, "平台：",
            ["Android", "iOS", "Web"], default_idx, False)
        return plat if ok else None

    def _configure_web_inspect(self, title: str = "Web 检视") -> bool:
        """配置 Web 检视目标（URL + 浏览器 + 引擎）。"""
        url, ok = QInputDialog.getText(
            self, title, "页面 URL：",
            text=getattr(self, "_inspect_url", "") or "https://")
        if not ok:
            return False
        self._inspect_url = url.strip()
        browsers = ["chrome", "edge", "firefox", "headless"]
        cur_br = getattr(self, "_inspect_browser", "") or settings.web_browser()
        br_idx = browsers.index(cur_br) if cur_br in browsers else 0
        br, ok = QInputDialog.getItem(
            self, title, "浏览器：", browsers, br_idx, False)
        if not ok:
            return False
        self._inspect_browser = br
        settings.set_web_browser(br)
        engines = ["selenium", "playwright"]
        cur_eng = getattr(self, "_web_engine", "") or settings.web_engine()
        eng_idx = engines.index(cur_eng) if cur_eng in engines else 0
        eng, ok = QInputDialog.getItem(
            self, title, "Web 引擎：", engines, eng_idx, False)
        if not ok:
            return False
        self._web_engine = eng
        settings.set_web_engine(eng)
        if hasattr(self, "cmb_web_engine"):
            idx = self.cmb_web_engine.findData(eng)
            if idx >= 0:
                self.cmb_web_engine.blockSignals(True)
                self.cmb_web_engine.setCurrentIndex(idx)
                self.cmb_web_engine.blockSignals(False)
        self._inspect_platform = "Web"
        self._inspect_udid = ""
        self._inspect_chosen = True
        self._update_device_status()
        return True

    def _configure_mobile_inspect(self, plat: str, title: str = "连接检视设备") -> bool:
        """配置 Android/iOS 检视目标（选 UDID，iOS 可填 WDA bundle）。"""
        if plat not in ("Android", "iOS"):
            return False
        if not self._pick_udid(plat):
            return False
        if plat == "iOS":
            wda, ok = QInputDialog.getText(
                self, title, "WDA bundle id：",
                text=self._inspect_wda)
            if not ok:
                return False
            self._inspect_wda = wda.strip()
        self._inspect_platform = plat
        self._resolve_inspect_udid()
        return self._commit_mobile_target()

    def _pick_inspect_target(self, *, title: str = "选择检视目标") -> bool:
        """检视器向导：先选平台，再选真机或 Web URL（刷新快照前 / 菜单连接检视共用）。"""
        plat = self._pick_inspect_platform(title)
        if not plat:
            return False
        if plat == "Web":
            if not self._configure_web_inspect(title):
                return False
        elif not self._configure_mobile_inspect(plat, title):
            return False
        self._reset_inspect_session()
        tail = self._inspect_udid if plat in ("Android", "iOS") else self._inspect_url
        self.console.log(f"检视目标已设置：{plat} {tail or ''}".strip(), "检视")
        self.console.log(self._dep_hint(plat), "检视")
        self._sync_device_panel_controls()
        return True

    def connect_inspector(self) -> None:

        if not self._has_mobile_device():
            QMessageBox.information(
                self, "连接检视设备", self._no_mobile_devices_message())
        if not self._pick_inspect_target(title="连接检视设备"):
            return
        if hasattr(self, "inspector"):
            self.inspector.refresh()

    @staticmethod
    def _device_pick_label(platform: str, udid: str) -> str:
        """选机展示：机型/名称 + 完整 id；与 AI 编写/运行选机共用 friendly_pick_labels。"""

        # noinspection PyBroadException
        try:
            labels = friendly_pick_labels(platform, [udid])
            if labels:
                return labels[0]
        except Exception:
            pass
        return device_label(platform, udid)

    def _choose_device(self, title: str, prompt: str) -> tuple:
        """在检测到的 Android/iOS 间定目标（单台自动、多台弹选、无设备中止）。

        统一规则见 device_select.choose_device；返回 (status, (platform, udid)|None)，
        status ∈ {'ok','empty','cancel'}。命中后已写入 _inspect_platform/_inspect_udid + 状态栏。"""

        lists = self._device_lists()
        choices = build_choices(list(lists.android), list(lists.ios))
        values = [u for _p, u in choices]
        cur = self._inspect_udid or ""
        status, pick = choose_device(
            list(lists.android), list(lists.ios), cur,
            list_pick_ask(self, title, prompt, values=values),
            label_fn=self._device_pick_label,
            ask_returns_udid=True,
        )
        if status == "ok":
            self._inspect_platform, self._inspect_udid = pick
            self._update_device_status()
        return status, pick

    @staticmethod
    def _short_device_label(text: str, limit: int = 18) -> str:
        t = (text or "").strip()
        if len(t) <= limit:
            return t or "默认"
        return t[: limit - 1] + "…"

    def _update_device_status(self) -> None:
        """刷新状态栏设备 Chip（idle / detected / connected）。"""
        chip = getattr(self, "_sb_device", None)
        if chip is None or not hasattr(chip, "set_status"):
            return
        if getattr(self, "_inspect_chosen", False):
            plat = getattr(self, "_inspect_platform", "") or "?"
            tail = (getattr(self, "_inspect_udid", "") or getattr(self, "_inspect_url", "")
                    or "默认")
            short = self._short_device_label(tail)
            chip.set_status(
                "connected",
                f"{plat} · {short}",
                f"检视已连接：{plat} {tail}\n点击查看已连接设备列表",
            )
            return
        android, ios = getattr(self, "_devices", ([], []))
        parts: list[str] = []
        if android:
            parts.append(f"Android {len(android)}")
        if ios:
            parts.append(f"iOS {len(ios)}")
        if parts:
            chip.set_status(
                "detected",
                f"已检测 {' / '.join(parts)}",
                "已插入设备，点击查看已连接列表",
            )
        else:
            chip.set_status("idle", "未连接设备", "点击查看已连接设备 / 连接检视")
        self._sync_device_panel_controls()

    def _sync_device_panel_controls(self) -> None:
        """按当前设备列表同步检视器/镜像面板可启动态（无真机时镜像禁用）。"""

        mobile = self._has_mobile_device()
        mirror = getattr(self, "mirror", None)
        if mirror is not None and hasattr(mirror, "set_mobile_available"):
            hint = no_device_placeholder(for_mirror=True) if not mobile else ""
            mirror.set_mobile_available(mobile, hint=hint)

    def _ensure_inspect_device(self) -> bool:
        """「刷新快照」前确认检视目标：已选过则校验仍在线；否则先选平台再选设备/Web。"""
        if getattr(self, "_inspect_chosen", False):
            self._resolve_inspect_udid()
            ok, msg = self._inspect_device_available()
            if ok:
                return True
            gone = (getattr(self, "_inspect_udid", "") or "").strip()
            self._inspect_chosen = False
            self._release_runner_exclude_if_unbound(gone)
            self._warn_inspect_unavailable(msg)
            return False
        return self._pick_inspect_target(title="选择检视目标")

    def _pick_udid(self, plat: str) -> bool:
        """选择目标设备 UDID：已检测到的列成下拉（多台时显式选，避免「首个」歧义），
        无在线设备则中止。返回是否确认。"""

        detected = self._devices_for_platform(plat)
        manual = "（手动输入…）"
        if not detected:

            lines = pick_udid_unavailable_message(plat, self._device_lists())
            QMessageBox.warning(self, "连接检视设备", lines)
            self.console.log(lines.replace("\n", " "), "检视", "WARNING")
            return False
        if len(detected) == 1:
            self._inspect_udid = detected[0]      # 单台直接用，不弹选
            return True
        if detected:
            cur = self._inspect_udid if self._inspect_udid in detected else detected[0]
            labels: list[str] = []
            for u in detected:
                # noinspection PyBroadException
                try:
                    labels.append(device_picker_line(plat, u))
                except Exception:
                    labels.append(u)
            labels.append(manual)
            values = list(detected) + [manual]
            choice, ok = pick_list_item(
                self, "连接检视设备", f"{plat} 设备（已检测 {len(detected)} 台）：",
                labels, values.index(cur) if cur in values else 0,
                values=values)
            if not ok:
                return False
            if choice != manual:
                self._inspect_udid = choice
                return True
        udid, ok = QInputDialog.getText(
            self, "连接检视设备", "设备 UDID：", text=self._inspect_udid)
        if not ok:
            return False
        udid = udid.strip()
        if not udid:
            QMessageBox.warning(self, "连接检视设备", "请填写设备 UDID。")
            return False
        self._inspect_udid = udid
        return True

    def _dep_hint(self, plat: str) -> str:
        """各平台检视依赖提示，避免用户上来就撞连接失败。"""
        if plat == "iOS":
            mode = getattr(self, "_ios_backend_mode", "auto") or "auto"
            if mode == "appium":
                return ("iOS 检视强制 Appium：将自动 go-ios 准备 WDA 并以 webDriverAgentUrl 直连"
                        "（勿 usePreinstalledWDA）；请确认设备已解锁并信任此电脑。")
            if mode == "wda":
                return ("iOS 检视强制 WDA-direct：请确认 WebDriverAgent 已安装、"
                        "设备已解锁并信任此电脑，端口转发正常。")
            resolved = mp.effective_ios_backend_label(mode)
            return (f"iOS 检视为 Auto 模式，将按宿主环境选择 {resolved}。"
                    " Mac 默认 Appium + go-ios WDA；Windows/Linux 默认 WDA-direct。")
        return {
            "Android": "Android 控件检视依赖 Appium（uiautomator2）——未启动会自动拉起；实时镜像走 scrcpy 不需 Appium。",
            "Web": "Web 检视走 Selenium 浏览器，不需 Appium。",
        }.get(plat, "")

    def _ios_inspector_uses_appium(self) -> bool:
        mode = getattr(self, "_ios_backend_mode", "auto") or "auto"
        return mp.ios_inspector_uses_appium(mode)

    # ---- 会话清理（镜像/检视/终止快照共用的组件化拆分）----
    @staticmethod
    def _close_mobile_driver(ctx) -> None:
        """退移动端 driver——iOS 会连带 IosDevicePrep.stop()：杀隧道/runwda/端口转发。"""
        if ctx is None:
            return
        # noinspection PyBroadException
        try:
            from ...keywords.mobile.driver import get_manager as _m  # 延迟：可选 Appium
            _m(ctx).close()
        except Exception:
            pass

    @staticmethod
    def _quit_web_driver(ctx) -> None:
        if ctx is None:
            return
        # noinspection PyBroadException
        try:
            from ...keywords.web.driver import get_manager as _w  # 延迟：可选 Selenium
            _w(ctx).quit_all()
        except Exception:
            pass

    def _stop_our_appium(self) -> None:
        """只停我们自己拉起的 Appium（4723），不动用户自管的服务。"""
        srv = getattr(self, "_appium_server", None)
        if srv is None:
            return
        # noinspection PyBroadException
        try:
            srv.stop()
        except Exception:
            pass

    def _reset_inspect_session(self, *, blocking: bool = True) -> None:
        """彻底还原检视会话：退移动端 driver+WDA 准备、退浏览器、停我们起的 Appium、清 ctx。

        ``blocking=False``：关闭/收尾放到后台线程，避免终止检视时卡住 GUI。
        关窗路径须 ``blocking=True``，确保进程退出前尽量释放端口。
        """
        ctx = self._inspect_ctx
        old_udid = ""
        if ctx is not None:
            old_udid = str(ctx.get_var("__device_udid__") or "").strip()
        self._inspect_ctx = None
        if hasattr(self, "inspector"):
            self.inspector.sync_cancel_btn()
        self._release_runner_exclude_if_unbound(old_udid)

        def _work() -> None:
            self._close_mobile_driver(ctx)
            self._quit_web_driver(ctx)
            self._stop_our_appium()

        if blocking or ctx is None:
            _work()
            return

        threading.Thread(
            target=_work, name="reset-inspect-session", daemon=True
        ).start()

    def _on_inspect_cancelled(self) -> None:
        """用户终止检视：释放会话并清除检视目标，下次「刷新快照」从平台重选。"""
        gone = (getattr(self, "_inspect_udid", "") or "").strip()
        self._reset_inspect_session(blocking=False)
        self._inspect_chosen = False
        self._runner_guard_bound_plat = ""
        self._runner_guard_bound_udid = ""
        self._release_runner_exclude_if_unbound(gone)
        self._update_device_status()
        self.console.log("检视已终止；点「刷新快照」重新选择平台与目标", "检视")
        if hasattr(self, "inspector"):
            self.inspector.view.set_hint(
                "检视已终止\n点「🔄 刷新快照」重新选择平台（Android / iOS / Web）与设备")

    def _release_device_session(self, *, blocking: bool = False) -> None:
        """释放移动 driver/Appium（控制重建时可调用，不关高帧画面）。

        非阻塞时先摘掉 ``_inspect_ctx``，避免后台 close 与下一次建会话竞态。
        """
        ctx = self._inspect_ctx
        if not blocking:
            self._inspect_ctx = None

        def _work() -> None:
            self._close_mobile_driver(ctx)
            self._stop_our_appium()

        if blocking or ctx is None:
            _work()
            return

        threading.Thread(
            target=_work, name="release-device-session", daemon=True
        ).start()

    def _ensure_appium_server(self, log_tag: str = "检视") -> bool:
        """确保 Appium server 就绪（Android 检视 / Mac iOS Appium 镜像控制）。"""
        log = get_logger(log_tag)
        # noinspection PyBroadException
        try:
            if not self._appium_server.is_running():
                from ...keywords.mobile.appium_server import resolve_appium_binary  # 延迟：仅探测本机 Appium
                appium_bin = resolve_appium_binary()
                log.info(
                    "Appium 未运行，正在自动启动（127.0.0.1:4723）… bin=%s",
                    appium_bin or "(未找到)")
            self._appium_server.ensure_running()
            return True
        except RuntimeError as e:
            log.error("Appium 不可用：%s", e)
            return False
        except Exception as e:  # noqa: BLE001
            log.error("Appium 启动异常：%s", e)
            return False

    def _ensure_android_appium(self) -> bool:
        return self._ensure_appium_server("检视")

    def _inspector_snapshot(self):
        """为检视器取 (截图png, page_source/DOM, platform)；无会话则尝试建立。"""
        plat = self._inspect_platform
        if plat == "Web":
            return self._inspector_web_snapshot()
        if not self._guard_mobile_session_target("检视"):
            return None
        from ...keywords.mobile.driver import get_manager
        if self._inspect_ctx is None:
            self._inspect_ctx = ExecutionContext()
            self._inspect_ctx.set_var("__device_udid__", self._inspect_udid)
            self._inspect_ctx.set_var("__inspect_platform__", plat)
            backend_mode = getattr(self, "_ios_backend_mode", "auto") or "auto"
            self._inspect_ctx.set_var("__mobile_backend_mode__", backend_mode)
            if plat == "iOS":
                from ...mobile import ios_bootstrap as ib  # 延迟：iOS 工具链
                base_vars: dict = {}
                if self._inspect_wda:
                    base_vars["__appium_caps__"] = {"wdaBundleId": self._inspect_wda}
                if self._ios_inspector_uses_appium():
                    ib.merge_appium_ios_caps(
                        base_vars, self._inspect_udid, self._inspect_wda.strip(),
                        backend_mode)
                    self._inspect_ctx.set_var(
                        "__appium_server__",
                        getattr(self._appium_server, "url", None) or "http://127.0.0.1:4723")
                for k, v in base_vars.items():
                    self._inspect_ctx.set_var(k, v)
            elif self._inspect_wda:
                self._inspect_ctx.set_var("__appium_caps__", {"wdaBundleId": self._inspect_wda})
        # 协作取消：终止检视时置位，打断 IosDevicePrep 等待循环
        if hasattr(self, "inspector"):
            self._inspect_ctx.set_var(
                "__inspect_cancel_event__", self.inspector.cancel_event)
        if plat == "Android" and not self._ensure_android_appium():
            return None                     # Appium 未就绪：已给友好提示，不撞 ECONNREFUSED
        if plat == "iOS" and self._ios_inspector_uses_appium() and not self._ensure_android_appium():
            return None
        mgr = get_manager(self._inspect_ctx)
        last = ""
        for attempt in range(2):            # 会话失效（terminated/not started）→ 关掉重建一次
            # noinspection PyBroadException
            try:
                # noinspection PyBroadException
                try:
                    drv = mgr.driver()
                except Exception:
                    mgr.create(plat, "", "", self._inspect_udid)
                    drv = mgr.driver()
                png = drv.get_screenshot_as_png()
                xml = drv.page_source
                backend = getattr(mgr, "backend", "")
                logical_size = None
                if plat == "iOS" and getattr(mgr, "backend", "") == "appium":
                    # 仅 Appium iOS 需要 logical_size；WDA-direct 走根 bounds，与 Windows 一致
                    # noinspection PyBroadException
                    try:
                        logical_size = drv.get_window_size()
                    except Exception:
                        pass
                return (
                    png, xml, "ios" if plat == "iOS" else "android", backend, logical_size,
                )
            except Exception as e:  # noqa: BLE001
                last = clean_driver_err(e, plat, getattr(mgr, "backend", ""))
                if attempt == 0:
                    # noinspection PyBroadException
                    try:
                        mgr.close()
                    except Exception:
                        pass
                    continue
                break
        get_logger("检视").error("检视取快照失败：%s", last)
        if plat == "iOS":
            backend = ""
            # noinspection PyBroadException
            try:
                backend = getattr(get_manager(self._inspect_ctx), "backend", "")
            except Exception:
                pass
            if backend == "appium":
                get_logger("检视").warning(
                    "iOS Appium：确认 Appium 服务、XCUITest 驱动就绪，设备已解锁并信任此电脑")
            else:
                get_logger("检视").warning(
                    "iOS WDA-direct：确认设备已解锁并信任此电脑、WebDriverAgent 已安装且未过期"
                    "（免费证书 7 天）；换机后旧转发会自动回收重建，稍候重点「刷新快照」即可")
        else:
            get_logger("检视").warning(
                "确认设备已授权（USB 调试）、Appium 与 uiautomator2 驱动正常，"
                "重连设备后再点「刷新快照」")
        return None

    def _inspector_web_snapshot(self):
        """Web 检视：复用浏览器会话（无则新建并打开 URL）→ DOM 快照 + 截图。"""
        from ...keywords.web.driver import get_manager as get_web_manager  # 延迟：仅 Web 检视
        from ...inspector.web_snapshot import web_snapshot
        if self._inspect_ctx is None:
            self._inspect_ctx = ExecutionContext()
        eng = getattr(self, "_web_engine", None) or settings.web_engine()
        if eng in ("selenium", "playwright"):
            self._inspect_ctx.set_var("__web_engine__", eng)
        mgr = get_web_manager(self._inspect_ctx)
        # noinspection PyBroadException
        try:
            # noinspection PyBroadException
            try:
                drv = mgr.driver()
            except Exception:
                drv = mgr.open("", getattr(self, "_inspect_browser", "chrome") or "chrome")
                url = getattr(self, "_inspect_url", "") or ""
                if url and url != "https://":
                    drv.get(url)
            png, payload = web_snapshot(drv)
            return png, payload, "web"
        except Exception as e:  # noqa: BLE001
            get_logger("检视").error("Web 检视取快照失败：%s", clean_driver_err(e))
            return None

    def _ios_session_alive(self) -> bool:
        """iOS 是否已有可用自动化会话（含 Appium session 探活）。"""
        if self._inspect_ctx is None:
            return False
        from ...keywords.mobile.driver import get_manager, ios_session_probe  # 延迟：可选 Appium/WDA
        return ios_session_probe(get_manager(self._inspect_ctx))

    def _inspector_fill_step(self, locator: str) -> None:
        from ...model.testcase import Step, StepVerbs, ParamValue  # 延迟：仅回填步骤定位符

        editor = self._current_step_editor()
        node = editor.selected_node() if editor else None
        if node is None or not hasattr(node, "params"):
            self.console.log("请先在用例/套件/自定义关键字编辑器中选中一个步骤，再填入定位符", "检视", "WARNING")
            return
        kid = getattr(node, "keyword_id", "") or getattr(node, "ks_id", "") or ""
        if is_picture_locator(locator) and not supports_picture_locator(kid):
            self.console.log(picture_fill_hint(kid), "检视", "WARNING")
            return
        # 优先替换已有 locator/element 参数，否则新增 locator
        # selected_node() 静态类型偏宽；上面已用 hasattr(params) 收窄
        params = getattr(node, "params")
        target = next((p for p in params if p.param_id in ("locator", "element", "by")), None)
        if target is not None:
            target.value = locator
        else:
            params.append(ParamValue("locator", locator))
        editor.refresh_node_row(node)
        if isinstance(node, (Step, StepVerbs)):
            self._on_step_selected(node)
        self.console.log(f"已填入步骤定位符：{locator}", "检视")

    def _ask_crop_image_path(self, default_path: str) -> str:
        """弹出另存为；测试可注入 ``_pick_crop_image_path`` 回调绕过对话框。"""
        picker = getattr(self, "_pick_crop_image_path", None)
        if callable(picker):
            return str(picker(default_path) or "")
        path, _ = QFileDialog.getSaveFileName(
            self, "保存图片定位", default_path, "PNG 图片 (*.png)")
        return path or ""

    def _on_inspector_crop(self, png: bytes) -> None:
        """检视器框选裁出的图片 → 另存为对话框选路径 → picture:: 定位并填入步骤。"""
        if not (self.project_dir and os.path.isdir(self.project_dir)):
            self.console.log("请先打开工程，再保存图片定位", "检视", "WARNING")
            return
        img_dir = os.path.join(self.project_dir, "images")
        # noinspection PyBroadException
        try:
            os.makedirs(img_dir, exist_ok=True)
        except OSError:
            pass
        default_name = datetime.now().strftime("%Y%m%d%H%M%S") + ".png"
        default_path = os.path.join(img_dir, default_name)
        path = self._ask_crop_image_path(default_path)
        if not path:
            self.console.log("已取消图片定位（未保存）", "检视")
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        # noinspection PyBroadException
        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(path, "wb") as f:
                f.write(png)
        except OSError as e:
            self.console.log(f"图片保存失败：{e}", "检视", "ERROR")
            return
        locator = picture_locator_for_path(self.project_dir, path)
        rel_or_abs = locator.partition("::")[2]
        self.console.log(f"已保存图片定位：{rel_or_abs}", "检视")
        self._inspector_fill_step(locator)            # 顺带填入当前选中步骤(无选中则提示)

    def _inspector_to_map(self, locator: str) -> None:
        if self.center.currentWidget() is not self.map_editor or self.map_editor.mapfile is None:
            self.console.log("请先打开或新建一个对象库(.map)，再写入定位符", "检视", "WARNING")
            return
        name, ok = QInputDialog.getText(self, "写入对象库", "控件命名：")
        if not ok or not name.strip():
            return
        from ...model.mapfile import MapElement, Locator  # 延迟：仅写入对象库
        prefix, _, value = locator.partition("::")
        type_map = {"id": "ID", "name": "NAME", "xpath": "XPATH", "css": "CSS",
                    "predicate": "PREDICATE",
                    "classname": "CLASS", "linktext": "TEXT"}
        loc = Locator(type=type_map.get(prefix, "XPATH"), value=value or locator)
        slot_locators = {}
        inspect_platform = (getattr(self, "_inspect_platform", "") or "").lower()
        inspect_backend = getattr(self.inspector, "_backend", "") or ""
        if inspect_platform == "android":
            slot_locators["android"] = loc
        elif inspect_platform == "ios":
            if inspect_backend == "appium":
                slot_locators["ios_appium"] = loc
            elif inspect_backend == "wda":
                slot_locators["ios_wda"] = loc
            else:
                slot_locators["ios"] = loc
        element = (MapElement(name=name.strip(), locator=loc)
                   if not slot_locators
                   else MapElement(name=name.strip(), locator=None,
                                   locators_by_platform=slot_locators))
        self.map_editor.mapfile.elements.append(element)
        self.map_editor.show_map(self.map_editor.mapfile, select=element)
        self.console.log(f"已写入对象库元素：{name}（{locator}）", "检视")

    # ---- 设备信息 / 安装包信息 / iOS 装包 ----
    def show_connected_devices(self) -> None:
        """菜单「已连接设备…」：在光标附近弹出设备列表菜单。"""
        menu = self._build_connected_devices_menu()
        menu.exec(QCursor.pos())

    def show_device_chip_menu(self) -> None:
        """状态栏 Chip 点击：弹出已连接设备列表（替代直接进连接向导）。"""
        chip = getattr(self, "_sb_device", None)
        menu = self._build_connected_devices_menu()
        if chip is not None:
            menu.exec(chip.mapToGlobal(chip.rect().bottomLeft()))
        else:
            menu.exec(QCursor.pos())

    def _build_connected_devices_menu(self):
        android, ios = getattr(self, "_devices", ([], []))
        devices = list_connected_devices(android, ios)
        return build_connected_devices_menu(
            self,
            devices,
            inspect_chosen=bool(getattr(self, "_inspect_chosen", False)),
            inspect_platform=getattr(self, "_inspect_platform", "") or "",
            inspect_udid=getattr(self, "_inspect_udid", "") or "",
            on_set_inspect=self._set_inspect_from_connected,
            on_show_info=self._show_info_for_connected,
            on_start_mirror=self._start_mirror_from_connected,
        )

    def _set_inspect_from_connected(self, device) -> None:
        """从已连接列表设为检视目标（不走完整连接向导；iOS 保留已有 WDA bundle）。"""
        plat = getattr(device, "platform", "") or ""
        udid = getattr(device, "udid", "") or ""
        if plat not in ("Android", "iOS") or not udid:
            return
        self._inspect_platform = plat
        self._inspect_udid = udid
        if not self._commit_mobile_target(tag="检视"):
            return
        self._reset_inspect_session()
        self.console.log(f"检视设备已设置：{plat} {self._inspect_udid}", "检视")
        self.console.log(self._dep_hint(plat), "检视")
        self._inspect_chosen = True
        self._update_device_status()
        self._sync_device_panel_controls()
        if hasattr(self, "inspector"):
            self.inspector.refresh()

    def _show_info_for_connected(self, device) -> None:
        """对列表中指定设备直接读信息（跳过再选）。"""
        plat = (getattr(device, "platform", "") or "").strip().lower()
        device_id = getattr(device, "udid", "") or ""
        if plat not in ("android", "ios") or not device_id:
            return
        # noinspection PyBroadException
        try:
            if plat == "android":
                sheet = collect_android_device_info(device_id)
            else:
                sheet = collect_ios_device_info(device_id)
        except Exception as e:  # noqa: BLE001
            self.console.log(f"读取设备信息失败：{e}", "设备", "ERROR")
            return
        self.console.log(f"已读取 {sheet.title}", "设备")
        show_info_sheet(self, sheet.title, sheet.rows)

    def show_device_info(self) -> None:
        """选已连接 Android/iOS 设备 → 汇总硬件/系统信息（不依赖 Appium 会话）。"""
        target = self._pick_connected_device("查看设备信息")
        if target is None:
            return
        platform, device_id = target
        try:
            if platform == "android":
                sheet = collect_android_device_info(device_id)
            else:
                sheet = collect_ios_device_info(device_id)
        except Exception as e:  # noqa: BLE001
            self.console.log(f"读取设备信息失败：{e}", "设备", "ERROR")
            return
        self.console.log(f"已读取 {sheet.title}", "设备")
        show_info_sheet(self, sheet.title, sheet.rows)

    def _ask_device_pick_runtime(
        self, title: str, prompt: str, *, current: str = "",
    ) -> tuple[str, str] | None:
        """跨 Android/iOS 弹选一台，返回 (android|ios, udid)。"""

        android, ios = getattr(self, "_devices", ([], []))
        choices = build_choices(android, ios)
        values = [u for _p, u in choices]
        status, pick = choose_device_runtime(
            android, ios, current or "",
            list_pick_ask(self, title, prompt, values=values),
            label_fn=self._device_pick_label,
            ask_returns_udid=True,
        )
        if status != "ok" or not pick:
            return None
        return pick

    def _pick_connected_device(self, title: str) -> tuple[str, str] | None:
        """从当前监控到的设备里选一个。返回 (android|ios, serial/udid)。"""

        if not self._has_mobile_device():
            QMessageBox.information(self, title, no_device_info_message())
            self.console.log("未检测到设备，无法查看设备信息", "设备", "WARNING")
            return None
        return self._ask_device_pick_runtime(title, "选择目标设备：")

    def show_package_info(self) -> None:
        """选一个 .ipa/.apk/.xapk → 纯 Python 解析 → 只读对话框展示元信息与签名/描述文件。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择安装包", "", "移动安装包 (*.ipa *.apk *.xapk);;所有文件 (*)")
        if not path:
            return
        low = path.lower()
        try:
            if low.endswith(".ipa"):
                from ...mobile.ipa import parse_ipa  # 延迟：仅 iOS 包解析
                i = parse_ipa(path)
                title = "IPA 包信息"
                exp = i.expiration_date
                if exp and i.expires_in_days is not None:
                    exp += (f"（剩 {i.expires_in_days} 天）" if i.expires_in_days >= 0
                            else f"（已过期 {-i.expires_in_days} 天）")
                rows = [
                    ("Bundle ID", i.display(i.bundle_id)), ("应用名", i.display(i.app_name)),
                    ("版本(Short)", i.display(i.version_name)),
                    ("构建号(Bundle)", i.display(i.version_code)),
                    ("最低系统", i.display(f"iOS {i.minimum_os}" if i.minimum_os else "")),
                    ("设备类型", i.display(i.device_family)),
                    ("URL Scheme", i.display(i.url_schemes)),
                    ("隐私权限", i.display(i.permissions)),
                    ("分发类型", i.display(i.signing_type)),
                    ("描述文件", i.display(i.provision_name)),
                    ("AppID 名", i.display(i.app_id_name)),
                    ("团队", i.display(i.team_name or i.team_identifier)),
                    ("推送环境", i.display(i.aps_environment)),
                    ("UUID", i.display(i.uuid)),
                    ("过期时间", i.display(exp)),
                    ("授权设备数", i.display(len(i.provisioned_devices)
                                        if i.provisioned_devices else "")),
                    ("MD5", i.display(i.file_md5)), ("大小", f"{i.file_size_mb} MB"),
                ]
                self.console.log(
                    f"IPA：{i.bundle_id} v{i.version_name}（{i.signing_type}，最低 iOS {i.minimum_os or '—'}）",
                    "设备")
            elif low.endswith((".apk", ".xapk")):
                from ...mobile.apk import parse_apk  # 延迟：仅 Android 包解析
                from ...mobile.xapk import is_xapk_path, primary_apk_for_parse

                with primary_apk_for_parse(path) as parse_path:
                    a = parse_apk(parse_path)
                title = "XAPK 包信息" if is_xapk_path(path) else "APK 包信息"
                perm_txt = a.display(a.permissions)
                if len(a.permissions) > 8:
                    perm_txt = f"{perm_txt[:120]}…（共 {len(a.permissions)} 项）"
                rows = [
                    ("包名", a.display(a.package)),
                    ("应用名", a.display(a.app_name)),
                    ("主 Activity", a.display(a.main_activity)),
                    ("版本名", a.display(a.version_name)),
                    ("版本号", a.display(a.version_code)),
                    ("最低 SDK", a.display(f"API {a.min_sdk}" if a.min_sdk else "")),
                    ("目标 SDK", a.display(f"API {a.target_sdk}" if a.target_sdk else "")),
                    ("最高 SDK", a.display(f"API {a.max_sdk}" if a.max_sdk else "")),
                    ("原生 ABI", a.display(a.native_abis)),
                    ("权限", perm_txt),
                    ("签名", a.display(a.signing)),
                    ("MD5", a.display(a.file_md5)),
                    ("大小", f"{a.file_size_mb} MB"),
                ]
                self.console.log(
                    f"{'XAPK' if is_xapk_path(path) else 'APK'}：{a.package} v{a.version_name}"
                    f"（minSdk={a.min_sdk or '—'}，权限 {len(a.permissions)} 项）",
                    "设备")
            else:
                self.console.log("仅支持 .ipa / .apk / .xapk 安装包", "设备", "WARNING")
                return
        except Exception as e:  # noqa: BLE001
            self.console.log(f"解析安装包失败：{e}", "设备", "ERROR")
            return
        show_info_sheet(self, title, rows)

    def _pick_ios_udid_for_install(self) -> tuple:
        """为装包选 iOS 目标设备：单台自动、多台弹选、无设备允许手动/留空。
        返回 (ok: bool, udid: str)。"""

        mode, udid = ios_install_pick_status(self._device_lists())
        if mode == "ok":
            return True, udid
        if mode == "multi":
            ios = list(self._device_lists().ios)
            labels: list[str] = []
            for u in ios:
                # noinspection PyBroadException
                try:
                    labels.append(device_picker_line("iOS", u))
                except Exception:
                    labels.append(u)
            sel, ok = pick_list_item(
                self, "安装 iOS 应用", f"目标 iOS 设备（已检测 {len(ios)} 台）：",
                labels, 0, values=ios)
            return ok, (sel if ok else "")
        udid, ok = QInputDialog.getText(
            self, "安装 iOS 应用", no_ios_install_message())
        return ok, udid.strip()

    def install_ios_app(self) -> None:
        """选设备 + .ipa → parse_ipa 预检（不过给可操作提示并中止）→ 后台 go-ios 装包。"""
        ok, udid = self._pick_ios_udid_for_install()
        if not ok:
            return
        path, _ = QFileDialog.getOpenFileName(self, "选择 IPA", "", "iOS 应用 (*.ipa)")
        if not path:
            return
        try:
            from ...mobile.ipa import parse_ipa, ipa_precheck  # 延迟：仅 iOS 装包预检
            info = parse_ipa(path)
            problems = ipa_precheck(info, udid)
        except Exception as e:  # noqa: BLE001
            self.console.log(f"IPA 解析失败：{e}", "设备", "ERROR")
            return
        if problems:
            for p in problems:
                self.console.log(f"预检未通过：{p}", "设备", "ERROR")
            return
        if not confirm(self, "安装 iOS 应用",
                       f"将安装到设备 {udid or '（默认）'}：\n\n"
                       f"{info.bundle_id}  v{info.version_name}\n"
                       f"最低系统 iOS {info.minimum_os or '—'}"):
            return
        self.console.log(f"开始安装 IPA：{info.bundle_id} → {udid or '默认设备'}", "设备")

        def job():
            from ...keywords.mobile.session import ios_install_app  # 延迟：仅 iOS 装包
            # noinspection PyBroadException
            try:
                backend = ios_install_app(path, udid, log=lambda m: get_logger("设备").info(m))
                return "ok", f"{info.bundle_id}（{backend}）"
            except Exception as ex:  # noqa: BLE001
                return "err", str(ex)

        self._ipa_install_worker = SnapshotWorker(job, self)
        # noinspection PyUnresolvedReferences
        self._ipa_install_worker.done.connect(self._on_ipa_install_done)
        self._ipa_install_worker.start()

    def _on_ipa_install_done(self, result) -> None:
        if not result:
            self.console.log("安装 IPA 失败（未知错误）", "设备", "ERROR")
            return
        status, msg = result
        if status == "ok":
            self.console.log(f"IPA 安装成功：{msg}", "设备")
        else:
            self.console.log(f"IPA 安装失败：{msg}", "设备", "ERROR")
