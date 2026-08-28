"""设备判空/容错集中化静态审计（无 Qt 运行时依赖）。

防止检视/镜像/运行入口回退到手写 `_devices[0]`、内嵌平台分支等零散逻辑。

用法：
    .venv/bin/python skills/autopilot-lint/check_device_readiness.py
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Violation:
    rule: str
    path: str
    detail: str

    def format(self) -> str:
        return f"[{self.rule}] {self.path} — {self.detail}"


_REQUIRED_SYMBOLS = (
    "DeviceLists",
    "validate_inspect_target",
    "validate_mobile_target",
    "auto_run_udid",
    "missing_runtime_platforms",
    "choose_device_runtime",
)


def audit_device_readiness(project_root: str) -> list[Violation]:
    ui = os.path.join(project_root, "autopilot", "ui")
    violations: list[Violation] = []

    def read(rel: str) -> str:
        path = os.path.join(ui, rel)
        if not os.path.isfile(path):
            violations.append(Violation("missing_file", rel, "文件不存在"))
            return ""
        with open(path, encoding="utf-8") as f:
            return f.read()

    dr = read("main_window/device_readiness.py")
    ds = read("main_window/device_select.py")
    device = read("main_window/device.py")
    run = read("main_window/run.py")
    window = read("main_window/window.py")
    insp = read("widgets/inspector_panel.py")
    mir = read("widgets/mirror_panel.py")

    for sym in _REQUIRED_SYMBOLS:
        if sym in ("choose_device_runtime",):
            if f"def {sym}" not in ds:
                violations.append(Violation(
                    "device_select_symbol", "main_window/device_select.py",
                    f"须导出 {sym}",
                ))
        elif sym == "DeviceLists":
            if "class DeviceLists" not in dr:
                violations.append(Violation(
                    "device_readiness_symbol", "main_window/device_readiness.py",
                    "须导出 DeviceLists",
                ))
        elif f"def {sym}" not in dr:
            violations.append(Violation(
                "device_readiness_symbol", "main_window/device_readiness.py",
                f"须导出 {sym}",
            ))

    if "device_readiness" not in device:
        violations.append(Violation(
            "device_mixin_import", "main_window/device.py",
            "DeviceMixin 须通过 device_readiness 做判空/校验",
        ))
    if "_device_lists" not in device:
        violations.append(Violation(
            "device_mixin_lists", "main_window/device.py",
            "须实现 _device_lists() 统一读取 _devices",
        ))
    if "choose_device_runtime" not in device and "_ask_device_pick_runtime" not in device:
        violations.append(Violation(
            "device_mixin_pick", "main_window/device.py",
            "跨平台设备弹选须走 choose_device_runtime",
        ))

    if "device_readiness" not in run:
        violations.append(Violation(
            "run_mixin_import", "main_window/run.py",
            "RunMixin 运行设备逻辑须用 device_readiness",
        ))
    if "auto_run_udid" not in run:
        violations.append(Violation(
            "run_auto_udid", "main_window/run.py",
            "_run_base_vars 须用 auto_run_udid",
        ))
    if 'android if plat == "android" else ios' in run:
        violations.append(Violation(
            "run_inline_platform_branch",
            "main_window/run.py",
            "禁止手写 android/ios 分支取设备列表，改用 DeviceLists.for_platform",
        ))

    if "before_refresh" not in window or "_ensure_inspect_device" not in window:
        violations.append(Violation(
            "inspector_before_refresh", "main_window/window.py",
            "检视器须注入 before_refresh → _ensure_inspect_device",
        ))
    if "before_start" not in window or "_prepare_mirror_start" not in window:
        violations.append(Violation(
            "mirror_before_start", "main_window/window.py",
            "镜像须注入 before_start → _prepare_mirror_start",
        ))

    if "before_refresh" not in insp or "_abort_refresh_precheck" not in insp:
        violations.append(Violation(
            "inspector_panel_guard", "widgets/inspector_panel.py",
            "InspectorPanel 须在 before_refresh 失败时 _abort_refresh_precheck",
        ))
    if "before_start" not in mir or "set_mobile_available" not in mir:
        violations.append(Violation(
            "mirror_panel_guard", "widgets/mirror_panel.py",
            "MirrorPanel 须有 before_start 与 set_mobile_available",
        ))

    if "_commit_mobile_target" not in device:
        violations.append(Violation(
            "device_commit_target", "main_window/device.py",
            "镜像/检视选设备后须经 _commit_mobile_target 统一提交",
        ))
    if "_guard_mobile_session_target" not in device:
        violations.append(Violation(
            "device_session_guard", "main_window/device.py",
            "镜像建会话前须经 _guard_mobile_session_target 二次校验",
        ))
    if "if not self._guard_mobile_session_target" not in device:
        violations.append(Violation(
            "mirror_session_guard", "main_window/device.py",
            "镜像/检视建会话须调用 _guard_mobile_session_target",
        ))

    for fn, label in (
        ("run_selected_step", "单步调试"),
        ("run_to_selected_step", "运行至此"),
    ):
        if f"def {fn}" in run:
            body_start = run.find(f"def {fn}")
            body_end = run.find("\n    def ", body_start + 1)
            chunk = run[body_start:body_end if body_end > 0 else len(run)]
            if "_platform_guard" not in chunk:
                violations.append(Violation(
                    "run_debug_guard", "main_window/run.py",
                    f"{label}（{fn}）须调用 _platform_guard",
                ))

    if "_run_base_vars" in run and "当前未连接" not in run:
        violations.append(Violation(
            "run_base_vars_hard_block", "main_window/run.py",
            "_run_base_vars 须在所需平台无设备时硬阻断",
        ))

    if '仍要执行' in run and "平台不匹配" in run:
        violations.append(Violation(
            "run_platform_force", "main_window/run.py",
            "无匹配设备时不应提供「仍要执行」绕过",
        ))

    return violations


def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    violations = audit_device_readiness(root)
    if violations:
        print(f"设备容错审计：{len(violations)} 处违规")
        for v in violations:
            print(" ", v.format())
        return 1
    print("设备容错审计：通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
