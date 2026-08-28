"""已连接真机的设备信息汇总（设备层：adb / lockdown，不依赖 Appium 会话）。"""

from __future__ import annotations

import asyncio
import inspect
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class DeviceInfoSheet:
    platform: str          # android | ios
    device_id: str
    title: str
    rows: list[tuple[str, str]]


def _disp(value, empty: str = "—") -> str:
    if value is None or value == "" or value == [] or value == {}:
        return empty
    if isinstance(value, dict):
        return empty
    if isinstance(value, (list, tuple)):
        return "，".join(str(x) for x in value)
    return str(value)


def _android_getprop(serial: str, prop: str) -> str:
    from .adb import adb_shell
    return adb_shell(f"getprop {prop}", serial=serial).strip()


def _android_prop_first(serial: str, *props: str) -> str:
    for prop in props:
        v = _android_getprop(serial, prop)
        if v:
            return v
    return ""


def _android_wifi_ip(serial: str) -> str:
    from .adb import adb_shell
    # noinspection PyBroadException
    try:
        out = adb_shell("ip -f inet addr show wlan0", serial=serial)
        m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", out)
        if m:
            return m.group(1)
    except Exception:
        pass
    # noinspection PyBroadException
    try:
        out = adb_shell("ifconfig wlan0", serial=serial)
        m = re.search(r"(?:inet addr:|inet\s+)(\d+\.\d+\.\d+\.\d+)", out)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


def _android_abi(serial: str) -> str:
    abilist = _android_prop_first(serial, "ro.product.cpu.abilist", "ro.system.product.cpu.abilist")
    if abilist:
        return abilist.split(",")[0].strip()
    return _android_prop_first(serial, "ro.product.cpu.abi")


def _android_chip(serial: str) -> str:
    vendor = _android_prop_first(serial, "ro.soc.manufacturer", "ro.boot.hardware.platform")
    model = _android_prop_first(serial, "ro.soc.model", "ro.board.platform", "ro.hardware")
    if vendor and model:
        return f"{vendor} · {model}"
    return vendor or model


def collect_android_device_info(serial: str) -> DeviceInfoSheet:
    name = _android_prop_first(
        serial, "ro.product.marketname", "ro.product.model", "ro.product.name")
    brand = _android_prop_first(serial, "ro.product.brand")
    release = _android_prop_first(serial, "ro.build.version.release")
    sdk = _android_prop_first(serial, "ro.build.version.sdk")
    cpu_brand = _android_prop_first(serial, "ro.soc.manufacturer", "ro.product.cpu.abilist")
    cpu_model = _android_prop_first(serial, "ro.soc.model", "ro.board.platform", "ro.hardware")
    abi = _android_abi(serial)
    sn = _android_prop_first(serial, "ro.serialno") or serial

    size_out = ""
    dpi = ""
    from .adb import adb_shell
    # noinspection PyBroadException
    try:
        wm = adb_shell("wm size", serial=serial)
        m = re.search(r"(\d+x\d+)", wm)
        if m:
            size_out = m.group(1).replace("x", " × ")
    except Exception:
        pass
    # noinspection PyBroadException
    try:
        dm = adb_shell("wm density", serial=serial)
        m = re.search(r"(\d+)", dm)
        if m:
            dpi = m.group(1)
    except Exception:
        pass
    resolution = size_out
    if resolution and dpi:
        resolution = f"{resolution} · {dpi} dpi"

    rows = [
        ("设备名称", _disp(name)),
        ("设备品牌", _disp(brand)),
        ("安卓版本", _disp(release)),
        ("SDK 版本", _disp(sdk)),
        ("CPU 品牌", _disp(cpu_brand)),
        ("CPU 型号", _disp(cpu_model)),
        ("CPU 架构", _disp(abi)),
        ("设备序列号", _disp(sn)),
        ("IP 地址", _disp(_android_wifi_ip(serial))),
        ("芯片", _disp(_android_chip(serial))),
        ("分辨率", _disp(resolution)),
    ]
    return DeviceInfoSheet(
        platform="android",
        device_id=serial,
        title=f"Android 设备信息 · {name or serial}",
        rows=rows,
    )


def _pmd3_run(awaitable):
    """运行 pymobiledevice3 异步 API（与 session.ios_install_app 一致）。"""
    return asyncio.run(awaitable)


