"""IDE 与 Platform vendored 执行核的公开版本契约。"""

from __future__ import annotations

import re
from typing import Any

from .client import MgmtClientError


def _major_minor(raw: str) -> tuple[str, str] | None:
    value = (raw or "").strip().lower().removeprefix("v")
    value = value.replace("-vendored", "").replace("+vendored", "")
    match = re.match(r"^(\d+)\.(\d+)", value)
    return (match.group(1), match.group(2)) if match else None


def versions_compatible(required: str, actual: str) -> bool:
    """与 Platform runtime_compat 对齐：major.minor 相同。"""
    req = _major_minor(required)
    act = _major_minor(actual)
    return bool(req and act and req == act)


def validate_platform_runtime(payload: dict[str, Any]) -> str:
    """校验 IDE 执行核与 Platform pin/actual，返回写入 manifest 的期望版本。"""
    from autopilot import __version__ as ide_version

    actual = str(payload.get("ap_version") or "").strip()
    pin = str(payload.get("runtime_pin") or "").strip()
    expected = pin or actual
    if not expected:
        raise MgmtClientError("Platform 未返回执行核版本，已阻止打包/提交")
    if actual and not versions_compatible(expected, actual):
        raise MgmtClientError(
            f"Platform runtime pin={expected} 与实际执行核 ap={actual} 不兼容"
        )
    if not versions_compatible(str(ide_version), expected):
        raise MgmtClientError(
            f"IDE runtime={ide_version} 与 Platform runtime={expected} 不兼容，"
            "请先同步执行核后再提交"
        )
    return expected


def required_runtime_version(client: Any) -> str:
    return validate_platform_runtime(client.runtime_version())


def validate_artifact_runtime(artifact: dict[str, Any], expected: str) -> None:
    required = str(artifact.get("required_runtime_version") or "").strip()
    if not required:
        raise MgmtClientError(
            "所选历史制品未声明 required_runtime_version，请勾选重新打包上传"
        )
    if not versions_compatible(required, expected):
        raise MgmtClientError(
            f"历史制品 runtime={required} 与 Platform runtime={expected} 不兼容，"
            "请重新打包上传"
        )
