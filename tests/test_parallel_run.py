"""多机并行执行白盒：引擎每台全量复跑/停止合并/故障隔离 + UI 对话框/解析/报告元数据。"""

from __future__ import annotations

import os
import sys
import threading
import time
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from autopilot.engine.run import run_suite
from autopilot.engine.run.config import RunConfig
from autopilot.engine.run.parallel import run_parallel_device
from autopilot.engine.executor import RunResult, StepResult
from autopilot.engine.suite import SuiteResult
from autopilot.model.testcase import TestCase
from autopilot.runtime.device_pool import build_sessions
from autopilot.runtime.device_session import DeviceSession

_APP = None


def _app():
    global _APP
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _fail_result(name: str, udid: str = "") -> RunResult:
    return RunResult(
        case_name=name,
        device_udid=udid,
        results=[StepResult(keyword_id="x", comment="", status="FAIL", message="boom")],
    )


def _pass_result(name: str, udid: str = "") -> RunResult:
    return RunResult(
        case_name=name,
        device_udid=udid,
        results=[StepResult(keyword_id="x", comment="", status="PASS")],
    )


# ---- 引擎 ----

def test_parallel_invokes_shards() -> bool:
    """每台设备完整跑全部用例：4 条 × 2 台 = 8 次结果。"""
    calls: list[str] = []

    def fake_run_cases(_testcases, name="Suite", **_kwargs):
        udid = (_kwargs.get("base_vars") or {}).get("__device_udid__", "")
        calls.append(f"{name}:{udid}:{len(_testcases)}")
        return SuiteResult(
            name=name,
            results=[_pass_result(tc.name, udid) for tc in _testcases],
        )

    cases = [TestCase(name=f"t{i}") for i in range(4)]
    with patch("autopilot.engine.run.parallel.run_cases", fake_run_cases):
        suite = run_suite(
            cases,
            name="P",
            mode="parallel_device",
            platform="android",
            device_udids=["D0", "D1"],
            parallel_workers=2,
        )
    ok = (len(calls) == 2
          and all(c.endswith(":4") for c in calls)
          and len(suite.results) == 8
          and {r.device_udid for r in suite.results} == {"D0", "D1"})
    print("parallel 每台全量:", "✅" if ok else "❌", calls, len(suite.results))
    return ok


def test_sequential_default() -> bool:
    cases = [TestCase(name="one")]
    with patch("autopilot.engine.run.sequential.run_cases") as m:
        m.return_value = SuiteResult(name="S", results=[])
        run_suite(cases, mode="sequential")
        ok = m.called
    print("sequential:", "✅" if ok else "❌")
    return ok


def test_parallel_requires_udids() -> bool:
    try:
        run_suite([TestCase(name="t")], mode="parallel_device", platform="android")
        ok = False
    except RuntimeError as e:
        ok = "device_udids" in str(e)
    print("parallel 缺 udids:", "✅" if ok else "❌")
    return ok


def test_parallel_pops_single_udid_from_base() -> bool:
    """并行时 base 里的单机 __device_udid__ 不得覆盖各 shard 注入。"""
    seen: list[str] = []

    def fake_run_cases(_testcases, name="Suite", **_kwargs):
        udid = (_kwargs.get("base_vars") or {}).get("__device_udid__", "")
        seen.append(udid)
        return SuiteResult(name=name, results=[_pass_result(tc.name, udid) for tc in _testcases])

    with patch("autopilot.engine.run.parallel.run_cases", fake_run_cases):
        run_suite(
            [TestCase(name="a"), TestCase(name="b")],
            mode="parallel_device",
            platform="android",
            device_udids=["X", "Y"],
            base_vars={"__device_udid__": "SHOULD_NOT_WIN"},
        )
    ok = set(seen) == {"X", "Y"}
    print("并行覆盖单机 udid:", "✅" if ok else "❌", seen)
    return ok


