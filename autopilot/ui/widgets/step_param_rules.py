"""步骤参数的平台条件显隐（参数面板与用例表格共用）。"""

from __future__ import annotations

from typing import Callable

from ...model.testcase import Step


def step_platform(step: Step) -> str:
    """步骤 type/platform 参数值（小写）；缺省 android。"""
    for p in step.params:
        if p.param_id in ("type", "platform"):
            v = str(p.value or "").strip().lower()
            if v:
                return v
    return "android"


def effective_platform(step: Step, case_platform: str = "") -> str:
    """有效目标平台：步骤参数 > 用例平台 > android。

    与 mobile-backend-boundaries §4.1 一致——用例已标 iOS 时，即使步骤未填 type，
    仍应按 iOS 处理 backendMode/keepData 等条件显隐。
    """
    from_step = ""
    for p in step.params:
        if p.param_id in ("type", "platform"):
            v = str(p.value or "").strip().lower()
            if v:
                from_step = v
                break
    if from_step.startswith("ios"):
        return "ios"
    if from_step.startswith("android"):
        return "android"
    case = (case_platform or "").strip().lower()
    if case.startswith("ios"):
        return "ios"
    if case.startswith("android"):
        return "android"
    return "android"


def _is_ios(step: Step, case_platform: str = "") -> bool:
    return effective_platform(step, case_platform).startswith("ios")


def _not_ios(step: Step, case_platform: str = "") -> bool:
    return not _is_ios(step, case_platform)


_IOS_ONLY_MONKEY_PARAMS = (
    "durationSec",
    "throttleMs",
    "monkeyPolicy",
    "seed",
    "collectDeviceLogs",
    "deviceLogsBackend",
    "syslogMode",
    "reportHtml",
)

# keyword_id → param_id → 为 True 时隐藏/忽略该参数
_PARAM_HIDE_WHEN: dict[str, dict[str, Callable[[Step, str], bool]]] = {
    "mobile_app_install_and_open": {
        "keepData": lambda step, cp="": _is_ios(step, cp),
        "backendMode": lambda step, cp="": not _is_ios(step, cp),
    },
    "mobile_app_adb_uninstall": {
        "cacheSave": lambda step, cp="": _is_ios(step, cp),
    },
    "mobile_app_start": {
        "backendMode": lambda step, cp="": not _is_ios(step, cp),
    },
    "mobile_monkey": {
        pid: (lambda _s, _cp="", p=pid: _not_ios(_s, _cp))
        for pid in _IOS_ONLY_MONKEY_PARAMS
    },
}


def param_visible(keyword_id: str, param_id: str, step: Step,
                  case_platform: str = "") -> bool:
    hide = _PARAM_HIDE_WHEN.get(keyword_id, {}).get(param_id)
    if hide is None:
        return True
    return not hide(step, case_platform)


def strip_hidden_params(step: Step, case_platform: str = "") -> None:
    """从步骤模型移除当前平台下不应存在的参数。"""
    rules = _PARAM_HIDE_WHEN.get(step.keyword_id, {})
    if not rules:
        return
    step.params = [
        p for p in step.params
        if param_visible(step.keyword_id, p.param_id, step, case_platform)
    ]


def format_step_params(step: Step, case_platform: str = "") -> str:
    """表格「参数」列文本：跳过当前平台隐藏的参数。"""
    parts = [
        f"{p.param_id}={p.value}"
        for p in step.params
        if param_visible(step.keyword_id, p.param_id, step, case_platform)
    ]
    return "  ".join(parts)


def keyword_has_conditional_params(keyword_id: str) -> bool:
    return keyword_id in _PARAM_HIDE_WHEN
