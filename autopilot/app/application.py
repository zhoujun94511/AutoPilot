"""应用引导：把 QApplication 装配与主窗口构建从入口脚本中分离出来。

- build_window(): 构建主窗口（便于测试，可在离屏模式下调用）。
- run(): 完整启动 GUI 事件循环。
"""

from __future__ import annotations

import os
import signal
import sys
from typing import Optional

# noinspection PyUnresolvedReferences
from PyQt6.QtCore import QTimer
# noinspection PyUnresolvedReferences
from PyQt6.QtWidgets import QApplication

from ..ui.main_window import MainWindow

# 默认不预设工程目录：启动时优先恢复「上次工程」，无则空工作区（避免误把仓库 tests/ 当工程）
DEFAULT_PROJECT_DIR = ""
DEFAULT_CONFIG_DIR = ""  # 空 = 用 autopilot/metadata/keyword_defs 内置资源


def build_window(
    project_dir: Optional[str] = None,
    config_dir: Optional[str] = None,
) -> MainWindow:
    return MainWindow(
        project_dir=project_dir if project_dir is not None else DEFAULT_PROJECT_DIR,
        config_dir=config_dir if config_dir is not None else DEFAULT_CONFIG_DIR,
    )


def run(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    config = argv[2] if len(argv) > 2 else DEFAULT_CONFIG_DIR
    if len(argv) > 1:
        project = argv[1]                       # 命令行显式指定优先
    else:
        from ..runtime import settings          # 否则恢复上次工程；无则空工作区
        last = settings.last_project()
        project = last if (last and os.path.isdir(last)) else ""
    from ..runtime.log import setup_logging, get_logger
    logfile = setup_logging()         # 装配文件(轮转)+ stderr 日志，全局一次
    from ..ui.branding import app_icon, APP_NAME, set_macos_app_name, set_macos_app_icon, set_windows_app_id, configure_app_font
    set_windows_app_id()              # 须在建窗口前：让 Windows 任务栏用本程序图标而非 python.exe
    set_macos_app_name()              # macOS Dock/菜单栏显示 AutoPilot 而非 Python
    app = QApplication(argv)
    configure_app_font(app)           # macOS：避免 Qt 解析 "Sans Serif" 的 qpa.fonts 警告
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setWindowIcon(app_icon())     # 任务栏/Alt-Tab 图标
    set_macos_app_icon()              # macOS 系统弹框（QMessageBox）用应用图标而非 Python 火箭
    app.setDesktopFileName("autopilot")   # Linux：与 .desktop 启动器关联，任务栏/Dock 用其图标
    window = build_window(project, config)
    from ..ui.theme import install_system_theme_listener
    install_system_theme_listener(app, window)
    window.console.install_log_bridge()   # 让引擎/设备等纯 logging 来源也进控制台
    get_logger("app").info("AutoPilot 启动；日志文件：%s", logfile or "(未落盘)")
    if not window.ensure_ide_login():
        get_logger("app").info("未登录，退出")
        return 1
    window.show()
    _install_graceful_shutdown(app, window)
    return app.exec()


def _install_graceful_shutdown(app: QApplication, window: MainWindow) -> None:
    """让 Ctrl+C / kill 走正常关闭流程，避免在 Qt 槽里抛 KeyboardInterrupt。

    直接抛 KeyboardInterrupt 会打断正在跑的槽（如镜像帧回调），事件循环随之退出，
    但后台 QThread（AVFoundation 采集等）仍在运行 → 被销毁时 Qt abort()（SIGABRT/134）。
    这里改为收到信号后触发 window.close()（走 closeEvent 停镜像/线程/子进程）再退出。
    """
    def _stop_background() -> None:
        # noinspection PyBroadException
        try:
            window.mirror.stop()          # 停采集线程 + helper 子进程（幂等）
        except Exception:
            pass

    app.aboutToQuit.connect(_stop_background)

    triggered = {"v": False}

    def _handle_signal(*_a) -> None:
        if triggered["v"]:
            return
        triggered["v"] = True
        # 先停后台线程/子进程，再关窗口（closeEvent 会再幂等停一次），最后退出事件循环
        _stop_background()
        # noinspection PyBroadException
        try:
            window.close()
        except Exception:
            pass
        app.quit()

    for sig in (signal.SIGINT, signal.SIGTERM):
        # noinspection PyBroadException
        try:
            signal.signal(sig, _handle_signal)
        except (ValueError, OSError):
            pass   # 非主线程或平台不支持时跳过

    # Qt 的 C++ 事件循环期间 Python 不会执行字节码 → 挂起的信号无法及时处理。
    # 用一个定时器周期性把控制权交回 Python，让信号处理器有机会运行。
    timer = QTimer(app)
    timer.start(200)
    # noinspection PyUnresolvedReferences
    timer.timeout.connect(lambda: None)
    # 持有引用，防止被 GC（否则定时器停摆，信号又变得不及时）
    app._autopilot_sig_timer = timer  # type: ignore[attr-defined]