def test_parallel_worker_drops_sibling_udid_list() -> bool:
    """并行 worker 收尾不得带着兄弟设备的 UDID 列表。"""
    seen: list[dict] = []

    def fake_run_cases(_testcases, name="Suite", **_kwargs):
        seen.append(dict(_kwargs.get("base_vars") or {}))
        return SuiteResult(name=name, results=[])

    with patch("autopilot.engine.run.parallel.run_cases", fake_run_cases):
        run_suite(
            [TestCase(name="a")],
            mode="parallel_device",
            platform="android",
            device_udids=["X", "Y"],
            parallel_workers=2,
        )
    ok = bool(seen) and all(
        "__parallel_device_udids__" not in v and v.get("__device_udid__") in {"X", "Y"}
        for v in seen
    )
    print("worker 去掉兄弟 UDID 列表:", "✅" if ok else "❌")
    return ok


def test_cancel_merges_completed_shards() -> bool:
    """停止后 drain：FAST 必进报告；SLOW 在超时内完成也应进报告。"""
    cancel = threading.Event()
    started = threading.Event()
    release_slow = threading.Event()

    def fake_run_cases(_testcases, name="Suite", **_kwargs):
        udid = (_kwargs.get("base_vars") or {}).get("__device_udid__", "")
        if udid == "FAST":
            started.set()
            return SuiteResult(
                name=name,
                results=[_pass_result(tc.name, udid) for tc in _testcases],
            )
        started.wait(timeout=2)
        cancel.set()
        release_slow.wait(timeout=5)
        return SuiteResult(
            name=name,
            results=[_pass_result(tc.name, udid) for tc in _testcases],
        )

    sessions = [
        DeviceSession.from_slot("android", "FAST", slot=0),
        DeviceSession.from_slot("android", "SLOW", slot=1),
    ]
    cases = [TestCase(name="c0"), TestCase(name="c1")]
    cfg = RunConfig(
        name="C",
        mode="parallel_device",
        device_sessions=sessions,
        cancel_event=cancel,
        base_vars={},
        parallel_stop_drain_sec=5.0,
    )
    with patch("autopilot.engine.run.parallel.run_cases", fake_run_cases):
        out: list[SuiteResult] = []

        def _run():
            out.append(run_parallel_device(cases, cfg))

        t = threading.Thread(target=_run)
        t.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not cancel.is_set():
            time.sleep(0.02)
        release_slow.set()
        t.join(timeout=10)
    suite = out[0] if out else None
    udids = {r.device_udid for r in (suite.results if suite else [])}
    ok = (suite is not None
          and "FAST" in udids
          and "SLOW" in udids
          and len(suite.results) >= 4)
    print("停止 drain 合并两机:", "✅" if ok else "❌",
          [r.device_udid for r in (suite.results if suite else [])])
    return ok


def test_worker_exception_becomes_fail() -> bool:
    """Worker 抛异常 → 合成带 device_udid 的 FAIL，不静默消失。"""

    def fake_run_cases(_testcases, name="Suite", **_kwargs):
        udid = (_kwargs.get("base_vars") or {}).get("__device_udid__", "")
        if udid == "BOOM":
            raise RuntimeError("boom-slot")
        return SuiteResult(
            name=name,
            results=[_pass_result(tc.name, udid) for tc in _testcases],
        )

    sessions = [
        DeviceSession.from_slot("android", "BOOM", slot=0),
        DeviceSession.from_slot("android", "OK", slot=1),
    ]
    cfg = RunConfig(
        name="E",
        device_sessions=sessions,
        cancel_event=threading.Event(),
        parallel_fault_isolation=True,
    )
    with patch("autopilot.engine.run.parallel.run_cases", fake_run_cases):
        suite = run_parallel_device([TestCase(name="a")], cfg)
    boom = [r for r in suite.results if r.device_udid == "BOOM"]
    ok_dev = [r for r in suite.results if r.device_udid == "OK"]
    ok = (len(boom) >= 1 and not boom[0].passed
          and "boom-slot" in (boom[0].results[0].message or "")
          and len(ok_dev) >= 1 and ok_dev[0].passed)
    print("Worker 异常合成 FAIL:", "✅" if ok else "❌",
          [(r.device_udid, r.passed) for r in suite.results])
    return ok


