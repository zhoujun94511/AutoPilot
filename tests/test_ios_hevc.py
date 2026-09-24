"""iOS 27 HEVC 版本闸、帧封装与开流取消（不打开真机）。"""

import asyncio
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autopilot.mobile.ios_hevc import (
    HevcAccessUnit,
    IosHevcStream,
    annexb_access_unit,
    await_until_stopped,
    hevc_enabled_by_env,
    hevc_supported_ios,
    parse_ios_version,
)
from autopilot.mobile import ios_mirror as im


def test_ios27_gate() -> bool:
    ok = (
        parse_ios_version("27.0") == (27, 0, 0)
        and hevc_supported_ios("27.0")
        and hevc_supported_ios("27.0.1")
        and not hevc_supported_ios("26.0.1")
        and not hevc_supported_ios("18.6.2")
        and not hevc_supported_ios("")
    )
    print("HEVC 版本闸:", "OK" if ok else "FAIL")
    return ok


def test_env_disables_hevc() -> bool:
    old = os.environ.get("IOS_HEVC")
    try:
        os.environ["IOS_HEVC"] = "0"
        off = not hevc_enabled_by_env()
        os.environ["IOS_HEVC"] = "auto"
        on = hevc_enabled_by_env()
        mac = not im.can_try_hevc_mirror("auto", "mac", "27.0")
        forced = not im.can_try_hevc_mirror("mjpeg", "windows", "27.0")
        ok = off and on and mac and forced
        print("HEVC 开关:", "OK" if ok else "FAIL")
        return ok
    finally:
        if old is None:
            os.environ.pop("IOS_HEVC", None)
        else:
            os.environ["IOS_HEVC"] = old


def test_access_unit_framing() -> bool:
    nal = bytes((40 << 1, 1, 2, 3))
    unit = HevcAccessUnit(
        keyframe=True,
        reset=True,
        nals=[nal],
        vps=bytes((32 << 1, 9)),
        sps=bytes((33 << 1, 9)),
        pps=bytes((34 << 1, 9)),
    )
    packet = unit.webcodecs_packet()
    annex = annexb_access_unit(unit)
    ok = packet[4] == 2 and annex.startswith(b"\x00\x00\x00\x01") and annex.count(b"\x00\x00\x00\x01") == 4
    print("HEVC 帧封装:", "OK" if ok else "FAIL")
    return ok


def test_await_until_stopped_cancels() -> bool:
    async def slow() -> str:
        await asyncio.sleep(30)
        return "late"

    async def main_async() -> str | None:
        stopped = asyncio.Event()

        async def poke() -> None:
            await asyncio.sleep(0.02)
            stopped.set()

        poker = asyncio.create_task(poke())
        result = await asyncio.wait_for(await_until_stopped(slow(), stopped), timeout=2)
        await poker
        return result

    ok = asyncio.run(main_async()) is None
    print("HEVC 取消等待:", "OK" if ok else "FAIL")
    return ok


def test_stop_before_start_refuses() -> bool:
    stream = IosHevcStream("abc")
    stream.stop()
    refused = False
    try:
        stream.start()
    except RuntimeError as exc:
        refused = "已取消" in str(exc)
    ok = refused and not stream.thread_alive()
    print("HEVC 停止后拒绝再开:", "OK" if ok else "FAIL")
    return ok


def _install_fake_tunnel(tunnel_cls: type) -> callable:
    import sys
    import types

    names = (
        "pymobiledevice3.remote.core_device",
        "pymobiledevice3.remote.core_device.screen_stream",
        "pymobiledevice3.remote.core_device.display_service",
        "pymobiledevice3.remote.userspace_tunnel",
    )
    previous = {name: sys.modules.get(name) for name in names}

    def ensure(name: str):
        module = sys.modules.get(name)
        if module is None:
            module = types.ModuleType(name)
            sys.modules[name] = module
        return module

    screen = ensure("pymobiledevice3.remote.core_device.screen_stream")
    screen.depacketize_hevc = lambda *_a, **_k: None
    screen.hevc_codec_string_from_sps = lambda *_a, **_k: ""
    screen.hevc_decoder_configuration_record = lambda *_a, **_k: b""
    screen.open_media_receiver = lambda *_a, **_k: (None, None)
    display = ensure("pymobiledevice3.remote.core_device.display_service")
    display.DisplayService = object
    users = ensure("pymobiledevice3.remote.userspace_tunnel")
    users.UserspaceRsdTunnel = tunnel_cls

    def restore() -> None:
        for name, module in previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    return restore


def test_stop_during_open_closes_tunnel() -> bool:
    closed: list[str] = []
    opened = threading.Event()

    class _Tunnel:
        def __init__(self, serial: str = "", remotepairing_fallback: bool = False) -> None:
            self.serial = serial
            self.remotepairing_fallback = remotepairing_fallback

        @staticmethod
        async def aopen() -> object:
            opened.set()
            await asyncio.sleep(30)
            return object()

        async def aclose(self) -> None:
            closed.append(self.serial)

    restore = _install_fake_tunnel(_Tunnel)
    stream = IosHevcStream("deadbeef")
    errors: list[str] = []

    def _run_start() -> None:
        try:
            stream.start()
        except RuntimeError as exc:
            errors.append(str(exc))

    try:
        worker = threading.Thread(target=_run_start)
        worker.start()
        if not opened.wait(2):
            stream.stop()
            worker.join(timeout=6)
            print("HEVC 开流中取消会 aclose: FAIL 未进入 aopen", errors, closed)
            return False
        stream.stop()
        worker.join(timeout=3)
        ok = (
            not worker.is_alive()
            and bool(errors)
            and "已取消" in errors[0]
            and closed == ["deadbeef"]
            and not stream.thread_alive()
        )
    finally:
        restore()
    print("HEVC 开流中取消会 aclose:", "OK" if ok else "FAIL", errors, closed)
    return ok


def test_stop_closes_tunnel_socket_while_thread_blocks() -> bool:
    import socket

    left, right = socket.socketpair()
    left.settimeout(2)
    released = threading.Event()

    class _Sock:
        def __init__(self, raw: socket.socket) -> None:
            self._raw = raw

        def recv(self, _n: int) -> bytes:
            return self._raw.recv(_n)

        def close(self) -> None:
            self._raw.close()
            released.set()

    stream = IosHevcStream("deadbeef")
    stream._tunnel = type("T", (), {"tun": type("U", (), {"_peer": _Sock(left), "_pend": _Sock(right)})()})()

    def _block() -> None:
        try:
            left.recv(8)
        except OSError:
            pass

    worker = threading.Thread(target=_block)
    stream._thread = worker
    worker.start()
    stream.stop()
    ok = released.is_set() and not worker.is_alive() and not stream.thread_alive()
    print("HEVC stop 关闭隧道套接字:", "OK" if ok else "FAIL")
    return ok


def main() -> None:
    results = [
        test_ios27_gate(),
        test_env_disables_hevc(),
        test_access_unit_framing(),
        test_await_until_stopped_cancels(),
        test_stop_before_start_refuses(),
        test_stop_during_open_closes_tunnel(),
        test_stop_closes_tunnel_socket_while_thread_blocks(),
    ]
    if not all(results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
