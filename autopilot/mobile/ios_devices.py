"""已连接 iOS 真机枚举（usbmux / pymobiledevice3，失败时 go-ios 回退）。"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass

from ..runtime.subproc import run as run_hidden

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IosUsbDevice:
    udid: str
    name: str
    product_type: str
    ios_version: str
    connection: str = "USB"

    @property
    def label(self) -> str:
        return f"{self.name} iOS {self.ios_version} ({self.product_type})"


#: 最近一次工具链失败原因（枚举为空时给出可行动的提示，而不是「没插设备」）
_TOOL_ERRORS: dict[str, str] = {}


def _note_tool_error(tool: str, message: str) -> None:
    msg = (message or "").strip()
    if msg:
        _TOOL_ERRORS[tool] = msg[:300]
        log.warning("iOS 设备枚举失败（%s）：%s", tool, msg[:300])
    else:
        _TOOL_ERRORS.pop(tool, None)


def ios_tooling_error() -> str:
    """枚举工具链的最近失败原因；空串表示工具链正常或尚未探测。"""
    parts = [f"{tool}: {msg}" for tool, msg in sorted(_TOOL_ERRORS.items())]
    return "；".join(parts)


def note_enumeration_error(tool: str, message: str) -> None:
    """供外层枚举包装（如 ``mgmt.local_devices``）留痕，别让异常静默变成「没设备」。"""
    _note_tool_error(tool, message)


def ios_tooling_available() -> bool:
    """本机是否具备 iOS 设备通道（pymobiledevice3 可用或 go-ios 存在）。"""
    try:
        import importlib.util

        if importlib.util.find_spec("pymobiledevice3") is not None:
            return True
    except (ImportError, ValueError):
        pass
    try:
        from autopilot.mobile.ios_bootstrap import resolve_go_ios

        return resolve_go_ios() is not None
    except (ImportError, OSError, RuntimeError):
        return False


#: 禁掉 click/rich 颜色，避免 JSON 被 ANSI 污染后解析失败
_CLI_ENV_EXTRA = {
    "NO_COLOR": "1",
    "FORCE_COLOR": "0",
    "TERM": "dumb",
    "PYTHONIOENCODING": "utf-8",
}

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _decode(raw: bytes | str | None) -> str:
    """子进程输出解码：宽容处理非法字节。

    ``subprocess`` 的 ``text=True`` 按控制台编码严格解码，GBK 环境下一个非法字节就抛
    ``UnicodeDecodeError``（在 ``_readerthread`` 里炸，主流程还以为命令成功了）。
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    return raw.decode("utf-8", "replace")


def strip_ansi(text: str) -> str:
    """去掉 CSI 颜色码（日志里常见尾部 ``\\x1b[0m``）。跨模块可复用。"""
    return _ANSI_RE.sub("", text or "")


def cli_subprocess_env() -> dict[str, str]:
    """跑 pymobiledevice3 / go-ios 子进程时的环境：禁颜色、强制 UTF-8。"""
    env = dict(os.environ)
    env.update(_CLI_ENV_EXTRA)
    return env


def _extract_json_array(text: str) -> str:
    """从可能夹带日志行的输出里截出 JSON 数组；截不到返回空串。"""
    s = strip_ansi(text or "").strip()
    if s.startswith("["):
        return s
    start, end = s.find("["), s.rfind("]")
    if 0 <= start < end:
        return s[start : end + 1]
    return ""


def parse_usbmux_list(stdout: str) -> list[IosUsbDevice]:
    """解析 ``pymobiledevice3 usbmux list`` 输出（允许日志/ANSI 包在 JSON 外）。"""
    clean = strip_ansi(stdout)
    try:
        raw = json.loads(_extract_json_array(clean))
    except (json.JSONDecodeError, TypeError, ValueError):
        # 输出不是 JSON（日志刷屏 / 新版换成表格）时按 UDID 兜底，别当成「没设备」
        return _parse_goios_list(clean)
    out: list[IosUsbDevice] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        udid = str(item.get("UniqueDeviceID") or item.get("Identifier") or "").strip()
        if not udid:
            continue
        out.append(
            IosUsbDevice(
                udid=udid,
                name=str(item.get("DeviceName") or "iPhone"),
                product_type=str(item.get("ProductType") or ""),
                ios_version=str(item.get("ProductVersion") or ""),
                connection=str(item.get("ConnectionType") or "USB"),
            )
        )
    return out


