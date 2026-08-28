"""iOS prepare 取消令牌 + 进程清理作用域（离线单测）。"""

from __future__ import annotations

import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from autopilot.mobile import ios_bootstrap as ib


def test_cmdline_matches_tunnel_filters_by_info_port():
    joined = "ios.exe tunnel start --userspace --tunnel-info-port 28100"
    assert ib.cmdline_matches_tunnel(joined.lower(), 28100)
    assert not ib.cmdline_matches_tunnel(joined.lower(), 28101)
    assert ib.cmdline_matches_tunnel(joined.lower(), None)
    assert not ib.cmdline_matches_tunnel("ios.exe apps list", 28100)


def test_prep_cancelled_during_sleep():
    ev = threading.Event()
    prep = ib.IosDevicePrep("UDID", "com.x.WDA", cancel_event=ev, log=lambda _m: None)

    def cancel_soon():
        time.sleep(0.15)
        ev.set()

    threading.Thread(target=cancel_soon, daemon=True).start()
    t0 = time.monotonic()
    try:
        prep._sleep(5.0)
        raised = False
    except ib.PrepCancelled:
        raised = True
    elapsed = time.monotonic() - t0
    assert raised
    assert elapsed < 2.0


def test_ensure_tunnel_respects_cancel(monkeypatch):
    ev = threading.Event()
    prep = ib.IosDevicePrep("UDID", "com.x.WDA", cancel_event=ev, log=lambda _m: None)
    monkeypatch.setattr(prep, "reclaim", lambda **_k: None)
    monkeypatch.setattr(prep, "tunnel_running", lambda: False)
    monkeypatch.setattr(ib, "_spawn", lambda *_a, **_k: None)
    ev.set()
    try:
        prep.ensure_tunnel(timeout=30, force=True)
        ok = False
    except ib.PrepCancelled:
        ok = True
    assert ok
