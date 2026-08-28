"""iOS Monkey 组件层离线测试。"""

import os
import sys
import tempfile
import random

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (OSError, ValueError, UnicodeError):
    pass

from autopilot.mobile.ios.monkey.bundle import resolve_target_bundle_id
from autopilot.mobile.ios.monkey.element import parse_elements, pick_random_element
from autopilot.mobile.ios.monkey.policy import (
    apply_preset,
    clamp_duration,
    clamp_steps,
    is_blacklisted,
    should_refresh_source,
    throttle_sleep_ms,
    MonkeyConfig,
)
from autopilot.mobile.ios.monkey.state import StuckTracker
from autopilot.mobile.ios.monkey.engine import IOSMonkeyEngine
from autopilot.mobile.ios.monkey.config import build_monkey_config
from autopilot.mobile.ios.monkey.driver import IOSMonkeyDriver
from autopilot.keywords.context import ExecutionContext


SAMPLE_XML = """
<XCUIElementTypeApplication>
  <XCUIElementTypeButton type="XCUIElementTypeButton" name="OK" label="OK"
    enabled="true" visible="true" x="10" y="400" width="300" height="44"/>
  <XCUIElementTypeButton type="XCUIElementTypeButton" name="Delete" label="Delete"
    enabled="true" visible="true" x="10" y="500" width="300" height="44"/>
</XCUIElementTypeApplication>
"""


class _FakeMonkeyDriver(IOSMonkeyDriver):
    backend = "wda"

    def __init__(self):
        self.taps: list[tuple[int, int]] = []
        self.swipes = 0
        self.source_calls = 0
        self._state = 4

    def raw_driver(self):
        return self

    def tap(self, x, y):
        self.taps.append((x, y))

    def swipe_direction(self, direction):
        self.swipes += 1
        return "xctest"

    def long_press(self, x, y, duration_ms=800):
        self.taps.append((x, y))

    def screenshot_png(self):
        return b""

    def page_source(self):
        self.source_calls += 1
        return SAMPLE_XML

    def window_size(self):
        return 390, 844

    def launch_app(self, bundle_id):
        self._state = 4

    def activate_app(self, bundle_id):
        self._state = 4

    def app_state(self, bundle_id):
        return self._state


def test_clamp_steps():
    assert clamp_steps(10) == 20
    assert clamp_steps(150) == 150
    assert clamp_steps(999) == 200


def test_clamp_duration():
    assert clamp_duration(0) == 0
    assert clamp_duration(300) == 300
    assert clamp_duration(99999) == 21600


def test_preset_safe():
    cfg = MonkeyConfig(bundle_id="com.a")
    apply_preset(cfg, "safe")
    assert cfg.allow_dangerous is False
    assert cfg.weights["tap_random_element"] == 50


def test_should_refresh_source():
    assert should_refresh_source(1, "swipe_random", interval=5, last_index=0)
    assert not should_refresh_source(2, "swipe_random", interval=5, last_index=1)
    assert should_refresh_source(3, "tap_random_element", interval=5, last_index=1)


def test_throttle_jitter():
    cfg = MonkeyConfig(bundle_id="x", throttle_ms=500, throttle_jitter_ms=100)
    rng = random.Random(1)
    vals = {throttle_sleep_ms(cfg, rng) for _ in range(20)}
    assert min(vals) >= 400
    assert max(vals) <= 600


def test_parse_elements_and_blacklist():
    els = parse_elements(SAMPLE_XML, screen_w=390, screen_h=844)
    assert len(els) == 2
    rng = random.Random(1)
    picked = pick_random_element(els, rng, allow_dangerous=False)
    assert picked is not None
    assert picked.label == "OK"
    assert is_blacklisted("确认购买", allow_dangerous=False)


def test_resolve_bundle_from_ctx():
    ctx = ExecutionContext()
    ctx.set_var("app_package", "com.test.app")
    assert resolve_target_bundle_id(ctx) == "com.test.app"


def test_build_config_duration():
    ctx = ExecutionContext()
    cfg = build_monkey_config(ctx, "com.test.app", 50, durationSec=120, monkeyPolicy="safe")
    assert cfg.duration_sec == 120
    assert cfg.max_events == 50
    assert cfg.policy_preset == "safe"


def test_preset_safe_no_dead_actions():
    cfg = MonkeyConfig(bundle_id="com.a")
    apply_preset(cfg, "safe")
    assert "input_random_text" not in cfg.weights


