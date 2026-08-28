"""AI 编写试跑 / 上传校验。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .contract import AuthoringError

#: 校验结论落盘文件（与草稿同目录），上传/入队时据此判断是否已验证
AUTHORING_STATE_FILE = "_authoring.json"


@dataclass
class GateResult:
    ok: bool
    message: str = ""
    allow_upload: bool = False
    details: list[str] = field(default_factory=list)
    #: session（编写时逐步执行）| dry_run（本地整例试跑）| 空串（未验证）
    verified_by: str = ""


RunCaseFn = Callable[[str], bool]


def assert_local_dry_run_passed(
    case_path: str | Path,
    *,
    draft_only: bool = False,
    runner: RunCaseFn | None = None,
    session_verified: bool = False,
    goal_completed: bool = True,
) -> GateResult:
    """生成后校验：验证过才允许上传批跑；draft_only 仅保存草稿。

    ``session_verified`` 表示这些步骤是编写过程中在真机/浏览器上逐步执行成功后
    记录的——它们本身就是一次真实试跑，再整例重跑一遍只是重复消耗设备时间。

    ``goal_completed`` 为 False 时（回合耗尽 / 连续失败收手）即便每步都执行成功也不放行：
    实测这种草稿会带一串无关步骤，"能跑通"并不等于"符合需求"。
    """
    path = Path(case_path)
    if not path.is_file():
        raise AuthoringError(f"用例文件不存在：{case_path}")
    if draft_only:
        return GateResult(
            ok=True,
            message="已保存为草稿；上传批跑前请先本地运行验证",
            allow_upload=False,
            details=["draft_only"],
        )
    if session_verified and not goal_completed:
        return GateResult(
            ok=True,
            message=(
                "步骤已在设备上执行成功，但未确认完成你的需求。"
                "请人工核对步骤，并本地运行验证后再上传。"
            ),
            allow_upload=False,
            details=["session_verified", "goal_incomplete"],
        )
    if session_verified:
        return GateResult(
            ok=True,
            message="已在编写过程中逐步验证，可以上传或远程批跑",
            allow_upload=True,
            details=["session_verified"],
            verified_by="session",
        )
    if runner is None:
        return GateResult(
            ok=True,
            message="请先在本机运行用例验证，通过后再上传",
            allow_upload=False,
            details=["no_runner"],
        )
    try:
        passed = bool(runner(str(path)))
    except Exception as exc:  # noqa: BLE001
        return GateResult(
            ok=False,
            message=f"试跑异常：{exc}",
            allow_upload=False,
            details=[str(exc)],
        )
    if not passed:
        return GateResult(
            ok=False,
            message="试跑未通过，暂不能入队；可保留草稿继续编辑",
            allow_upload=False,
        )
    return GateResult(
        ok=True,
        message="试跑通过，可以上传或远程批跑",
        allow_upload=True,
        verified_by="dry_run",
    )


def upload_blocked_reason(
    *,
    gate: GateResult | None,
    authoring_meta: dict[str, Any] | None = None,
) -> str:
    """给上传/入队调用的软拦截文案；空串表示不拦。"""
    meta = authoring_meta or {}
    if meta.get("chain") != "3":
        return ""
    if gate is None:
        return "该 AI 用例尚未本地验证，请先运行通过后再上传"
    if gate.allow_upload:
        return ""
    return gate.message or "该 AI 用例尚未通过本地验证"


def record_gate_result(case_path: str | Path, gate: GateResult) -> Path:
    """把校验结论写到草稿目录的 sidecar，供后续上传/入队判断。"""
    path = Path(case_path)
    state_path = path.parent / AUTHORING_STATE_FILE
    state = _read_state(state_path)
    state[path.name] = {
        "chain": "3",
        "allow_upload": bool(gate.allow_upload),
        "verified_by": gate.verified_by,
        "message": gate.message,
    }
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return state_path


def _read_state(state_path: Path) -> dict[str, Any]:
    if not state_path.is_file():
        return {}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def unverified_drafts(project_dir: str | Path, *, subdir: str = "authored") -> list[str]:
    """authored/ 下尚未通过校验的草稿文件名（无记录也算未验证）。"""
    out_dir = Path(project_dir) / subdir
    if not out_dir.is_dir():
        return []
    state = _read_state(out_dir / AUTHORING_STATE_FILE)
    names: list[str] = []
    for p in sorted(out_dir.iterdir()):
        if not p.is_file() or not p.name.endswith((".tc.yaml", ".tc")):
            continue
        rec = state.get(p.name)
        if not isinstance(rec, dict) or not rec.get("allow_upload"):
            names.append(p.name)
    return names


def project_upload_blocked_reason(
    project_dir: str | Path,
    *,
    subdir: str = "authored",
) -> str:
    """上传整个工程前的拦截文案；空串表示无未验证草稿。"""
    names = unverified_drafts(project_dir, subdir=subdir)
    if not names:
        return ""
    sample = "、".join(names[:5])
    more = f" 等 {len(names)} 个" if len(names) > 5 else ""
    return (
        f"工程中有尚未本地验证的 AI 草稿：{sample}{more}。\n"
        "请先在本机运行通过后再上传批跑"
        "（AI 编写过程中已逐步验证的草稿会自动记为已通过）。"
    )
