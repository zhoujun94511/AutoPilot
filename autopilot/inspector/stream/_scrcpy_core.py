"""scrcpy 视频采集+解码核心（精简、视频-only）。

仅保留 Inspector 实时镜像所需的部分：部署 scrcpy-server → adb reverse 隧道 →
读视频 socket → 解析 scrcpy 视频包 → PyAV 解 H.264 → 回调原始 RGB 帧。
不含音频/控制/剪贴板/WebRTC（投屏只看不控，控制由 WDA/Appium 走）。

协议依据 Genymobile/scrcpy `doc/develop.md`：
  设备名(64B) + 视频前导(4B codec + 1B session_flags + 3B pad + u32 w + u32 h)，
  随后每包 12B 头：最高位=会话包(随旋转/重置更新分辨率)，否则媒体包
  (config/keyframe 标志 + 61bit PTS(us) + u32 载荷长度) + 载荷。

依赖：av(PyAV)、adbutils。available() 缺任一即不可用，工厂自动回退。
"""

from __future__ import annotations

import logging
import os
import random
import socket
import struct
import threading
import time
from typing import Callable, Optional

_log = logging.getLogger(__name__)

SERVER_VERSION = "4.0"

# 视频流 wire-format 常量（与上游一致）
_HDR = 12
_FLAG_SESSION = 1 << 63
_FLAG_CONFIG = 1 << 62
_FLAG_KEYFRAME = 1 << 61
_PTS_MASK = (1 << 61) - 1
_MAX_PAYLOAD = 64 * 1024 * 1024

# 控制消息类型（scrcpy server，与 doc/develop.md 一致）
_CTRL_KEYCODE = 0
_CTRL_TEXT = 1
_CTRL_TOUCH = 2
_CTRL_SCROLL = 3
_CTRL_BACK = 4
_CTRL_EXPAND_NOTIFICATION = 5
_CTRL_EXPAND_SETTINGS = 6
_CTRL_COLLAPSE_PANELS = 7
_CTRL_SET_CLIPBOARD = 9
_CTRL_SET_POWER_MODE = 10
_CTRL_ROTATE = 11
# Android MotionEvent action / KeyEvent keycode
_ACT_DOWN, _ACT_UP, _ACT_MOVE = 0, 1, 2
KEYCODE = {"home": 3, "back": 4, "app_switch": 187, "enter": 66, "delete": 67,
           "volume_up": 24, "volume_down": 25, "power": 26, "menu": 82}
POWER_MODE_OFF, POWER_MODE_NORMAL = 0, 2
_TOUCH_ID = 0x1234567887654321


def build_touch(action: int, x: float, y: float, w: int, h: int) -> bytes:
    """TYPE_INJECT_TOUCH_EVENT 报文（含类型字节）。压力=1.0、单指。"""
    return struct.pack(">BBqiiHHHii", _CTRL_TOUCH, action, _TOUCH_ID,
                       int(x), int(y), int(w), int(h), 0xFFFF, 1, 1)


def build_text(s: str) -> bytes:
    buf = s.encode("utf-8")
    return struct.pack(">Bi", _CTRL_TEXT, len(buf)) + buf


def build_keycode(keycode: int, action: int = _ACT_DOWN, repeat: int = 0, meta: int = 0) -> bytes:
    return struct.pack(">BBiii", _CTRL_KEYCODE, action, int(keycode), repeat, meta)


def build_scroll(x: float, y: float, w: int, h: int, hscroll: float, vscroll: float) -> bytes:
    """TYPE_INJECT_SCROLL_EVENT：hscroll/vscroll 为 i16 定点(±32767=±1屏)。"""
    def fx(raw):
        n = max(-1.0, min(1.0, raw / 1200.0))
        return max(-32767, min(32767, int(round(n * 32767))))
    return struct.pack(">BiiHHhhi", _CTRL_SCROLL, int(x), int(y),
                       int(w), int(h), fx(hscroll), fx(vscroll), 0)


def build_back(action: int = _ACT_DOWN) -> bytes:
    return struct.pack(">BB", _CTRL_BACK, action)


