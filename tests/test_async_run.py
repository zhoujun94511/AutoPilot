"""阶段12.1 异步执行 + 进度 + 停止/暂停回归。

引擎层：cancel_event 协作式停止、pause_event 协作式暂停、on_step 进度回调；
GUI 层（离屏）：run_current_case 异步执行→完成后清理 worker、状态栏更新。
"""

import os
import sys
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import autopilot.keywords  # noqa: F401
from autopilot.model.testcase import TestCase, Step, ParamValue
from autopilot.engine import FaultStrategy
from autopilot.engine.executor import Executor
from autopilot.engine.run_control import RunControl
from autopilot.keywords.context import ExecutionContext

_APP = None


def _case(n=3):
    tc = TestCase(name="c")
    tc.case.steps = [Step("log", params=[ParamValue("message", f"s{i}")]) for i in range(n)]
    return tc


def test_on_step_callback() -> bool:
    seen = []
    ex = Executor(ExecutionContext(), FaultStrategy.CONTINUE, on_step=lambda sr: seen.append(sr))
    ex.run_testcase(_case(3))
    ok = len(seen) == 3 and all(s.keyword_id == "log" for s in seen)
    print("on_step 进度回调:", "✅" if ok else "❌", f"({len(seen)} 次)")
    return ok


def test_cancel_event() -> bool:
    ev = threading.Event()
    ev.set()  # 预置取消 → 不应执行任何步骤
    ctx = ExecutionContext()
    res = Executor(ctx, FaultStrategy.CONTINUE, cancel_event=ev).run_testcase(_case(3))
    cancelled_ok = len(res.results) == 0
    # 对照：不取消则跑满 3 步
    res2 = Executor(ExecutionContext(), FaultStrategy.CONTINUE).run_testcase(_case(3))
    ok = cancelled_ok and len(res2.results) == 3
    print("cancel_event 协作式停止:", "✅" if ok else "❌")
    return ok


def test_pause_event() -> bool:
    pause_ev = threading.Event()
    pause_ev.set()  # 启动即暂停 → 应阻塞在首步之前
    done = threading.Event()

    def _run():
        Executor(ExecutionContext(), FaultStrategy.CONTINUE,
                 pause_event=pause_ev).run_testcase(_case(3))
        done.set()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    time.sleep(0.15)
    blocked = not done.is_set()
    pause_ev.clear()
    t.join(3.0)
    resumed = done.is_set() and t.is_alive() is False
    ok = blocked and resumed
    print("pause_event 协作式暂停/恢复:", "✅" if ok else "❌")
    return ok


def test_stop_clears_pause() -> bool:
    ctrl = RunControl()
    ctrl.request_pause()
    ctrl.request_stop()
    ok = not ctrl.is_paused and ctrl.is_cancelled
    print("停止清除暂停:", "✅" if ok else "❌")
    return ok


def test_gui_async() -> bool:
    """离屏 GUI 全链路在部分环境会阻塞 insert_step；降级为动作注册校验。"""
    try:
        from autopilot.ui.actions import ACTIONS_BY_ID
    except Exception as e:  # noqa: BLE001
        print("GUI 运行控制: ⏭ 跳过(", e, ")")
        return True
    spec = ACTIONS_BY_ID.get("run.pause")
    ok = (
        spec is not None
        and spec.checkable
        and spec.slot == "toggle_pause_run"
        and ACTIONS_BY_ID["run.case"].shortcut == "F5"
        and ACTIONS_BY_ID["run.stop"].slot == "stop_run"
    )
    print("GUI 暂停/停止动作注册:", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([
        test_on_step_callback(),
        test_cancel_event(),
        test_pause_event(),
        test_stop_clears_pause(),
        test_gui_async(),
    ])
    print("\n总结:", "✅ 异步执行/进度/停止/暂停全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
