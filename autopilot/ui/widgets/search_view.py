"""工程内文本检索与引用查找（纯函数，供打开文件定位等逻辑复用）。

基于工程文件原文做大小写不敏感的子串匹配（覆盖 .tc/.ts/.map/.properties/.ks 及其 .yaml），
以及关键字 / ks:: / map:: 的语义级「查找引用」。

底栏输入框统一走 ``find_in_project``：精确语义优先，支持中文名/id 子串解析，
无语义命中时回退全文检索。
"""

from __future__ import annotations

import os
import re


_SEARCH_EXTS = (".tc", ".ts", ".map", ".properties", ".ks",
                ".tc.yaml", ".ts.yaml", ".map.yaml", ".ks.yaml", ".tp", ".tp.yaml")
_MAX_RESULTS = 500
_MAX_FILE_BYTES = 2_000_000
_MAX_RESOLVED_KEYWORDS = 40
_catalog_cache = None  # None=未加载；False=失败；KeywordCatalog=已缓存


def search_project(directory: str, query: str) -> list[tuple[str, int, str]]:
    """在目录下工程文件中检索 query（大小写不敏感）。返回 (路径, 行号, 行文本)。"""
    q = query.strip().lower()
    out: list[tuple[str, int, str]] = []
    if not q or not directory or not os.path.isdir(directory):
        return out
    for root, _dirs, files in os.walk(directory):
        for f in files:
            if not f.endswith(_SEARCH_EXTS):
                continue
            path = os.path.join(root, f)
            try:
                if os.path.getsize(path) > _MAX_FILE_BYTES:
                    continue
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    for ln, line in enumerate(fh, 1):
                        if q in line.lower():
                            out.append((path, ln, line.strip()))
                            if len(out) >= _MAX_RESULTS:
                                return out
            except OSError:
                continue
    return out


def _scan_with_patterns(
    directory: str, pats: list[str], *, limit: int = _MAX_RESULTS,
) -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    if not pats or not directory or not os.path.isdir(directory):
        return out
    rx = re.compile("|".join(pats), re.IGNORECASE)
    for root, _dirs, files in os.walk(directory):
        for f in files:
            if not f.endswith(_SEARCH_EXTS):
                continue
            path = os.path.join(root, f)
            try:
                if os.path.getsize(path) > _MAX_FILE_BYTES:
                    continue
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    for ln, line in enumerate(fh, 1):
                        if rx.search(line):
                            out.append((path, ln, line.strip()))
                            if len(out) >= limit:
                                return out
            except OSError:
                continue
    return out


def _patterns_for_target(t: str) -> list[str]:
    """按 target 形态生成语义引用正则。"""
    if t.startswith("map::"):
        return [re.escape(t)]
    if t.startswith("ks::"):
        kid = t[4:]
        return [
            rf"stepverbs:\s*['\"]?{re.escape(kid)}\b",
            rf"ks_id[:=]\s*['\"]?{re.escape(kid)}\b",
            rf"ks::{re.escape(kid)}\b",
        ]
    # 内建关键字：YAML step / keyword_id，以及 XML <step id="...">
    return [
        rf"step:\s*['\"]?{re.escape(t)}\b",
        rf"keyword_id[:=]\s*['\"]?{re.escape(t)}\b",
        rf'id\s*=\s*["\']{re.escape(t)}["\']',
    ]


def find_references(directory: str, target: str) -> list[tuple[str, int, str]]:
    """查找引用：target 可为 关键字id / `ks::自定义关键字` / `map::文件::元素`，
    扫描工程文件找出「引用它」的位置（比全文 grep 精准，避开注释/说明里的同名子串）。
    返回 (路径, 行号, 行文本)。
    """
    t = (target or "").strip()
    if not t or not directory or not os.path.isdir(directory):
        return []
    return _scan_with_patterns(directory, _patterns_for_target(t))


