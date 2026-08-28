"""Android Appium 基础设施 parity 用例骨架（离线校验，真机另行执行）。"""

from __future__ import annotations

PARITY_CASES: list[dict] = [
    {
        "name": "android-device-meta",
        "platform": "android",
        "tags": ["infra"],
        "steps": [
            {"keyword_id": "mobile_app_start", "params": {"type": "android"}},
            {"keyword_id": "mobile_get_device_ip", "out": "ip"},
            {"keyword_id": "mobile_get_deviceinfo", "params": {"deviceInfo": "AndroidVersion"}, "out": "ver"},
            {"keyword_id": "mobile_get_deviceinfo", "params": {"deviceInfo": "model"}, "out": "model"},
            {"keyword_id": "mobile_app_close"},
        ],
    },
    {
        "name": "android-session-infra",
        "platform": "android",
        "tags": ["infra"],
        "steps": [
            {"keyword_id": "mobile_app_start", "params": {"type": "android"}},
            {"keyword_id": "mobile_swipe_direction", "params": {"direction": "上"}},
            {"keyword_id": "mobile_presskey", "params": {"oKeys": "home"}},
            {"keyword_id": "mobile_app_close"},
        ],
    },
    {
        "name": "android-package-meta",
        "platform": "android",
        "tags": ["infra"],
        "steps": [
            {"keyword_id": "mobile_app_start", "params": {"type": "android"}},
            {"keyword_id": "mobile_app_get_package_and_activity", "params": {"package": "pkg", "activity": "act"}},
            {"keyword_id": "mobile_app_close"},
        ],
    },
]


def parity_case_ids() -> list[str]:
    return [c["name"] for c in PARITY_CASES]


def infra_parity_case_ids() -> list[str]:
    return [c["name"] for c in PARITY_CASES if "infra" in (c.get("tags") or [])]


def validate_parity_skeleton() -> bool:
    if not PARITY_CASES:
        return False
    for case in PARITY_CASES:
        if case.get("platform") != "android":
            return False
        for step in case.get("steps", []):
            if not step.get("keyword_id"):
                return False
    return True