def build_simple(ctrl_type: int) -> bytes:
    """无载荷控制报文（展开通知/设置、收起面板、旋转）。"""
    return struct.pack(">B", ctrl_type)


def build_power(mode: int) -> bytes:
    return struct.pack(">Bb", _CTRL_SET_POWER_MODE, mode)


def build_set_clipboard(text: str, paste: bool = True, sequence: int = 0) -> bytes:
    buf = text.encode("utf-8")
    return struct.pack(">BQ?i", _CTRL_SET_CLIPBOARD, sequence, paste, len(buf)) + buf


def deps_ok() -> bool:
    # noinspection PyBroadException
    try:
        # noinspection PyPackageRequirements
        import av  # noqa: F401
        # noinspection PyPackageRequirements
        import adbutils  # noqa: F401
        return True
    except Exception:
        return False


class ScrcpyCore:
    """连接一台设备、把解码出的 RGB 帧通过 on_frame(rgb_bytes, w, h, stride) 回调出去。"""

    def __init__(self, server_jar: str, serial: str = "",
                 max_width: int = 0, bitrate: int = 8_000_000, max_fps: int = 0) -> None:
        self.server_jar = server_jar
        self.serial = serial
        self.max_width = max_width
        self.bitrate = bitrate
        self.max_fps = max_fps
        self.on_frame: Optional[Callable[[bytes, int, int, int], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.alive = False
        self.resolution: Optional[tuple] = None
        self.scid = random.randint(0, 0x7FFFFFFF)
        self.scid_hex = f"{self.scid:08x}"
        self.socket_name = f"scrcpy_{self.scid_hex}"
        self._device = None
        self._server_stream = None
        self._listen_sock: Optional[socket.socket] = None
        self._video_sock: Optional[socket.socket] = None
        self._control_sock: Optional[socket.socket] = None
        self._control_lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    # ---- 启动/停止 ----
    def start(self) -> bool:
        # noinspection PyPackageRequirements
        import adbutils
        self._device = (adbutils.adb.device(serial=self.serial) if self.serial
                        else adbutils.adb.device_list()[0])
        if not self._deploy_server():
            self.stop()
            return False
        if not self._init_connection():
            self.stop()
            return False
        self.alive = True
        self._thread = threading.Thread(target=self._stream_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self.alive = False
        for attr in ("_video_sock", "_control_sock", "_listen_sock"):
            s = getattr(self, attr, None)
            if s is not None:
                # noinspection PyBroadException
                try:
                    s.close()
                except Exception:
                    pass
                setattr(self, attr, None)
        if self._server_stream is not None:
            # noinspection PyBroadException
            try:
                self._server_stream.close()
            except Exception:
                pass
            self._server_stream = None
        # 移除 adb reverse 隧道（否则每次镜像残留一条 localabstract 映射，逐渐堆积）
        if self._device is not None:
            # noinspection PyBroadException
            try:
                self._device.reverse_remove(f"localabstract:{self.socket_name}")
            except Exception:
                pass

    # ---- 连接握手 ----
    def _open_listen(self) -> int:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        s.listen(3)
        s.settimeout(3.0)
        self._listen_sock = s
        return s.getsockname()[1]

    def _deploy_server(self) -> bool:
        if not os.path.exists(self.server_jar):
            self._fail(f"scrcpy-server 不存在：{self.server_jar}")
            return False
        jar = os.path.basename(self.server_jar)
        remote = f"/data/local/tmp/{jar}"
        # noinspection PyBroadException
        try:
            self._device.sync.push(self.server_jar, remote)
        except Exception as e:  # noqa: BLE001
            self._fail(f"推送 scrcpy-server 失败：{e}")
            return False
        # adb reverse 隧道：设备侧 localabstract → 本机 listen 端口
        # noinspection PyBroadException
        try:
            port = self._open_listen()
            self._device.reverse(f"localabstract:{self.socket_name}", f"tcp:{port}")
        except Exception as e:  # noqa: BLE001
            self._fail(f"建立 adb reverse 隧道失败：{e}")
            return False
        # 只传与默认不同的最小选项（避免某些 ROM 上 server 参数栈溢出 SIGABRT）
        cmd = [
            f"CLASSPATH={remote}", "app_process", "/",
            "com.genymobile.scrcpy.Server", SERVER_VERSION,
            f"scid={self.scid_hex}", "log_level=info",
            f"max_size={self.max_width}" if self.max_width else None,
            f"max_fps={self.max_fps}" if self.max_fps else None,
            f"video_bit_rate={self.bitrate}" if self.bitrate else None,
            "video_codec_options=i-frame-interval=2",
            "control=true", "audio=false",
        ]
        cmd = [c for c in cmd if c is not None]
        # noinspection PyBroadException
        try:
            self._server_stream = self._device.shell(cmd, stream=True)
            self._server_stream.read(10)  # 等 server 起来
            return True
        except Exception as e:  # noqa: BLE001
            self._fail(f"启动 scrcpy-server 失败：{e}")
            return False

    @staticmethod
    def _recv_exact(sock: socket.socket, size: int) -> bytes:
        buf = bytearray()
        while len(buf) < size:
            chunk = sock.recv(size - len(buf))
            if not chunk:
                break
            buf.extend(chunk)
        return bytes(buf)

    def _init_connection(self) -> bool:
        if self._listen_sock is None:
            return False
        # noinspection PyBroadException
        try:
            self._video_sock, _ = self._listen_sock.accept()
            self._video_sock.settimeout(3.0)
            name = self._recv_exact(self._video_sock, 64)
            if not name:
                self._fail("未收到设备名（握手失败）")
                return False
            preamble = self._recv_exact(self._video_sock, 16)
            if len(preamble) != 16:
                self._fail("未收到视频编解码元数据")
                return False
            width, height = struct.unpack(">II", preamble[8:16])
            if 0 < width <= 10000 and 0 < height <= 10000:
                self.resolution = (width, height)
            self._video_sock.setblocking(False)
            # 控制 socket（control=true 时 server 在视频之后再开一路）
            # noinspection PyBroadException
            try:
                self._control_sock, _ = self._listen_sock.accept()
                self._control_sock.setblocking(True)
            except Exception:
                self._control_sock = None  # 控制不可用不阻断画面
            return True
        except Exception as e:  # noqa: BLE001
            self._fail(f"初始化 scrcpy 连接失败：{e}")
            return False

    # ---- 控制（投递到设备；无控制 socket 时回退 adb shell input）----
    def _send_control(self, payload: bytes) -> bool:
        if self._control_sock is None:
            return False
        # noinspection PyBroadException
        try:
            with self._control_lock:
                self._control_sock.send(payload)
            return True
        except Exception:
            return False

    def _res(self) -> tuple:
        return self.resolution or (1080, 1920)

    def tap(self, x: float, y: float) -> None:
        w, h = self._res()
        if self._control_sock is None:
            self._shell("input", "tap", str(int(x)), str(int(y)))
            return
        self._send_control(build_touch(_ACT_DOWN, x, y, w, h))
        self._send_control(build_touch(_ACT_UP, x, y, w, h))

    def swipe(self, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 200) -> None:
        w, h = self._res()
        if self._control_sock is None:
            self._shell("input", "swipe", str(int(x1)), str(int(y1)),
                        str(int(x2)), str(int(y2)), str(int(duration_ms)))
            return
        dx, dy = x2 - x1, y2 - y1
        dist = (dx * dx + dy * dy) ** 0.5
        steps = max(8, min(int(dist // 25), 25))
        delay = duration_ms / steps / 1000.0
        self._send_control(build_touch(_ACT_DOWN, x1, y1, w, h))
        for i in range(1, steps + 1):
            self._send_control(build_touch(_ACT_MOVE, x1 + dx * i / steps,
                                           y1 + dy * i / steps, w, h))
            time.sleep(delay)
        self._send_control(build_touch(_ACT_UP, x2, y2, w, h))

    def text(self, s: str) -> None:
        # 非 ASCII（中文/emoji 等）：scrcpy INJECT_TEXT 与 adb `input text` 都丢弃，
        # 改走「写设备剪贴板 + 触发粘贴」（scrcpy 自身对非 ASCII 也是这么做）。
        if s and any(ord(c) > 127 for c in s):
            self.set_clipboard(s, paste=True)
            return
        if self._control_sock is None:
            self._shell("input", "text", s.replace(" ", "%s"))
            return
        self._send_control(build_text(s))

    def keycode(self, code: int) -> None:
        if self._control_sock is None:
            self._shell("input", "keyevent", str(code))
            return
        self._send_control(build_keycode(code, _ACT_DOWN))
        self._send_control(build_keycode(code, _ACT_UP))

    def back(self) -> None:
        if self._control_sock is None:
            self._shell("input", "keyevent", str(KEYCODE["back"]))
            return
        self._send_control(build_back(_ACT_DOWN))
        self._send_control(build_back(_ACT_UP))

    def scroll(self, x: float, y: float, dx: float, dy: float) -> None:
        w, h = self._res()
        if self._control_sock is None:
            self.swipe(x, y, x - dx, y - dy, 120)
            return
        self._send_control(build_scroll(x, y, w, h, dx, dy))

    def long_press(self, x: float, y: float, duration_ms: int = 600) -> None:
        w, h = self._res()
        if self._control_sock is None:
            self._shell("input", "swipe", str(int(x)), str(int(y)),
                        str(int(x)), str(int(y)), str(int(duration_ms)))   # 原地 swipe=长按
            return
        self._send_control(build_touch(_ACT_DOWN, x, y, w, h))
        time.sleep(duration_ms / 1000.0)
        self._send_control(build_touch(_ACT_UP, x, y, w, h))

    def double_tap(self, x: float, y: float) -> None:
        self.tap(x, y)
        time.sleep(0.05)
        self.tap(x, y)

    def expand_notifications(self) -> None:
        if not self._send_control(build_simple(_CTRL_EXPAND_NOTIFICATION)):
            self._shell("cmd", "statusbar", "expand-notifications")

    def expand_settings(self) -> None:
        if not self._send_control(build_simple(_CTRL_EXPAND_SETTINGS)):
            self._shell("cmd", "statusbar", "expand-settings")

    def collapse_panels(self) -> None:
        if not self._send_control(build_simple(_CTRL_COLLAPSE_PANELS)):
            self._shell("cmd", "statusbar", "collapse")

    def rotate(self) -> None:
        # scrcpy ROTATE_DEVICE(11) 在不少设备/服务端实测无效，改用 adb 强制 user_rotation
        # 轮转（关自动旋转后 0→1→2→3）——跨设备可靠。
        cur = 0
        # noinspection PyBroadException
        try:
            if self._device is not None:
                out = self._device.shell("settings get system user_rotation")
                cur = int((out or "0").strip() or 0)
        except Exception:
            cur = 0
        self._shell("settings", "put", "system", "accelerometer_rotation", "0")
        self._shell("settings", "put", "system", "user_rotation", str((cur + 1) % 4))

    def power(self, mode: int) -> None:
        # 注：SET_SCREEN_POWER_MODE 只控镜像背光、非按电源键；锁屏/唤醒请用 keycode(power)。
        if not self._send_control(build_power(mode)):
            self._shell("input", "keyevent", str(KEYCODE["power"]))

    def set_clipboard(self, text: str, paste: bool = True) -> None:
        if not self._send_control(build_set_clipboard(text, paste)):
            # 兜底：仅写入剪贴板（无法触发粘贴）
            self._shell("am", "broadcast", "-a", "clipper.set", "-e", "text", text)

    def get_clipboard(self, timeout: float = 1.5) -> str:
        """读设备剪贴板：发 GET_CLIPBOARD，从控制 socket 读回设备消息(CLIPBOARD)。

        控制 socket 平时只写、无人读，这里持锁做一次同步请求-应答；非剪贴板设备消息
        (ACK/未知)best-effort 跳过或放弃。失败返回空串。"""
        sock = self._control_sock
        if sock is None:
            return ""
        _CTRL_GET_CLIPBOARD, _DEV_CLIPBOARD, _DEV_ACK = 8, 0, 1
        result = ""
        # noinspection PyBroadException
        try:
            with self._control_lock:
                sock.settimeout(timeout)
                sock.send(struct.pack(">BB", _CTRL_GET_CLIPBOARD, 0))
                for _ in range(6):                       # 跳过有限个非剪贴板消息
                    head = self._recv_exact(sock, 1)
                    if not head:
                        break
                    mtype = head[0]
                    if mtype == _DEV_CLIPBOARD:
                        raw = self._recv_exact(sock, 4)  # u32 长度（不足 4 字节=断流，放弃）
                        if len(raw) != 4:
                            break
                        ln = struct.unpack(">I", raw)[0]
                        data = self._recv_exact(sock, ln) if ln else b""
                        result = data.decode("utf-8", "replace")
                        break
                    if mtype == _DEV_ACK:                # ACK_CLIPBOARD：u64 序列，跳过
                        self._recv_exact(sock, 8)
                        continue
                    break                                # 未知类型长度不定 → 放弃
        except Exception:
            result = ""
        finally:
            # noinspection PyBroadException
            try:
                sock.setblocking(True)                   # 复原阻塞，不影响后续写
            except Exception:
                pass
        return result

    def _shell(self, *args) -> None:
        # noinspection PyBroadException
        try:
            if self._device is not None:
                self._device.shell(list(args))
        except Exception:
            pass

    # ---- 取流+解码 ----
    @staticmethod
    def consume_packets(buf: bytearray, owner: "ScrcpyCore | None" = None):
        """从 buf 中抽出完整视频包；会话包静默消费(更新分辨率)，媒体包入列。

        返回 (frame_bytes, pts_us, is_keyframe, is_config) 列表；
        头部异常返回 None（调用方丢缓冲重新同步）。"""
        ready: list = []
        while True:
            if len(buf) < _HDR:
                return ready
            head_lo, head_hi = struct.unpack(">QI", buf[:_HDR])
            if head_lo & _FLAG_SESSION:
                new_w = head_lo & 0xFFFFFFFF
                new_h = head_hi
                if owner is not None and new_w and new_h:
                    owner.resolution = (int(new_w), int(new_h))
                del buf[:_HDR]
                continue
            size = head_hi
            if size == 0 or size > _MAX_PAYLOAD:
                buf.clear()
                return None
            if len(buf) < _HDR + size:
                return ready
            frame_bytes = bytes(buf[_HDR:_HDR + size])
            del buf[:_HDR + size]
            ready.append((frame_bytes,
                          head_lo & _PTS_MASK,
                          bool(head_lo & _FLAG_KEYFRAME),
                          bool(head_lo & _FLAG_CONFIG)))

    def _stream_loop(self) -> None:
        # noinspection PyPackageRequirements
        from av.codec import CodecContext
        # noinspection PyPackageRequirements
        from av.error import InvalidDataError
        codec = CodecContext.create("h264", "r")
        buf = bytearray()
        while self.alive and self._video_sock is not None:
            try:
                chunk = self._video_sock.recv(0x10000)
                if chunk == b"":
                    break
                buf.extend(chunk)
                ready = ScrcpyCore.consume_packets(buf, self)
                if ready is None:
                    continue
                for frame_bytes, _pts, _key, _cfg in ready:
                    self._decode_emit(codec, frame_bytes)
            except (BlockingIOError, InvalidDataError):
                time.sleep(0.005)
            except (ConnectionError, OSError) as e:
                if self.alive:
                    self._fail(f"视频流中断：{e}")
                break

    def _decode_emit(self, codec, frame_bytes: bytes) -> None:
        if self.on_frame is None:
            return
        for packet in codec.parse(frame_bytes):
            for frame in codec.decode(packet):
                rgb = frame.reformat(format="rgb24")
                plane = rgb.planes[0]
                self.on_frame(bytes(plane), rgb.width, rgb.height, plane.line_size)

    def _fail(self, msg: str) -> None:
        _log.error(msg)
        if self.on_error is not None:
            self.on_error(msg)
