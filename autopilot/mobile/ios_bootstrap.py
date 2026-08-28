"""iOS 真机工具链编排（Windows 无 Mac 运行期）。

组合三件套把 iOS 真机准备到「Appium 可直连」状态：
  1) go-ios 启动用户态 RSD 隧道（iOS 17+，免管理员）+ 挂载 DeveloperDiskImage + runwda；
  2) pymobiledevice3 把设备上 WDA 的端口转发到本机；
  3) 产出 Appium xcuitest 的 caps（仅 webDriverAgentUrl，勿 usePreinstalledWDA），交由会话直连已就绪的 WDA。

资源用内置 resources/re_go_ios（go-ios 二进制 / devimages / wintun）。
命令构造（*_cmd）为纯函数、离线可测；真正的子进程启动为 best-effort 薄封装，需真机环境。
"""

from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional, Collection

from ..runtime.subproc import popen as popen_hidden, run as run_hidden
from ._paths import REPO_ROOT as _REPO_ROOT
from .ios_ports import DEFAULT_MJPEG_PORT, DEFAULT_TUNNEL_INFO_PORT, DEFAULT_WDA_PORT
_IOS_RES = _REPO_ROOT / "resources" / "re_go_ios"
DEVIMAGE_DIR = _IOS_RES / "devimages"

# go-ios 用户态隧道 agent 环境（免管理员，来自社区实践）
AGENT_ENV = {"ENABLE_GO_IOS_AGENT": "user"}


def _os_subdir() -> str:
    # 透传宿主系统名（小写），不臆测回退到 win——未知系统就用其真实名去找对应目录
    return {"Windows": "win", "Darwin": "mac", "Linux": "linux"}.get(
        platform.system(), platform.system().lower())


def resolve_go_ios() -> Optional[Path]:
    """定位内置 go-ios 二进制（resources/re_go_ios/executable/<os>/ios[.exe]）。"""
    exe = "ios.exe" if platform.system() == "Windows" else "ios"
    candidate = _IOS_RES / "executable" / _os_subdir() / exe
    if candidate.exists():
        return candidate
    # 回退：在 executable 下递归找
    base = _IOS_RES / "executable"
    if base.exists():
        for c in base.rglob(exe):
            if c.is_file():
                return c
    return None


def available() -> bool:
    return resolve_go_ios() is not None


# ---- 纯函数：命令构造（便于离线测试与审阅）----
def tunnel_cmd(info_port: int = DEFAULT_TUNNEL_INFO_PORT) -> list[str]:
    # --userspace 是 Windows 免管理员用户态隧道的关键开关；runwda 连的就是这个 agent
    return [str(resolve_go_ios()), "tunnel", "start", "--userspace",
            "--tunnel-info-port", str(info_port)]


def tunnel_ls_cmd(info_port: int = DEFAULT_TUNNEL_INFO_PORT) -> list[str]:
    """查询隧道状态（用于轮询就绪，查 pinned info-port 避免另起 agent）。"""
    return [str(resolve_go_ios()), "tunnel", "ls", "--tunnel-info-port", str(info_port)]


def image_cmd(basedir: Optional[str] = None) -> list[str]:
    return [str(resolve_go_ios()), "image", "auto", f"--basedir={basedir or DEVIMAGE_DIR}"]


def image_mount_cmd(restore_dir: str | Path, udid: str = "") -> list[str]:
    """显式挂载个性化 DDI 的 Restore 目录（绕过 go-ios 硬编码的旧 ddi-15F31d）。"""
    cmd = [str(resolve_go_ios()), "image", "mount", "--path", str(restore_dir)]
    if udid:
        cmd += ["--udid", udid]
    return cmd


