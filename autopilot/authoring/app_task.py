"""目标应用任务归属：系统叠加层仍算在当前 App 内。

权限框、安装器、设置搜索等前台包名会变，但不等于离开了编写目标。
harness 只根据包名集合判断，不解析自然语言措辞。
"""

from __future__ import annotations

from typing import Any, Iterable

#: 已知会盖在目标 App 之上的系统包（权限 / 安装 / 设置搜索 / 系统 UI）
OVERLAY_PACKAGES = frozenset({
    "com.android.permissioncontroller",
    "com.google.android.permissioncontroller",
    "com.android.packageinstaller",
    "com.google.android.packageinstaller",
    "com.android.systemui",
    "com.android.settings.intelligence",
    "com.android.settings.overlay",
    "com.apple.springboard",
    "com.apple.PreferencesUI",
})

_OVERLAY_PREFIXES = (
    "com.android.permission",
    "com.google.android.permission",
    "com.android.packageinstaller",
    "com.google.android.packageinstaller",
)


def is_overlay_package(package_name: str) -> bool:
    pkg = (package_name or "").strip()
    if not pkg:
        return False
    if pkg in OVERLAY_PACKAGES:
        return True
    return any(pkg.startswith(prefix) for prefix in _OVERLAY_PREFIXES)


def packages_from_elements(elements: Iterable[Any] | None) -> tuple[str, ...]:
    found: list[str] = []
    seen: set[str] = set()
    for el in elements or ():
        if not isinstance(el, dict):
            continue
        pkg = str(el.get("package") or "").strip()
        if pkg and pkg not in seen:
            seen.add(pkg)
            found.append(pkg)
    return tuple(found)


def belongs_to_target(
    current_packages: Iterable[str],
    target_package: str,
) -> bool:
    """当前页包名是否仍属于目标应用任务（含叠加层）。"""
    target = (target_package or "").strip()
    pkgs = [str(p).strip() for p in (current_packages or ()) if str(p).strip()]
    if not target or not pkgs:
        return True
    if target in pkgs:
        return True
    return all(is_overlay_package(pkg) or pkg == target for pkg in pkgs)


def task_ownership_note(
    current_packages: Iterable[str],
    target_package: str,
) -> str:
    if belongs_to_target(current_packages, target_package):
        pkgs = [str(p).strip() for p in (current_packages or ()) if str(p).strip()]
        target = (target_package or "").strip()
        if target and pkgs and target not in pkgs and any(is_overlay_package(p) for p in pkgs):
            return "当前前台是系统叠加层（权限/搜索等），仍视为目标应用任务，不要重新启动 App"
        return ""
    shown = ", ".join(str(p).strip() for p in (current_packages or ()) if str(p).strip())
    return f"当前页包名与目标应用不一致（{shown}），先确认是否误入其它 App"
