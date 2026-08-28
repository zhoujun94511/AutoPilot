"""本机 USB 设备探测（IDE 本地池 / 本机 UI）。

不依赖 ``managementconsole`` 包。Runner（``autopilot.runner``）复用本模块探测结果。
"""

from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass, field


@dataclass(frozen=True)
class LocalDevice:
    udid: str
    platform: str  # android | ios
    name: str = ""
    model: str = ""
    os_version: str = ""
    state: str = "ready"  # ready | error | unauthorized | offline
    backends: tuple[str, ...] = ()
    health_note: str = ""
    labels: tuple[str, ...] = field(default_factory=tuple)


def _parse_adb_devices(text: str) -> list[tuple[str, str]]:
    """返回 [(serial, state)]，state 为 device/unauthorized/offline/..."""
    out: list[tuple[str, str]] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices"):
            continue
        parts = line.split("\t") if "\t" in line else line.split()
        if len(parts) >= 2:
            out.append((parts[0], parts[1].strip().lower()))
    return out


def list_android_udids() -> list[str]:
    return [d.udid for d in list_android_devices() if d.state == "ready"]


def list_ios_udids() -> list[str]:
    """best-effort：与 IDE/tools 一致，走 ``python -m pymobiledevice3``（非 PATH 裸命令）。"""
    return [d.udid for d in list_ios_devices() if d.state == "ready"]


def _android_props(serial: str) -> tuple[str, str, str]:
    """返回 (model, version, name)。"""
    try:
        from autopilot.mobile.adb import run_adb

        def _prop(key: str) -> str:
            try:
                return (run_adb(["-s", serial, "shell", "getprop", key]) or "").strip()
            except (OSError, RuntimeError, TypeError, ValueError):
                return ""

        model = _prop("ro.product.model") or _prop("ro.product.device")
        ver = _prop("ro.build.version.release")
        name = _prop("ro.product.marketname") or _prop("ro.product.name") or model
        return name, model, ver
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return "", "", ""


def _ios_host_backends(has_appium: bool) -> list[str]:
    """本机可用的 iOS 后端。

    Windows/Linux 不支持 Appium 的 iOS17+ RemoteXPC 隧道，但可走 WDA-direct
    （go-ios 隧道/runwda + pymobiledevice3 端口转发），因此只要工具链在就算可用；
    Appium iOS 后端仍限 macOS。判断口径与 ``keywords.mobile.platform.select_backend`` 一致。
    """
    from autopilot.mobile.ios_devices import ios_tooling_available

    if not ios_tooling_available():
        return []
    if platform.system().lower() == "darwin":
        return ["ios-wda", "ios-appium"] if has_appium else ["ios-wda"]
    return ["ios-wda"]


def _host_backends() -> list[str]:
    """本机可提供的执行后端（轻量探测，不启会话）。"""
    backends: list[str] = []
    try:
        from autopilot.mobile.adb import ensure_adb

        has_adb = bool(ensure_adb())
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        has_adb = bool(shutil.which("adb"))
    has_appium = bool(shutil.which("appium"))
    if has_adb:
        backends.append("android-appium")
    backends.extend(_ios_host_backends(has_appium))
    return backends


def _has_web_browser() -> bool:
    """本机是否可跑 web(Selenium) 用例：显式开关优先，否则探测常见浏览器。

    MC_RUNNER_WEB=1/0 可强制开启/关闭；Selenium Manager 会自动解析对应 driver。
    """
    forced = os.environ.get("MC_RUNNER_WEB", "").strip().lower()
    if forced in ("1", "true", "yes", "on"):
        return True
    if forced in ("0", "false", "no", "off"):
        return False
    names = (
        "chrome", "google-chrome", "chromium", "chromium-browser",
        "msedge", "microsoft-edge", "firefox",
    )
    if any(shutil.which(n) for n in names):
        return True
    sysname = platform.system().lower()
    if sysname.startswith("win"):
        candidates = (
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
        )
        return any(os.path.exists(c) for c in candidates)
    if sysname == "darwin":
        candidates = (
            "/Applications/Google Chrome.app",
            "/Applications/Microsoft Edge.app",
            "/Applications/Firefox.app",
        )
        return any(os.path.exists(c) for c in candidates)
    return False


def _has_playwright() -> bool:
    """本机是否可跑 web_engine=playwright：包 + Chromium 浏览器已安装。

    MC_RUNNER_WEB_PLAYWRIGHT=1/0 可强制开启/关闭 Runner 上报 web-playwright 能力。
    """
    forced = os.environ.get("MC_RUNNER_WEB_PLAYWRIGHT", "").strip().lower()
    if forced in ("1", "true", "yes", "on"):
        return True
    if forced in ("0", "false", "no", "off"):
        return False
    try:
        import importlib.util

        if importlib.util.find_spec("playwright") is None:
            return False
        # 可选依赖 autopilot[web_playwright]：用 import_module，避免 IDE 报「未列入项目要求」
        sync_playwright = importlib.import_module("playwright.sync_api").sync_playwright
        pw = sync_playwright().start()
        try:
            exe = pw.chromium.executable_path
            return bool(exe and os.path.isfile(exe))
        finally:
            pw.stop()
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return False


