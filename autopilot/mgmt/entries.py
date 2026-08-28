"""可执行入口清单：用例 / 套件 / 计划（供管理台勾选后按 entry_paths 执行）。"""

from __future__ import annotations

import os
import zipfile
from typing import Any, BinaryIO, Iterable

from .pack import _SKIP_DIR_NAMES

_CASE_SUFFIXES = (".tc.yaml", ".tc.yml", ".tc")
_SUITE_SUFFIXES = (".ts.yaml", ".ts.yml", ".ts")
_PLAN_SUFFIXES = (".tp.yaml", ".tp.yml", ".tp")


def _basename(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def entry_kind(filename: str) -> str | None:
    """返回 case | suite | plan；其它可执行资源返回 None。"""
    base = _basename(filename).lower()
    if any(base.endswith(s) for s in _CASE_SUFFIXES):
        return "case"
    if any(base.endswith(s) for s in _SUITE_SUFFIXES):
        return "suite"
    if any(base.endswith(s) for s in _PLAN_SUFFIXES):
        return "plan"
    return None


def entry_display_name(path: str) -> str:
    base = _basename(path)
    low = base.lower()
    for suf in _CASE_SUFFIXES + _SUITE_SUFFIXES + _PLAN_SUFFIXES:
        if low.endswith(suf):
            return base[: -len(suf)]
    return os.path.splitext(base)[0]


def _norm_rel(path: str) -> str:
    return (path or "").replace("\\", "/").lstrip("/")


def _is_safe_rel(rel: str) -> bool:
    rel = _norm_rel(rel)
    if not rel or rel.startswith("/") or ":" in rel.split("/")[0]:
        return False
    parts = rel.split("/")
    return ".." not in parts and all(p and not p.startswith(".") for p in parts)


def _skip_dir(name: str) -> bool:
    return name in _SKIP_DIR_NAMES or name.startswith(".")


def list_runnable_entries(directory: str) -> list[dict[str, str]]:
    """扫描工程目录，返回 [{path, kind, name}, ...]（path 相对工程根，/ 分隔）。"""
    root = os.path.abspath(directory)
    if not os.path.isdir(root):
        raise FileNotFoundError(f"not a directory: {directory}")
    found: list[dict[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _skip_dir(d)]
        for fn in filenames:
            kind = entry_kind(fn)
            if not kind:
                continue
            full = os.path.join(dirpath, fn)
            rel = _norm_rel(os.path.relpath(full, root))
            if not _is_safe_rel(rel):
                continue
            found.append({"path": rel, "kind": kind, "name": entry_display_name(rel)})
    kind_order = {"case": 0, "suite": 1, "plan": 2}
    found.sort(key=lambda e: (kind_order.get(e["kind"], 9), e["path"].lower()))
    return found


def _strip_zip_arcroot(names: Iterable[str]) -> list[str]:
    files = [_norm_rel(n) for n in names if n and not str(n).endswith("/")]
    files = [n for n in files if n]
    if not files:
        return []
    with_slash = [n for n in files if "/" in n]
    tops = {n.split("/", 1)[0] for n in with_slash}
    bare = [n for n in files if "/" not in n]
    if len(tops) == 1 and not bare:
        root = next(iter(tops))
        return [n[len(root) + 1 :] for n in with_slash]
    return files


def list_runnable_entries_in_zip(
    source: str | bytes | BinaryIO | zipfile.ZipFile,
) -> list[dict[str, str]]:
    """从 zip 列出可执行入口（自动剥掉打包时的顶层目录名）。"""
    own = False
    zf: zipfile.ZipFile
    if isinstance(source, zipfile.ZipFile):
        zf = source
    elif isinstance(source, (bytes, bytearray)):
        import io  # 延迟：仅传入 bytes 时包一层缓冲

        zf = zipfile.ZipFile(io.BytesIO(source), "r")
        own = True
    elif hasattr(source, "read"):
        zf = zipfile.ZipFile(source, "r")  # type: ignore[arg-type]
        own = True
    else:
        zf = zipfile.ZipFile(str(source), "r")
        own = True
    try:
        rels = _strip_zip_arcroot(zf.namelist())
        found: list[dict[str, str]] = []
        for rel in rels:
            if any(_skip_dir(p) for p in rel.split("/")):
                continue
            kind = entry_kind(rel)
            if not kind or not _is_safe_rel(rel):
                continue
            found.append({"path": rel, "kind": kind, "name": entry_display_name(rel)})
        kind_order = {"case": 0, "suite": 1, "plan": 2}
        found.sort(key=lambda e: (kind_order.get(e["kind"], 9), e["path"].lower()))
        return found
    finally:
        if own:
            zf.close()


def as_entry_dicts(entries: list[dict[str, Any]]) -> list[dict[str, str]]:
    """规范化外部传入的 entry 列表。"""
    out: list[dict[str, str]] = []
    for e in entries or []:
        path = _norm_rel(str(e.get("path") or ""))
        kind = str(e.get("kind") or entry_kind(path) or "")
        name = str(e.get("name") or entry_display_name(path))
        if path and kind:
            out.append({"path": path, "kind": kind, "name": name})
    return out
