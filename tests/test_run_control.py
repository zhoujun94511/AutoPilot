"""执行流控：协作式停止与暂停。"""

from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import autopilot.keywords  # noqa: F401
from autopilot.engine import FaultStrategy
from autopilot.engine.executor import Executor
from autopilot.engine.run_control import RunControl, checkpoint
from autopilot.keywords.context import ExecutionContext
from autopilot.model.testcase import TestCase, Step, ParamValue


def _case(n: int = 3) -> TestCase:
    tc = TestCase(name="c")
    tc.case.steps = [Step("log", params=[ParamValue("message", f"s{i}")]) for i in range(n)]
    return tc


def test_checkpoint_cancel_immediate() -> None:
    cancel = threading.Event()
    cancel.set()
    assert checkpoint(cancel, None) is True


def test_checkpoint_pause_blocks_until_resume() -> None:
    pause = threading.Event()
    pause.set()
    done = threading.Event()

    def _run() -> None:
        assert checkpoint(None, pause) is False
        done.set()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    time.sleep(0.1)
    assert not done.is_set()
    pause.clear()
    t.join(2.0)
    assert done.is_set()


def test_run_control_stop_clears_pause() -> None:
    ctrl = RunControl()
    ctrl.request_pause()
    ctrl.request_stop()
    assert ctrl.is_paused is False
    assert ctrl.is_cancelled is True


def test_executor_respects_pause_event() -> None:
    pause = threading.Event()
    pause.set()
    done = threading.Event()

    def _run() -> None:
        Executor(ExecutionContext(), FaultStrategy.CONTINUE,
                 pause_event=pause).run_testcase(_case(2))
        done.set()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    time.sleep(0.1)
    assert not done.is_set()
    pause.clear()
    t.join(2.0)
    assert done.is_set()


def test_pause_action_registered() -> None:
    from autopilot.ui.actions import ACTIONS_BY_ID

    spec = ACTIONS_BY_ID["run.pause"]
    assert spec.checkable is True
    assert spec.slot == "toggle_pause_run"
    assert ACTIONS_BY_ID["run.case"].shortcut == "F5"
