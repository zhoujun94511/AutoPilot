"""被测 App 前台监视：意外退出才记崩溃。"""

from __future__ import annotations

from autopilot.engine.app_watch import (
    detect_crash_on_fail,
    expected_package,
    remember_target_package,
    unexpected_exit,
)
from autopilot.engine.executor import Executor, StepResult
from autopilot.keywords.context import ExecutionContext


def test_unexpected_exit_only_when_foreground_is_launcher():
    assert unexpected_exit("com.demo.app", "com.android.launcher3")
    assert unexpected_exit("com.demo.app", "com.apple.springboard")
    assert not unexpected_exit("com.demo.app", "com.demo.app")
    assert not unexpected_exit("com.demo.app", "com.other.app")
    assert not unexpected_exit("", "com.android.launcher3")
    assert not unexpected_exit("com.demo.app", "")


def test_detect_crash_from_message_hint():
    ctx = ExecutionContext()
    remember_target_package(ctx, "com.demo.app")
    assert expected_package(ctx) == "com.demo.app"
    assert detect_crash_on_fail(ctx, "app crashed: process died") == "com.demo.app"


def test_detect_crash_without_target_uses_unknown():
    ctx = ExecutionContext()
    assert detect_crash_on_fail(ctx, "Fatal exception in main") == "unknown"


def test_enrich_crash_overrides_locator():
    ctx = ExecutionContext()
    remember_target_package(ctx, "com.demo.app")
    ex = Executor(ctx)
    sr = StepResult(
        "mobile_element_click",
        "点按钮",
        "FAIL",
        "app crashed: process died",
        fail_class="locator",
        fail_reason="element_not_found",
    )
    ex._enrich_step_result(sr)
    assert sr.fail_reason == "app_crash"
    assert sr.attribution == "product_bug"
    assert "目标应用已离开前台" in sr.message
    assert sr.fail_class == "other"
