"""KEEP_WDA 跨用例复用 AppiumManager。"""

from __future__ import annotations

from autopilot.keywords.context import ExecutionContext
from autopilot.keywords.mobile import driver as mobile_driver


def test_keep_wda_reuses_manager_across_contexts(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_INTENT_KEEP_WDA", "1")
    mobile_driver._KEEP_WDA_MANAGERS.clear()
    try:
        ctx1 = ExecutionContext()
        ctx1.set_var("__device_udid__", "UDID-A")
        ctx1.set_var("__worker_slot__", 0)
        mgr1 = mobile_driver.get_manager(ctx1)

        ctx2 = ExecutionContext()
        ctx2.set_var("__device_udid__", "UDID-A")
        ctx2.set_var("__worker_slot__", 0)
        mgr2 = mobile_driver.get_manager(ctx2)
        assert mgr1 is mgr2

        mgr1.close()  # keep 模式不销毁 prep；manager 仍应可复用
        ctx3 = ExecutionContext()
        ctx3.set_var("__device_udid__", "UDID-A")
        ctx3.set_var("__worker_slot__", 0)
        assert mobile_driver.get_manager(ctx3) is mgr1
    finally:
        mobile_driver._KEEP_WDA_MANAGERS.clear()
        monkeypatch.delenv("AUTOPILOT_INTENT_KEEP_WDA", raising=False)


def test_without_keep_wda_creates_fresh_manager(monkeypatch):
    monkeypatch.delenv("AUTOPILOT_INTENT_KEEP_WDA", raising=False)
    monkeypatch.delenv("IOS_KEEP_WDA", raising=False)
    mobile_driver._KEEP_WDA_MANAGERS.clear()
    ctx1 = ExecutionContext()
    ctx2 = ExecutionContext()
    assert mobile_driver.get_manager(ctx1) is not mobile_driver.get_manager(ctx2)