def _parse_pmd3(stdout: str) -> list[IosUsbDevice]:
    return parse_usbmux_list(stdout)


def _list_via_pymobiledevice3(*, python: str | None = None) -> list[IosUsbDevice]:
    py = python or sys.executable
    try:
        r = run_hidden(
            [py, "-m", "pymobiledevice3", "usbmux", "list"],
            capture_output=True,
            timeout=30,
            env=cli_subprocess_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _note_tool_error("pymobiledevice3", str(exc))
        return []
    out, err = strip_ansi(_decode(r.stdout)), strip_ansi(_decode(r.stderr))
    if r.returncode != 0:
        # 依赖装坏（如缺 coloredlogs）也是非 0；不留痕就会表现成「没插设备」
        tail = (err or out).strip().splitlines()
        _note_tool_error(
            "pymobiledevice3",
            tail[-1] if tail else f"exit={r.returncode}",
        )
        return []
    devices = parse_usbmux_list(out)
    if devices:
        _note_tool_error("pymobiledevice3", "")  # 工具正常：清掉历史故障
        return devices
    stripped = out.strip()
    if not stripped:
        # 空输出或只剩 ANSI 颜色码：交给上层 inproc/go-ios，不谎报「无法解析」
        _note_tool_error("pymobiledevice3", "")
        return []
    # 合法空列表不要报「无法解析」
    try:
        parsed = json.loads(_extract_json_array(stripped) or "null")
        if isinstance(parsed, list) and not parsed:
            _note_tool_error("pymobiledevice3", "")
            return []
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    # rc=0 却解析不出设备：输出格式变了，必须留痕，否则同样被读成「没插设备」
    tail = [ln for ln in stripped.splitlines() if ln.strip()]
    hint = (tail[-1] if tail else stripped)[:120]
    _note_tool_error("pymobiledevice3", f"输出无法解析为设备列表：{hint}")
    return []


def _list_via_usbmux_inproc() -> list[IosUsbDevice] | None:
    """进程内 usbmux 枚举：零 spawn，不受控制台编码与 CLI 输出格式影响。

    仅拿得到 UDID（无型号/系统版本），因此只作为 CLI 的兜底。返回 ``None`` 表示该通道
    不可用，与「确实没插设备」的空列表区分。
    """
    try:
        import asyncio

        from pymobiledevice3.usbmux import list_devices
    except ImportError:
        return None
    try:
        res = list_devices()
        if asyncio.iscoroutine(res):
            res = asyncio.run(res)
    except Exception as exc:  # noqa: BLE001 — 通道异常一律留痕后回退，不能静默
        _note_tool_error("usbmux", str(exc))
        return None
    _note_tool_error("usbmux", "")
    out: list[IosUsbDevice] = []
    seen: set[str] = set()
    for d in res or []:
        udid = str(getattr(d, "serial", "") or getattr(d, "udid", "") or "").strip()
        if not udid or udid in seen:
            continue
        seen.add(udid)
        out.append(
            IosUsbDevice(udid=udid, name="iPhone", product_type="", ios_version="")
        )
    return out


_GOIOS_UDID_RE = re.compile(
    r"(?:UDID|Serial|Identifier)\s*[:=]\s*([0-9A-Fa-f-]{8,})",
    re.IGNORECASE,
)


def _devices_from_goios_payload(payload: object) -> list[IosUsbDevice]:
    """``ios list`` 的 JSON 对象/数组 → 设备列表。"""
    if isinstance(payload, dict):
        raw = payload.get("deviceList")
        if not isinstance(raw, list):
            return []
        payload = raw
    if not isinstance(payload, list):
        return []
    out: list[IosUsbDevice] = []
    for item in payload:
        if isinstance(item, str) and item.strip():
            out.append(
                IosUsbDevice(
                    udid=item.strip(),
                    name="iPhone",
                    product_type="",
                    ios_version="",
                )
            )
            continue
        if not isinstance(item, dict):
            continue
        udid = str(
            item.get("udid")
            or item.get("UDID")
            or item.get("UniqueDeviceID")
            or item.get("Identifier")
            or ""
        ).strip()
        if not udid:
            continue
        out.append(
            IosUsbDevice(
                udid=udid,
                name=str(item.get("name") or item.get("DeviceName") or "iPhone"),
                product_type=str(item.get("productType") or item.get("ProductType") or ""),
                ios_version=str(item.get("version") or item.get("ProductVersion") or ""),
            )
        )
    return out


def _parse_goios_list(text: str) -> list[IosUsbDevice]:
    """解析 ``ios list`` 文本或 JSON；仅需稳定 UDID。"""
    text = (text or "").strip()
    if not text:
        return []
    # JSONL：warning 行 + {"deviceList":[...]}（当前 go-ios 常见输出）
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        parsed = _devices_from_goios_payload(payload)
        if parsed:
            return parsed
    # JSON 数组
    if text.startswith("["):
        try:
            raw = json.loads(text)
        except (json.JSONDecodeError, TypeError, ValueError):
            raw = None
        parsed = _devices_from_goios_payload(raw)
        if parsed:
            return parsed
    # 行式 / 键值
    found: list[str] = []
    for line in text.splitlines():
        m = _GOIOS_UDID_RE.search(line)
        if m:
            found.append(m.group(1))
            continue
        # 常见：整行就是 40 位 hex UDID
        tok = line.strip().split()[0] if line.strip() else ""
        if re.fullmatch(r"[0-9A-Fa-f-]{25,}", tok):
            found.append(tok)
    # 去重保序
    seen: set[str] = set()
    out2: list[IosUsbDevice] = []
    for u in found:
        if u in seen:
            continue
        seen.add(u)
        out2.append(
            IosUsbDevice(udid=u, name="iPhone", product_type="", ios_version="")
        )
    return out2


def _list_via_goios() -> list[IosUsbDevice]:
    try:
        from autopilot.mobile.ios_bootstrap import resolve_go_ios

        exe = resolve_go_ios()
    except (ImportError, OSError):
        return []
    if exe is None:
        return []
    try:
        # 禁止 text=True：go-ios 列表含中文应用名时，GBK 控制台会在 _readerthread
        # 里抛 UnicodeDecodeError（byte 0x80），主流程表现为神秘线程异常。
        r = run_hidden(
            [str(exe), "list"],
            capture_output=True,
            timeout=30,
            env=cli_subprocess_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if r.returncode != 0 and not (r.stdout or r.stderr):
        return []
    text = strip_ansi(_decode(r.stdout) + "\n" + _decode(r.stderr))
    return _parse_goios_list(text)


def list_usb_devices(
    *,
    python: str | None = None,
    retries: int = 2,
    retry_delay_sec: float = 0.4,
) -> list[IosUsbDevice]:
    """枚举 USB iOS 设备。

    pymobiledevice3 CLI 优先（信息最全）；拿不到时用进程内 usbmux 兜底——设备插拔监测走
    的就是这条通道，两者结论必须一致，否则会出现「设备面板看得见、编写却说没插」。都空
    才短暂重试（应对刚插上的抖动），最后退 go-ios list。
    """
    inproc = _list_via_usbmux_inproc()
    rich = _list_via_pymobiledevice3(python=python)
    if rich:
        return rich
    if inproc:
        return inproc
    last: list[IosUsbDevice] = []
    for _ in range(max(0, int(retries))):
        if retry_delay_sec > 0:
            time.sleep(retry_delay_sec)
        last = _list_via_pymobiledevice3(python=python)
        if last:
            return last
    fallback = _list_via_goios()
    return fallback or last
