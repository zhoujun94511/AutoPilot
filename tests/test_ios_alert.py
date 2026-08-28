"""iOS 系统弹框组件层离线测试。"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from autopilot.mobile.ios.alert.model import AlertInfo
from autopilot.mobile.ios.alert.policy import decide
from autopilot.mobile.ios.alert.rules import match_rule, pick_accept_button
from autopilot.mobile.ios.alert.wda_adapter import WdaAlertAdapter
from autopilot.mobile.ios.alert.handler import IOSAlertHandler
from autopilot.mobile.ios.alert.recorder import AlertRecorder
from autopilot.keywords.context import ExecutionContext


class _FakeAlertClient:
    def __init__(self, text: str = "", buttons: list[str] | None = None, open_: bool = True):
        self.text = text
        self.buttons = buttons or []
        self.open = open_
        self.accepts: list[str] = []

    def alert_text(self) -> str:
        if not self.open:
            raise RuntimeError("no alert")
        return self.text

    def alert_accept(self, label: str = "") -> None:
        self.accepts.append(label)
        self.open = False

    def alert_dismiss(self, label: str = "") -> None:
        self.accepts.append(f"dismiss:{label}")
        self.open = False

    def source(self) -> str:
        if not self.open:
            return "<App/>"
        btns = "".join(
            f'<XCUIElementTypeButton label="{b}"/>' for b in self.buttons
        )
        return f"<XCUIElementTypeAlert>{btns}</XCUIElementTypeAlert>"


def test_match_rule_local_network():
    rule = match_rule('"AIID" Would Like to Find Devices on Local Networks')
    assert rule is not None
    assert rule["id"] == "local_network"


def test_decide_auto_wlan():
    info = AlertInfo(
        exists=True,
        text="Would Like to Find Devices on Local Networks",
        buttons=["Don't Allow", "WLAN & Cellular"],
    )
    d = decide(info, "auto")
    assert d.action == "accept"
    assert "WLAN" in d.button


def test_pick_accept_button():
    btn = pick_accept_button(["Cancel", "Allow"])
    assert btn == "Allow"


def test_wda_adapter_get_and_accept():
    client = _FakeAlertClient(
        text="Allow notifications?",
        buttons=["Don't Allow", "Allow"],
    )
    adapter = WdaAlertAdapter(client)
    info = adapter.get_alert()
    assert info.exists
    assert info.alert_kind == "system"
    adapter.accept("Allow")
    assert not adapter.is_open()


def test_handler_maybe_handle_auto():
    client = _FakeAlertClient(
        text="Would Like to Access the Camera",
        buttons=["Don't Allow", "Allow"],
    )
    drv = type("D", (), {
        "capabilities": {"platformName": "iOS", "automationName": "WDA-Direct"},
        "wda_client": client,
    })()

    class _FakeMgr:
        platform = "ios"
        backend = "wda"
        backend_mode = "wda"
        extra_caps = {}

        def __init__(self, driver):
            self._driver = driver

        def optional_driver(self):
            return self._driver

    ctx = ExecutionContext()
    ctx.set_var("__ios_alert_enabled__", True)
    ctx.appium = _FakeMgr(drv)
    handler = IOSAlertHandler(ctx)
    res = handler.maybe_handle(stage="test")
    assert res.handled, res
    assert res.action == "accept"


def test_recorder_writes_files():
    client = _FakeAlertClient(text="unknown", buttons=["OK"])
    adapter = WdaAlertAdapter(client)
    info = adapter.get_alert()
    with tempfile.TemporaryDirectory() as tmp:
        rec = AlertRecorder(tmp)
        from autopilot.mobile.ios.alert.model import AlertDecision
        folder = rec.save(info, AlertDecision("fail", reason="test"), adapter, stage="unit")
        assert os.path.isdir(folder)
        assert os.path.isfile(os.path.join(folder, "alert.json"))
        assert os.path.isfile(os.path.join(folder, "page_source.xml"))


if __name__ == "__main__":
    test_match_rule_local_network()
    test_decide_auto_wlan()
    test_pick_accept_button()
    test_wda_adapter_get_and_accept()
    test_handler_maybe_handle_auto()
    test_recorder_writes_files()
    print("test_ios_alert: all passed")
