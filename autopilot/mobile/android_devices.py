"""已连接 Android 真机枚举（adb devices）。"""

from __future__ import annotations

from dataclasses import dataclass

from .adb import adb_available, run_adb
from .device_info import _android_prop_first


@dataclass(frozen=True)
class AndroidUsbDevice:
    serial: str
    state: str
    model: str = ""
    product: str = ""
    transport: str = ""

    @property
    def label(self) -> str:
        name = self.model or self.product or "Android"
        return f"{name} ({self.serial})"


def list_usb_devices(*, online_only: bool = True) -> list[AndroidUsbDevice]:
    """列出 adb 可见设备；online_only 时仅 state=device。"""
    if not adb_available():
        return []
    # noinspection PyBroadException
    try:
        out = run_adb(["devices", "-l"])
    except Exception:
        return []
    devs: list[AndroidUsbDevice] = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        if online_only and state != "device":
            continue
        meta = {p.split(":", 1)[0]: p.split(":", 1)[1]
                for p in parts[2:] if ":" in p}
        model = meta.get("model", "").replace("_", " ")
        product = meta.get("product", "")
        transport = meta.get("transport_id", "")
        if not model:
            model = _android_prop_first(serial, "ro.product.model", "ro.product.marketname")
        devs.append(AndroidUsbDevice(
            serial=serial, state=state, model=model,
            product=product, transport=transport,
        ))
    return devs