def test_parallel_deepcopy_base_vars() -> bool:
    """各 worker deepcopy base_vars，嵌套 dict 互不污染。"""
    shared = {"nest": {"k": "v0"}}
    seen: list[str] = []

    def fake_run_cases(_testcases, name="Suite", **_kwargs):
        bv = _kwargs.get("base_vars") or {}
        nest = bv.get("nest")
        udid = bv.get("__device_udid__", "")
        if isinstance(nest, dict):
            nest["k"] = udid
            seen.append(nest["k"])
        return SuiteResult(name=name, results=[_pass_result("t", udid)])

    sessions = [
        DeviceSession.from_slot("android", "A", slot=0),
        DeviceSession.from_slot("android", "B", slot=1),
    ]
    cfg = RunConfig(
        name="D",
        device_sessions=sessions,
        base_vars=shared,
    )
    with patch("autopilot.engine.run.parallel.run_cases", fake_run_cases):
        run_parallel_device([TestCase(name="t")], cfg)
    # 外层 shared 未被改写；两机各自看到自己的值
    ok = (shared["nest"]["k"] == "v0"
          and set(seen) == {"A", "B"})
    print("base_vars deepcopy:", "✅" if ok else "❌", shared, seen)
    return ok


def test_fault_isolation_default_continues() -> bool:
    """默认隔离：一分片失败不置 cancel，其它分片仍跑完。"""
    cancel = threading.Event()
    calls: list[str] = []

    def fake_run_cases(_testcases, name="Suite", **_kwargs):
        udid = (_kwargs.get("base_vars") or {}).get("__device_udid__", "")
        calls.append(udid)
        if udid == "BAD":
            return SuiteResult(name=name, results=[_fail_result(tc.name, udid) for tc in _testcases])
        time.sleep(0.05)
        return SuiteResult(name=name, results=[_pass_result(tc.name, udid) for tc in _testcases])

    sessions = [
        DeviceSession.from_slot("android", "BAD", slot=0),
        DeviceSession.from_slot("android", "OK", slot=1),
    ]
    cfg = RunConfig(
        name="I",
        device_sessions=sessions,
        cancel_event=cancel,
        parallel_fault_isolation=True,
    )
    with patch("autopilot.engine.run.parallel.run_cases", fake_run_cases):
        suite = run_parallel_device(
            [TestCase(name="a"), TestCase(name="b")], cfg)
    ok = (not cancel.is_set()
          and set(calls) == {"BAD", "OK"}
          and suite.case_counts()["failed"] >= 1
          and suite.case_counts()["passed"] >= 1)
    print("故障隔离(默认继续):", "✅" if ok else "❌", calls, suite.case_counts())
    return ok


def test_fault_isolation_off_cancels_others() -> bool:
    """非隔离：一分片失败 → 置 cancel。"""
    cancel = threading.Event()

    def fake_run_cases(_testcases, name="Suite", **_kwargs):
        udid = (_kwargs.get("base_vars") or {}).get("__device_udid__", "")
        if udid == "BAD":
            return SuiteResult(name=name, results=[_fail_result(tc.name, udid) for tc in _testcases])
        # 其它分片：若已被 cancel 应尽快返回（协作式）
        for _ in range(50):
            if cancel.is_set():
                break
            time.sleep(0.02)
        return SuiteResult(name=name, results=[_pass_result(tc.name, udid) for tc in _testcases])

    sessions = [
        DeviceSession.from_slot("android", "BAD", slot=0),
        DeviceSession.from_slot("android", "OK", slot=1),
    ]
    cfg = RunConfig(
        name="K",
        device_sessions=sessions,
        cancel_event=cancel,
        parallel_fault_isolation=False,
    )
    with patch("autopilot.engine.run.parallel.run_cases", fake_run_cases):
        run_parallel_device([TestCase(name="a"), TestCase(name="b")], cfg)
    ok = cancel.is_set()
    print("非隔离失败即停其它:", "✅" if ok else "❌")
    return ok


def test_build_sessions_empty_raises() -> bool:
    try:
        build_sessions("android", [])
        ok = False
    except RuntimeError:
        ok = True
    print("空设备 build_sessions:", "✅" if ok else "❌")
    return ok


