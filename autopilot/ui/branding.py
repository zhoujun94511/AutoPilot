"""项目品牌：窗口/应用图标 + 标题。

图标程序化绘制（无需外部图片）：品牌色圆角徽章 + 居中白色 glyph。
寓意——「自动化」(机器人) 驱动「测试」；缺 qtawesome 时退化为「AP」字母组合。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPixmap, QPainter, QColor, QIcon, QFont

from .actions import qicon

APP_NAME = "AutoPilot"
APP_VERSION = "1.0.0"
# 关于页副标题；不进窗口标题（对标 VS Code / JetBrains：标题栏只承载工程上下文）
APP_TAGLINE = "关键字自动化测试 IDE"
# 无工程时的默认窗口标题（与 format_window_title() 无参结果一致）
APP_TITLE = APP_NAME
BRAND_COLOR = "#1565C0"   # 深蓝：稳重、专业
APP_ID = "AutoPilot.TestIDE"   # Windows 任务栏 AppUserModelID（决定任务栏用哪个图标分组）


def format_window_title(project_name: str = "") -> str:
    """窗口标题：固定品牌名（工程上下文由侧栏/编辑器承载，不进标题栏）。"""
    _ = project_name  # 保留参数以兼容既有调用
    return APP_NAME


def set_windows_app_id() -> None:
    """Windows：显式设进程 AppUserModelID，让任务栏/Alt-Tab 用本程序图标而非 python.exe。
    须在创建窗口前调用；非 Windows 或调用失败均无害跳过。"""
    import sys
    if not sys.platform.startswith("win"):
        return
    # noinspection PyBroadException
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def set_macos_app_name(name: str = APP_NAME) -> None:
    """macOS：让 Dock 悬停/菜单栏显示应用名而非 Python（须在 QApplication 前调用）。

    直接 ``python run.py`` 启动时进程名仍是解释器；Qt 的 setApplicationName 只影响
    内部标识，Dock 读的是 NSProcessInfo / argv[0]。此处用 setprogname + ObjC
    setProcessName 对齐正式 .app 的显示名；失败则无害跳过。"""
    import sys
    if sys.platform != "darwin":
        return
    sys.argv[0] = name
    # noinspection PyBroadException
    try:
        import ctypes
        import ctypes.util

        libc = ctypes.CDLL(ctypes.util.find_library("c"))
        if hasattr(libc, "setprogname"):
            libc.setprogname(name.encode())
    except Exception:
        pass
    # noinspection PyBroadException
    try:
        import ctypes
        import ctypes.util

        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))

        def _sel(s: bytes):
            objc.sel_registerName.restype = ctypes.c_void_p
            objc.sel_registerName.argtypes = [ctypes.c_char_p]
            return objc.sel_registerName(s)

        def _cls(s: bytes):
            objc.objc_getClass.restype = ctypes.c_void_p
            objc.objc_getClass.argtypes = [ctypes.c_char_p]
            return objc.objc_getClass(s)

        send = objc.objc_msgSend
        send.restype = ctypes.c_void_p
        send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p]

        ns_name = send(_cls(b"NSString"), _sel(b"stringWithUTF8String:"), name.encode("utf-8"))
        info = send(_cls(b"NSProcessInfo"), _sel(b"processInfo"))
        send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        send(info, _sel(b"setProcessName:"), ns_name)
    except Exception:
        pass


def configure_app_font(app) -> None:
    """为各平台设置存在的系统 UI 字体，避免 Qt 解析泛用名 ``Sans Serif`` 时的警告。"""
    import sys

    if sys.platform == "darwin":
        # macOS 无字面字体族 "Sans Serif"；用系统 UI 字体替代 Qt 默认泛用名。
        app.setFont(QFont(".AppleSystemUIFont", 13))
    elif sys.platform.startswith("win"):
        app.setFont(QFont("Segoe UI", 9))


def _mac_objc_send():
    """加载 libobjc 并返回 (objc, send, cls, sel) 辅助；失败返回 None。"""
    import ctypes
    import ctypes.util

    # noinspection PyBroadException
    try:
        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))

        def _sel(name: bytes):
            objc.sel_registerName.restype = ctypes.c_void_p
            objc.sel_registerName.argtypes = [ctypes.c_char_p]
            return objc.sel_registerName(name)

        def _cls(name: bytes):
            objc.objc_getClass.restype = ctypes.c_void_p
            objc.objc_getClass.argtypes = [ctypes.c_char_p]
            return objc.objc_getClass(name)

        send = objc.objc_msgSend
        send.restype = ctypes.c_void_p
        send.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        return objc, send, _cls, _sel
    except Exception:
        return None


def _ensure_icon_png_path() -> str:
    """供 macOS NSApplication 使用的 PNG 路径（优先 resources，否则渲染到临时文件）。"""
    import os
    import tempfile

    f = _icon_file()
    if f:
        return f
    pm = draw_icon(512).pixmap(512, 512)
    if pm.isNull():
        return ""
    path = os.path.join(tempfile.gettempdir(), "autopilot_app_icon.png")
    if pm.save(path, "PNG"):
        return path
    return ""


def set_macos_app_icon() -> None:
    """macOS：让系统弹框（QMessageBox 等）显示应用图标而非 Python 小火箭。

    须在 QApplication 创建之后调用（渲染回退图标时需要 Qt）。直接 ``python run.py``
    启动时进程 bundle 仍是 Python；需 ``NSApplication.setApplicationIconImage`` 覆盖。
    """
    import sys

    if sys.platform != "darwin":
        return
    png = _ensure_icon_png_path()
    if not png:
        return
    helpers = _mac_objc_send()
    if helpers is None:
        return
    _objc, send, _cls, _sel = helpers
    import ctypes
    # noinspection PyBroadException
    try:
        send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p]
        path_ns = send(
            _cls(b"NSString"), _sel(b"stringWithUTF8String:"), png.encode("utf-8"),
        )
        send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        image = send(
            send(_cls(b"NSImage"), _sel(b"alloc")),
            _sel(b"initWithContentsOfFile:"),
            path_ns,
        )
        if not image:
            return
        app = send(_cls(b"NSApplication"), _sel(b"sharedApplication"))
        send(image, _sel(b"retain"))
        send(app, _sel(b"setApplicationIconImage:"), image)
    except Exception:
        pass


def _icon_file() -> str:
    """导出的品牌图标文件路径（resources/branding/autopilot.png），不存在返回空。
    由 tools/export_icon.py 从 app_icon() 渲染生成；要换 logo 直接替换该文件即可。"""
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    p = os.path.join(root, "resources", "branding", "autopilot.png")
    return p if os.path.isfile(p) else ""


def app_icon(size: int = 256) -> QIcon:
    """品牌图标：优先用导出的图片文件(resources/branding/autopilot.png)，
    无文件则回退到程序化绘制。导出工具用 draw_icon(高分辨率)生成各平台图标文件。"""
    f = _icon_file()
    if f:
        ic = QIcon(f)
        if not ic.isNull():
            return ic
    return draw_icon(size)


def draw_icon(size: int = 256) -> QIcon:
    """程序化绘制品牌图标（矢量级，任意尺寸清晰）：品牌色圆角徽章 + 居中机器人 glyph。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(BRAND_COLOR))
    m = size * 0.06
    radius = size * 0.22
    p.drawRoundedRect(QRectF(m, m, size - 2 * m, size - 2 * m), radius, radius)
    p.end()

    glyph = qicon("mdi6.robot-outline", color="#FFFFFF")
    if glyph is not None:
        g = int(size * 0.6)
        gp = glyph.pixmap(g, g)
        p2 = QPainter(pm)
        p2.drawPixmap((size - g) // 2, (size - g) // 2, gp)
        p2.end()
    else:   # 退化：白色 "AP" 字母组合
        p3 = QPainter(pm)
        p3.setPen(QColor("#FFFFFF"))
        f = QFont()
        f.setBold(True)
        f.setPixelSize(int(size * 0.42))
        p3.setFont(f)
        p3.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "AP")
        p3.end()
    return QIcon(pm)