def _plist_int(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip().lower()
    if not s:
        return None
    # noinspection PyBroadException
    try:
        return int(s, 16) if s.startswith("0x") else int(s)
    except Exception:
        return None


def list_local_ddi_restore_dirs(basedir: Optional[Path] = None) -> list[Path]:
    """枚举 devimages 下所有含 Restore/BuildManifest.plist 的 DDI。"""
    root = Path(basedir or DEVIMAGE_DIR)
    out: list[Path] = []
    seen: set[str] = set()
    if not root.is_dir():
        return out
    for manifest in sorted(root.rglob("BuildManifest.plist")):
        restore = manifest.parent
        if restore.name != "Restore":
            continue
        key = str(restore.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(restore)
    # 新镜像名靠前作同优先级时的 tie-break
    def _rank(p: Path) -> tuple[int, str]:
        name = p.parent.name.lower()
        if name == "ddi-17e5179g":
            return 0, name
        if name == "ddi-15f31d":
            return 1, name
        return 2, name

    out.sort(key=_rank)
    return out


def ddi_identity_matches(restore_dir: Path, chip_id: int, board_id: int) -> bool:
    """BuildManifest 是否含与本机 ApChipID / ApBoardID 一致的 BuildIdentity。"""
    manifest = Path(restore_dir) / "BuildManifest.plist"
    if not manifest.is_file():
        return False
    # noinspection PyBroadException
    try:
        import plistlib
        data = plistlib.loads(manifest.read_bytes())
    except Exception:
        return False
    for bi in data.get("BuildIdentities", []):
        info = bi.get("Info", {})
        chip = _plist_int(bi.get("ApChipID") or info.get("ApChipID"))
        board = _plist_int(bi.get("ApBoardID") or info.get("ApBoardID"))
        if chip == chip_id and board == board_id:
            return True
    return False


def query_personalization_ids(udid: str) -> tuple[int, int] | None:
    """读设备个性化标识（ChipID / BoardId），供挑选 DDI。"""
    # noinspection PyBroadException
    try:
        r = run_hidden(
            [sys.executable, "-m", "pymobiledevice3", "mounter",
             "query-personalization-identifiers", "--udid", udid],
            capture_output=True, timeout=45)
    except Exception:
        return None
    text = (r.stdout or b"").decode("utf-8", "replace").strip()
    if not text:
        return None
    # noinspection PyBroadException
    try:
        data = json.loads(text)
    except Exception:
        return None
    chip = _plist_int(data.get("ChipID"))
    board = _plist_int(data.get("BoardId"))
    if chip is None or board is None:
        return None
    return chip, board


def ddi_restore_dirs_for_device(udid: str, basedir: Optional[Path] = None) -> list[Path]:
    """按本机芯片身份匹配 DDI；匹配项在前，其余本地镜像作兜底。

    go-ios ``image auto`` 在部分版本仍硬编码 ``ddi-15F31d``，对新机（如 ApChipId
    0x8140）会 findIdentity 失败；须用 BuildManifest 含该身份的个性化 DDI。
    """
    all_dirs = list_local_ddi_restore_dirs(basedir)
    if not all_dirs:
        return []
    ids = query_personalization_ids(udid)
    if ids is None:
        return all_dirs
    chip_id, board_id = ids
    matched = [p for p in all_dirs if ddi_identity_matches(p, chip_id, board_id)]
    rest = [p for p in all_dirs if p not in matched]
    return matched + rest


def preferred_ddi_restore_dirs(basedir: Optional[Path] = None) -> list[Path]:
    """兼容旧名：无 udid 时按本地目录枚举顺序（新 DDI 名优先）。"""
    return list_local_ddi_restore_dirs(basedir)


def runwda_cmd(bundle_id: str, test_runner_bundle_id: str = "",
               xctest_config: str = "WebDriverAgentRunner.xctest", udid: str = "",
               env: Optional[dict] = None) -> list[str]:
    # 与 go-ios 实证用法对齐：=-形参 + 经 --env 传 USE_PORT 等给 WDA 测试运行器
    cmd = [str(resolve_go_ios())]
    if udid:
        cmd += ["--udid", udid]
    cmd += ["runwda",
            f"--bundleid={bundle_id}",
            f"--testrunnerbundleid={test_runner_bundle_id or bundle_id}",
            f"--xctestconfig={xctest_config}"]
    for k, v in (env or {}).items():
        cmd.append(f"--env={k}={v}")
    return cmd


def is_wda_bundle(bundle_id: str) -> bool:
    """是否为 WDA 测试运行器 bundle id：含 'webdriveragentrunner' 且以 '.xctrunner' 结尾。
    既命中常规 `...test.xctrunner`，也命中设备上常见的双后缀 `...xctrunner.xctrunner`。"""
    low = (bundle_id or "").lower()
    return "webdriveragentrunner" in low and low.endswith(".xctrunner")


def parse_wda_bundles(text: str) -> list[str]:
    """从 `ios apps --list` 文本里挑出 WDA bundle id（go-ios 兜底路径用，纯函数可测）。"""
    out: list[str] = []
    for line in (text or "").splitlines():
        for tok in line.replace(",", " ").split():
            if is_wda_bundle(tok) and tok not in out:
                out.append(tok)
                break
    return out


def wda_bundles_from_pmd3_json(stdout: str) -> list[str]:
    """从 pymobiledevice3 `apps list` 的 JSON 里挑 WDA bundle id（**只取顶层 key**，
    避免把 Entitlements 里的 team 前缀串误当包名）。纯函数、可测。"""
    # noinspection PyBroadException
    try:
        data = json.loads(stdout)
    except Exception:
        return []
    keys = data.keys() if isinstance(data, dict) else []
    return [k for k in keys if is_wda_bundle(k)]


@lru_cache(maxsize=1)
def pmd3_forward_device_flag(python_exe: str = "") -> str:
    """``usbmux forward`` 选设备的参数名：新版 pymobiledevice3 用 ``--serial``。

    4.x 起 ``--udid`` 被移除，误传会直接 exit 2 —— 表现是「转发没起来 / WDA
    /status 未就绪」，很难定位。这里读 ``-h`` 现场确认，取不到时按新版兜底。
    """
    py = python_exe or sys.executable
    # noinspection PyBroadException
    try:
        # 禁止 text=True：Windows GBK 控制台下非法字节会在 _readerthread 崩掉
        env = {**os.environ, "NO_COLOR": "1", "FORCE_COLOR": "0", "PYTHONIOENCODING": "utf-8"}
        r = run_hidden(
            [py, "-m", "pymobiledevice3", "usbmux", "forward", "-h"],
            capture_output=True,
            timeout=30,
            env=env,
        )
    except Exception:
        return "--serial"
    text = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")
    if "--serial" in text:
        return "--serial"
    if "--udid" in text:
        return "--udid"
    return "--serial"


def pmd3_forward_cmd(local_port: int = DEFAULT_WDA_PORT,
                     device_port: int = DEFAULT_WDA_PORT,
                     udid: str = "", python_exe: str = "") -> list[str]:
    """``python -m pymobiledevice3 usbmux forward`` 命令（含正确的设备选择参数）。"""
    cmd = [python_exe or sys.executable, "-m", "pymobiledevice3", "usbmux",
           "forward", str(local_port), str(device_port)]
    if udid:
        cmd += [pmd3_forward_device_flag(python_exe), udid]
    return cmd


def forward_cmd(local_port: int = DEFAULT_WDA_PORT, device_port: int = DEFAULT_WDA_PORT,
                udid: str = "") -> list[str]:
    """pymobiledevice3 usbmux 端口转发命令（裸命令形式，文档/排障用）。"""
    cmd = ["pymobiledevice3", "usbmux", "forward", str(local_port), str(device_port)]
    if udid:
        cmd += [pmd3_forward_device_flag(), udid]
    return cmd


def goios_forward_cmd(local_port: int = DEFAULT_WDA_PORT, device_port: int = DEFAULT_WDA_PORT,
                      udid: str = "") -> list[str]:
    """go-ios 自带端口转发命令（少一个依赖，作为 pymobiledevice3 的替代）。"""
    cmd = [str(resolve_go_ios()), "forward", str(local_port), str(device_port)]
    if udid:
        cmd += ["--udid", udid]
    return cmd


def install_app(ipa_path: str, udid: str = "",
                log: Optional[Callable[[str], None]] = None, timeout: int = 300) -> str:
    """go-ios 安装 .ipa（供 _ios_install_app 回退路径调用）。"""
    _log = log or (lambda _m: None)
    exe = resolve_go_ios()
    if exe is None:
        raise RuntimeError("未找到 go-ios 二进制（resources/re_go_ios），无法安装 iOS 应用")
    from .ipa import parse_ipa, ipa_precheck
    info = parse_ipa(ipa_path)              # 文件不存在/非法在此抛 PackageError
    problems = ipa_precheck(info, udid)
    if problems:
        raise RuntimeError("IPA 预检未通过：\n- " + "\n- ".join(problems))
    _log(f"预检通过：{info.bundle_id} v{info.version_name}（最低 iOS {info.minimum_os or '—'}）")
    cmd = [str(exe), "install", f"--path={ipa_path}"]
    if udid:
        cmd.append(f"--udid={udid}")
    _log(f"go-ios 安装中：{os.path.basename(ipa_path)} …")
    r = run_hidden(cmd, capture_output=True, timeout=timeout,
                   env={**os.environ, **AGENT_ENV})
    out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace").strip()
    if r.returncode != 0:
        raise RuntimeError(f"go-ios 安装失败（exit {r.returncode}）：{out[-400:]}")
    return out


def uninstall_cmd(bundle_id: str, udid: str = "") -> list[str]:
    """go-ios 卸载应用命令（纯函数，便于离线测试）。"""
    cmd = [str(resolve_go_ios()), "uninstall", bundle_id]
    if udid:
        cmd.append(f"--udid={udid}")
    return cmd


def uninstall_app(bundle_id: str, udid: str = "",
                  log: Optional[Callable[[str], None]] = None, timeout: int = 120) -> str:
    """go-ios 卸载应用（供 _ios_uninstall_app 回退路径调用）。"""
    _log = log or (lambda _m: None)
    if not bundle_id:
        raise RuntimeError("iOS 卸载失败：bundle id 不能为空")
    exe = resolve_go_ios()
    if exe is None:
        raise RuntimeError("未找到 go-ios 二进制（resources/re_go_ios），无法卸载 iOS 应用")
    cmd = uninstall_cmd(bundle_id, udid)
    _log(f"go-ios 卸载中：{bundle_id} …")
    r = run_hidden(cmd, capture_output=True, timeout=timeout,
                   env={**os.environ, **AGENT_ENV})
    out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace").strip()
    if r.returncode != 0:
        raise RuntimeError(f"go-ios 卸载失败（exit {r.returncode}）：{out[-400:]}")
    _log("卸载完成")
    return out


def build_ios_caps(udid: str, wda_local_port: int = DEFAULT_WDA_PORT,
                   extra: Optional[dict] = None) -> dict:
    """构造 Appium xcuitest caps：直连已由 go-ios 拉起、并经转发到本机的 WDA。

    注意：iOS 17+ 经 go-ios 用户态隧道 + usbmux 转发的 WDA，Appium 建 session 会 ECONNRESET
    （Appium 内部 pymobiledevice3 无法路由 go-ios 的进程内隧道）。iOS 17+ 请改用
    build_ios_caps_managed() + pymobiledevice3 remote tunneld（见下）。
    """
    # 纯外部直连已由 go-ios 拉起的 WDA：只给 webDriverAgentUrl，Appium 只当 HTTP 代理，
    # 不 build/install/launch，也不碰设备上的 WDA。
    # 切勿再设 usePreinstalledWDA —— 它会触发 xcuitest 驱动的 preparePreinstalled→cleanupApps，
    # 把 CFBundleName=WebDriverAgentRunner-Runner 且 bundleId!=保留id 的 WDA 直接卸载
    # （保留id 默认 com.facebook.WebDriverAgentRunner.xctrunner，与自定义签名的 WDA 不匹配 → 误删）。
    caps = {
        "platformName": "iOS",
        "appium:automationName": "XCUITest",
        "appium:udid": udid,
        "appium:webDriverAgentUrl": f"http://127.0.0.1:{wda_local_port}",
    }
    if extra:
        caps.update(extra)
    return caps


def build_ios_caps_managed(udid: str, wda_bundle_id: str,
                           extra: Optional[dict] = None) -> dict:
    """iOS 17+ 推荐 caps：配合 pymobiledevice3 remote tunneld（管理员），

    让 Appium xcuitest 自己发现隧道、挂镜像、用预装 WDA 拉起并连接——不手动 runwda/forward。
    """
    # Appium 会在 updatedWDABundleId 后自动补 .xctrunner 派生测试运行器 id；
    # 故这里传基名（去掉已有的 .xctrunner 后缀），避免变成 ...xctrunner.xctrunner
    base = wda_bundle_id[:-len(".xctrunner")] if wda_bundle_id.endswith(".xctrunner") else wda_bundle_id
    caps = {
        "platformName": "iOS",
        "appium:automationName": "XCUITest",
        "appium:udid": udid,
        "appium:usePreinstalledWDA": True,
        "appium:updatedWDABundleId": base,
    }
    if extra:
        caps.update(extra)
    return caps


def tunneld_cmd(python_exe: str = "") -> list[str]:
    """pymobiledevice3 remote tunneld 命令（Appium 可自动发现的隧道守护进程）。

    Windows 需管理员 shell 运行。python_exe 缺省用当前解释器。
    """
    return [python_exe or sys.executable, "-m", "pymobiledevice3", "remote", "tunneld"]


def start_tunneld(python_exe: str = ""):
    """启动 pymobiledevice3 remote tunneld（常驻；Windows 需管理员）。返回 Popen 或 None。"""
    # noinspection PyBroadException
    try:
        return popen_hidden(tunneld_cmd(python_exe),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return None


def tunneld_running() -> bool:
    """本机是否已有 pymobiledevice3 remote tunneld 进程（Appium iOS 17+ 必需）。"""
    # noinspection PyBroadException
    try:
        r = run_hidden(
            ["pgrep", "-f", "pymobiledevice3 remote tunneld"],
            capture_output=True, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def device_ios_version(udid: str) -> str:
    """从 usbmux 读取设备 iOS 版本字符串（如 26.5）。"""
    # noinspection PyBroadException
    try:
        r = run_hidden(
            [sys.executable, "-m", "pymobiledevice3", "usbmux", "list"],
            capture_output=True, timeout=30,
        )
        from .ios_devices import _decode, parse_usbmux_list

        for item in parse_usbmux_list(_decode(r.stdout)):
            if item.udid == udid:
                return item.ios_version
    except Exception:
        pass
    return ""


def device_ios_major(udid: str) -> int:
    ver = device_ios_version(udid)
    # noinspection PyBroadException
    try:
        return int(ver.split(".", 1)[0])
    except Exception:
        return 0


def prefer_appium_managed(udid: str) -> bool:
    """是否用 managed caps（usePreinstalledWDA + tunneld/RemoteXPC）。

    Mac 真机验证（iOS 26）：managed/xcodebuild 不可用；默认 go-ios runwda + webDriverAgentUrl。
    仅当显式 IOS_APPIUM_MANAGED=1 时在 Mac 上启用 managed。
    """
    env = os.getenv("IOS_APPIUM_MANAGED", "").strip().lower()
    if env in ("0", "false", "no"):
        return False
    if env in ("1", "true", "yes"):
        return True
    if platform.system() == "Darwin":
        return False
    return device_ios_major(udid) >= 17


def merge_appium_ios_caps(base_vars: dict, udid: str, wda_bundle: str = "",
                          backend_mode: str = "appium",
                          extra: Optional[dict] = None) -> None:
    """按宿主/iOS 版本为 Appium 路径合入 __appium_caps__（就地修改 base_vars）。"""
    mode = (backend_mode or "").strip().lower()
    if mode not in ("appium", "auto"):
        return
    if mode == "auto" and platform.system() != "Darwin":
        return
    defaults = {
        "appium:noReset": True,
        "appium:wdaLaunchTimeout": 180000,
        "appium:wdaConnectionTimeout": 180000,
    }
    merged_extra = {**defaults, **(extra or {})}
    if prefer_appium_managed(udid):
        caps = build_ios_caps_managed(udid, wda_bundle, extra=merged_extra)
    else:
        port = int(os.getenv("IOS_WDA_LOCAL_PORT", str(DEFAULT_WDA_PORT)))
        caps = build_ios_caps(udid, port, extra=merged_extra)
    existing = base_vars.get("__appium_caps__")
    if isinstance(existing, dict):
        caps = {**caps, **existing}
    base_vars["__appium_caps__"] = caps


# ---- best-effort 运行封装（需真机；返回 Popen 或 None）----
def _spawn(cmd: list[str], use_agent: bool = False):
    # 长驻进程(隧道/runwda)输出量大；用 DEVNULL 而非 PIPE，否则管道缓冲填满会让进程卡死/退出
    env = os.environ.copy()
    if use_agent:
        env.update(AGENT_ENV)
    # noinspection PyBroadException
    try:
        return popen_hidden(cmd, env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    except Exception:
        return None


def start_tunnel(info_port: int = DEFAULT_TUNNEL_INFO_PORT):
    """启动用户态隧道（常驻进程）。返回 Popen 或 None。"""
    if not available():
        return None
    return _spawn(tunnel_cmd(info_port), use_agent=True)


def mount_developer_image(basedir: Optional[str] = None) -> bool:
    if not available():
        return False
    proc = _spawn(image_cmd(basedir), use_agent=True)
    if proc is None:
        return False
    proc.wait(timeout=120)
    return proc.returncode == 0


def run_wda(bundle_id: str, **kwargs):
    """在设备上拉起 WDA（常驻进程）。返回 Popen 或 None。"""
    if not available():
        return None
    return _spawn(runwda_cmd(bundle_id, **kwargs), use_agent=True)


def forward_wda(local_port: int = DEFAULT_WDA_PORT, device_port: int = DEFAULT_WDA_PORT,
                udid: str = ""):
    """pymobiledevice3 端口转发（常驻进程）。返回 Popen 或 None。"""
    return _spawn(forward_cmd(local_port, device_port, udid))


# ---- 端口工具 + 健壮编排（端口回收 + 隧道复用 + 每步就绪门控）----
_GOIOS_DEFAULT_AGENT_PORT = 60105   # ENABLE_GO_IOS_AGENT=user 还会起这个默认 agent

# 仅杀疑似本工具链的监听进程，避免误伤无关服务 / 其它 Runner
_IOS_TOOL_MARKERS = (
    "go-ios",
    "ios.exe",
    "pymobiledevice3",
    "runwda",
    "webdriveragent",
    "tunnel",
    "usbmux",
)


class PrepCancelled(RuntimeError):
    """用户取消检视/镜像准备（协作式中断）。"""


def is_port_listening(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def wda_alive(port: int = DEFAULT_WDA_PORT, timeout: float = 3.0) -> bool:
    """端口背后是否有「真正存活」的 WDA（/status 返回 200）。

    比 is_port_listening 可靠：换机/WDA 退出后，陈旧的 pmd3 转发仍会占着端口处于
    LISTENING，但连上去立刻被中止（WinError 10053 / Server disconnected）。只有
    /status 能 200 才算真可达。"""
    if not is_port_listening(port, timeout=0.5):
        return False
    import urllib.request
    # noinspection PyBroadException
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/status", timeout=timeout) as r:
            return getattr(r, "status", r.getcode()) == 200
    except Exception:
        return False


def mjpeg_alive(port: int = DEFAULT_MJPEG_PORT, timeout: float = 3.0) -> bool:
    """本机 MJPEG 端口是否真有屏幕流（非仅端口占用）。"""
    if not is_port_listening(port, timeout=0.5):
        return False
    import urllib.request
    # noinspection PyBroadException
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ct = (r.headers.get("Content-Type") or "").lower()
            if "multipart" in ct or "jpeg" in ct:
                return True
            return b"\xff\xd8" in r.read(512)
    except Exception:
        return False


def ensure_mjpeg_ready(
    udid: str,
    mjpeg_port: int = DEFAULT_MJPEG_PORT,
    *,
    prep: "IosDevicePrep | None" = None,
    timeout: float = 10.0,
) -> bool:
    """Best-effort：转发并探活 MJPEG（不重启 WDA）。WDA 须由 runwda 带 MJPEG_SERVER_PORT 启动。"""
    if mjpeg_alive(mjpeg_port):
        return True
    if prep is not None:
        prep.ensure_forward_port(mjpeg_port, timeout=timeout)
    elif udid and not is_port_listening(mjpeg_port):
        cmd = pmd3_forward_cmd(mjpeg_port, mjpeg_port, udid=udid)
        popen_hidden(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if mjpeg_alive(mjpeg_port, timeout=1.0):
                return True
            time.sleep(0.5)
    return mjpeg_alive(mjpeg_port, timeout=min(3.0, timeout))


def cmdline_matches_tunnel(joined_lower: str, info_port: int | None) -> bool:
    """判断 cmdline 是否为本机 go-ios tunnel（可限定 tunnel-info-port）。"""
    if "tunnel" not in joined_lower:
        return False
    if info_port is None:
        return True
    if "tunnel-info-port" not in joined_lower:
        return False
    return str(int(info_port)) in joined_lower


def pid_looks_like_ios_tool(pid: int) -> bool:
    """进程命令行是否像 go-ios / pymobiledevice3 等本工具链。"""
    # noinspection PyBroadException
    try:
        import psutil

        cmdline = psutil.Process(pid).cmdline() or []
        joined = " ".join(str(x) for x in cmdline).lower()
        return any(m in joined for m in _IOS_TOOL_MARKERS)
    except Exception:
        return False


def kill_goios_tunnel_agents(
    *,
    info_port: int | None = None,
    owned_pids: Collection[int] | None = None,
) -> list[int]:
    """Best-effort：终止 go-ios tunnel/agent。

    - ``info_port``：只杀命令行含该 ``--tunnel-info-port`` 的进程（避免误伤其它会话）。
    - ``owned_pids``：若给出，只杀其中的 pid（会话级登记）。
    """
    killed: list[int] = []
    exe = resolve_go_ios()
    if exe is None:
        return killed
    exe_base = exe.name.lower()
    owned = set(int(p) for p in owned_pids) if owned_pids is not None else None
    # noinspection PyBroadException
    try:
        import psutil
        for proc in psutil.process_iter(["pid", "cmdline"]):
            cmdline = proc.info.get("cmdline") or []
            if not cmdline:
                continue
            joined = " ".join(str(x) for x in cmdline).lower()
            if exe_base not in joined:
                continue
            if not cmdline_matches_tunnel(joined, info_port):
                continue
            pid = proc.info.get("pid")
            if not pid:
                continue
            if owned is not None and int(pid) not in owned:
                continue
            # noinspection PyBroadException
            try:
                psutil.Process(pid).kill()
                killed.append(int(pid))
            except Exception:
                pass
    except Exception:
        pass
    return killed


def reclaim_stale_local_ios_prep(
    *,
    info_port: int = DEFAULT_TUNNEL_INFO_PORT,
    wda_port: int = DEFAULT_WDA_PORT,
    mjpeg_port: int = DEFAULT_MJPEG_PORT,
    log: Optional[Callable[[str], None]] = None,
) -> tuple[list[int], list[int]]:
    """启动或新会话前回收异常退出残留的隧道/端口。

    仅针对指定 info/wda/mjpeg 端口与匹配该 info_port 的 go-ios tunnel；
    端口监听只杀本工具链进程，降低对并行 Runner 的误伤。
    """
    _log = log or (lambda _m: None)
    tunnel_pids = kill_goios_tunnel_agents(info_port=info_port)
    port_pids: list[int] = []
    for p in (info_port, wda_port, mjpeg_port, _GOIOS_DEFAULT_AGENT_PORT):
        port_pids.extend(kill_listeners(p, tool_only=True))
    if tunnel_pids or port_pids:
        _log(
            f"已回收残留 iOS 本地资源：tunnel pid={tunnel_pids or '—'} "
            f"port listener pid={port_pids or '—'}")
    return tunnel_pids, port_pids


def kill_listeners(
    port: int,
    *,
    owned_pids: Collection[int] | None = None,
    tool_only: bool = True,
) -> list:
    """杀掉监听该端口的进程（回收残留 go-ios / pmd3 forward）。best-effort。

    ``tool_only=True``（默认）：仅杀命令行像本工具链的进程。
    ``owned_pids``：若给出，只杀登记过的 pid（可与 tool_only 组合）。
    """
    killed = []
    owned = set(int(p) for p in owned_pids) if owned_pids is not None else None
    # noinspection PyBroadException
    try:
        import psutil  # 随 pymobiledevice3 传递依赖可用
        for c in psutil.net_connections(kind="inet"):
            if not (c.laddr and c.laddr.port == port
                    and c.status == psutil.CONN_LISTEN and c.pid):
                continue
            pid = int(c.pid)
            if owned is not None and pid not in owned:
                continue
            if tool_only and not pid_looks_like_ios_tool(pid):
                continue
            # noinspection PyBroadException
            try:
                psutil.Process(pid).kill()
                killed.append(pid)
            except Exception:
                pass
    except Exception:
        pass
    return killed


class IosDevicePrep:
    """把 iOS 真机准备到「WDA /status 可达」的健壮编排器。

    用法：
        prep = IosDevicePrep(udid, wda_bundle, log=print)
        url = prep.prepare()      # 成功返回 http://127.0.0.1:8100，失败抛 RuntimeError
        ...                       # 用 url 配 Appium caps 直连
        prep.stop()               # 结束时清理隧道/runwda/forward 进程
    """

    def __init__(
        self,
        udid: str,
        wda_bundle: str,
        info_port: int = DEFAULT_TUNNEL_INFO_PORT,
        wda_port: int = DEFAULT_WDA_PORT,
        log: Optional[Callable[[str], None]] = None,
        cancel_event=None,
        mjpeg_port: int = DEFAULT_MJPEG_PORT,
    ) -> None:
        self.udid = udid
        self.wda_bundle = wda_bundle
        self.info_port = info_port
        self.wda_port = wda_port
        self.mjpeg_port = mjpeg_port
        self.log = log or (lambda _m: None)
        self.cancel_event = cancel_event
        self._procs: list = []
        self._wda_log: Optional[str] = None    # runwda 输出日志临时文件路径（ensure_wda 填）
        self._forward_log: Optional[str] = None  # usbmux forward 输出（ensure_forward_port 填）
        self._image_error: str = ""            # ensure_image 失败时的末行诊断

    def _check_cancel(self) -> None:
        ev = self.cancel_event
        if ev is not None and hasattr(ev, "is_set") and ev.is_set():
            raise PrepCancelled("iOS 设备准备已取消")

    def _sleep(self, sec: float) -> None:
        """可中断 sleep（约 0.2s 检查一次取消）。"""
        end = time.monotonic() + max(0.0, float(sec))
        while True:
            self._check_cancel()
            remain = end - time.monotonic()
            if remain <= 0:
                return
            time.sleep(min(0.2, remain))

    def _owned_pids(self) -> set[int]:
        out: set[int] = set()
        for p in self._procs:
            pid = getattr(p, "pid", None)
            if pid:
                out.add(int(pid))
        return out

    @staticmethod
    def _goios(args, timeout=20):
        return run_hidden([str(resolve_go_ios()), *args], capture_output=True,
                          timeout=timeout, env={**os.environ, **AGENT_ENV})

    def reclaim(self, *, hard: bool = False) -> None:
        ports = {self.info_port, _GOIOS_DEFAULT_AGENT_PORT}
        owned = self._owned_pids()
        if hard:
            for proc in list(self._procs):
                # noinspection PyBroadException
                try:
                    if proc.poll() is None:
                        proc.terminate()
                except Exception:
                    pass
            # 只杀本会话 info_port 的 tunnel，勿扫全机
            kill_goios_tunnel_agents(info_port=self.info_port)
            ports |= {self.wda_port, self.mjpeg_port}
        for p in ports:
            if is_port_listening(p):
                # 优先杀本会话登记 pid；否则仅杀本工具链监听者
                kill_listeners(
                    p,
                    owned_pids=owned or None,
                    tool_only=True,
                )
                if is_port_listening(p):
                    kill_listeners(p, tool_only=True)

    def tunnel_running(self) -> bool:
        # noinspection PyBroadException
        try:
            r = self._goios(["tunnel", "ls", "--tunnel-info-port", str(self.info_port)])
        except Exception:
            return False
        out = (r.stdout or b"").decode("utf-8", "replace").lower()
        if "not running" in out or "refused" in out:
            return False
        return "userspacetun" in out or self.udid.lower() in out

    def ensure_tunnel(self, timeout: float = 40, *, force: bool = False) -> bool:
        self._check_cancel()
        if force:
            self.reclaim(hard=True)
        elif self.tunnel_running():
            return True
        else:
            self.reclaim()
        self._procs.append(_spawn(tunnel_cmd(self.info_port), use_agent=True))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._check_cancel()
            if self.tunnel_running():
                return True
            self._sleep(2)
        return False

    def wda_installed(self) -> bool:
        """设备上是否已安装目标 WDA 测试运行器（runwda 前置）。"""
        if not self.wda_bundle:
            return False   # 空 bundle 是任意串子串，会恒 True 误报「已装」
        # noinspection PyBroadException
        try:
            r = self._goios(["apps", "--list", "--all", "--udid", self.udid], timeout=30)
        except Exception:
            return True   # 查不动就不阻断，交给 runwda 自己报
        out = (r.stdout or b"").decode("utf-8", "replace")
        return self.wda_bundle in out

    def _bundles_pmd3(self) -> list[str]:
        """优先用 pymobiledevice3 列 WDA（走 usbmux/lockdown，不依赖隧道，更稳）。"""
        # noinspection PyBroadException
        try:
            r = run_hidden([sys.executable, "-m", "pymobiledevice3", "apps", "list",
                            "--udid", self.udid], capture_output=True, timeout=45)
            return wda_bundles_from_pmd3_json((r.stdout or b"").decode("utf-8", "replace"))
        except Exception:
            return []

    def _bundles_goios(self) -> list[str]:
        """兜底：go-ios apps --list 文本解析（iOS17 需隧道已起）。"""
        # noinspection PyBroadException
        try:
            r = self._goios(["apps", "--list", "--all", "--udid", self.udid], timeout=30)
            text = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")
            return parse_wda_bundles(text)
        except Exception:
            return []

    def discover_wda(self) -> str:
        """自动发现设备上已安装的 WDA bundle id。

        **不做任何后缀拼接**：只返回 pymobiledevice3 / go-ios ``apps list`` 顶层
        CFBundleIdentifier 原样字符串。真机 Test Runner 登记名常带 ``.xctrunner``，
        且可能出现 ``…xctrunner.xctrunner``（与 Xcode 工程里主 target Bundle ID 不同属正常）。

        0 个 → 报「未安装」；多个 → 报错并列出，要求用 wdaBundleId 指定。
        """
        cands = self._bundles_pmd3() or self._bundles_goios()
        if not cands:
            raise RuntimeError(
                f"设备 {self.udid or '（未指定）'} 上未找到 WDA 测试运行器"
                "（WebDriverAgentRunner …xctrunner）——"
                "请先在该机安装并信任 WebDriverAgent（Mac/Xcode 编译，或签名 ipa 安装；"
                "免费证书 7 天会过期需重装）。"
                "这与 Appium usePreinstalledWDA 卸载无关：当前只是 apps list 未检索到包。")
        if len(cands) > 1:
            raise RuntimeError(
                f"设备 {self.udid or ''} 上存在多个 WDA 包，请用 wdaBundleId 明确指定其一：\n  "
                + "\n  ".join(cands))
        chosen = cands[0]
        self.log(f"  自动发现 WDA（设备 apps list 原样）：{chosen}")
        if chosen.lower().endswith(".xctrunner.xctrunner"):
            self.log(
                "  提示：真机 Test Runner 登记名带双 .xctrunner 时，runwda 须用此完整 id；"
                "与 Xcode 工程 Bundle ID 不一致不代表检索错误。")
        return chosen

    def _image_already_mounted(self) -> bool:
        """``ios image list``：已挂载时 msg 为签名 hash；未挂载为 ``none``。"""
        # noinspection PyBroadException
        try:
            r = self._goios(["image", "list", "--udid", self.udid], timeout=30)
        except Exception:
            return False
        text = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            # noinspection PyBroadException
            try:
                msg = str(json.loads(line).get("msg", "")).strip().lower()
            except Exception:
                continue
            if msg and msg != "none":
                return True
        return False

    def ensure_image(self) -> bool:
        """挂载开发者镜像：优先本地芯片匹配项；否则 image auto / pymobiledevice3 在线拉取。

        大体积 DDI 通常不进 Git：缺本地匹配镜像时依赖网络自动下载到 ``devimages/``。
        切勿先硬挂不匹配的旧 DDI（会 findIdentity 失败，且掩盖 auto 下载路径）。
        """
        self._image_error = ""
        if self._image_already_mounted():
            return True

        ids = query_personalization_ids(self.udid)
        all_dirs = list_local_ddi_restore_dirs()
        if ids:
            chip, board = ids
            matched = [p for p in all_dirs if ddi_identity_matches(p, chip, board)]
            self.log(
                f"  DDI：ChipID=0x{chip:x} BoardId=0x{board:x}，"
                f"本地匹配 {len(matched)}/{len(all_dirs)}")
        else:
            # 读不到个性化标识时仍尝试本地全部，再走在线
            matched = list(all_dirs)
            self.log(f"  DDI：未能读取 ChipID，将尝试本地 {len(matched)} 个后在线下载")

        last_err = ""
        for restore in matched:
            # noinspection PyBroadException
            try:
                r = self._goios(
                    ["image", "mount", "--path", str(restore), "--udid", self.udid],
                    timeout=120)
            except Exception as e:  # noqa: BLE001
                last_err = str(e)
                continue
            out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")
            low = out.lower()
            if "success mounting" in low or ("already" in low and "mounted" in low):
                return True
            if out.strip():
                last_err = out.strip().splitlines()[-1]

        # 在线：go-ios image auto（下载到 basedir 并挂载；需可访问 Apple 相关源）
        self.log("  本地无匹配镜像，尝试 go-ios image auto 在线下载并挂载…")
        # noinspection PyBroadException
        try:
            r = self._goios(
                ["image", "auto", f"--basedir={DEVIMAGE_DIR}", "--udid", self.udid],
                timeout=300)
            out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")
            low = out.lower()
            if "success mounting" in low or ("already" in low and "mounted" in low):
                self.log("  image auto 成功")
                return True
            if out.strip():
                last_err = out.strip().splitlines()[-1]
                self.log(f"  image auto 未成功：{last_err[:160]}")
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            self.log(f"  image auto 异常：{last_err[:160]}")

        # 兜底：pymobiledevice3（隧道已在 prepare 中拉起时可走 --userspace）
        self.log("  尝试 pymobiledevice3 mounter auto-mount…")
        # noinspection PyBroadException
        try:
            r = run_hidden(
                [sys.executable, "-m", "pymobiledevice3", "mounter", "auto-mount",
                 "--udid", self.udid, "--userspace"],
                capture_output=True, timeout=300)
            out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")
            if r.returncode == 0:
                self.log("  pymobiledevice3 auto-mount 成功")
                return True
            if out.strip():
                last_err = out.strip().splitlines()[-1]
                self.log(f"  auto-mount 未成功：{last_err[:160]}")
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            self.log(f"  auto-mount 异常：{last_err[:160]}")

        self._image_error = last_err
        return False

    def ensure_wda(self, warmup: float = 16) -> bool:
        # runwda 输出写临时日志，失败时可读出原因（签名/信任/设备锁/隧道）
        self._wda_log = tempfile.NamedTemporaryFile(
            prefix="autopilot_runwda_", suffix=".log", delete=False).name
        env = {**os.environ, **AGENT_ENV}
        cmd = runwda_cmd(self.wda_bundle, udid=self.udid,
                         env={"USE_PORT": self.wda_port,
                              "MJPEG_SERVER_PORT": self.mjpeg_port})
        # noinspection PyBroadException
        try:
            lf = open(self._wda_log, "wb")
            proc = popen_hidden(cmd, env=env, stdout=lf, stderr=subprocess.STDOUT)
        except Exception:
            return False
        self._procs.append(proc)
        self._sleep(warmup)
        return proc.poll() is None

    def runwda_log_tail(self, n: int = 6) -> str:
        return self._log_tail(getattr(self, "_wda_log", ""), n)

    def forward_log_tail(self, n: int = 6) -> str:
        return self._log_tail(getattr(self, "_forward_log", ""), n)

    @staticmethod
    def _log_tail(path: str, n: int = 6) -> str:
        if not path or not os.path.exists(path):
            return ""
        # noinspection PyBroadException
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return "\n".join(f.read().splitlines()[-n:])
        except Exception:
            return ""

    def ensure_forward(self, timeout: float = 10) -> bool:
        return self.ensure_forward_port(self.wda_port, timeout)

    def ensure_forward_port(self, port: int, timeout: float = 10) -> bool:
        self._check_cancel()
        cmd = pmd3_forward_cmd(port, port, udid=self.udid)
        # 转发进程退出码/stderr 要留痕：参数不兼容时否则只表现为 /status 不通
        self._forward_log = self._forward_log or tempfile.NamedTemporaryFile(
            prefix="autopilot_forward_", suffix=".log", delete=False).name
        try:
            lf = open(self._forward_log, "ab")
        except OSError:
            lf = subprocess.DEVNULL
        self._procs.append(popen_hidden(cmd, stdout=lf, stderr=subprocess.STDOUT))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._check_cancel()
            if is_port_listening(port):
                return True
            self._sleep(1)
        return is_port_listening(port)

    def wait_status(self, timeout: float = 90) -> bool:
        # noinspection PyUnresolvedReferences
        import httpx
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._check_cancel()
            # noinspection PyBroadException
            try:
                if httpx.get(f"http://127.0.0.1:{self.wda_port}/status",
                             timeout=3).status_code == 200:
                    return True
            except Exception:
                pass
            self._sleep(3)
        return False

    def prepare(self, *, force_tunnel_rebuild: bool = False) -> str:
        """完整准备并返回本机 WDA URL；任一步失败抛 RuntimeError。

        force_tunnel_rebuild：屏幕采集（AVFoundation/CoreMediaIO）激活后，iPhone 因进入
        QuickTime 录制 USB 配置而重新枚举，已建立的 RSD 隧道失效。此时强制回收并重建
        用户态隧道再 ``runwda``，否则 runwda 会连到过期 RSD（connection refused）。
        """
        self._check_cancel()
        url = f"http://127.0.0.1:{self.wda_port}"
        if wda_alive(self.wda_port) and not force_tunnel_rebuild:
            self.log(f"复用已有 WDA（{url} /status OK）")
            # noinspection PyBroadException
            try:
                self.ensure_forward_port(self.mjpeg_port)
            except Exception:
                pass
            if not mjpeg_alive(self.mjpeg_port):
                self.log(
                    f"  MJPEG {self.mjpeg_port} 未就绪"
                    "（WDA 需由 runwda 带 MJPEG_SERVER_PORT 启动）"
                )
            return url
        if not available():
            raise RuntimeError("未找到 go-ios 二进制（resources/re_go_ios）")
        # 走到这里说明没有可复用的健康 WDA（上面 wda_alive 复用分支已 return）。无论是否
        # force_tunnel_rebuild，都先硬回收上一次运行残留的隧道/agent/转发端口，再干净重建。
        # 关键：不能只靠 tunnel_running()——它看不出「隧道进程还在、但 RSD 代理已死」的陈旧
        # 隧道，误复用就会让 runwda 报 could not connect to RSD / connection refused。
        if force_tunnel_rebuild:
            self.log("屏幕采集已激活（USB 重枚举）→ 强制回收并重建 RSD 隧道…")
        else:
            self.log("无可复用 WDA → 硬回收残留隧道/端口后重建…")
        self.reclaim(hard=True)
        self._sleep(3 if force_tunnel_rebuild else 1)
        self.log("启动用户态隧道(--userspace)…")
        tunnel_timeout = 60.0 if force_tunnel_rebuild else 45.0
        if not self.ensure_tunnel(timeout=tunnel_timeout, force=True):
            hint = "（屏幕采集切换 USB 后 RSD 隧道需重建）" if force_tunnel_rebuild else ""
            raise RuntimeError(f"隧道未就绪（iOS17+ 需 --userspace 用户态隧道）{hint}")
        if not self.wda_bundle:
            self.log("自动发现 WDA bundle id（go-ios apps）…")
            self.wda_bundle = self.discover_wda()
            self.log(f"  使用 WDA：{self.wda_bundle}")
        elif not self.wda_installed():
            self.log(f"  警告：apps 列表未命中 [{self.wda_bundle}]，仍尝试 runwda…")
        self.log("挂载开发者镜像…")
        img_ok = False
        for _ in range(2):
            self._check_cancel()
            if self.ensure_image():
                img_ok = True
                break
            self._sleep(2)
        if not img_ok:
            detail = (getattr(self, "_image_error", "") or "").strip()
            low = detail.lower()
            if "findidentity" in low or "could not find identity" in low or "apchipid" in low:
                local = [p.parent.name for p in list_local_ddi_restore_dirs()]
                local_s = "、".join(local) if local else "（无）"
                raise RuntimeError(
                    "开发者镜像挂载失败：本地无匹配本机芯片的 DDI，且自动下载/挂载未成功"
                    "（常见于 iPhone 16 / A18，ApChipId 0x8140）。\n"
                    f"本机已有缓存：{local_s}。\n"
                    "请确认网络可访问 Apple 镜像源后重试「刷新快照」"
                    "（go-ios image auto / pymobiledevice3 会下载到 "
                    "resources/re_go_ios/devimages）；"
                    "或离线放入已含该芯片身份的个性化镜像目录。\n"
                    "大体积 DDI 通常不进 Git，依赖首次联网自动拉取。"
                    + (f"\n{detail}" if detail else ""))
            self.log("  警告：镜像挂载未确认，继续尝试 runwda"
                     + (f"（{detail[:120]}）" if detail else ""))
        self._sleep(3)   # 让隧道/镜像 settle，否则 runwda 可能 "Did not find test app"
        self.log("runwda 拉起 WDA…")
        if not self.ensure_wda():
            # 失败重试一次：再确认镜像 + settle（多为镜像/隧道 agent 未就绪的瞬态）
            tail = self.runwda_log_tail()
            self.log(f"  runwda 首次失败，重试… ({tail.splitlines()[-1][:80] if tail else ''})")
            self.ensure_image()
            self._sleep(4)
            if not self.ensure_wda():
                tail = self.runwda_log_tail()
                hint = ""
                low_tail = tail.lower()
                if "could not connect to rsd" in low_tail or "connection refused" in low_tail:
                    hint = "\n（屏幕采集中 go-ios RSD 隧道可能失效，已尝试重建；仍失败请停止镜像后重试）"
                elif "timed out waiting" in low_tail or "initiate a ide session" in low_tail:
                    hint = "\n（XCTest/DTX 会话超时：请确认设备已解锁、开发者模式开启、开发者镜像已挂载）"
                raise RuntimeError("runwda 进程已退出（检查签名/信任/设备解锁）"
                                   + hint + "\nrunwda 输出:\n" + tail)
        self.log("pymobiledevice3 转发 + 等待 WDA /status…")
        forwarded = self.ensure_forward()
        if not forwarded:
            self.log(f"  警告：本机 {self.wda_port} 未监听，转发疑似启动失败")
        # 顺带转发 MJPEG（实时镜像用，best-effort，不阻断主流程）
        # noinspection PyBroadException
        try:
            self.ensure_forward_port(self.mjpeg_port)
        except Exception:
            pass
        if not self.wait_status():
            raise RuntimeError(
                "WDA /status 未就绪" + self._status_failure_detail(forwarded))
        return f"http://127.0.0.1:{self.wda_port}"

    def _status_failure_detail(self, forwarded: bool) -> str:
        """区分「端口转发没起来」和「WDA 自身没起来」，否则两者报错一模一样。"""
        parts: list[str] = []
        if not forwarded:
            parts.append(
                f"本机 {self.wda_port} 端口未监听 → pymobiledevice3 usbmux forward "
                "未成功（常见于 pymobiledevice3 版本变更导致选设备参数不兼容）")
            tail = self.forward_log_tail(4)
            if tail:
                parts.append("forward 输出:\n" + tail)
        else:
            parts.append(f"本机 {self.wda_port} 已监听但 /status 无响应 → WDA 侧未提供 HTTP 服务"
                         "（检查设备是否解锁、WDA 签名是否过期）")
            tail = self.runwda_log_tail(4)
            if tail:
                parts.append("runwda 输出:\n" + tail)
        return "\n" + "\n".join(parts)

    def mjpeg_url(self) -> str:
        return f"http://127.0.0.1:{self.mjpeg_port}"

    def stop(self) -> None:
        for p in self._procs:
            # noinspection PyBroadException
            try:
                p.terminate()
            except Exception:
                pass
        owned = self._owned_pids()
        self._procs.clear()
        # terminate 不保证立刻释放端口（pmd3 forward 子进程可能滞留）→ 强制回收，
        # 否则 WDA/MJPEG 残留为「陈旧转发」，下次连接还得靠探活兜底重建。
        for port in (self.wda_port, self.mjpeg_port):
            if is_port_listening(port):
                kill_listeners(port, owned_pids=owned or None, tool_only=True)
                if is_port_listening(port):
                    kill_listeners(port, tool_only=True)