def test_shard_empty_worker_skipped() -> bool:
    """1 条用例 × 3 台设备：每台都跑这一条（复跑，不是空 shard 跳过）。"""
    calls: list[int] = []

    def fake_run_cases(_testcases, name="Suite", **_kwargs):
        calls.append(len(_testcases))
        return SuiteResult(name=name, results=[_pass_result(tc.name) for tc in _testcases])

    with patch("autopilot.engine.run.parallel.run_cases", fake_run_cases):
        suite = run_suite(
            [TestCase(name="only")],
            mode="parallel_device",
            platform="android",
            device_udids=["A", "B", "C"],
            parallel_workers=3,
        )
    ok = len(calls) == 3 and calls == [1, 1, 1] and len(suite.results) == 3
    print("单用例多机复跑:", "✅" if ok else "❌", calls)
    return ok


# ---- UI ----

def test_ask_parallel_lt2_devices() -> bool:
    from autopilot.ui.parallel_run_dialog import ask_parallel_run
    _app()
    got = ask_parallel_run(None, "android", 1, case_count=5)
    ok = got == (False, 0, True)
    print("设备<2 不弹窗:", "✅" if ok else "❌", got)
    return ok


def test_ask_parallel_single_case_ok() -> bool:
    """单用例 + 多设备仍可并行（每台各跑这一条）。"""
    from PyQt6.QtWidgets import QDialog
    from autopilot.ui.parallel_run_dialog import ask_parallel_run
    _app()
    with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Accepted):
        got = ask_parallel_run(None, "ios", 2, case_count=1)
    ok = got == (True, 2, True)
    print("单用例可并行弹窗:", "✅" if ok else "❌", got)
    return ok


def test_ask_parallel_cancel() -> bool:
    from PyQt6.QtWidgets import QDialog
    from autopilot.ui.parallel_run_dialog import ask_parallel_run
    _app()
    with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Rejected):
        got = ask_parallel_run(None, "android", 3, case_count=3)
    ok = got is None
    print("并行对话框取消:", "✅" if ok else "❌")
    return ok


def test_ask_parallel_ok_unchecked() -> bool:
    from PyQt6.QtWidgets import QDialog, QCheckBox
    from autopilot.ui.parallel_run_dialog import ask_parallel_run
    _app()

    def _exec(self):
        for w in self.findChildren(QCheckBox):
            # 只关「并行执行」主勾选；隔离勾选可保持
            if "并行执行" in (w.text() or ""):
                w.setChecked(False)
        return QDialog.DialogCode.Accepted

    with patch.object(QDialog, "exec", _exec):
        got = ask_parallel_run(None, "ios", 2, case_count=2)
    ok = got == (False, 0, True)
    print("不勾选并行→串行:", "✅" if ok else "❌", got)
    return ok


def test_ask_parallel_isolate_and_android_hint() -> bool:
    """确认并行时返回 isolate；Android 对话框含 4723 提示。"""
    from PyQt6.QtWidgets import QDialog, QCheckBox, QLabel
    from autopilot.ui.parallel_run_dialog import ask_parallel_run
    _app()
    seen = {"hint": False}

    def _exec(self):
        texts = " ".join(w.text() or "" for w in self.findChildren(QLabel))
        seen["hint"] = "4723" in texts
        for w in self.findChildren(QCheckBox):
            if "失败隔离" in (w.text() or ""):
                w.setChecked(False)
        return QDialog.DialogCode.Accepted

    with patch.object(QDialog, "exec", _exec):
        got = ask_parallel_run(None, "android", 2, case_count=2)
    ok = got == (True, 2, False) and seen["hint"] is True
    print("隔离勾选+Android提示:", "✅" if ok else "❌", got, seen)
    return ok


def test_resolve_parallel_cancel() -> bool:
    import tempfile
    from autopilot.ui.main_window import MainWindow
    from autopilot.model.testcase import TestCase
    _app()
    with tempfile.TemporaryDirectory() as tmp:
        win = MainWindow(project_dir=tmp, config_dir="")
        win._devices = (["d1", "d2"], [])
        cases = [TestCase(name="a"), TestCase(name="b")]
        with patch.object(win, "_target_platforms", return_value={"android"}), \
                patch("autopilot.ui.parallel_run_dialog.ask_parallel_run", return_value=None):
            got = win._resolve_parallel_run(cases)
        ok = got is None
        win.close()
    print("解析并行取消:", "✅" if ok else "❌")
    return ok