def test_stuck_tracker():
    t = StuckTracker(3)
    assert t.observe("a") == 1
    assert t.observe("a") == 2
    assert t.observe("a") == 3
    assert t.is_stuck()


def test_engine_minimal_run():
    ctx = ExecutionContext()
    ctx.set_var("app_package", "com.test.app")
    ctx.set_var("__ios_alert_enabled__", False)
    with tempfile.TemporaryDirectory() as tmp:
        ctx.set_var("__project_path__", tmp)
        cfg = MonkeyConfig(
            bundle_id="com.test.app", max_events=5, throttle_ms=0,
            seed=42, source_interval=3,
            weights={"swipe_random": 100},
        )
        drv = _FakeMonkeyDriver()
        summary = IOSMonkeyEngine(ctx, drv, cfg).run()
        assert summary["eventCount"] == 5
        assert drv.source_calls < 5
        assert os.path.isfile(os.path.join(summary["reportDir"], "events.jsonl"))


def test_param_visible_monkey_android():
    from autopilot.model.testcase import Step, ParamValue
    from autopilot.ui.widgets.step_param_rules import param_visible, format_step_params, strip_hidden_params

    step = Step(
        "mobile_monkey",
        params=[
            ParamValue("monkeySteps", "50"),
            ParamValue("durationSec", "60"),
            ParamValue("throttleMs", "500"),
            ParamValue("monkeyPolicy", "balanced"),
        ],
    )
    assert param_visible("mobile_monkey", "monkeySteps", step, "android")
    assert not param_visible("mobile_monkey", "durationSec", step, "android")
    assert not param_visible("mobile_monkey", "throttleMs", step, "android")
    txt = format_step_params(step, "android")
    assert "monkeySteps=50" in txt
    assert "durationSec" not in txt
    strip_hidden_params(step, "android")
    assert not any(p.param_id == "durationSec" for p in step.params)


def test_param_visible_monkey_ios():
    from autopilot.model.testcase import Step, ParamValue
    from autopilot.ui.widgets.step_param_rules import param_visible

    step = Step("mobile_monkey", params=[ParamValue("monkeySteps", "50"), ParamValue("durationSec", "60")])
    assert param_visible("mobile_monkey", "durationSec", step, "ios")
    assert param_visible("mobile_monkey", "collectDeviceLogs", step, "ios")
    assert not param_visible("mobile_monkey", "collectDeviceLogs", step, "android")


def test_ios_monkey_run_helpers():
    import tempfile
    import tools.ios_monkey_run as cli

    assert cli._latest_report_dir(tempfile.gettempdir() + "/no_such_ios_monkey_root") == ""
    with tempfile.TemporaryDirectory() as tmp:
        report = os.path.join(tmp, "logs", "ios_monkey", "20260102_120000")
        os.makedirs(report)
        assert cli._latest_report_dir(tmp) == report


def test_crash_diff():
    from autopilot.mobile.ios.monkey.device_logs.crash_diff import (
        diff_new, is_relevant_crash, parse_crash_ls,
    )

    before = parse_crash_ls("App-2026.ips\nOther.crash\n")
    after = parse_crash_ls("App-2026.ips\nApp-2026-2.ips\n")
    assert diff_new(before, after) == ["App-2026-2.ips"]
    assert is_relevant_crash("imobile.broadcast.app-2026.ips", "imobile.broadcast.app")