def probe_host_capabilities() -> tuple[list[str], list[str]]:
    """返回 (capabilities, host_backends)。capabilities 含平台与功能标签。"""
    backends = _host_backends()
    caps: list[str] = ["parallel", "report", "http"]
    if "android-appium" in backends:
        caps.append("android")
    if "ios-wda" in backends or "ios-appium" in backends:
        caps.append("ios")
    if _has_web_browser():
        caps.append("web")
    if _has_playwright():
        caps.append("web-playwright")
    for b in backends:
        if b not in caps:
            caps.append(b)
    return caps, backends


def list_android_devices() -> list[LocalDevice]:
    host_backends = _host_backends()
    android_backends = tuple(b for b in host_backends if b.startswith("android-"))
    try:
        from autopilot.mobile.adb import ensure_adb, run_adb

        if not ensure_adb():
            return []
        rows = _parse_adb_devices(run_adb(["devices"]))
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return []

    out: list[LocalDevice] = []
    for serial, adb_state in rows:
        if adb_state == "device":
            name, model, ver = _android_props(serial)
            out.append(
                LocalDevice(
                    udid=serial,
                    platform="android",
                    name=name or serial,
                    model=model or "",
                    os_version=ver,
                    state="ready",
                    backends=android_backends or ("android-appium",),
                    health_note="",
                )
            )
        elif adb_state == "unauthorized":
            out.append(
                LocalDevice(
                    udid=serial,
                    platform="android",
                    name=serial,
                    state="unauthorized",
                    backends=(),
                    health_note="adb unauthorized; unlock phone and allow USB debugging",
                )
            )
        else:
            out.append(
                LocalDevice(
                    udid=serial,
                    platform="android",
                    name=serial,
                    state="offline" if adb_state == "offline" else "error",
                    backends=(),
                    health_note=f"adb state={adb_state}",
                )
            )
    return out


def list_ios_devices() -> list[LocalDevice]:
    host_backends = _host_backends()
    ios_backends = tuple(b for b in host_backends if b.startswith("ios-"))
    try:
        from autopilot.mobile.ios_devices import list_usb_devices, note_enumeration_error
        from autopilot.mobile.ios_marketing import marketing_name
    except ImportError:
        return []
    try:
        raw = list_usb_devices()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        # 静默返回空会被上层读成「没插设备」；留痕让提示能说出真实原因
        note_enumeration_error("enumerate", f"{type(exc).__name__}: {exc}")
        return []

    out: list[LocalDevice] = []
    for d in raw:
        udid = getattr(d, "udid", "") or ""
        if not udid:
            continue
        name = getattr(d, "name", "") or "iPhone"
        product_type = getattr(d, "product_type", "") or ""
        # 平台卡片的 model 应是用户认识的市场型号；ProductType 仅是内部硬件标识。
        # 未知新机型由 marketing_name 原样回退，避免映射滞后导致信息丢失。
        model = marketing_name(product_type)
        ver = getattr(d, "ios_version", "") or ""
        backends = ios_backends
        note = ""
        state = "ready"
        if not backends:
            state = "error"
            note = "no ios backend on this host (need macOS + WDA/Appium)"
        out.append(
            LocalDevice(
                udid=udid,
                platform="ios",
                name=name,
                model=model,
                os_version=ver,
                state=state,
                backends=backends,
                health_note=note,
            )
        )
    return out


def list_local_devices() -> list[LocalDevice]:
    return [*list_android_devices(), *list_ios_devices()]


def format_probe_report(devices: list[LocalDevice] | None = None) -> str:
    """CLI --dry-probe 输出。"""
    caps, backends = probe_host_capabilities()
    devices = list_local_devices() if devices is None else devices
    lines = [
        f"host capabilities: {', '.join(caps) or '(none)'}",
        f"host backends:     {', '.join(backends) or '(none)'}",
        f"devices ({len(devices)}):",
    ]
    if not devices:
        lines.append("  (none)")
    for d in devices:
        be = ",".join(d.backends) or "-"
        extra = f" note={d.health_note}" if d.health_note else ""
        lines.append(
            f"  [{d.state}] {d.platform} {d.udid} "
            f"name={d.name or '-'} model={d.model or '-'} "
            f"os={d.os_version or '-'} backends={be}{extra}"
        )
    return "\n".join(lines)