def test_resolve_parallel_confirm() -> bool:
    import tempfile
    from autopilot.ui.main_window import MainWindow
    from autopilot.model.testcase import TestCase
    _app()
    with tempfile.TemporaryDirectory() as tmp:
        win = MainWindow(project_dir=tmp, config_dir="")
        win._devices = (["d1", "d2", "d3"], [])
        cases = [TestCase(name="a"), TestCase(name="b"), TestCase(name="c")]
        with patch.object(win, "_target_platforms", return_value={"android"}), \
                patch("autopilot.ui.parallel_run_dialog.ask_parallel_run",
                      return_value=(True, 2, False)):
            got = win._resolve_parallel_run(cases)
        ok = (got is not None
              and got[0] == "parallel_device"
              and got[1] == "android"
              and got[2] == 2
              and got[3] == ["d1", "d2"]
              and got[4] is False)
        win.close()
    print("解析并行确认:", "✅" if ok else "❌", got)
    return ok


def test_resolve_parallel_single_case_ok() -> bool:
    """单用例多设备仍可进入并行（每台复跑）。"""
    import tempfile
    from autopilot.ui.main_window import MainWindow
    from autopilot.model.testcase import TestCase
    _app()
    with tempfile.TemporaryDirectory() as tmp:
        win = MainWindow(project_dir=tmp, config_dir="")
        win._devices = (["d1", "d2"], [])
        with patch.object(win, "_target_platforms", return_value={"android"}), \
                patch("autopilot.ui.parallel_run_dialog.ask_parallel_run",
                      return_value=(True, 2, True)):
            got = win._resolve_parallel_run([TestCase(name="solo")])
        ok = (got is not None
              and got[0] == "parallel_device"
              and got[2] == 2
              and got[3] == ["d1", "d2"])
        win.close()
    print("单用例可解析并行:", "✅" if ok else "❌", got)
    return ok


def test_f5_disables_parallel_dialog() -> bool:
    """运行当前用例(F5) 传 allow_parallel=False，不走并行解析。"""
    import tempfile
    from autopilot.ui.main_window import MainWindow
    from autopilot.model.testcase import TestCase
    _app()
    with tempfile.TemporaryDirectory() as tmp:
        win = MainWindow(project_dir=tmp, config_dir="")
        win.case_editor.show_case(TestCase(name="solo"))
        seen = {"allow_parallel": None, "resolve": False}

        def _spy_resolve(_cases_arg):
            seen["resolve"] = True
            return "sequential", "", 0, None, True

        def _spy_start(_cases, _name, _maps, _report=False, _keyword_store=None, *,
                       allow_parallel=True, _unattended=False, _fault_times=0):
            seen["allow_parallel"] = allow_parallel
            return True

        win._resolve_parallel_run = _spy_resolve  # type: ignore[method-assign]
        win._platform_guard = lambda cases, **kw: True  # type: ignore[method-assign]
        win._start_worker = _spy_start  # type: ignore[method-assign]
        win.run_current_case()
        ok = seen["allow_parallel"] is False and seen["resolve"] is False
        win.close()
    print("F5 禁并行弹窗:", "✅" if ok else "❌", seen)
    return ok


def test_parallel_skips_device_pick() -> bool:
    """并行拍：_run_base_vars(skip_device_pick=True) 不弹选设备。"""
    import tempfile
    from autopilot.ui.main_window import MainWindow
    _app()
    with tempfile.TemporaryDirectory() as tmp:
        win = MainWindow(project_dir=tmp, config_dir="")
        win._devices = (["a", "b"], [])
        with patch.object(win, "_target_platforms", return_value={"android"}), \
                patch("autopilot.ui.main_window.run.pick_list_item") as dlg:
            got = win._run_base_vars([], skip_device_pick=True)
        ok = got is not None and "__device_udid__" not in got and dlg.call_count == 0
        win.close()
    print("并行跳过选设备:", "✅" if ok else "❌")
    return ok