def test_render_monkey_report():
    import json
    import tempfile
    from autopilot.mobile.ios.monkey.report_html import render_monkey_report

    with tempfile.TemporaryDirectory() as tmp:
        summary = {
            "bundleId": "com.test.app",
            "result": "passed",
            "eventCount": 2,
            "durationSec": 10,
            "backend": "wda",
            "policy": "balanced",
            "seed": 1,
        }
        with open(os.path.join(tmp, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f)
        with open(os.path.join(tmp, "events.jsonl"), "w", encoding="utf-8") as f:
            f.write('{"index":1,"time":"t","action":"tap","result":"ok"}\n')
        html_path = render_monkey_report(tmp)
        assert os.path.isfile(html_path)
        with open(html_path, encoding="utf-8") as f:
            text = f.read()
        assert "com.test.app" in text
        assert "tap" in text


def test_goios_syslog_cmd():
    from autopilot.mobile.ios.monkey.device_logs import goios_backend

    if not goios_backend.available():
        return
    cmd = goios_backend.syslog_cmd("UDID1")
    assert "syslog" in cmd
    assert "UDID1" in cmd
    ocmd = goios_backend.ostrace_cmd("UDID1", process="MyApp", match="com.test")
    assert "ostrace" in ocmd
    assert "--process=MyApp" in ocmd


def test_report_registry():
    import tempfile
    from autopilot.mobile.ios.monkey.report_registry import (
        latest_report_dir, latest_report_html, write_latest_pointer,
    )

    with tempfile.TemporaryDirectory() as tmp:
        report = os.path.join(tmp, "logs", "ios_monkey", "20260102_120000")
        os.makedirs(report)
        html = os.path.join(report, "report.html")
        with open(html, "w", encoding="utf-8") as f:
            f.write("<html></html>")
        write_latest_pointer(tmp, report, html)
        assert latest_report_dir(tmp) == os.path.abspath(report)
        assert latest_report_html(tmp) == os.path.abspath(html)


def test_ios_device_lease():
    import os
    import tempfile
    from autopilot.runtime.ios_device_lease import (
        acquire_udid,
        purge_stale_leases,
        release_udid,
        try_claim_udid,
    )

    with tempfile.TemporaryDirectory() as tmp:
        devs = ["AAAA-BBBB", "CCCC-DDDD"]
        u1, leased1 = acquire_udid(devs, tmp)
        assert u1 == "AAAA-BBBB"
        assert leased1 is True
        u2, leased2 = acquire_udid(devs, tmp)
        assert u2 == "CCCC-DDDD"
        assert leased2 is True
        u3, _ = acquire_udid(devs, tmp)
        assert u3 == ""
        release_udid("AAAA-BBBB", tmp)
        u4, _ = acquire_udid(devs, tmp)
        assert u4 == "AAAA-BBBB"

        release_udid("AAAA-BBBB", tmp)
        release_udid("CCCC-DDDD", tmp)

        u_single, leased_single = acquire_udid(["ONLY-ONE"], tmp, always_lease=True)
        assert u_single == "ONLY-ONE"
        assert leased_single is True
        u_single2, _ = acquire_udid(["ONLY-ONE"], tmp, always_lease=True)
        assert u_single2 == ""
        release_udid("ONLY-ONE", tmp)

        try_claim_udid("STALE-DEV", tmp, pid=999999999)
        root = os.path.join(tmp, "logs", "ios_monkey", ".leases")
        assert os.path.isdir(root)
        assert purge_stale_leases(tmp) >= 1
        u_stale, leased_stale = acquire_udid(["STALE-DEV"], tmp, always_lease=True)
        assert u_stale == "STALE-DEV"
        assert leased_stale is True
        release_udid("STALE-DEV", tmp)


def test_assign_ports_for_udid():
    from autopilot.runtime import port_allocator as pa
    from autopilot.runtime.port_allocator import assign_ports_for_udid

    old_free = pa.is_port_free
    pa.is_port_free = lambda *args, **kwargs: True
    try:
        devs = ["AAAA-BBBB", "CCCC-DDDD"]
        ps0 = assign_ports_for_udid("AAAA-BBBB", devices=devs)
        ps1 = assign_ports_for_udid("CCCC-DDDD", devices=devs)
        assert ps0.slot == 0
        assert ps1.slot == 1
        assert ps0.wda_port + 1 == ps1.wda_port
        assert ps0.tunnel_port + 10 == ps1.tunnel_port
    finally:
        pa.is_port_free = old_free


def test_log_collection_options():
    from autopilot.mobile.ios.monkey.device_logs.collector import LogCollectionOptions
    from autopilot.keywords.context import ExecutionContext

    ctx = ExecutionContext()
    ctx.set_var("__ios_monkey_device_logs__", "false")
    opt = LogCollectionOptions.from_context(ctx, {})
    assert opt.enabled is False


if __name__ == "__main__":
    test_clamp_steps()
    test_clamp_duration()
    test_preset_safe()
    test_should_refresh_source()
    test_throttle_jitter()
    test_parse_elements_and_blacklist()
    test_resolve_bundle_from_ctx()
    test_build_config_duration()
    test_preset_safe_no_dead_actions()
    test_stuck_tracker()
    test_engine_minimal_run()
    test_param_visible_monkey_android()
    test_param_visible_monkey_ios()
    test_ios_monkey_run_helpers()
    test_crash_diff()
    test_render_monkey_report()
    test_goios_syslog_cmd()
    test_report_registry()
    test_ios_device_lease()
    test_assign_ports_for_udid()
    test_log_collection_options()
    print("test_ios_monkey: all passed")
