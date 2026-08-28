"""链路 3 编排：会话驱动编写（主路径）或仅规划草稿。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .agent import ProgressFn, run_session_authoring
from .capture import capture_ui_context
from .codegen import parse_llm_draft, save_draft_tc
from .contract import (
    AuthoringDraft,
    AuthoringError,
    AuthoringRequest,
    clamp_max_steps,
    normalize_platform,
)
from .gate import GateResult, assert_local_dry_run_passed, record_gate_result
from .llm_client import ChatFn, complete_json
from .prompt import build_authoring_prompt
from .registry_catalog import build_keyword_catalog
from .step_runner import StepExecutor


@dataclass
class AuthoringResult:
    draft: AuthoringDraft
    path: Path | None = None
    gate: GateResult | None = None
    capture_meta: dict[str, Any] = field(default_factory=dict)


def generate_traditional_case(
    request: AuthoringRequest,
    *,
    ctx: Any = None,
    elements_text: str = "",
    project_dir: str | Path | None = None,
    chat: ChatFn | None = None,
    runner: Callable[[str], bool] | None = None,
    executor: StepExecutor | None = None,
    on_progress: ProgressFn | None = None,
    save: bool = True,
) -> AuthoringResult:
    """主入口。

    - mode=session（默认正式路径）：驱动 ctx 会话 observe-act，固化已执行成功的步骤
    - mode=plan_only：不执行，仅根据当前树/注入树规划草稿
    """
    nl = (request.natural_language or "").strip()
    if not nl:
        raise AuthoringError("请输入自然语言需求")
    platform = normalize_platform(request.platform)
    mode = (request.mode or "session").strip().lower()
    if mode not in ("session", "plan_only"):
        raise AuthoringError(f"不支持的 mode: {request.mode!r}")

    if mode == "session":
        draft = run_session_authoring(
            request,
            ctx=ctx,
            chat=chat,
            executor=executor,
            on_progress=on_progress,
        )
        capture_meta = {
            "platform": platform,
            "source": "session_agent",
            "step_count": len(draft.steps),
        }
    else:
        draft, capture_meta = _plan_only(
            request,
            platform=platform,
            ctx=ctx,
            elements_text=elements_text,
            chat=chat,
        )

    path: Path | None = None
    gate: GateResult | None = None
    if save:
        if not project_dir:
            raise AuthoringError("请先选择要写入的工程目录")
        path = save_draft_tc(draft, project_dir)
        gate = assert_local_dry_run_passed(
            path,
            draft_only=request.draft_only,
            runner=runner,
            session_verified=draft.session_verified,
            goal_completed=draft.goal_completed,
        )
        record_gate_result(path, gate)
    return AuthoringResult(draft=draft, path=path, gate=gate, capture_meta=capture_meta)


def _plan_only(
    request: AuthoringRequest,
    *,
    platform: str,
    ctx: Any,
    elements_text: str,
    chat: ChatFn | None,
) -> tuple[AuthoringDraft, dict[str, Any]]:
    max_steps = clamp_max_steps(request.max_steps)
    capture_meta: dict[str, Any] = {"platform": platform, "source": "plan_only"}
    if elements_text:
        el_text = elements_text
        capture_meta["element_count"] = -1
    elif ctx is not None:
        cap = capture_ui_context(ctx, platform)
        el_text = str(cap["elements_text"])
        capture_meta["element_count"] = cap["element_count"]
        capture_meta["source"] = "session_snapshot"
    else:
        el_text = "[]"
        capture_meta["element_count"] = 0

    catalog = build_keyword_catalog(platform)
    if not catalog:
        raise AuthoringError(f"平台 {platform} 无可用关键字白名单")
    prompt = build_authoring_prompt(
        natural_language=request.natural_language,
        platform=platform,
        elements_text=el_text,
        keyword_catalog=catalog,
        max_steps=max_steps,
        package_name=request.package_name,
        start_url=request.start_url,
    )
    data = complete_json(prompt, chat=chat, purpose="authoring")
    draft = parse_llm_draft(
        data,
        platform=platform,
        max_steps=max_steps,
        fallback_title=request.title or request.natural_language[:40],
    )
    draft.mode = "plan_only"
    draft.raw_llm = str(data)
    return draft, capture_meta