async def _await_maybe(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _ios_get_value(ld, key: str, domain: str | None = None) -> str:
    """读取 lockdown 单键。

    pymobiledevice3 签名为 ``get_value(domain=None, key=None)``：位置参数会进
    ``domain``，误写成 ``get_value("DeviceName")`` 会得到空 dict ``{}``，
    ``str({})`` 即界面上的 ``{}``。必须用关键字参数 ``key=``。

    磁盘容量等键在 ``com.apple.disk_usage`` 域，根域会 MissingValue。
    """
    # noinspection PyBroadException
    try:
        v = await _await_maybe(ld.get_value(domain=domain, key=key))
        if v is None or v == "" or v == {}:
            return ""
        if isinstance(v, bytes):
            return v.decode("utf-8", "replace")
        if isinstance(v, dict):
            # 误把整域当单值时不展示裸 {}
            return ""
        return str(v)
    except Exception:
        return ""


def _fmt_bytes(value) -> str:
    """字节数 → 可读容量（十进制 GB/MB，与 iOS 标称一致）。"""
    # noinspection PyBroadException
    try:
        n = int(value)
    except Exception:
        return ""
    if n < 0:
        return ""
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f} GB"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f} MB"
    if n >= 1_000:
        return f"{n / 1_000:.2f} KB"
    return f"{n} B"


async def _ios_disk_rows(ld) -> list[tuple[str, str]]:
    """从 com.apple.disk_usage 读磁盘信息（根域无这些键）。"""
    domain = "com.apple.disk_usage"
    # noinspection PyBroadException
    try:
        raw = await _await_maybe(ld.get_value(domain=domain))
    except Exception:
        raw = None
    if not isinstance(raw, dict):
        raw = {}

    def _num(*keys: str) -> int | None:
        for k in keys:
            v = raw.get(k)
            if v is None:
                continue
            # noinspection PyBroadException
            try:
                return int(v)
            except Exception:
                continue
        return None

    total = _num("TotalDiskCapacity")
    avail = _num("TotalDataAvailable", "AmountDataAvailable")
    data_cap = _num("TotalDataCapacity")
    used = None
    if total is not None and avail is not None:
        used = max(0, total - avail)
    elif data_cap is not None and avail is not None:
        used = max(0, data_cap - avail)

    block = await _ios_get_value(ld, "NANDBlockSize", domain=domain)
    if not block:
        block = await _ios_get_value(ld, "BlockSize", domain=domain)
    if not block:
        block = await _ios_get_value(
            ld, "NANDBlockSize", domain="com.apple.disk_usage.factory")

    return [
        ("存储块规格", _disp(f"{block} B" if block else "")),
        ("闲置空间", _disp(_fmt_bytes(avail) if avail is not None else "")),
        ("已使用空间", _disp(_fmt_bytes(used) if used is not None else "")),
        ("总体空间", _disp(_fmt_bytes(total) if total is not None else "")),
    ]


async def _ios_battery(ld) -> dict[str, str]:
    out: dict[str, str] = {}
    # noinspection PyBroadException
    try:
        from pymobiledevice3.services.diagnostics import DiagnosticsService
        ds_cm = DiagnosticsService(lockdown=ld)
        if hasattr(ds_cm, "__aenter__"):
            async with ds_cm as ds:
                raw = await _await_maybe(ds.ioregistry(ioclass="IOPMPowerSource"))
        else:
            ds = ds_cm
            raw = await _await_maybe(ds.ioregistry(ioclass="IOPMPowerSource"))
        if isinstance(raw, list) and raw:
            b = raw[0] if isinstance(raw[0], dict) else {}
        elif isinstance(raw, dict):
            b = raw
        else:
            b = {}
        cap = b.get("CurrentCapacity") or b.get("AppleRawCurrentCapacity")
        if cap is not None:
            out["电池容量"] = f"{cap}%"
        temp = b.get("Temperature")
        if temp is not None:
            try:
                out["电池温度"] = f"{float(temp) / 100:.2f}°C"
            except (TypeError, ValueError):
                out["电池温度"] = str(temp)
        volt = b.get("Voltage")
        if volt is not None:
            try:
                out["电池电压"] = f"{float(volt) / 1000:.3f} V"
            except (TypeError, ValueError):
                out["电池电压"] = str(volt)
        design = b.get("DesignCapacity")
        if design is not None:
            out["设计容量"] = f"{design} mAh"
        nominal = b.get("NominalChargeCapacity") or b.get("MaxCapacity")
        if nominal is not None:
            out["标称容量"] = f"{nominal} mAh"
    except Exception:
        pass
    return out


