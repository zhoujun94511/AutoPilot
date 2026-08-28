"""设备已装应用解析：应用名/别名 → package / bundle id。"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .contract import AuthoringError
from .system_app_aliases import (
    alias_entry,
    expand_hint_keys,
    is_android_settings_hint,
)


@dataclass(frozen=True)
class InstalledApp:
    package_name: str
    app_label: str = ""
    platform: str = ""


def _extract_json_object(text: str) -> str:
    """从可能夹带日志/ANSI 的输出里截出 JSON 对象；截不到返回空串。"""
    from ..mobile.ios_devices import strip_ansi

    s = strip_ansi(text or "").strip()
    if s.startswith("{"):
        return s
    start, end = s.find("{"), s.rfind("}")
    if 0 <= start < end:
        return s[start : end + 1]
    return ""


def _apps_from_pmd3_dict(data: object) -> list[InstalledApp]:
    if not isinstance(data, dict):
        return []
    out: list[InstalledApp] = []
    for bid, meta in data.items():
        pkg = str(bid or "").strip()
        if not pkg:
            continue
        label = ""
        if isinstance(meta, dict):
            label = str(
                meta.get("CFBundleDisplayName")
                or meta.get("CFBundleName")
                or meta.get("Name")
                or ""
            ).strip()
        out.append(InstalledApp(package_name=pkg, app_label=label or pkg, platform="ios"))
    return out


def _list_ios_apps_inproc(udid: str) -> list[InstalledApp] | None:
    """进程内 InstallationProxy：零 spawn、不受 CLI 输出格式影响。

    返回 ``None`` 表示通道不可用（与「设备上确实没装应用」的空列表区分）。
    """
    try:
        import asyncio

        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.installation_proxy import InstallationProxyService
    except ImportError:
        return None

    async def _load() -> object:
        ld = create_using_usbmux(serial=udid)
        if asyncio.iscoroutine(ld):
            ld = await ld
        svc = InstallationProxyService(lockdown=ld)
        # User 优先：编写场景几乎都是第三方 App，体量远小于 Any（常见 2MB+）
        apps = svc.get_apps(application_type="User")
        if asyncio.iscoroutine(apps):
            apps = await apps
        return apps

    try:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # 无运行中的事件循环：直接跑
            return _apps_from_pmd3_dict(asyncio.run(_load()))
        # 已在事件循环里（少见）：退回同步桥，避免嵌套 run
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return _apps_from_pmd3_dict(
                pool.submit(lambda: asyncio.run(_load())).result(timeout=60)
            )
    except (OSError, RuntimeError, TypeError, ValueError, TimeoutError, AttributeError):
        return None


def _list_ios_apps_cli(udid: str, *, app_type: str = "User") -> tuple[list[InstalledApp], str]:
    """pymobiledevice3 CLI。返回 (apps, error_detail)；成功时 error_detail 为空。"""
    cmd = [
        sys.executable,
        "-m",
        "pymobiledevice3",
        "apps",
        "list",
        "--udid",
        udid,
        "--type",
        app_type,
    ]
    from ..mobile.ios_devices import cli_subprocess_env, strip_ansi
    from ..runtime.subproc import run as run_hidden

    try:
        proc = run_hidden(
            cmd,
            capture_output=True,
            timeout=60,
            check=False,
            env=cli_subprocess_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], f"CLI 调用失败：{exc}"
    out = strip_ansi((proc.stdout or b"").decode("utf-8", "replace"))
    err = strip_ansi((proc.stderr or b"").decode("utf-8", "replace"))
    if proc.returncode != 0:
        tail = (err or out).strip().splitlines()
        return [], tail[-1][:200] if tail else f"exit={proc.returncode}"
    blob = _extract_json_object(out)
    if not blob:
        tail = out.strip().splitlines()
        hint = tail[-1][:120] if tail else "(空输出)"
        return [], f"返回非 JSON：{hint}"
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as exc:
        return [], f"返回非 JSON：{exc.msg}"
    return _apps_from_pmd3_dict(data), ""


def _list_ios_apps_goios(udid: str) -> list[InstalledApp]:
    """go-ios ``apps --list`` 文本行：``bundleid DisplayName version``。"""
    try:
        from ..mobile.ios_bootstrap import resolve_go_ios
    except ImportError:
        return []
    exe = resolve_go_ios()
    if exe is None:
        return []
    from ..mobile.ios_devices import cli_subprocess_env
    from ..runtime.subproc import run as run_hidden

    try:
        proc = run_hidden(
            [str(exe), "apps", "--list", "--udid", udid],
            capture_output=True,
            timeout=60,
            check=False,
            env=cli_subprocess_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    text = (proc.stdout or b"").decode("utf-8", "replace")
    out: list[InstalledApp] = []
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) < 1:
            continue
        pkg = parts[0].strip()
        if not pkg or "." not in pkg:
            continue
        # 中间字段是显示名（可能含空格），最后常是版本号 x.y.z
        label = pkg
        if len(parts) >= 2:
            mid = parts[1:-1] if len(parts) >= 3 and re.match(r"^\d", parts[-1]) else parts[1:]
            label = " ".join(mid).strip() or pkg
        out.append(InstalledApp(package_name=pkg, app_label=label, platform="ios"))
    return out


def list_ios_installed_apps(udid: str) -> list[InstalledApp]:
    """列举设备已装应用：进程内 InstallationProxy → CLI(User) → go-ios。

    旧实现只跑 ``pymobiledevice3 apps list`` 并 ``json.loads`` 整段 stdout：一旦 CLI
    夹带日志、或与设备监听抢 usbmux 输出异常，就会抛「返回非 JSON」，把明明插着的
    手机说成解析失败。进程内通道与设备监测同源，优先走它。
    """
    serial = (udid or "").strip()
    if not serial:
        raise AuthoringError("列举 iOS 应用需要 udid")

    inproc = _list_ios_apps_inproc(serial)
    if inproc:
        return inproc

    apps, cli_err = _list_ios_apps_cli(serial, app_type="User")
    if apps:
        return apps

    # User 为空时再拉 Any（系统 App / 占位符）；CLI 整段失败则跳过
    if not cli_err:
        more, _ = _list_ios_apps_cli(serial, app_type="Any")
        if more:
            return more

    goios = _list_ios_apps_goios(serial)
    if goios:
        return goios

    if inproc is not None and not inproc and not cli_err:
        return []  # 通道正常，设备上确实没有 User App

    detail = cli_err or "进程内 InstallationProxy 与 go-ios 均未拿到应用列表"
    raise AuthoringError(f"无法列举 iOS 应用：{detail}")


#: 中文/非包名词条匹配不到时，最多探测多少个可启动应用的显示名
DEFAULT_MAX_LABEL_PROBES = 12
#: 拉 APK 解析显示名的体积上限，避免为了一个名字下载几百兆
MAX_PULL_APK_BYTES = 80 * 1024 * 1024

_LABEL_CACHE: dict[tuple[str, str], str] = {}
_DISK_CACHE_LOADED = False
_DISK_CACHE: dict[str, str] = {}


def _adb_text(args: list[str], serial: str) -> str:
    """跑一条 adb 子命令，取不到就返回空串（调用方按需回退）。"""
    from ..mobile.adb import run_adb

    try:
        return run_adb(args, serial=serial, timeout=30)
    except (RuntimeError, OSError):
        return ""


def _max_label_probes() -> int:
    raw = (os.environ.get("AUTOPILOT_AUTHORING_LABEL_PROBES") or "").strip()
    try:
        return max(0, min(int(raw), 40))
    except ValueError:
        return DEFAULT_MAX_LABEL_PROBES


def _label_disk_cache_path() -> Path | None:
    """Android 显示名磁盘缓存路径；``0/off/false`` 关闭。"""
    raw = (os.environ.get("AUTOPILOT_AUTHORING_LABEL_CACHE") or "").strip()
    if raw.lower() in ("0", "off", "false", "no"):
        return None
    if raw:
        return Path(raw)
    return Path.home() / ".autopilot" / "android_app_labels.json"


def clear_label_cache() -> None:
    """测试/排障：清空内存与已加载的磁盘缓存视图。"""
    global _DISK_CACHE_LOADED, _DISK_CACHE
    _LABEL_CACHE.clear()
    _DISK_CACHE = {}
    _DISK_CACHE_LOADED = False


def _ensure_disk_cache_loaded() -> None:
    global _DISK_CACHE_LOADED, _DISK_CACHE
    if _DISK_CACHE_LOADED:
        return
    _DISK_CACHE_LOADED = True
    path = _label_disk_cache_path()
    if path is None or not path.is_file():
        _DISK_CACHE = {}
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        _DISK_CACHE = {}
        return
    if not isinstance(raw, dict):
        _DISK_CACHE = {}
        return
    out: dict[str, str] = {}
    for key, value in raw.items():
        k = str(key or "").strip()
        if not k:
            continue
        if isinstance(value, dict):
            label = str(value.get("label") or "").strip()
        else:
            label = str(value or "").strip()
        out[k] = label
    _DISK_CACHE = out


def _disk_cache_key(serial: str, pkg: str) -> str:
    return f"{serial}|{pkg}"


def _read_disk_label(serial: str, pkg: str) -> str | None:
    """命中返回标签（可为空串）；未命中返回 None。"""
    path = _label_disk_cache_path()
    if path is None:
        return None
    _ensure_disk_cache_loaded()
    key = _disk_cache_key(serial, pkg)
    if key not in _DISK_CACHE:
        return None
    return _DISK_CACHE[key]


def _write_disk_label(serial: str, pkg: str, label: str) -> None:
    path = _label_disk_cache_path()
    if path is None:
        return
    _ensure_disk_cache_loaded()
    key = _disk_cache_key(serial, pkg)
    _DISK_CACHE[key] = label
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: {"label": v} for k, v in sorted(_DISK_CACHE.items())}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return

def android_launchable_packages(udid: str = "") -> list[str]:
    """带启动入口的应用包名（桌面可见的那些），保持设备返回顺序。"""
    text = _adb_text(
        [
            "shell", "cmd", "package", "query-activities", "--brief",
            "-a", "android.intent.action.MAIN",
            "-c", "android.intent.category.LAUNCHER",
        ],
        (udid or "").strip(),
    )
    out: list[str] = []
    for line in text.splitlines():
        item = line.strip()
        if "/" not in item or " " in item:
            continue
        pkg = item.split("/", 1)[0].strip()
        if pkg and pkg not in out:
            out.append(pkg)
    return out


def android_launch_activity(package_name: str, udid: str = "") -> str:
    """应用的启动 Activity；取不到返回空串（mobile_app_start 可留空由 Appium 决定）。"""
    pkg = (package_name or "").strip()
    if not pkg:
        return ""
    text = _adb_text(
        ["shell", "cmd", "package", "resolve-activity", "--brief", pkg],
        (udid or "").strip(),
    )
    for line in text.splitlines():
        item = line.strip()
        if item.startswith(f"{pkg}/"):
            return item.split("/", 1)[1].strip()
    return ""


def android_app_label(package_name: str, udid: str = "") -> str:
    """Android 显示名：内存缓存 → 磁盘缓存 → dumpsys → 拉 APK。

    Android 没有稳定的「按当前语言读桌面名」命令；dumpsys 只覆盖部分字段，
    中文场景常需 APK 解析。代价高，故双级缓存并限制探测个数与 APK 体积。
    """
    pkg = (package_name or "").strip()
    serial = (udid or "").strip()
    if not pkg:
        return ""
    cached = _LABEL_CACHE.get((serial, pkg))
    if cached is not None:
        return cached
    disk = _read_disk_label(serial, pkg)
    if disk is not None:
        _LABEL_CACHE[(serial, pkg)] = disk
        return disk
    label = _label_from_dumpsys(pkg, serial) or _label_from_apk(pkg, serial)
    _LABEL_CACHE[(serial, pkg)] = label
    _write_disk_label(serial, pkg, label)
    return label


def _label_from_dumpsys(pkg: str, serial: str) -> str:
    """从 dumpsys package 尽量抠显示名，减少不必要的 APK pull。"""
    text = _adb_text(["shell", "dumpsys", "package", pkg], serial)
    if not text.strip():
        return ""
    patterns = (
        r"nonLocalizedLabel=([^\s}]+)",
        r"applicationLabel=([^\s}]+)",
        r"Application Label:\s*(.+)",
        r"appName=([^\s}]+)",
    )
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if not m:
            continue
        label = (m.group(1) or "").strip().strip('"').strip("'")
        # dumpsys 有时给出 null / 资源 id，不是可读名
        if not label or label.lower() in ("null", "none"):
            continue
        if label.startswith("0x") or label.isdigit():
            continue
        return label
    return ""


def _label_from_apk(pkg: str, serial: str) -> str:
    import tempfile

    apk_path = ""
    for line in _adb_text(["shell", "pm", "path", pkg], serial).splitlines():
        item = line.strip()
        if item.startswith("package:"):
            apk_path = item.split(":", 1)[-1].strip()
            break
    if not apk_path:
        return ""
    size_raw = _adb_text(["shell", "stat", "-c", "%s", apk_path], serial).strip()
    try:
        if int(size_raw) > MAX_PULL_APK_BYTES:
            return ""
    except ValueError:
        pass  # 拿不到体积就赌一把，pull 自身有超时
    with tempfile.TemporaryDirectory(prefix="ap_label_") as tmp:
        local = Path(tmp) / f"{pkg}.apk"
        if not _adb_text(["pull", apk_path, str(local)], serial) and not local.exists():
            return ""
        if not local.exists():
            return ""
        try:
            from ..mobile.apk import parse_apk

            return str(parse_apk(str(local)).app_name or "").strip()
        except (ImportError, OSError, RuntimeError, ValueError):
            return ""


def list_android_installed_packages(udid: str = "") -> list[InstalledApp]:
    """adb pm list packages（第三方优先，失败则全量）。"""
    serial = (udid or "").strip()
    lines: list[str] = []
    for args in (
        ["shell", "pm", "list", "packages", "-3"],
        ["shell", "pm", "list", "packages"],
    ):
        text = _adb_text(args, serial)
        if text.strip():
            lines = text.splitlines()
            break
    out: list[InstalledApp] = []
    for line in lines:
        line = line.strip()
        if not line.startswith("package:"):
            continue
        pkg = line.split(":", 1)[-1].strip()
        if pkg:
            out.append(InstalledApp(package_name=pkg, app_label=pkg, platform="android"))
    return out


def android_settings_component(udid: str = "") -> tuple[str, str]:
    """用 SETTINGS intent 解析真机设置包名/Activity（不启动 UI）。

    适配 MIUI 等改包名 ROM；失败时回落 ``com.android.settings``。
    """
    serial = (udid or "").strip()
    text = _adb_text(
        [
            "shell",
            "cmd",
            "package",
            "resolve-activity",
            "--brief",
            "-a",
            "android.settings.SETTINGS",
        ],
        serial,
    )
    for line in text.splitlines():
        item = line.strip()
        if "/" not in item or item.startswith("No activity"):
            continue
        # 可能带 priority 前缀，取最后 token
        token = item.split()[-1] if " " in item else item
        if "/" not in token:
            continue
        pkg, act = token.split("/", 1)
        pkg, act = pkg.strip(), act.strip()
        if pkg:
            return pkg, act
    return "com.android.settings", ""


def resolve_installed_app(
    platform: str,
    *,
    udid: str = "",
    app_name: str = "",
    package_name: str = "",
) -> InstalledApp:
    """按显式包名或应用名模糊匹配已装应用。"""
    plat = (platform or "").strip().lower()
    explicit = (package_name or "").strip()
    hint = (app_name or "").strip()
    if explicit and ("." in explicit or plat == "android"):
        # 已是包名形态则直接采用（仍可校验安装）
        return InstalledApp(package_name=explicit, app_label=hint or explicit, platform=plat)

    if plat == "ios":
        apps = list_ios_installed_apps(udid)
    elif plat == "android":
        apps = list_android_installed_packages(udid)
    else:
        raise AuthoringError(f"Web 无需解析安装包：{platform!r}")

    if explicit:
        for app in apps:
            if app.package_name == explicit:
                return app
        raise AuthoringError(f"设备未安装包：{explicit}")

    if not hint:
        raise AuthoringError("未提供应用名/包名，无法自动解析")

    # 1) 目录优先（custom > system > popular）：与设备语言无关；第三方仍须已安装
    catalog_hit = _resolve_via_catalog_alias(plat, hint, apps=apps, udid=udid)
    if catalog_hit is not None:
        return catalog_hit

    hit = _best_app_match(apps, hint, platform=plat)
    if hit is None and plat == "android":
        # Android 的 pm list 只有包名，中文应用名必须补显示名再匹配
        apps = _enrich_android_labels(apps, udid=udid, hint=hint)
        hit = _best_app_match(apps, hint, platform=plat)
    if hit is None:
        sample = ", ".join(a.app_label for a in apps[:8])
        raise AuthoringError(
            f"设备上未找到匹配「{hint}」的应用"
            + (f"；示例：{sample}" if sample else "")
        )
    return hit


def _resolve_via_catalog_alias(
    platform: str,
    hint: str,
    *,
    apps: list[InstalledApp],
    udid: str = "",
) -> InstalledApp | None:
    """别名目录命中后：按候选包在设备上校验；仅 system+trusted 可无清单回落。"""
    plat = (platform or "").strip().lower()
    # Android「设置」：厂商可能改包名，intent 比死表更准
    if plat == "android" and is_android_settings_hint(hint):
        pkg, _act = android_settings_component(udid)
        for app in apps:
            if app.package_name == pkg:
                return InstalledApp(
                    package_name=pkg,
                    app_label=app.app_label or hint,
                    platform=plat,
                )
        return InstalledApp(package_name=pkg, app_label=hint or pkg, platform=plat)

    entry = alias_entry(plat, hint)
    if entry is None:
        return None
    for pkg in entry.packages:
        for app in apps:
            if app.package_name == pkg:
                return InstalledApp(
                    package_name=pkg,
                    app_label=app.app_label or hint,
                    platform=plat,
                )
    # 仅稳定、平台自带的系统 Bundle 可在安装列表缺失时回落。
    # Android ROM 差异大的应用和所有第三方应用都必须以设备清单为准。
    if entry.kind == "system" and entry.trusted_fallback and entry.packages:
        pkg = entry.packages[0]
        return InstalledApp(package_name=pkg, app_label=hint or pkg, platform=plat)
    return None


def _android_label_probe_order(
    apps: list[InstalledApp],
    *,
    udid: str,
    hint: str,
) -> list[str]:
    """探测顺序：目录候选包 → LAUNCHER 可启动 → 已装列表。

    Midscene/activity-finder 同类实践：先打高概率包，避免盲目扫前 N 个桌面图标。
    """
    preferred: list[str] = []
    entry = alias_entry("android", hint)
    if entry is not None:
        preferred.extend(entry.packages)
    launchable = android_launchable_packages(udid)
    fallback = [a.package_name for a in apps]
    order: list[str] = []
    seen: set[str] = set()
    for pkg in list(preferred) + list(launchable) + fallback:
        name = (pkg or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        order.append(name)
    return order


def _enrich_android_labels(
    apps: list[InstalledApp],
    *,
    udid: str,
    hint: str,
) -> list[InstalledApp]:
    """给桌面可见的应用补显示名；探测个数有上限，避免逐个拉 APK。"""
    budget = _max_label_probes()
    if budget <= 0:
        return apps
    known = {a.package_name for a in apps}
    order = _android_label_probe_order(apps, udid=udid, hint=hint)
    labels: dict[str, str] = {}
    for pkg in order[:budget]:
        label = android_app_label(pkg, udid)
        if not label:
            continue
        labels[pkg] = label
        if _best_app_match([InstalledApp(pkg, label, "android")], hint, platform="android") is not None:
            break  # 命中即停，别为剩下的应用继续拉包
    if not labels:
        return apps
    out = [
        InstalledApp(
            package_name=a.package_name,
            app_label=labels.get(a.package_name, a.app_label),
            platform=a.platform,
        )
        for a in apps
    ]
    out.extend(
        InstalledApp(package_name=pkg, app_label=label, platform="android")
        for pkg, label in labels.items()
        if pkg not in known
    )
    return out


def _best_app_match(
    apps: list[InstalledApp],
    hint: str,
    *,
    platform: str = "",
) -> InstalledApp | None:
    keys = expand_hint_keys(platform or (apps[0].platform if apps else ""), hint)
    if not keys:
        return None
    scored: list[tuple[int, InstalledApp]] = []
    for app in apps:
        label = re.sub(r"[\s_\-]+", "", (app.app_label or "").lower())
        pkg = (app.package_name or "").lower()
        score = 0
        for key in keys:
            if not key:
                continue
            if label == key or pkg == key:
                score = max(score, 100)
            elif key in label or key in pkg:
                score = max(score, 80)
            elif label and (label in key):
                score = max(score, 60)
            elif any(part and part in pkg for part in key.split(".") if len(part) >= 3):
                score = max(score, 40)
        if score:
            scored.append((score, app))
    if not scored:
        return None
    scored.sort(key=lambda x: (-x[0], len(x[1].package_name)))
    return scored[0][1]
