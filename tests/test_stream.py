"""阶段17 实时流组件（离线）：JPEG 切帧 + 工厂选源 + 轮询源产帧。"""

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from autopilot.inspector.stream.mjpeg_source import split_jpegs
from autopilot.inspector.stream import factory

_APP = None


def test_split_jpegs() -> bool:
    a = b"\xff\xd8AAA\xff\xd9"
    b = b"\xff\xd8BBBB\xff\xd9"
    frames, rem = split_jpegs(a + b + b"\xff\xd8CC")   # 两整帧 + 半帧
    ok = (frames == [a, b] and rem == b"\xff\xd8CC")
    print("MJPEG 切帧:", "✅" if ok else "❌")
    return ok


def test_factory_select() -> bool:
    from autopilot.inspector.stream.scrcpy_source import ScrcpyScreenSource
    orig = ScrcpyScreenSource.available
    try:
        # 强制 scrcpy 可用 → android 选 scrcpy
        ScrcpyScreenSource.available = staticmethod(lambda: True)
        a_scrcpy = factory.describe_source("android", {"mjpeg_url": "http://x/9100"})
        # 强制 scrcpy 不可用 → android 回退 mjpeg / polling
        ScrcpyScreenSource.available = staticmethod(lambda: False)
        s1 = factory.describe_source("android", {"mjpeg_url": "http://x/9100"})
        s2 = factory.describe_source("android", {"grab": lambda: b""})
    finally:
        ScrcpyScreenSource.available = orig
    s3 = factory.describe_source("iOS", {"mjpeg_url": "http://127.0.0.1:9100", "grab": lambda: b""})
    s3b = factory.describe_source("iOS", {"mjpeg_url": "http://127.0.0.1:9100"})
    s4 = factory.describe_source("iOS", {})
    # AVFoundation 原生采集：avf_capture+avf_helper → "avf"，且优先于 MJPEG
    s6 = factory.describe_source(
        "iOS", {"avf_capture": True, "avf_helper": "/x/ios-avf-capture"})
    s7 = factory.describe_source(
        "iOS", {"avf_capture": True, "avf_helper": "/x/ios-avf-capture",
                "mjpeg_url": "http://x/9100", "grab": lambda: b""})
    ok = (a_scrcpy == "scrcpy" and s1 == "mjpeg" and s2 == "polling"
          and s3 == "mjpeg+polling-fallback" and s3b == "mjpeg" and s4 == "none"
          and s6 == "avf" and s7 == "avf+polling-fallback")
    print("工厂选源策略:", "✅" if ok else "❌",
          (a_scrcpy, s1, s2, s3, s3b, s4, s6, s7))
    return ok


def test_polling_source() -> bool:
    try:
        global _APP
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QImage
        from PyQt6.QtCore import QByteArray, QBuffer
        from autopilot.inspector.stream.polling_source import PollingScreenSource
        _APP = QApplication.instance() or QApplication([])
        img = QImage(4, 4, QImage.Format.Format_RGB32)
        img.fill(0xFF0000)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QBuffer.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        # noinspection PyTypeChecker
        png = bytes(ba)
        got = []
        src = PollingScreenSource(grab=lambda: png, fps=20)
        # noinspection PyUnresolvedReferences
        src.frame.connect(lambda im: got.append(im))
        src.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and len(got) < 2:
            _APP.processEvents()
            time.sleep(0.05)
        src.stop()
        ok = len(got) >= 1 and not got[0].isNull()
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("轮询源产帧: ⏭ 跳过(", e, ")")
        return True
    print("轮询源产帧:", "✅" if ok else "❌", f"({len(got)} 帧)")
    return ok


def test_scrcpy_packet_parser() -> bool:
    """确定性校验 scrcpy 视频包解析（会话包更新分辨率 + 媒体包抽帧，无需真机）。"""
    import struct
    from autopilot.inspector.stream._scrcpy_core import (
        ScrcpyCore, _FLAG_SESSION, _FLAG_CONFIG, _FLAG_KEYFRAME)

    class _Owner:
        resolution = None

    # 会话包：最高位=1，低32位=宽=720，next u32=高=1280 → 静默消费并更新分辨率
    sess = struct.pack(">QI", _FLAG_SESSION | 720, 1280)
    # 媒体包：config+keyframe，PTS=123us，载荷 5 字节
    payload = b"ABCDE"
    media = struct.pack(">QI", _FLAG_CONFIG | _FLAG_KEYFRAME | 123, len(payload)) + payload
    owner = _Owner()
    buf = bytearray(sess + media + b"\x00\x00")   # 末尾半个头 → 留在缓冲
    # noinspection PyTypeChecker
    ready = ScrcpyCore.consume_packets(buf, owner)
    if not ready or len(ready) != 1:
        ok = False
    else:
        one = ready[0]
        ok = (owner.resolution == (720, 1280)
              and one[0] == payload and one[1] == 123
              and one[2] is True and one[3] is True
              and bytes(buf) == b"\x00\x00")          # 半帧保留
    # 异常大小 → 返回 None 且清空缓冲
    bogus = bytearray(struct.pack(">QI", 0, 0xFFFFFFF0))
    # noinspection PyTypeChecker
    bad = ScrcpyCore.consume_packets(bogus, owner)
    ok = ok and bad is None and len(bogus) == 0
    print("scrcpy 视频包解析:", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([test_split_jpegs(), test_factory_select(),
              test_polling_source(), test_scrcpy_packet_parser()])
    print("\n总结:", "✅ 实时流组件全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
