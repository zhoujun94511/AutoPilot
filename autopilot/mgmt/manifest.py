"""工程制品 ArtifactManifest 生成（写入 zip 根或 arcroot 下的 manifest.json）。"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .entries import list_runnable_entries
from .pack import _INCLUDE_SUFFIXES, _MAX_FILE_BYTES, _SKIP_DIR_NAMES, _SKIP_SUFFIXES


def _is_included_file(filename: str) -> bool:
    lower = filename.lower()
    if lower.startswith(".") or lower in ("thumbs.db", "desktop.ini"):
        return False
    if any(lower.endswith(s) for s in _SKIP_SUFFIXES):
        return False
    return any(lower.endswith(s) for s in _INCLUDE_SUFFIXES)


def iter_project_files(project_dir: str) -> list[tuple[str, str]]:
    """返回 [(abs_path, rel_posix), ...]。"""
    root = os.path.abspath(project_dir)
    out: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if d not in _SKIP_DIR_NAMES and not d.startswith(".")
        ]
        for fn in filenames:
            if not _is_included_file(fn):
                continue
            full = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(full) > _MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            rel = os.path.relpath(full, root).replace("\\", "/")
            out.append((full, rel))
    out.sort(key=lambda x: x[1].lower())
    return out


# noinspection PyUnresolvedReferences
def content_sha256(project_dir: str) -> str:
    """对工程纳入文件按路径排序做内容哈希（稳定，不依赖最终 zip 包装）。"""
    h = hashlib.sha256()
    for full, rel in iter_project_files(project_dir):
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        with open(full, "rb") as fh:
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        h.update(b"\0")
    return h.hexdigest()


def _read_case_ids(path: str) -> dict[str, str]:
    try:
        # noinspection PyUnresolvedReferences
        import yaml

        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return {
            "automation_case_id": str(data.get("automation_case_id") or ""),
            "logical_case_id": str(data.get("logical_case_id") or ""),
            "case_key": str(data.get("case_key") or ""),
        }
    except (ImportError, OSError, UnicodeDecodeError, ValueError, TypeError, AttributeError):
        return {}


def build_artifact_manifest(
    project_dir: str,
    *,
    project_id: str = "",
    artifact_version: str = "",
    required_runtime_version: str = "0.1.0",
    change_summary: str = "",
) -> dict[str, Any]:
    root = os.path.abspath(project_dir)
    entries = list_runnable_entries(root)
    case_index: list[dict[str, str]] = []
    for e in entries:
        rel = e.get("path") or ""
        item: dict[str, str] = {"relative_path": rel}
        if (e.get("kind") or "") == "case":
            meta = _read_case_ids(os.path.join(root, rel.replace("/", os.sep)))
            for k, v in meta.items():
                if v:
                    item[k] = v
        case_index.append(item)

    caps: list[str] = []
    # 粗略能力标签：有移动对象库/用例则声明常见能力
    lower_blob = " ".join(p for _, p in iter_project_files(root)).lower()
    if "android" in lower_blob or any("android" in (e.get("path") or "").lower() for e in entries):
        caps.append("android.appium")
    if "ios" in lower_blob:
        caps.extend(["ios.wda-direct", "ios.appium"])
    if any(p.endswith((".tc.yaml", ".ts.yaml")) for _, p in iter_project_files(root)):
        if "web.selenium" not in caps:
            caps.append("web.selenium")
    if not caps:
        caps = ["web.selenium"]

    version = (artifact_version or "").strip() or datetime.now(timezone.utc).strftime(
        "%Y.%m.%d.%H%M%S"
    )
    # Intent Binding 约定路径；有文件或目录时声明，便于 Runner 定位
    bindings_dir = Path(root) / "bindings"
    has_bindings = bindings_dir.is_dir() and any(bindings_dir.glob("*.json"))
    logical_ids = sorted(
        {
            str(item.get("logical_case_id") or "").strip()
            for item in case_index
            if str(item.get("logical_case_id") or "").strip()
        }
    )
    missing_binding: list[str] = []
    for cid in logical_ids:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in cid)[:120]
        if not (bindings_dir / f"{safe}.json").is_file():
            missing_binding.append(cid)
    binding_file_count = (
        len(list(bindings_dir.glob("*.json"))) if bindings_dir.is_dir() else 0
    )
    out: dict[str, Any] = {
        "schema_version": "1.0",
        "artifact_id": "",  # 上传后由 Platform 分配
        "artifact_version": version,
        "project_id": (project_id or "").strip(),
        "sha256": content_sha256(root),
        "created_from_revision": uuid.uuid4().hex,
        "git_commit": _try_git_commit(root),
        "required_runtime_version": required_runtime_version or "0.1.0",
        "required_capabilities": caps,
        "entry_paths": [e.get("path") or "" for e in entries if e.get("path")],
        "case_index": case_index,
        "change_summary": change_summary or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if has_bindings or bindings_dir.is_dir():
        out["bindings_glob"] = "bindings/*.json"
    if logical_ids:
        if missing_binding:
            hint = (
                "部分 logical_case 尚无 Binding 文件；云端将依赖运行时解析/自愈。"
                "建议 IDE 本地跑通后再打包上传。"
            )
        elif binding_file_count == 0:
            hint = "含 Intent 用例但无 bindings；批跑将纯靠运行时解析。"
        else:
            hint = "Intent Binding 已随制品打包。"
        out["intent_readiness"] = {
            "logical_case_count": len(logical_ids),
            "binding_file_count": binding_file_count,
            "missing_binding_case_ids": missing_binding[:50],
            "hint": hint,
        }
    return out


def _try_git_commit(root: str) -> str:
    import subprocess

    from ..runtime.subproc import check_output

    try:
        out = check_output(
            ["git", "-C", root, "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        return out.decode("utf-8", errors="ignore").strip()
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""


def write_manifest_json(project_dir: str, manifest: dict[str, Any]) -> Path:
    path = Path(project_dir) / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
