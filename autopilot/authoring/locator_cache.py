"""同页定位缓存：同一页签名下复用已成功的 locator。

借鉴 Midscene 的 cache：页未变时不要让模型反复猜同一控件。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def page_signature(elements_text: str) -> str:
    """用摘要里定位符集合做稳定签名（顺序无关）。"""
    locs = _extract_locators(elements_text)
    blob = "\n".join(sorted(locs))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16] if blob else "empty"


def _extract_locators(elements_text: str) -> set[str]:
    try:
        items = json.loads(elements_text or "[]")
    except (TypeError, ValueError):
        return set()
    if not isinstance(items, list):
        return set()
    out: set[str] = set()
    for el in items:
        if isinstance(el, dict):
            loc = str(el.get("l") or "").strip()
            if loc:
                out.add(loc)
    return out


def _norm_key(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip().lower())


class PageLocatorCache:
    """``(page_sig, hint) -> locator``；hint 来自 comment / 目标文案。"""

    def __init__(self) -> None:
        self._by_sig: dict[str, dict[str, str]] = {}

    def remember(
        self,
        page_sig: str,
        *,
        hint: str,
        locator: str,
        page_locators: set[str] | None = None,
    ) -> None:
        loc = (locator or "").strip()
        key = _norm_key(hint)
        if not page_sig or not key or not loc:
            return
        if page_locators is not None and loc not in page_locators:
            return
        self._by_sig.setdefault(page_sig, {})[key] = loc

    def lookup(
        self,
        page_sig: str,
        *,
        hint: str,
        page_locators: set[str],
    ) -> str:
        key = _norm_key(hint)
        if not page_sig or not key:
            return ""
        loc = (self._by_sig.get(page_sig) or {}).get(key) or ""
        if loc and loc in page_locators:
            return loc
        return ""

    def rewrite_step_locator(
        self,
        step: Any,
        *,
        page_sig: str,
        page_locators: set[str],
    ) -> str:
        """若步骤 locator 不在当前页，尝试用 hint 缓存改写；返回说明（空=未改）。"""
        params = getattr(step, "params", None) or {}
        if not isinstance(params, dict):
            return ""
        current = str(params.get("locator") or "").strip()
        if current and current in page_locators:
            # 成功路径上记住
            hint = str(getattr(step, "comment", "") or "") or current
            self.remember(
                page_sig, hint=hint, locator=current, page_locators=page_locators
            )
            return ""
        hint = str(getattr(step, "comment", "") or "").strip()
        cached = self.lookup(page_sig, hint=hint, page_locators=page_locators)
        if not cached:
            return ""
        params["locator"] = cached
        return f"命中同页定位缓存：{hint or current} → {cached}"
