"""设备选择的纯逻辑组件（与 Qt 解耦，便于复用与单测）。

统一「单台自动用、多台弹选、无设备中止」的规则，供镜像入口 / 控件检视刷新 / 其它
需要在 Android+iOS 间定目标设备的场景共用，避免各处各写一份还漏掉默认 Android 的坑。

弹选交互通过 `ask` 回调注入（GUI 层传 QInputDialog），本模块不依赖 PyQt。

在线校验 / 文案 / UDID 补齐见同目录 device_readiness.py。
"""

from __future__ import annotations

from typing import Callable, Optional


def build_choices(android: list, ios: list) -> list:
    """把检测到的设备拍平成 [(platform, udid), …]，Android 在前、iOS 在后。"""
    return [("Android", u) for u in (android or [])] + [("iOS", u) for u in (ios or [])]


def device_label(platform: str, udid: str) -> str:
    """默认标签（无查询机型）：``Android · serial`` / ``iOS · udid``。"""
    return f"{platform} · {udid}"


def _platform_ui_name(platform: str) -> str:
    p = (platform or "").strip().lower()
    if p == "ios":
        return "iOS"
    if p == "android":
        return "Android"
    return (platform or "").strip() or "设备"


def friendly_pick_labels(platform: str, udids: list[str]) -> list[str]:
    """与检视/镜像选机同一套文案：``iOS · iPhone 15 Pro Max  (UDID)``。

    展示给 ``pick_list_item`` 的 items；确认后仍用原 udids 作 values 回传。
    """
    from ...mobile.device_info import device_picker_line

    ui = _platform_ui_name(platform)
    out: list[str] = []
    for u in udids or []:
        line = device_picker_line(platform, u)
        out.append(f"{ui} · {line}" if line else device_label(ui, u))
    return out


def choose_device(android: list, ios: list,
                  current: str = "",
                  ask: Optional[Callable[[list, int], Optional[str]]] = None,
                  *,
                  label_fn: Optional[Callable[[str, str], str]] = None,
                  ask_returns_udid: bool = False) -> tuple:
    """在检测到的设备里定目标。

    规则：无设备 → ("empty", None)；单台 → 直接 ("ok", (platform, udid))；
    多台 → 用 `ask(labels, default_idx)` 弹选，取消 → ("cancel", None)，否则 ("ok", …)。

    `current` 是当前已选标签（"Android · xxx"）或纯 UDID，用于多台时定位光标。
    `label_fn(platform, udid)` 可注入「机型 (UDID)」展示文案。
    `ask_returns_udid=True` 时 ask 返回纯 UDID（配合 list_pick values），否则返回展示文案。
    """
    choices = build_choices(android, ios)
    if not choices:
        return "empty", None
    if len(choices) == 1:
        return "ok", choices[0]
    fn = label_fn or device_label
    labels = [fn(p, u) for p, u in choices]
    idx = _index_for_current(choices, labels, current)
    sel = ask(labels, idx) if ask is not None else None
    if not sel:
        return "cancel", None
    if ask_returns_udid:
        for p, u in choices:
            if u == sel:
                return "ok", (p, u)
        if sel in labels:
            return "ok", choices[labels.index(sel)]
        return "cancel", None
    if sel in labels:
        return "ok", choices[labels.index(sel)]
    # 兼容测试/旧回调直接回传 UDID
    for p, u in choices:
        if u == sel:
            return "ok", (p, u)
    return "cancel", None


def _index_for_current(choices: list, labels: list[str], current: str) -> int:
    if not current:
        return 0
    if current in labels:
        return labels.index(current)
    for i, (p, u) in enumerate(choices):
        if not u:
            continue
        if current == u or current == device_label(p, u):
            return i
        if current.endswith(u) or f"({u})" in current or f"· {u}" in current:
            return i
    return 0


def choose_device_runtime(
    android: list,
    ios: list,
    current: str = "",
    ask: Optional[Callable[[list, int], Optional[str]]] = None,
    *,
    label_fn: Optional[Callable[[str, str], str]] = None,
    ask_returns_udid: bool = False,
) -> tuple:
    """与 choose_device 相同，但返回 runtime 平台名 (android|ios, udid)。

    status ∈ {'ok','empty','cancel'}；ok 时第二项为 (platform_runtime, udid)。
    """
    from .device_readiness import normalize_platform_ui

    status, pick = choose_device(
        android, ios, current, ask,
        label_fn=label_fn, ask_returns_udid=ask_returns_udid)
    if status != "ok" or not pick:
        return status, None
    plat_ui, udid = pick
    return "ok", (normalize_platform_ui(plat_ui).lower(), udid)