def test_report_meta_parallel_devices() -> bool:
    """_on_suite_done 报告 meta 含全部并行 UDID。"""
    import tempfile
    from autopilot.ui.main_window import MainWindow
    _app()
    with tempfile.TemporaryDirectory() as tmp:
        win = MainWindow(project_dir=tmp, config_dir="")
        win.create_resource("case", tmp, "c1")
        win._report_on_finish = True
        win._run_started_at = None
        win._run_case_paths = []
        win._fault_strategy = type("F", (), {"value": "continue"})()
        # 伪造 worker base_vars
        class _W:
            _base_vars = {
                "__parallel_device_udids__": ["U1", "U2"],
                "__parallel_platform__": "android",
            }
        win._worker = _W()
        captured = {}

        def _fake_write(_suite, out, _generated_at="", meta=None):
            captured["meta"] = meta
            return out

        with patch("autopilot.report.write_report", _fake_write), \
                patch("autopilot.report.default_report_path", return_value=os.path.join(tmp, "r.html")):
            win._on_suite_done(SuiteResult(name="R", results=[_pass_result("c")]))
        report_meta = captured.get("meta")
        devices = getattr(report_meta, "devices", {}) if report_meta else {}
        ok = "U1" in devices.values() and "U2" in devices.values()
        win.close()
    print("报告 meta 并行设备:", "✅" if ok else "❌", devices)
    return ok


def test_menu_suite_wired() -> bool:
    from autopilot.ui.actions import ACTIONS_BY_ID
    spec = ACTIONS_BY_ID.get("run.suite")
    ok = spec is not None and spec.slot == "run_suite"
    print("菜单运行测试套接线:", "✅" if ok else "❌")
    return ok


# ---- 运行时：per-slot caps / 停止时效 / 隔离接线 ----

def test_ios_per_slot_caps_no_cross_talk() -> bool:
    """并行 iOS：各 shard 的 webDriverAgentUrl/udid 与 slot 一致，无首台污染。"""
    seen: dict[str, dict] = {}

    def fake_run_cases(_testcases, name="Suite", **_kwargs):
        bv = _kwargs.get("base_vars") or {}
        udid = bv.get("__device_udid__", "")
        seen[udid] = bv.get("__appium_caps__") or {}
        return SuiteResult(
            name=name,
            results=[_pass_result(tc.name, udid) for tc in _testcases],
        )

    with patch("autopilot.engine.run.parallel.run_cases", fake_run_cases), \
            patch("autopilot.runtime.device_session.DeviceSession._ios_appium_caps",
                  lambda self: {
                      "appium:udid": self.udid,
                      "appium:webDriverAgentUrl": f"http://127.0.0.1:{self.wda_port}",
                  }):
        run_suite(
            [TestCase(name="a"), TestCase(name="b")],
            mode="parallel_device",
            platform="ios",
            device_udids=["PHONE0", "PHONE1"],
            parallel_workers=2,
            backend_mode="appium",
            base_vars={"__appium_caps__": {
                "appium:udid": "POLLUTE",
                "appium:webDriverAgentUrl": "http://127.0.0.1:9999",
            }},
        )
    c0 = seen.get("PHONE0") or {}
    c1 = seen.get("PHONE1") or {}
    ok = (
        c0.get("appium:udid") == "PHONE0"
        and c1.get("appium:udid") == "PHONE1"
        and c0.get("appium:webDriverAgentUrl") == "http://127.0.0.1:8100"
        and c1.get("appium:webDriverAgentUrl") == "http://127.0.0.1:8101"
        and "POLLUTE" not in str(c0) and "POLLUTE" not in str(c1)
        and "9999" not in str(c0) and "9999" not in str(c1)
    )
    print("iOS per-slot caps:", "✅" if ok else "❌", seen)
    return ok


