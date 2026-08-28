"""fault_times 用例级失败重试 + 测试计划展开。"""

from __future__ import annotations

import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import autopilot.keywords  # noqa: F401
from autopilot.engine import FaultStrategy, run_cases, expand_testplan_members, run_testplan
from autopilot.keywords.registry import keyword, KeywordError
from autopilot.model.testcase import TestCase, Step, ParamValue
from autopilot.model.testplan import TestPlan
from autopilot.model import serializer


_COUNTER = {"n": 0}


@keyword("_test_flaky_pass", name="测试用偶发通过", category="Public")
def _test_flaky_pass(_ctx, fail_times="1", **_kw):
    """前 fail_times 次抛错，之后通过。"""
    n = int(str(fail_times).strip() or "1")
    _COUNTER["n"] += 1
    if _COUNTER["n"] <= n:
        raise KeywordError(f"flaky fail #{_COUNTER['n']}")


@keyword("_test_always_fail", name="测试用恒失败", category="Public")
def _test_always_fail(_ctx, **_kw):
    _COUNTER["n"] += 1
    raise KeywordError("always fail")


def _case_with(kid: str, **params) -> TestCase:
    tc = TestCase(name=kid)
    tc.case.steps = [Step(kid, params=[ParamValue(k, str(v)) for k, v in params.items()])]
    return tc


def test_fault_times_zero() -> bool:
    _COUNTER["n"] = 0
    tc = _case_with("_test_always_fail")
    res = run_cases([tc], fault_times=0, fault_strategy=FaultStrategy.CONTINUE)
    ok = (not res.results[0].passed) and _COUNTER["n"] == 1
    print("fault_times=0 只跑一次:", "✅" if ok else "❌", _COUNTER["n"])
    return ok


def test_fault_times_retry_then_pass() -> bool:
    _COUNTER["n"] = 0
    tc = _case_with("_test_flaky_pass", fail_times="1")
    res = run_cases([tc], fault_times=1, fault_strategy=FaultStrategy.CONTINUE)
    ok = res.results[0].passed and _COUNTER["n"] == 2
    print("失败后重试成功:", "✅" if ok else "❌", _COUNTER["n"], res.results[0].passed)
    return ok


def test_fault_times_exhaust() -> bool:
    _COUNTER["n"] = 0
    tc = _case_with("_test_always_fail")
    res = run_cases([tc], fault_times=2, fault_strategy=FaultStrategy.CONTINUE)
    ok = (not res.results[0].passed) and _COUNTER["n"] == 3
    print("用尽重试仍失败:", "✅" if ok else "❌", _COUNTER["n"])
    return ok


def test_fault_times_cancel() -> bool:
    _COUNTER["n"] = 0
    ev = threading.Event()

    def on_case(_rr):
        pass

    tc = _case_with("_test_always_fail")
    # 第一次跑完后置取消：用 on_step 在首次失败后 set
    calls = {"n": 0}

    def on_step(sr):
        calls["n"] += 1
        if sr.status == "FAIL":
            ev.set()

    res = run_cases([tc], fault_times=5, fault_strategy=FaultStrategy.CONTINUE,
                    cancel_event=ev, on_step=on_step, on_case=on_case)
    # 首次 FAIL 后 cancel，不应再重试到 6 次
    ok = _COUNTER["n"] == 1 and len(res.results) == 1
    print("取消后不再重试:", "✅" if ok else "❌", _COUNTER["n"])
    return ok


def test_expand_and_run_testplan() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        tc = TestCase(name="t1")
        tc.case.steps = [Step("log", params=[ParamValue("message", "hi")])]
        path = os.path.join(tmp, "t1.tc.yaml")
        serializer.save_testcase(tc, path)
        tp = TestPlan(name="plan", fault_times=0, members=["t1.tc.yaml"], source_path=os.path.join(tmp, "p.tp.yaml"))
        cases = expand_testplan_members(tp, tmp)
        ok_exp = len(cases) == 1 and cases[0].name == "t1"
        suite = run_testplan(tp, tmp, fault_strategy=FaultStrategy.CONTINUE)
        ok_run = suite.case_counts()["passed"] == 1
    ok = ok_exp and ok_run
    print("测试计划展开+执行:", "✅" if ok else "❌", ok_exp, ok_run)
    return ok


def main() -> int:
    ok = all([
        test_fault_times_zero(),
        test_fault_times_retry_then_pass(),
        test_fault_times_exhaust(),
        test_fault_times_cancel(),
        test_expand_and_run_testplan(),
    ])
    print("\n总结:", "✅" if ok else "❌")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
