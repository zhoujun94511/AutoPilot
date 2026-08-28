"""运行环境预检（preflight）：开跑前确认依赖、资源、工具链是否就位。

按本项目实际配置逐项体检，**不连真机/真服务**（那是 verify_realenv.py 的职责）：
  1) Python 版本；
  2) 核心依赖（IDE/执行主路径：PyQt6、selenium、httpx、Appium、opencv、Jinja2、openpyxl 等）；
  3) 可选能力（pyproject optional：data / mirror / secure）；
  4) 内置资源（resources/re_adb、re_aapt、re_go_ios、re_scrcpy、re_uiautomator）；
  5) 派生工具链（adb / go-ios，由资源解包或 PATH 提供）；
  6) 移动端外部运行时（Java JDK / Node.js / Appium CLI + 驱动 / Appium 服务），
     这些非 Python 包，需各自单独安装——Android 经 Appium 必需，
     iOS 在 Windows 走直连 WDA、不经 Appium；
  5b) web 能力（Selenium 浏览器 + Playwright 可选引擎）。

每项给 OK / 缺失，并附「按需」安装命令；核心缺失才以非零码退出，可选缺失只提示。

用法：
    .venv/Scripts/python.exe tools/preflight.py            # 体检并报告
    .venv/Scripts/python.exe tools/preflight.py --install data,mirror,secure,web_playwright   # 装这些可选 Python 能力
    .venv/Scripts/python.exe tools/preflight.py --install-all            # 装全部可选 Python 能力
    .venv/Scripts/python.exe tools/preflight.py --install-drivers        # 装宿主侧 Appium 驱动(uiautomator2)
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

MIN_PY = (3, 10)   # 与 pyproject 的 requires-python 对齐

# extra 名 → [(显示名, 导入名), ...]（导入名对应已安装的包模块）
# http/mobile/image/report/openpyxl 已并入 pyproject 主依赖，此处计入 core
EXTRAS = {
    "core": [
        ("PyQt6", "PyQt6"),
        ("lxml", "lxml"),
        ("selenium", "selenium"),
        ("httpx", "httpx"),
        ("jsonpath-ng", "jsonpath_ng"),
        ("Jinja2", "jinja2"),
        ("openpyxl", "openpyxl"),
        ("Appium-Python-Client", "appium"),
        ("pyaxmlparser", "pyaxmlparser"),
        ("opencv-python-headless", "cv2"),
        ("numpy", "numpy"),
        ("cryptography", "cryptography"),
    ],
    "data": [
        ("redis", "redis"),
        ("paramiko", "paramiko"),
        ("SQLAlchemy", "sqlalchemy"),
        ("kafka-python", "kafka"),
        ("elasticsearch", "elasticsearch"),
        ("happybase", "happybase"),
    ],
    "mirror": [("av(PyAV)", "av"), ("adbutils", "adbutils")],
    "secure": [("keyring", "keyring")],
    "web_playwright": [("playwright", "playwright")],
}
_CAP_DESC = {
    "core": "IDE + Web/Http/Mobile/图像/报告/Excel",
    "data": "数据/中间件关键字（Redis/SSH/DB/Kafka/ES/HBase）",
    "mirror": "Android scrcpy 实时镜像（H.264 解码 + 控制）",
    "secure": "管理台密码 OS 钥匙串",
    "web_playwright": "Web Playwright 可选引擎（web_engine=playwright）",
}

_RESET, _G, _Y, _R, _DIM = "\033[0m", "\033[32m", "\033[33m", "\033[31m", "\033[2m"
_n_fail = 0   # 核心缺失计数（决定退出码）
_n_warn = 0   # 可选缺失计数


def _line(name: str, status: str, detail: str = "") -> None:
    mark = {"OK": f"{_G}✅", "WARN": f"{_Y}⚠", "FAIL": f"{_R}❌"}.get(status, "?")
    print(f"  {mark} {name:26}{_RESET} {detail}")


def _have(mod: str) -> bool:
    # noinspection PyBroadException
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


def check_python() -> None:
    print("\n[1] Python 解释器")
    v = sys.version_info
    ok = (v.major, v.minor) >= MIN_PY
    _line("Python", "OK" if ok else "FAIL",
          f"{v.major}.{v.minor}.{v.micro}（需 ≥ {MIN_PY[0]}.{MIN_PY[1]}）  {sys.executable}")
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    _line("虚拟环境", "OK" if in_venv else "WARN",
          "已在 venv 内" if in_venv else "未检测到 venv（建议在项目 .venv 内运行/安装）")
    if not ok:
        globals().__setitem__("_n_fail", _n_fail + 1)


def check_caps() -> None:
    global _n_fail, _n_warn
    print("\n[2] 依赖能力（core 必需；其余按需）")
    for extra, mods in EXTRAS.items():
        missing = [disp for disp, imp in mods if not _have(imp)]
        desc = _CAP_DESC.get(extra, "")
        if not missing:
            _line(f"{extra}", "OK", f"{desc}")
            continue
        if extra == "core":
            _n_fail += 1
            _line("core", "FAIL", f"缺 {', '.join(missing)} → pip install -e .")
        else:
            _n_warn += 1
            _line(f"{extra}", "WARN",
                  f"{desc}｜缺 {', '.join(missing)} → pip install -e .[{extra}]")


def _res(*parts) -> Path:
    return _ROOT.joinpath("resources", *parts)


def check_resources() -> None:
    global _n_warn
    print("\n[3] 内置资源（resources/）")
    ostag = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}.get(platform.system(), "windows")
    adbtag = {"Windows": "windows", "Darwin": "darwin", "Linux": "linux"}.get(platform.system(), "windows")
    checks = [
        ("re_adb (platform-tools)", _res("re_adb", f"platform-tools-latest-{adbtag}.zip")),
        ("re_aapt", _res("re_aapt", f"aapt-{ostag}.zip")),
        ("re_scrcpy/scrcpy-server.jar", _res("re_scrcpy", "scrcpy-server.jar")),
        ("re_uiautomator (设备侧apk)", _res("re_uiautomator", "app-uiautomator.apk")),
        ("re_go_ios/devimages", _res("re_go_ios", "devimages")),
    ]
    for name, p in checks:
        if p.exists():
            _line(name, "OK", _dim(str(p.relative_to(_ROOT))))
        else:
            _n_warn += 1
            _line(name, "WARN", f"缺失：{p.relative_to(_ROOT)}（对应平台能力不可用）")


def _dim(s: str) -> str:
    return f"{_DIM}{s}{_RESET}"


def check_toolchain() -> None:
    global _n_warn
    print("\n[4] 派生工具链（资源解包 / PATH）")
    # adb：项目优先用 resources/re_adb 解包，其次 PATH
    # noinspection PyBroadException
    try:
        from autopilot.mobile import adb
        exe = adb.ensure_adb()
        _line("adb", "OK" if exe else "WARN",
              str(exe) if exe else "未就绪（Android 关键字/镜像不可用）")
        if not exe:
            _n_warn += 1
    except Exception as e:  # noqa: BLE001
        _n_warn += 1
        _line("adb", "WARN", f"检测失败：{e}")
    # go-ios：iOS 真机工具链（Windows 无 Mac 时直连 WDA 用）
    # noinspection PyBroadException
    try:
        from autopilot.mobile.ios_bootstrap import resolve_go_ios
        goios = resolve_go_ios()
        _line("go-ios", "OK" if goios else "WARN",
              str(goios) if goios else "未找到（iOS 真机准备不可用）")
        if not goios:
            _n_warn += 1
    except Exception as e:  # noqa: BLE001
        _n_warn += 1
        _line("go-ios", "WARN", f"检测失败：{e}")


def _probe(exe: str, args: list[str], timeout: int = 8) -> tuple[bool, str]:
    """探测外部命令是否可用并取一行版本信息。返回 (found, version_or_msg)。"""
    path = shutil.which(exe)
    if not path:
        return False, ""
    # noinspection PyBroadException
    try:
        r = subprocess.run([path, *args], capture_output=True, timeout=timeout)
        out = (r.stdout or b"") + (r.stderr or b"")   # java -version 走 stderr
        first = out.decode("utf-8", "replace").strip().splitlines()
        return True, (first[0] if first else path)
    except Exception:
        return True, path   # 装了但探测失败，仍算存在


def _run_full(exe: str, args: list[str], timeout: int = 20) -> str:
    """运行外部命令并返回 stdout+stderr 全部文本（命令缺失或失败返回空串）。"""
    path = shutil.which(exe)
    if not path:
        return ""
    # noinspection PyBroadException
    try:
        r = subprocess.run([path, *args], capture_output=True, timeout=timeout)
        return ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")
    except Exception:
        return ""


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex((host, port)) == 0


def check_mobile_runtime() -> None:
    """移动端 Android 自动化所需的外部运行时（Appium 走 Node，且需要 JDK）。

    这些不是 Python 包，需各自单独安装；仅 Android(经 Appium) 必需，
    iOS 在 Windows 走直连 WDA、不经 Appium，故标 WARN 而非 FAIL。
    """
    global _n_warn
    print("\n[5] 移动端外部运行时（Android 经 Appium 必需；非 Python 包）")

    has_java, jver = _probe("java", ["-version"])
    _line("Java (JDK)", "OK" if has_java else "WARN",
          (jver if has_java else "未找到 java → 装 JDK 17+ 并设 JAVA_HOME（Appium Android 必需）"))
    if has_java:
        jh = os.getenv("JAVA_HOME")
        _line("  JAVA_HOME", "OK" if jh else "WARN", jh or "未设（uiautomator2 驱动多需此变量）")
        if not jh:
            _n_warn += 1
    else:
        _n_warn += 1

    has_node, nver = _probe("node", ["--version"])
    _line("Node.js", "OK" if has_node else "WARN",
          (nver if has_node else "未找到 node → 装 Node 18+（Appium 运行时）"))
    if not has_node:
        _n_warn += 1

    has_appium, aver = _probe("appium", ["--version"])
    _line("Appium CLI", "OK" if has_appium else "WARN",
          (f"v{aver}" if has_appium else "未找到 appium → npm i -g appium"))
    if has_appium:
        # `appium driver list --installed` 把结果打到 stderr，驱动名在表头之后的多行里，
        # 故必须扫「全部输出」而非首行。
        text = _run_full("appium", ["driver", "list", "--installed"], timeout=25).lower()
        u2 = "uiautomator2" in text
        # 注意分层：resources/re_uiautomator 是「设备侧」server apk（建会话时装到手机），
        # 与这里的「宿主侧」Appium uiautomator2 Node 驱动是两回事——前者替代不了后者。
        _line("  driver uiautomator2", "OK" if u2 else "WARN",
              "已装（宿主侧 Node 驱动）" if u2 else
              "未装 → appium driver install uiautomator2（设备侧 apk 已内置，但仍需此宿主驱动）")
        if not u2:
            _n_warn += 1
        if platform.system() == "Darwin":   # 仅 macOS 才用得上 Appium 的 xcuitest
            xc = "xcuitest" in text
            _line("  driver xcuitest", "OK" if xc else "WARN",
                  "已装（iOS/Mac）" if xc else "未装 → appium driver install xcuitest")
    else:
        _n_warn += 1

    # Appium 服务是否已在跑（可选；不在跑只是还没启动，不算缺失）
    _line("Appium server :4723", "OK" if _port_open(4723) else "WARN",
          "在监听" if _port_open(4723) else "未启动（用时再 `appium` 起；不影响安装就绪）")

    # Android SDK（Appium UiAutomator2 在**服务进程**内需要 ANDROID_HOME）
    # noinspection PyBroadException
    try:
        from autopilot.mobile.android_env import resolve_android_sdk_root
        sdk = resolve_android_sdk_root()
    except Exception:
        sdk = None
    ah = os.getenv("ANDROID_HOME") or os.getenv("ANDROID_SDK_ROOT") or (str(sdk) if sdk else "")
    _line("ANDROID_HOME", "OK" if ah else "WARN",
          ah or "未设 → Mac 可设 ~/Library/Android/sdk；启动 appium 前 export")

    if platform.system() != "Darwin":
        _line("iOS 说明", "OK", _dim("Windows/Linux 下 iOS 走直连 WDA（go-ios + 见上），不经 Appium/Node"))


def check_web() -> None:
    """web 能力：Selenium 浏览器 + Playwright 可选引擎。"""
    global _n_warn
    print("\n[5b] web 能力（Selenium / Playwright）")
    # noinspection PyBroadException
    try:
        from autopilot.mgmt.local_devices import probe_host_capabilities

        caps, _ = probe_host_capabilities()
        has_web = "web" in caps
        has_pw = "web-playwright" in caps
    except Exception as e:  # noqa: BLE001
        _line("浏览器探测", "WARN", f"检测失败：{e}")
        _n_warn += 1
        return
    forced = os.environ.get("MC_RUNNER_WEB", "").strip()
    hint = f"（MC_RUNNER_WEB={forced}）" if forced else ""
    _line("Selenium 浏览器", "OK" if has_web else "WARN",
          (f"检测到浏览器，Runner 将上报 web 能力{hint}" if has_web
           else "未检测到 Chrome/Edge/Firefox → 装浏览器，或 MC_RUNNER_WEB=1"))
    if not has_web:
        _n_warn += 1
    pw_pkg = _have("playwright")
    _line("playwright 包", "OK" if pw_pkg else "WARN",
          "已安装" if pw_pkg else "未装 → pip install -e \".[web_playwright]\"")
    if not pw_pkg:
        _n_warn += 1
    pw_forced = os.environ.get("MC_RUNNER_WEB_PLAYWRIGHT", "").strip()
    pw_hint = f"（MC_RUNNER_WEB_PLAYWRIGHT={pw_forced}）" if pw_forced else ""
    _line("Playwright Chromium", "OK" if has_pw else "WARN",
          (f"浏览器就绪，Runner 将上报 web-playwright{pw_hint}" if has_pw
           else "未就绪 → playwright install chromium，或 MC_RUNNER_WEB_PLAYWRIGHT=1"))
    if pw_pkg and not has_pw:
        _n_warn += 1


def do_install(groups: list[str]) -> int:
    spec = ",".join(groups)
    target = f".[{spec}]" if spec else "."
    cmd = [sys.executable, "-m", "pip", "install", "-e", target]
    print(f"\n[安装] {' '.join(cmd)}  (cwd={_ROOT})")
    return subprocess.call(cmd, cwd=str(_ROOT))


def do_install_drivers() -> int:
    """安装 Android（及 macOS 上 iOS）所需的宿主侧 Appium Node 驱动。"""
    appium = shutil.which("appium")
    if not appium:
        print("未找到 appium（先 npm i -g appium），无法安装驱动")
        return 2
    drivers = ["uiautomator2"] + (["xcuitest"] if platform.system() == "Darwin" else [])
    rc = 0
    for d in drivers:
        print(f"\n[安装驱动] appium driver install {d}")
        rc |= subprocess.call([appium, "driver", "install", d])
    return rc


def check_parallel_ports(workers: int = 3) -> None:
    """并行模式端口池预检（离线，不连真机）。"""
    global _n_warn
    print(f"\n[5c] 并行端口池（预览 {workers} workers）")
    from autopilot.runtime.port_allocator import PortAllocator, is_port_free
    pa = PortAllocator()
    for slot in range(workers):
        ps = pa.ports_for_slot(slot)
        busy = [p for p in (ps.wda_port, ps.tunnel_port, ps.mjpeg_port) if not is_port_free(p)]
        if busy:
            _n_warn += 1
            _line(f"slot{slot}", "WARN", f"端口占用 {busy}（并行前请释放或调环境变量基址）")
        else:
            _line(f"slot{slot}", "OK",
                  f"WDA {ps.wda_port} / tunnel {ps.tunnel_port} / MJPEG {ps.mjpeg_port}")


def main() -> int:
    ap = argparse.ArgumentParser(description="AutoPilot 运行环境预检")
    ap.add_argument("--install", default="",
                    help="安装指定可选能力（逗号分隔，如 data,mirror,secure,web_playwright）")
    ap.add_argument("--install-all", action="store_true", help="安装全部可选能力")
    ap.add_argument("--install-drivers", action="store_true",
                    help="安装宿主侧 Appium 驱动（uiautomator2；macOS 另装 xcuitest）")
    ap.add_argument("--parallel-preview", type=int, default=0, metavar="N",
                    help="预检 N 个并行 worker 的端口池（不连真机）")
    args = ap.parse_args()

    if args.install_drivers:
        return do_install_drivers()

    if args.install or args.install_all:
        groups = ([g for g in EXTRAS if g != "core"] if args.install_all
                  else [g.strip() for g in args.install.split(",") if g.strip()])
        bad = [g for g in groups if g != "core" and g not in EXTRAS]
        if bad:
            print(f"未知能力组：{bad}；可选：{[g for g in EXTRAS if g != 'core']}")
            return 2
        return do_install(groups)

    print("=== AutoPilot 运行环境预检 (preflight) ===")
    check_python()
    check_caps()
    check_resources()
    check_toolchain()
    check_mobile_runtime()
    check_web()
    if args.parallel_preview > 0:
        check_parallel_ports(args.parallel_preview)

    print("\n=== 小结 ===")
    if _n_fail:
        print(f"  {_R}❌ 核心未就绪（{_n_fail} 项）——先 pip install -e . 再启动{_RESET}")
    elif _n_warn:
        print(f"  {_Y}⚠ 核心就绪，可正常启动；{_n_warn} 项可选能力缺失（按需 "
              f"pip install -e .[<能力>] 或 tools/preflight.py --install <能力>）{_RESET}")
    else:
        print(f"  {_G}✅ 全部就位{_RESET}")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
