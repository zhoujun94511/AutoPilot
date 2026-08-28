"""异步执行 worker：在后台线程跑用例/测试套，通过信号回传进度与结果。

支持串行（默认）与同平台多设备并行（run_suite + parallel_device 策略）。
"""

from __future__ import annotations

import threading
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from ..engine import FaultStrategy
from ..engine.keyword_store import KeywordStore
from ..engine.run import run_suite
from ..engine.run_control import RunControl
from ..model.mapfile import MapFile
from ..model.testcase import TestCase


class ExecutionWorker(QThread):
    stepDone = pyqtSignal(object)     # StepResult
    caseDone = pyqtSignal(object)     # RunResult
    suiteDone = pyqtSignal(object)    # SuiteResult

    def __init__(self, testcases: list[TestCase], name: str = "Suite",
                 fault_strategy: FaultStrategy = FaultStrategy.CONTINUE,
                 base_vars: Optional[dict] = None,
                 maps: Optional[list[MapFile]] = None,
                 keyword_store: Optional[KeywordStore] = None,
                 run_mode: str = "sequential",
                 platform: str = "",
                 parallel_workers: int = 0,
                 device_udids: Optional[list[str]] = None,
                 wda_bundle: str = "",
                 backend_mode: str = "auto",
                 parallel_fault_isolation: bool = True,
                 fault_times: int = 0,
                 parent=None) -> None:
        super().__init__(parent)
        self._testcases = testcases
        self._name = name
        self._fault_strategy = fault_strategy
        self._base_vars = base_vars
        self._maps = maps
        self._keyword_store = keyword_store
        self._run_mode = run_mode
        self._platform = platform
        self._parallel_workers = parallel_workers
        self._device_udids = device_udids
        self._wda_bundle = wda_bundle
        self._backend_mode = backend_mode
        self._parallel_fault_isolation = parallel_fault_isolation
        self._fault_times = int(fault_times or 0)
        self.control = RunControl()
        self._context_lock = threading.Lock()
        self._active_contexts: set[object] = set()

    @property
    def cancel_event(self):
        """兼容旧代码：与 control.cancel_event 同一对象。"""
        return self.control.cancel_event

    @property
    def pause_event(self):
        return self.control.pause_event

    def request_stop(self) -> None:
        self.control.request_stop()
        with self._context_lock:
            contexts = tuple(self._active_contexts)
        for ctx in contexts:
            self.control.terminate_children(ctx)

    def _track_context(self, ctx) -> None:
        with self._context_lock:
            self._active_contexts.add(ctx)

    def request_pause(self) -> None:
        self.control.request_pause()

    def request_resume(self) -> None:
        self.control.request_resume()

    def _emit_step(self, sr) -> None:
        # noinspection PyUnresolvedReferences
        self.stepDone.emit(sr)

    def _emit_case(self, rr) -> None:
        # noinspection PyUnresolvedReferences
        self.caseDone.emit(rr)

    def _emit_suite_done(self, suite) -> None:
        # noinspection PyUnresolvedReferences
        self.suiteDone.emit(suite)

    def run(self) -> None:  # noqa: D401  在后台线程执行
        from ..runtime.log import run_log, get_logger
        from ..engine.suite import SuiteResult
        from ..engine.executor import RunResult, StepResult
        log = get_logger("run")
        suite: SuiteResult | None = None
        # noinspection PyBroadException
        try:
            with run_log(self._name):
                log.info("===== 开始执行 %s（%d 用例，模式 %s）=====",
                         self._name, len(self._testcases), self._run_mode)
                suite = run_suite(
                    self._testcases,
                    name=self._name,
                    mode=self._run_mode,
                    platform=self._platform,
                    parallel_workers=self._parallel_workers,
                    device_udids=self._device_udids,
                    wda_bundle=self._wda_bundle,
                    backend_mode=self._backend_mode,
                    fault_strategy=self._fault_strategy,
                    base_vars=self._base_vars,
                    maps=self._maps,
                    keyword_store=self._keyword_store,
                    cancel_event=self.control.cancel_event,
                    pause_event=self.control.pause_event,
                    on_step=self._emit_step,
                    on_case=self._emit_case,
                    on_context=self._track_context,
                    parallel_fault_isolation=self._parallel_fault_isolation,
                    fault_times=self._fault_times,
                )
                cc = suite.case_counts()
                log.info("===== 执行结束 %s：%d/%d 通过 =====",
                         self._name, cc.get("passed", 0), cc.get("total", 0))
        except Exception as e:  # noqa: BLE001 — 必须回传 suiteDone，否则 UI/计划会挂死
            log.exception("执行线程异常：%s", e)
            # 空 results 的 RunResult.passed=True，须显式 FAIL 步骤，计划 stop_on_fail 才能识别
            suite = SuiteResult(
                name=self._name,
                results=[RunResult(
                    case_name=f"{self._name}::worker_error",
                    results=[StepResult(
                        keyword_id="__worker__",
                        comment="执行线程异常",
                        status="FAIL",
                        message=str(e),
                    )],
                )],
            )
        finally:
            if suite is None:
                suite = SuiteResult(
                    name=self._name,
                    results=[RunResult(
                        case_name=f"{self._name}::worker_error",
                        results=[StepResult(
                            keyword_id="__worker__",
                            comment="执行线程异常",
                            status="FAIL",
                            message="unknown",
                        )],
                    )],
                )
            self._emit_suite_done(suite)
