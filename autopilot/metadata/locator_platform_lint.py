"""定位符与目标平台的启发式冲突检测（Phase 3 扩展）。"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..model.mapfile import Locator, MapFile

from ..model.mapfile import IOS_APPIUM_SLOT, IOS_WDA_SLOT

# iOS 用例中出现 Android 专有定位特征
_IOS_CASE_ANDROID_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"resource-id", re.I), "含 resource-id（Android UiAutomator 属性）"),
    (re.compile(r"android\.widget\.", re.I), "含 android.widget（Android 控件类名）"),
    (re.compile(r"uiautomator", re.I), "含 uiautomator（Android 定位策略）"),
    (re.compile(r"\bid::(?:com\.|android:)", re.I), "id:: 形如 Android 包名"),
    (re.compile(r"@resource-id\b", re.I), "XPath 使用 @resource-id"),
]

# Android 用例中出现 iOS 专有定位特征
_ANDROID_CASE_IOS_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"XCUIElementType", re.I), "含 XCUIElementType（iOS 控件类型）"),
    (re.compile(r"\bclass-chain::", re.I), "使用 class-chain（iOS 专用）"),
    (re.compile(r"\bpredicate::", re.I), "使用 predicate（iOS NSPredicate 定位）"),
    (re.compile(r"type\s*==\s*['\"]XCUI", re.I), "谓词含 XCUI 类型判断"),
]

_LOCATOR_PREFIXES = frozenset({
    "id", "name", "xpath", "css", "predicate", "classname", "linktext", "commonid",
    "class-chain", "map",
})

_VAR_ONLY = re.compile(r"^\$\{[^}]+}$")
_MAP_REF = re.compile(r"^map::", re.I)


def _looks_like_locator(raw: str) -> bool:
    s = raw.strip()
    if not s or _VAR_ONLY.match(s):
        return False
    if _MAP_REF.match(s):
        return True
    if "::" in s:
        head = s.split("::", 1)[0].lower()
        if head in _LOCATOR_PREFIXES:
            return True
    for pat, _ in _IOS_CASE_ANDROID_HINTS:
        if pat.search(s):
            return True
    for pat, _ in _ANDROID_CASE_IOS_HINTS:
        if pat.search(s):
            return True
    return False


def locator_param_ids(meta) -> frozenset[str]:
    """关键字中可能携带定位符的参数 id。"""
    ids: set[str] = set()
    for p in getattr(meta, "params", []) or []:
        pid = (getattr(p, "param_id", "") or "").strip()
        low = pid.lower()
        if not pid:
            continue
        if "locator" in low or low in ("element", "target", "source", "destination"):
            ids.add(pid)
    return frozenset(ids)


def locator_mismatch_reason(platform: str, raw: str) -> str:
    """定位串与目标平台冲突时返回说明，否则空串。"""
    plat = (platform or "").strip().lower()
    s = (raw or "").strip()
    if plat not in ("android", "ios") or not s or _VAR_ONLY.match(s):
        return ""
    hints = _IOS_CASE_ANDROID_HINTS if plat == "ios" else _ANDROID_CASE_IOS_HINTS
    for pat, msg in hints:
        if pat.search(s):
            return msg
    return ""


def parse_map_ref(raw: str) -> Optional[tuple[str, str]]:
    """解析 map::文件::元素，失败返回 None。"""
    parts = (raw or "").strip().split("::")
    if len(parts) < 3 or parts[0].lower() != "map":
        return None
    map_name = parts[1].strip()
    if map_name.endswith(".map"):
        map_name = map_name[:-4]
    el_name = parts[2].strip()
    if not map_name or not el_name:
        return None
    return map_name, el_name


def build_maps_index(maps: list["MapFile"] | None) -> dict[str, "MapFile"]:
    """按对象库名（不含扩展名）索引 MapFile，键为小写。"""
    idx: dict[str, "MapFile"] = {}
    for mf in maps or []:
        names: set[str] = set()
        if mf.name:
            names.add(mf.name)
            if mf.name.endswith(".map"):
                names.add(mf.name[:-4])
        if mf.source_path:
            names.add(os.path.splitext(os.path.basename(mf.source_path))[0])
        for name in names:
            if name:
                idx[name.lower()] = mf
    return idx


def locator_nonempty(loc: Locator | None) -> bool:
    if loc is None:
        return False
    if (loc.value or "").strip():
        return True
    if (loc.tag or "").strip():
        return True
    for prop in loc.properties or []:
        if str(prop.get("value", "")).strip():
            return True
    return False


def locator_as_text(loc: Locator | None) -> str:
    if loc is None:
        return ""
    chunks = [loc.value or "", loc.tag or ""]
    for prop in loc.properties or []:
        chunks.append(str(prop.get("value", "")))
    return " ".join(c for c in chunks if c)


def map_ref_lint_reason(
    platform: str,
    raw: str,
    maps_index: dict[str, "MapFile"],
    backend: str = "",
) -> str:
    """校验 map:: 引用；maps_index 为空时跳过（返回空串）。"""
    if not maps_index:
        return ""
    ref = parse_map_ref(raw)
    if ref is None:
        return ""
    map_name, el_name = ref
    mf = maps_index.get(map_name.lower())
    if mf is None:
        return f"对象库未加载: {map_name}"
    el = mf.find(el_name)
    if el is None:
        return f"对象库元素未找到: {map_name}::{el_name}"

    plat = (platform or "").strip().lower()
    if plat not in ("android", "ios"):
        loc = el.locator
        if not locator_nonempty(loc):
            return f"对象库元素无默认定位符: {map_name}::{el_name}"
        return locator_mismatch_reason(platform, locator_as_text(loc))

    bm = (backend or "").strip().lower()
    has_wda = locator_nonempty(el.locators_by_platform.get(IOS_WDA_SLOT))
    has_appium = locator_nonempty(el.locators_by_platform.get(IOS_APPIUM_SLOT))
    has_ios = locator_nonempty(el.locators_by_platform.get("ios"))
    has_generic = locator_nonempty(el.locator)

    if plat == "ios" and bm == "wda":
        if has_appium and not has_wda and not has_ios and not has_generic:
            return (f"对象库 {map_name}::{el_name}：仅有 ios_appium 槽位，"
                    f"当前 iOS 后端为 WDA-direct")
    if plat == "ios" and bm == "appium":
        if has_wda and not has_appium and not has_ios and not has_generic:
            return (f"对象库 {map_name}::{el_name}：仅有 ios_wda 槽位，"
                    f"当前 iOS 后端为 Appium")

    slot = el.locators_by_platform.get(plat)
    other = "ios" if plat == "android" else "android"
    has_other = locator_nonempty(el.locators_by_platform.get(other))

    if slot is None and not has_generic and has_other:
        label = "Android" if other == "android" else "iOS"
        return f"对象库元素仅有 {label} 定位符，缺少当前平台专属: {map_name}::{el_name}"

    loc = el.locator_for_target(plat, "")
    if not locator_nonempty(loc):
        return f"对象库元素无可用定位符: {map_name}::{el_name}"

    mismatch = locator_mismatch_reason(plat, locator_as_text(loc))
    if mismatch:
        return f"对象库 {map_name}::{el_name}：{mismatch}"
    return ""
