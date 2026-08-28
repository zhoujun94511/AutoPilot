"""iOS 录屏：WDA 存活时不 reclaim / 优先复用 MJPEG。"""

from __future__ import annotations

import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from autopilot.mobile import ios_screen_record as rec


def test_attach_wda_mjpeg_skips_goios() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "a.mp4")
        wrote = {"n": 0}

        def _fake_record(url, out_path, stop_evt, fps=12.0):
            _ = fps
            wrote["n"] += 1
            wrote["url"] = url
            with open(out_path, "wb") as f:
                f.write(b"x")
            stop_evt.wait(0.05)

        with (
            patch.object(rec, "probe_ios_screen_record", return_value=(True, "")),
            patch.object(rec, "mjpeg_alive", return_value=True),
            patch.object(rec, "_prepare_for_goios_stream") as prep,
            patch.object(rec, "_spawn_screenshot_stream") as spawn,
            patch.object(rec, "_record_mjpeg_to_mp4", side_effect=_fake_record),
        ):
            sess = rec.start_ios_screen_record(
                "UDID-1", out, mjpeg_port=9100, wda_port=8100, info_port=28100
            )
            path = rec.stop_ios_screen_record("UDID-1")
        ok = (
            sess.source == "wda_mjpeg"
            and sess.process is None
            and not prep.called
            and not spawn.called
            and wrote.get("url", "").startswith("http://127.0.0.1:9100")
            and path == out
        )
        print("复用 WDA MJPEG:", "✅" if ok else "❌", sess.source, wrote.get("url"))
        return ok


def test_prepare_skips_when_wda_alive() -> bool:
    logs: list[str] = []
    with (
        patch.object(rec, "wda_alive", return_value=True),
        patch.object(rec, "mjpeg_alive", return_value=False),
        patch.object(rec, "IosDevicePrep") as prep_cls,
    ):
        rec._prepare_for_goios_stream(
            "UDID",
            info_port=28100,
            wda_port=8100,
            mjpeg_port=9100,
            log=logs.append,
        )
    ok = not prep_cls.called and any("跳过隧道回收" in m for m in logs)
    print("WDA 存活跳过 prepare:", "✅" if ok else "❌", logs)
    return ok


def test_prepare_reuses_tunnel_no_force() -> bool:
    logs: list[str] = []
    prep = MagicMock()
    prep.tunnel_running.return_value = True
    prep.ensure_image.return_value = True
    with (
        patch.object(rec, "wda_alive", return_value=False),
        patch.object(rec, "mjpeg_alive", return_value=False),
        patch.object(rec, "IosDevicePrep", return_value=prep),
    ):
        rec._prepare_for_goios_stream(
            "UDID",
            info_port=28110,
            wda_port=8101,
            mjpeg_port=9101,
            log=logs.append,
        )
    ok = (
        prep.ensure_tunnel.call_count == 0
        and prep.ensure_image.called
        and any("不 reclaim" in m for m in logs)
    )
    print("复用隧道不 ensure_tunnel:", "✅" if ok else "❌", logs)
    return ok


def test_slot_port_defaults() -> bool:
    info, wda, mjpeg = rec._resolve_session_ports(worker_slot=2)
    ok = info == 28100 + 20 and wda == 8102 and mjpeg == 9102
    print("slot 端口偏移:", "✅" if ok else "❌", info, wda, mjpeg)
    return ok


def main() -> int:
    checks = [
        test_attach_wda_mjpeg_skips_goios(),
        test_prepare_skips_when_wda_alive(),
        test_prepare_reuses_tunnel_no_force(),
        test_slot_port_defaults(),
    ]
    ok = all(checks)
    print("\n总结:", "✅ WDA-safe 录屏全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
