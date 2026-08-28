"""iOS WDA 起不来时的取证脚本：保留隧道/runwda/转发，持续探测并打印证据。

``IosDevicePrep.prepare()`` 失败只抛「WDA /status 未就绪」，无法区分是转发没建、
WDA 进程死了，还是首启超时。此脚本把三类证据同时打出来。

用法::

    python tools/diag_ios_wda.py [udid] [wait_sec]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import autopilot.mobile.ios_bootstrap as ib  # noqa: E402


def main(argv: list[str]) -> int:
    udid = argv[1] if len(argv) > 1 else ""
    if not udid:
        from autopilot.mobile.ios_devices import list_usb_devices

        devices = list_usb_devices()
        if not devices:
            print("no ios device")
            return 2
        udid = devices[0].udid
    wait_sec = float(argv[2]) if len(argv) > 2 else 180.0

    prep = ib.IosDevicePrep(udid, "", log=print)
    try:
        print(f"[diag] udid={udid}")
        prep.reclaim(hard=True)
        print(f"[diag] tunnel: {prep.ensure_tunnel(timeout=45, force=True)}")
        prep.wda_bundle = prep.discover_wda()
        print(f"[diag] wda bundle: {prep.wda_bundle}")
        print(f"[diag] image mounted: {prep.ensure_image()}")
        print(f"[diag] runwda alive: {prep.ensure_wda()}")
        print(f"[diag] forward 8100: {prep.ensure_forward()}")
        deadline = time.monotonic() + wait_sec
        seen = ""
        while time.monotonic() < deadline:
            alive = ib.wda_alive(prep.wda_port)
            listening = ib.is_port_listening(prep.wda_port)
            print(f"[diag] t={int(time.monotonic() - (deadline - wait_sec))}s "
                  f"listening={listening} status_ok={alive}")
            if alive:
                print("[diag] WDA /status OK")
                return 0
            tail = prep.runwda_log_tail(4)
            if tail and tail != seen:
                seen = tail
                print("[diag] runwda tail:\n" + tail)
            time.sleep(10)
        print("[diag] 超时未就绪；最终 runwda 日志：")
        print(prep.runwda_log_tail(40))
        return 1
    finally:
        prep.stop()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
