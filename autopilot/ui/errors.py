"""UI 层错误文案：把驱动/Appium 长堆栈压成一行人话（检视、镜像、运行共用）。"""

from __future__ import annotations


def clean_driver_err(exc: BaseException, plat: str = "", backend: str = "") -> str:
    """按平台把异常压成短提示，避免控制台/状态栏刷屏。

    iOS 区分 WDA-direct 与 Appium；Android 用 Appium/uiautomator2 术语。
    """
    p = (plat or "").lower()
    b = (backend or "").lower()
    msg = getattr(exc, "msg", None) or str(exc)
    first = msg.strip().splitlines()[0] if msg.strip() else exc.__class__.__name__
    low = first.lower()
    if "session is either terminated or not started" in low or "nosuchdriver" in low:
        if p == "ios":
            if b == "appium":
                return "iOS Appium 会话未建立或已断开（设备未解锁/未信任，或 XCUITest 会话未就绪）"
            return "WDA 会话未建立或已断开（设备未解锁/未信任，或 WebDriverAgent 未就绪）"
        if p == "android":
            return "设备自动化会话未建立或已断开（设备未授权 / uiautomator2 未就绪）"
        return "设备自动化会话未建立或已断开（设备未就绪）"
    if p == "android" and "could not find a connected android device" in low:
        return "未检测到已连接的 Android 设备（请确认 USB 调试已授权）"
    if "econnrefused" in low or "failed to establish" in low:
        if p == "ios":
            if b == "appium":
                return "连不上 Appium 服务或 iOS XCUITest 驱动未就绪"
            return "连不上 WDA（8100 端口未就绪，转发可能未建立）"
        return "连不上 Appium 服务（127.0.0.1:4723 未就绪）"
    if ("10053" in low or "server disconnected" in low or "aborted" in low
            or "中止" in first or "remotedisconnected" in low):
        if p == "ios" and b == "appium":
            return "iOS Appium 连接被中止（Appium 服务、XCUITest 驱动或设备连接可能已断开）"
        return "WDA 连接被中止（转发陈旧或 WDA 已退出，正在自动回收重建）"
    return first[:160]
