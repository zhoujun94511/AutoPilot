"""镜像「静默断流」修复 — 白盒测试（离线，无需真机）。

设计场景（对应 bug：长时间无操作后画面冻在最后一帧、Mac 控制仍可用）：
  S1  帧停滞看门狗：>12s 无新帧 → 触发 video_fallback（不依赖 failed 信号）
  S2  首帧未到前：看门狗不误触发（仍由首帧超时器负责）
  S3  有新帧时：刷新停滞时钟，看门狗不触发
  S4  AVF 管道读：select 5s 超时，避免 read() 永久阻塞、无法 stop/重启
  S5  MJPEG HTTP：read 超时配置，避免 iter_bytes 永久阻塞
  S6  恢复策略 AVF：断流 → 重启 helper（最多 3 次）
  S7  恢复策略 MJPEG：非 AVF 模式 iOS 静默断流 → 重连 9100
  S8  恢复策略边界：无 WDA 会话时不盲目重连 MJPEG
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_APP = None


def _ensure_qt():
    global _APP
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication([])


# ---- S1–S3：MirrorPanel 帧停滞看门狗 ----

def test_stale_watchdog_constants() -> bool:
    """白盒：阈值与轮询间隔与实现一致。"""
    from autopilot.ui.widgets import mirror_panel as mp
    ok = mp._STALE_FRAME_SEC == 12.0 and mp._STALE_CHECK_MS == 4000
    print("S1 常量(12s/4s):", "✅" if ok else "❌")
    return ok


def test_stale_watchdog_fires_on_gap() -> bool:
    """S1：超过停滞阈值且无近期帧 → 调用 video_fallback。"""
    _ensure_qt()
    from autopilot.ui.widgets.mirror_panel import MirrorPanel

    reasons: list[str] = []
    p = MirrorPanel()
    p.video_fallback = lambda r: reasons.append(r) or True
    p._source = MagicMock()
    p._got_real_frame = True
    p._stopping = False
    p._stale_recovering = False
    p._last_frame_at = 0.0

    t0 = 1000.0
    with patch("autopilot.ui.widgets.mirror_panel.time.monotonic", side_effect=[t0 + 20.0, t0 + 20.0]):
        p._on_stale_frame_check()

    ok = len(reasons) == 1 and "无新帧" in reasons[0]
    print("S1 停滞触发 fallback:", "✅" if ok else "❌", reasons)
    return ok


def test_stale_watchdog_skips_when_recent_frame() -> bool:
    """S3：近期有帧 → 不触发 fallback。"""
    _ensure_qt()
    from autopilot.ui.widgets.mirror_panel import MirrorPanel

    reasons: list[str] = []
    p = MirrorPanel()
    p.video_fallback = lambda r: reasons.append(r) or True
    p._source = MagicMock()
    p._got_real_frame = True
    p._stopping = False

    t0 = 2000.0
    p._last_frame_at = t0
    with patch("autopilot.ui.widgets.mirror_panel.time.monotonic", return_value=t0 + 5.0):
        p._on_stale_frame_check()

    ok = reasons == []
    print("S3 近期有帧不触发:", "✅" if ok else "❌")
    return ok


def test_stale_watchdog_skips_before_first_frame() -> bool:
    """S2：首帧未到 → 看门狗不介入。"""
    _ensure_qt()
    from autopilot.ui.widgets.mirror_panel import MirrorPanel

    reasons: list[str] = []
    p = MirrorPanel()
    p.video_fallback = lambda r: reasons.append(r) or True
    p._source = MagicMock()
    p._got_real_frame = False
    p._last_frame_at = 0.0

    with patch("autopilot.ui.widgets.mirror_panel.time.monotonic", return_value=99999.0):
        p._on_stale_frame_check()

    ok = reasons == []
    print("S2 无首帧不触发:", "✅" if ok else "❌")
    return ok


def test_on_frame_refreshes_stale_clock() -> bool:
    """S3：每帧刷新 _last_frame_at。"""
    _ensure_qt()
    from PyQt6.QtGui import QImage
    from autopilot.ui.widgets.mirror_panel import MirrorPanel

    p = MirrorPanel()
    t0 = 3000.0
    with patch("autopilot.ui.widgets.mirror_panel.time.monotonic", return_value=t0):
        img = QImage(10, 10, QImage.Format.Format_RGB32)
        img.fill(0)
        p._on_frame(img)
    ok = p._last_frame_at == t0
    print("S3 _on_frame 刷新时钟:", "✅" if ok else "❌")
    return ok


def test_start_stop_stale_watch() -> bool:
    """S1：启动/停止镜像时看门狗随动。"""
    _ensure_qt()
    from autopilot.ui.widgets.mirror_panel import MirrorPanel, _STALE_CHECK_MS

    p = MirrorPanel()
    p._start_stale_watch()
    running = p._stale_frame_timer.isActive() and p._stale_frame_timer.interval() == _STALE_CHECK_MS
    p._stop_stale_watch()
    stopped = not p._stale_frame_timer.isActive()
    ok = running and stopped
    print("S1 看门狗启停:", "✅" if ok else "❌")
    return ok


# ---- S4：AVF 管道 select 超时 ----

def test_avf_select_uses_five_second_timeout() -> bool:
    """S4：管道读前 select 超时=5s（避免永久阻塞）。"""
    import select as select_mod
    from pathlib import Path
    from autopilot.inspector.stream.avf_source import AvfScreenSource

    timeouts: list[float] = []
    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"AVFH")
    reader = os.fdopen(read_fd, "rb", buffering=0)

    proc = MagicMock()
    proc.stdout = reader
    proc.poll.return_value = None

    real_select = select_mod.select

    def _fake_select(rlist, wlist, xlist, timeout=None):
        timeouts.append(timeout)
        if len(timeouts) >= 2:
            return [], [], []
        return real_select(rlist, wlist, xlist, 0)

    log_dir = Path(tempfile.mkdtemp(prefix="avf_test_log_"))
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        helper = tf.name
    try:
        src = AvfScreenSource(helper_path=helper)
        with patch("subprocess.Popen", return_value=proc), \
                patch("autopilot.inspector.stream.avf_source._log_dir", return_value=log_dir), \
                patch("autopilot.inspector.stream.avf_source.select.select", side_effect=_fake_select):
            th = threading.Thread(target=src.run, daemon=True)
            th.start()
            th.join(timeout=3.0)
            src.stop()
            src.wait(2000)
    finally:
        os.close(write_fd)
        os.unlink(helper)

    ok = any(t == 5.0 for t in timeouts)
    print("S4 AVF select 5s 超时:", "✅" if ok else "❌", timeouts[:5])
    return ok


def test_avf_stop_unblocks_stalled_reader() -> bool:
    """S4：停滞管道上 stop() 能在数秒内结束线程（非永久阻塞）。"""
    from pathlib import Path
    from autopilot.inspector.stream.avf_source import AvfScreenSource

    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"AVFH")
    reader = os.fdopen(read_fd, "rb", buffering=0)
    proc = MagicMock()
    proc.stdout = reader
    proc.poll.return_value = None

    with tempfile.NamedTemporaryFile(delete=False) as tf:
        helper = tf.name
    log_dir = Path(tempfile.mkdtemp(prefix="avf_test_log_"))
    try:
        src = AvfScreenSource(helper_path=helper)
        with patch("subprocess.Popen", return_value=proc), \
                patch("autopilot.inspector.stream.avf_source._log_dir", return_value=log_dir):
            src.start()
            time.sleep(0.3)
            t0 = time.monotonic()
            src.stop()
            src.wait(5000)
            elapsed = time.monotonic() - t0
    finally:
        os.close(write_fd)
        os.unlink(helper)

    ok = elapsed < 8.0
    print("S4 AVF stop 不永久阻塞:", "✅" if ok else "❌", f"elapsed={elapsed:.2f}s")
    return ok


# ---- S5：MJPEG HTTP 读超时 ----

def test_mjpeg_httpx_read_timeout_configured() -> bool:
    """S5：MJPEG 流使用有限 read 超时，而非 timeout=None。"""
    from autopilot.inspector.stream.mjpeg_source import MjpegScreenSource
    import httpx

    captured: dict = {}

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class _Resp:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def iter_bytes(self):
            return iter([])

    def _fake_stream(_method, _url, timeout=None):
        captured["timeout"] = timeout
        return _Resp()

    src = MjpegScreenSource("http://127.0.0.1:9100")
    src._stop = True   # 立即退出循环
    with patch("httpx.stream", side_effect=_fake_stream):
        src.run()

    t = captured.get("timeout")
    ok = isinstance(t, httpx.Timeout) and t.read == 10.0
    print("S5 MJPEG read=10s 超时:", "✅" if ok else "❌", t)
    return ok


# ---- S6–S8：DeviceMixin 恢复策略 ----

def _make_device_mixin_stub(**kwargs):
    from autopilot.ui.main_window.device import DeviceMixin

    class _Stub(DeviceMixin):
        mirror: MagicMock

    obj = _Stub()
    obj.mirror = MagicMock()
    obj.mirror.active.return_value = True
    obj.mirror._stopping = False          # MagicMock 默认子属性为真，会误触 early-return
    obj.mirror.swap_video = MagicMock(return_value=True)
    obj._stopping = False
    obj._mirror_avf_active = kwargs.get("avf_active", False)
    obj._mirror_avf_retries = kwargs.get("avf_retries", 0)
    obj._inspect_platform = kwargs.get("platform", "iOS")
    obj._inspect_ctx = kwargs.get("inspect_ctx", None)
    obj._inspect_udid = kwargs.get("udid", "U1")
    obj.console = MagicMock()
    for k, v in kwargs.items():
        if k.startswith("fn_"):
            setattr(obj, k[3:], v)
    return obj


def test_video_failed_avf_retries_helper() -> bool:
    """S6：AVF 断流 → swap_video 重启 helper，递增重试计数。"""
    obj = _make_device_mixin_stub(avf_active=True, avf_retries=0)
    with patch("autopilot.mobile.ios_mirror.avf_helper_path", return_value="/x/ios-avf-capture"), \
            patch("autopilot.mobile.ios_mirror.allows_mjpeg_fallback", return_value=True):
        ok_ret = obj._on_mirror_video_failed("管道 EOF")
    ok = (
        ok_ret is True
        and obj._mirror_avf_retries == 1
        and obj.mirror.swap_video.called
        and obj.mirror.swap_video.call_args[0][1].get("avf_capture") is True
    )
    print("S6 AVF 重启 helper:", "✅" if ok else "❌")
    return ok


def test_video_failed_mjpeg_reconnect() -> bool:
    """S7：MJPEG 模式静默断流 → 重连 9100。"""
    obj = _make_device_mixin_stub(avf_active=False)
    obj._ios_session_alive = lambda: True
    obj._build_ios_mjpeg_mirror_opts = lambda: {"mjpeg_url": "http://127.0.0.1:9100"}
    ok_ret = obj._on_mirror_video_failed("画面已超过 12s 无新帧")
    ok = ok_ret is True and obj.mirror.swap_video.called
    args = obj.mirror.swap_video.call_args[0]
    ok = ok and args[0] == "ios" and "mjpeg_url" in args[1]
    print("S7 MJPEG 重连:", "✅" if ok else "❌")
    return ok


def test_video_failed_mjpeg_skips_without_wda() -> bool:
    """S8：无 WDA 会话 → 不盲目重连 MJPEG。"""
    obj = _make_device_mixin_stub(avf_active=False)
    obj._ios_session_alive = lambda: False
    obj._build_ios_mjpeg_mirror_opts = lambda: {"mjpeg_url": "http://127.0.0.1:9100"}
    ok_ret = obj._on_mirror_video_failed("静默挂起")
    ok = ok_ret is False and not obj.mirror.swap_video.called
    print("S8 无 WDA 不重连:", "✅" if ok else "❌")
    return ok


def test_video_failed_avf_exhausted_hands_off_mjpeg() -> bool:
    """S6 延伸：AVF 重试耗尽 → 回退 MJPEG（生产默认）。"""
    obj = _make_device_mixin_stub(avf_active=True, avf_retries=3)
    obj._handoff_to_mjpeg = MagicMock(return_value=True)
    with patch("autopilot.mobile.ios_mirror.allows_mjpeg_fallback", return_value=True):
        ok_ret = obj._on_mirror_video_failed("重试耗尽")
    ok = ok_ret is True and obj._handoff_to_mjpeg.called
    print("S6 AVF 耗尽回退 MJPEG:", "✅" if ok else "❌")
    return ok


def main() -> int:
    tests = [
        test_stale_watchdog_constants,
        test_stale_watchdog_fires_on_gap,
        test_stale_watchdog_skips_when_recent_frame,
        test_stale_watchdog_skips_before_first_frame,
        test_on_frame_refreshes_stale_clock,
        test_start_stop_stale_watch,
        test_avf_select_uses_five_second_timeout,
        test_avf_stop_unblocks_stalled_reader,
        test_mjpeg_httpx_read_timeout_configured,
        test_video_failed_avf_retries_helper,
        test_video_failed_mjpeg_reconnect,
        test_video_failed_mjpeg_skips_without_wda,
        test_video_failed_avf_exhausted_hands_off_mjpeg,
    ]
    results = []
    for fn in tests:
        # noinspection PyBroadException
        try:
            results.append(fn())
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            print(f"{fn.__name__}: ❌ 异常 {e}")
            results.append(False)
    ok = all(results)
    print("\n总结:", f"{'✅ 镜像静默断流修复全绿' if ok else '❌ 存在失败'}",
          f"({sum(results)}/{len(results)})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
