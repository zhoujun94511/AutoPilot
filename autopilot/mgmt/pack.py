"""把工程目录打成 zip：仅纳入远程批跑所需资源。

必要：用例/套件/计划/对象库/自定义关键字/数据配置，以及 picture:: 等可能引用的图片与常用数据文件。
排除：VCS/虚拟环境/缓存、本机报告与日志、安装包（应走应用资源）、大体积媒体与备份等。
"""

from __future__ import annotations

import io
import json
import os
import zipfile

# 目录名整段跳过（任意层级）
_SKIP_DIR_NAMES = {
    ".git",
    ".svn",
    ".hg",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "node_modules",
    ".idea",
    ".vscode",
    ".cursor",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".cache",
    "reports",
    "logs",
    "log",
    "dist",
    "build",
    "__macosx",
}

# 远程执行不需要的后缀（安装包走 app-builds）
_SKIP_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".apk",
    ".aab",
    ".apks",
    ".xapk",
    ".ipa",
    ".app",
    ".exe",
    ".msi",
    ".dmg",
    ".deb",
    ".rpm",
    ".zip",
    ".7z",
    ".rar",
    ".tar",
    ".gz",
    ".tgz",
    ".log",
    ".tmp",
    ".bak",
    ".swp",
    ".html",
    ".htm",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".webm",
    ".mp3",
    ".wav",
    ".flac",
    ".ds_store",
)

# 白名单：工程模型资源 + 图像定位 + 常见数据驱动附件
_INCLUDE_SUFFIXES = (
    ".tc.yaml",
    ".ts.yaml",
    ".tp.yaml",
    ".map.yaml",
    ".ks.yaml",
    ".yaml",
    ".yml",
    ".properties",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".gif",
    ".csv",
    ".tsv",
    ".json",
    ".xml",
    ".txt",
)

# 单文件上限，防止误放巨大媒体/安装包漏网
_MAX_FILE_BYTES = 25 * 1024 * 1024


def _is_included_file(filename: str) -> bool:
    lower = filename.lower()
    if lower.startswith(".") or lower in ("thumbs.db", "desktop.ini"):
        return False
    if any(lower.endswith(s) for s in _SKIP_SUFFIXES):
        return False
    return any(lower.endswith(s) for s in _INCLUDE_SUFFIXES)


def zip_project_dir(
    project_dir: str,
    *,
    arcroot: str = "",
    project_id: str = "",
    artifact_version: str = "",
    required_runtime_version: str = "",
    write_manifest: bool = True,
) -> bytes:
    """打包工程中远程批跑必要文件；默认写入 ArtifactManifest（manifest.json）。"""
    root = os.path.abspath(project_dir)
    if not os.path.isdir(root):
        raise FileNotFoundError(f"not a directory: {project_dir}")
    name = (arcroot or os.path.basename(root) or "project").strip() or "project"

    manifest_bytes: bytes | None = None
    if write_manifest:
        from .manifest import build_artifact_manifest

        try:
            from autopilot import __version__ as ap_ver
        except ImportError:
            ap_ver = "0.1.0"
        man = build_artifact_manifest(
            root,
            project_id=project_id,
            artifact_version=artifact_version,
            required_runtime_version=required_runtime_version or str(ap_ver),
        )
        manifest_bytes = (json.dumps(man, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if manifest_bytes is not None:
            zf.writestr(f"{name}/manifest.json", manifest_bytes)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d
                for d in dirnames
                if d not in _SKIP_DIR_NAMES and not d.startswith(".")
            ]
            for fn in filenames:
                if not _is_included_file(fn):
                    continue
                # 避免把旧的/半成品 manifest 覆盖我们刚写入的规范版本
                if fn.lower() == "manifest.json":
                    continue
                full = os.path.join(dirpath, fn)
                try:
                    if os.path.getsize(full) > _MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                rel = os.path.relpath(full, root).replace("\\", "/")
                zf.write(full, f"{name}/{rel}")
    return buf.getvalue()