def test_cancel_returns_promptly() -> bool:
    """cancel 后限时 drain，超时则强制返回（不无限等待慢设备）。"""
    cancel = threading.Event()
    started = threading.Event()

    def fake_run_cases(_testcases, name="Suite", **_kwargs):
        udid = (_kwargs.get("base_vars") or {}).get("__device_udid__", "")
        if udid == "FAST":
            started.set()
            cancel.set()
            return SuiteResult(
                name=name,
                results=[_pass_result(tc.name, udid) for tc in _testcases],
            )
        started.wait(timeout=2)
        for _ in range(200):
            if cancel.is_set():
                time.sleep(0.05)
            else:
                time.sleep(0.05)
        return SuiteResult(
            name=name,
            results=[_pass_result(tc.name, udid) for tc in _testcases],
        )

    sessions = [
        DeviceSession.from_slot("android", "FAST", slot=0),
        DeviceSession.from_slot("android", "SLOW", slot=1),
    ]
    cfg = RunConfig(
        name="T",
        device_sessions=sessions,
        cancel_event=cancel,
        base_vars={},
        parallel_stop_drain_sec=0.3,
    )
    t0 = time.monotonic()
    with patch("autopilot.engine.run.parallel.run_cases", fake_run_cases):
        suite = run_parallel_device(
            [TestCase(name="c0"), TestCase(name="c1")], cfg)
    elapsed = time.monotonic() - t0
    ok = elapsed < 2.0 and any(r.device_udid == "FAST" for r in suite.results)
    print("停止时效:", "✅" if ok else "❌", f"{elapsed:.2f}s",
          [r.device_udid for r in suite.results])
    return ok


def test_worker_passes_fault_isolation() -> bool:
    """ExecutionWorker 把 parallel_fault_isolation 传给 run_suite。"""
    from autopilot.ui.runner import ExecutionWorker
    seen = {"iso": None}

    def fake_run_suite(*_a, **_kwargs):
        seen["iso"] = _kwargs.get("parallel_fault_isolation")
        return SuiteResult(name="x", results=[])

    _app()
    w = ExecutionWorker(
        [TestCase(name="t")],
        name="iso",
        parallel_fault_isolation=False,
    )
    with patch("autopilot.ui.runner.run_suite", fake_run_suite):
        w.run()
    ok = seen["iso"] is False
    print("Worker 隔离参数贯通:", "✅" if ok else "❌", seen)
    return ok


def test_worker_stop_terminates_tracked_context_children(monkeypatch) -> None:
    from autopilot.ui.runner import ExecutionWorker

    _app()
    worker = ExecutionWorker([TestCase(name="t")], name="stop")
    ctx = object()
    worker._track_context(ctx)
    terminated: list[object] = []
    monkeypatch.setattr(worker.control, "terminate_children", terminated.append)
    worker.request_stop()
    assert worker.control.is_cancelled
    assert terminated == [ctx]


def test_cli_kill_on_shard_fail_flag() -> bool:
    """tools/run_suite.py 注册 --kill-on-shard-fail。"""
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "tools", "run_suite.py")
    src = open(path, encoding="utf-8").read()
    ok = "--kill-on-shard-fail" in src and "parallel_fault_isolation" in src
    print("CLI kill-on-shard-fail:", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([
        test_parallel_invokes_shards(),
        test_sequential_default(),
        test_parallel_requires_udids(),
        test_parallel_pops_single_udid_from_base(),
        test_parallel_worker_drops_sibling_udid_list(),
        test_cancel_merges_completed_shards(),
        test_worker_exception_becomes_fail(),
        test_parallel_deepcopy_base_vars(),
        test_fault_isolation_default_continues(),
        test_fault_isolation_off_cancels_others(),
        test_build_sessions_empty_raises(),
        test_shard_empty_worker_skipped(),
        test_ask_parallel_lt2_devices(),
        test_ask_parallel_single_case_ok(),
        test_ask_parallel_cancel(),
        test_ask_parallel_ok_unchecked(),
        test_ask_parallel_isolate_and_android_hint(),
        test_resolve_parallel_cancel(),
        test_resolve_parallel_confirm(),
        test_resolve_parallel_single_case_ok(),
        test_f5_disables_parallel_dialog(),
        test_parallel_skips_device_pick(),
        test_report_meta_parallel_devices(),
        test_menu_suite_wired(),
        test_ios_per_slot_caps_no_cross_talk(),
        test_cancel_returns_promptly(),
        test_worker_passes_fault_isolation(),
        test_cli_kill_on_shard_fail_flag(),
    ])
    print("\n总结:", "✅ 多机并行执行全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
