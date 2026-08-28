"""iOS WDA-direct vs Appium iOS 行为 parity 用例骨架（离线校验结构，真机对照另行执行）。

Mac nightly 可跑 Appium iOS；Win/Linux PR 跑 WDA-direct。步骤 id 与关键字一致，便于 diff。
"""

from __future__ import annotations

# 最小 parity 集：覆盖 Phase 1/2 已补齐能力
PARITY_CASES: list[dict] = [
    {
        "name": "ios-lifecycle",
        "platform": "ios",
        "steps": [
            {"keyword_id": "mobile_app_start", "comment": "启动会话", "params": {"type": "ios"}},
            {"keyword_id": "mobile_element_click", "params": {"locator": "xpath:://XCUIElementTypeButton[@label='OK']"}},
            # WDA 会话不绑 bundleId；mobile_app_reset 需 terminate+activate 已知 App。
            # parity 用 close+start 测会话重建；带 App 的 reset 见 TEST002 / 显式 launch 后调用。
            {"keyword_id": "mobile_app_close", "comment": "关闭会话（parity 会话重建）"},
            {"keyword_id": "mobile_app_start", "comment": "再次启动会话", "params": {"type": "ios"}},
        ],
    },
    {
        "name": "ios-context-webview",
        "platform": "ios",
        "steps": [
            {"keyword_id": "native_web_swith_context", "params": {"swithoption": "WEB"}},
            {"keyword_id": "mobile_get_current_url", "out": "url"},
            {"keyword_id": "native_web_swith_context", "params": {"swithoption": "NATIVE"}},
        ],
    },
    {
        "name": "ios-gesture-keys",
        "platform": "ios",
        "steps": [
            {"keyword_id": "mobile_swipe_direction", "params": {"direction": "上"}},
            {"keyword_id": "mobile_presskey", "params": {"oKeys": "home"}},
        ],
    },
    {
        "name": "ios-alert-policy",
        "platform": "ios",
        "tags": ["infra"],
        "steps": [
            {"keyword_id": "ios_alert_set_policy", "params": {"policy": "auto"}},
            {"keyword_id": "ios_alert_set_enabled", "params": {"enabled": "是"}},
        ],
    },
    {
        "name": "ios-verify-wait",
        "platform": "ios",
        "steps": [
            {"keyword_id": "mobile_browser_wait_for_exist", "params": {
                "locator": "xpath:://XCUIElementTypeButton", "isExist": "true", "timeout": "3000"}},
            {"keyword_id": "mobile_verify_element_visible", "params": {
                "locator": "xpath:://XCUIElementTypeButton", "visible": "true"}},
        ],
    },
    {
        "name": "ios-device-meta",
        "platform": "ios",
        "tags": ["infra"],
        "steps": [
            {"keyword_id": "mobile_app_start", "comment": "建会话", "params": {"type": "ios"}},
            {"keyword_id": "mobile_get_device_ip", "out": "ip"},
            {"keyword_id": "mobile_get_deviceinfo", "params": {"deviceInfo": "version"}, "out": "ver"},
            {"keyword_id": "mobile_get_deviceinfo", "params": {"deviceInfo": "model"}, "out": "model"},
            {"keyword_id": "mobile_app_close"},
        ],
    },
    {
        "name": "ios-session-infra",
        "platform": "ios",
        "tags": ["infra"],
        "steps": [
            {"keyword_id": "mobile_app_start", "params": {"type": "ios"}},
            {"keyword_id": "mobile_swipe_direction", "params": {"direction": "上", "strategy": "w3c"}},
            {"keyword_id": "mobile_presskey", "params": {"oKeys": "home"}},
            {"keyword_id": "mobile_app_close"},
        ],
    },
]


def parity_case_ids() -> list[str]:
    return [c["name"] for c in PARITY_CASES]


def infra_parity_case_ids() -> list[str]:
    """不依赖特定 App 界面控件的真机基础设施用例（双机 parity 首选）。"""
    return [c["name"] for c in PARITY_CASES if "infra" in (c.get("tags") or [])]


def validate_parity_skeleton() -> bool:
    """离线：结构非空且步骤含 keyword_id。"""
    if not PARITY_CASES:
        return False
    for case in PARITY_CASES:
        if not case.get("platform") == "ios":
            return False
        for step in case.get("steps", []):
            if not step.get("keyword_id"):
                return False
    return True