async def _collect_ios_sheet(udid: str) -> DeviceInfoSheet:
    from pymobiledevice3.lockdown import create_using_usbmux

    from .ios_marketing import marketing_name

    async with await create_using_usbmux(serial=udid or None) as ld:
        product_type = await _ios_get_value(ld, "ProductType")
        hardware = await _ios_get_value(ld, "HardwareModel")
        version = await _ios_get_value(ld, "ProductVersion")
        cpu = await _ios_get_value(ld, "CPUArchitecture")
        activation = await _ios_get_value(ld, "ActivationState")
        region = await _ios_get_value(ld, "RegionInfo")
        tz = await _ios_get_value(ld, "TimeZone")
        device_udid = await _ios_get_value(ld, "UniqueDeviceID") or udid
        imei1 = await _ios_get_value(ld, "InternationalMobileEquipmentIdentity")
        imei2 = await _ios_get_value(ld, "MobileEquipmentIdentifier")
        device_name = await _ios_get_value(ld, "DeviceName")
        marketing = marketing_name(product_type)

        rows: list[tuple[str, str]] = [
            ("设备名称", _disp(device_name)),
            ("设备品牌", _disp(await _ios_get_value(ld, "DeviceClass") or "iPhone OS")),
            ("产品型号", _disp(marketing)),
            ("产品标识", _disp(product_type if product_type and product_type != marketing else "")),
            ("内部型号", _disp(hardware)),
            ("系统版本", _disp(version)),
            ("CPU 架构", _disp(cpu)),
            ("激活状态", _disp(activation)),
            ("设备区域", _disp(region)),
            ("设备时区", _disp(tz)),
            ("UDID", _disp(device_udid)),
        ]
        if imei1:
            rows.append(("IMEI", _disp(imei1)))
        if imei2 and imei2 != imei1:
            rows.append(("IMEI ②", _disp(imei2)))
        battery = await _ios_battery(ld)
        if battery:
            rows.append(("— 电池信息 —", ""))
            for k, v in battery.items():
                rows.append((k, v))
        rows.append(("— 磁盘信息 —", ""))
        rows.extend(await _ios_disk_rows(ld))
        name = device_name or marketing or product_type or udid
        return DeviceInfoSheet(
            platform="ios",
            device_id=device_udid or udid,
            title=f"iOS 设备信息 · {name}",
            rows=rows,
        )


def collect_ios_device_info(udid: str) -> DeviceInfoSheet:
    return _pmd3_run(_collect_ios_sheet(udid))


def _ios_picker_caption(udid: str) -> str:
    """选机列表用：市场型号 · 设备名称（尽量轻量，失败/超时返回空）。"""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
    from .ios_marketing import marketing_name

    async def _go() -> str:
        from pymobiledevice3.lockdown import create_using_usbmux

        async with await create_using_usbmux(serial=udid or None) as ld:
            name = await _ios_get_value(ld, "DeviceName")
            product_type = await _ios_get_value(ld, "ProductType")
            marketing = marketing_name(product_type)
            if name and marketing and name != marketing:
                return f"{marketing} · {name}"
            return name or marketing or product_type or ""

    def _run() -> str:
        return str(_pmd3_run(_go()) or "")

    # noinspection PyBroadException
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            return str(pool.submit(_run).result(timeout=4.0) or "")
    except (FuturesTimeout, Exception):
        return ""


_PICKER_CAPTION_CACHE: dict[tuple[str, str], str] = {}


def device_picker_caption(platform: str, device_id: str) -> str:
    """选机友好名：Android 市场名/型号；iOS 型号·设备名。失败返回空串。"""
    p = (platform or "").strip().lower()
    did = (device_id or "").strip()
    if not did:
        return ""
    key = (p, did)
    if key in _PICKER_CAPTION_CACHE:
        return _PICKER_CAPTION_CACHE[key]
    cap = ""
    # noinspection PyBroadException
    try:
        if p.startswith("android"):
            cap = _android_prop_first(
                did, "ro.product.marketname", "ro.product.model", "ro.product.name")
        elif p.startswith("ios"):
            cap = _ios_picker_caption(did)
    except Exception:
        cap = ""
    _PICKER_CAPTION_CACHE[key] = cap
    return cap


def device_picker_line(platform: str, device_id: str) -> str:
    """选机列表行：``机型/名称  (完整UDID/序列号)``；无友好名则仅 id。"""
    did = (device_id or "").strip()
    cap = device_picker_caption(platform, did)
    if cap:
        return f"{cap}  ({did})"
    return did