def resolve_keyword_ids(query: str) -> list[str]:
    """按关键字 id / 中文名 精确或子串匹配，解析为 keyword_id 列表。

    用于「安装」「mobile」等用户输入 → 实际步骤里的英文 id。
    """
    q = (query or "").strip()
    if not q or q.startswith(("map::", "ks::")):
        return []
    q_l = q.lower()
    scored: list[tuple[int, str]] = []  # (score, id) 越小越优先
    seen: set[str] = set()

    def _add(keyword_id: str, name: str = "") -> None:
        if not keyword_id or keyword_id in seen:
            return
        kid_l = keyword_id.lower()
        name_l = (name or "").lower()
        if kid_l == q_l:
            score = 0
        elif name_l == q_l:
            score = 1
        elif kid_l.startswith(q_l) or q_l in kid_l:
            score = 2
        elif name_l and q_l in name_l:
            score = 3
        else:
            return
        seen.add(keyword_id)
        scored.append((score, keyword_id))

    # noinspection PyBroadException
    try:
        import autopilot.keywords  # noqa: F401  触发注册
        from ...keywords.registry import REGISTRY
        for kid, kd in REGISTRY.items():
            _add(kid, getattr(kd, "name", "") or "")
    except Exception:
        pass

    # XML 元数据（中文名更全；进程内缓存，避免每次查找重读）
    global _catalog_cache
    if _catalog_cache is None:
        # noinspection PyBroadException
        try:
            from ...metadata.keyword_meta import load_catalog
            _catalog_cache = load_catalog()
        except Exception:
            _catalog_cache = False
    if _catalog_cache is not False and _catalog_cache is not None:
        for kid, meta in getattr(_catalog_cache, "by_id", {}).items():
            _add(kid, getattr(meta, "name", "") or "")

    scored.sort(key=lambda x: (x[0], x[1]))
    return [kid for _s, kid in scored[:_MAX_RESOLVED_KEYWORDS]]


def _dedupe_hits(
    hits: list[tuple[str, int, str]], *, limit: int = _MAX_RESULTS,
) -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    seen: set[tuple[str, int]] = set()
    for path, ln, text in hits:
        key = (os.path.normpath(path), int(ln))
        if key in seen:
            continue
        seen.add(key)
        out.append((path, ln, text))
        if len(out) >= limit:
            break
    return out


def find_in_project(directory: str, target: str) -> list[tuple[str, int, str]]:
    """底栏统一查找：语义引用 → 中文名/id 子串展开 → 全文检索回退。

    - ``map::`` / ``ks::``：只做精确语义引用
    - 其它：先精确 id 引用；再按注册表/元数据把「安装」「mobile」解析成关键字 id
      并查引用；仍无结果则 ``search_project`` 全文子串
    """
    t = (target or "").strip()
    if not t or not directory or not os.path.isdir(directory):
        return []

    if t.startswith(("map::", "ks::")):
        return find_references(directory, t)

    hits = list(find_references(directory, t))
    if hits:
        return hits

    # 中文名 / id 子串 → 多个关键字 id，合并正则一次扫盘
    pats: list[str] = []
    for kid in resolve_keyword_ids(t):
        if kid == t:
            continue
        pats.extend(_patterns_for_target(kid))
    if pats:
        hits = _dedupe_hits(_scan_with_patterns(directory, pats))
        if hits:
            return hits

    return search_project(directory, t)


def keyword_hint_from_line(line: str) -> str:
    """从 YAML 源行提取可定位的步骤/关键字 id（供编辑器选中行）。"""
    s = (line or "").strip()
    for pat in (
        r"step:\s*['\"]?([^'\"#\s]+)",
        r"stepverbs:\s*['\"]?([^'\"#\s]+)",
        r"ks_id:\s*['\"]?([^'\"#\s]+)",
    ):
        m = re.search(pat, s, re.IGNORECASE)
        if m:
            return m.group(1)
    return ""
