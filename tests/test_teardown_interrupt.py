"""停止后精简清理、长步骤中断。"""

from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import autopilot.keywords  # noqa: F401
from autopilot.engine import FaultStrategy
from autopilot.engine.executor import Executor
from autopilot.engine.interrupt import bind_run_control, flow_checkpoint
from autopilot.engine.teardown import is_teardown_keyword, iter_teardown_steps
from autopilot.keywords.context import ExecutionContext
from autopilot.model.testcase import Step, ParamValue, TestCase


def _case_with_after(*keyword_ids: str) -> TestCase:
    tc = TestCase(name="t")
    tc.case.steps = [Step("log", params=[ParamValue("message", "main")])]
    tc.after.steps = [Step(kw) for kw in keyword_ids]
    return tc


def test_teardown_whitelist() -> None:
    assert is_teardown_keyword("mobile_app_close")
    assert is_teardown_keyword("appium_stop")
    assert not is_teardown_keyword("log")
    assert not is_teardown_keyword("mobile_monkey")


def test_iter_teardown_steps_filters() -> None:
    tc = _case_with_after("mobile_app_close", "log", "appium_stop")
    steps = iter_teardown_steps(tc.after.steps)
    assert [s.keyword_id for s in steps] == ["mobile_app_close", "appium_stop"]


def test_cancel_runs_teardown_only() -> None:
    cancel = threading.Event()
    cancel.set()
    tc = _case_with_after("log", "appium_stop")  # log 不在白名单；appium_stop 无会话时可能 FAIL
    ctx = ExecutionContext()
    bind_run_control(ctx, cancel, None)
    res = Executor(ctx, FaultStrategy.CONTINUE, cancel_event=cancel).run_testcase(tc)
    ids = [r.keyword_id for r in res.results]
    assert ids.count("log") == 0
    assert "_teardown" in ids
    assert "appium_stop" in ids


def test_ios_monkey_cancelled_by_event() -> None:
    from autopilot.mobile.ios.monkey.engine import IOSMonkeyEngine
    from autopilot.mobile.ios.monkey.policy import MonkeyConfig
    from tests.test_ios_monkey import _FakeMonkeyDriver

    cancel = threading.Event()
    ctx = ExecutionContext()
    bind_run_control(ctx, cancel, None)
    ctx.set_var("__ios_alert_enabled__", False)
    cfg = MonkeyConfig(
        bundle_id="com.test.app", max_events=100, throttle_ms=0,
        seed=1, weights={"swipe_random": 100},
    )
    drv = _FakeMonkeyDriver()

    def _run():
        return IOSMonkeyEngine(ctx, drv, cfg).run()

    import threading as th
    t = th.Thread(target=_run)
    t.start()
    time.sleep(0.05)
    cancel.set()
    t.join(3)
    assert not t.is_alive()
    assert drv.swipes >= 1


def test_flow_checkpoint_blocks_pause() -> None:
    pause = threading.Event()
    pause.set()
    ctx = ExecutionContext()
    bind_run_control(ctx, None, pause)
    done = threading.Event()

    def _run():
        assert not flow_checkpoint(ctx)
        done.set()

    import threading as th
    t = th.Thread(target=_run, daemon=True)
    t.start()
    time.sleep(0.1)
    assert not done.is_set()
    pause.clear()
    t.join(2)
    assert done.is_set()


def test_run_interrupted_is_not_fail() -> None:
    from autopilot.engine.executor import RunResult, StepResult
    rr = RunResult(case_name="x")
    rr.results.append(StepResult("mobile_monkey", "", "CANCEL", "用户停止"))
    assert rr.passed is True
