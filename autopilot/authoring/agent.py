"""链路 3 会话驱动编写：observe → plan → 执行关键字 → 再观察 → 固化。

借鉴 Midscene：可能改变页面的动作执行后立即重新采页，避免用过期摘要编造定位符。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

from .capture import capture_settled_ui_context, capture_ui_context
from .codegen import parse_llm_draft
from .goal_judge import judge_authoring_goal
from .contract import (
    MAX_STEPS_PER_TURN,
    AuthoringDraft,
    AuthoringError,
    AuthoringRequest,
    GeneratedStep,
    clamp_max_steps,
    normalize_platform,
    turns_for_steps,
)
from .llm_client import ChatFn, complete_json
from .locate_resolve import resolve_planned_locators
from .locator_cache import PageLocatorCache, page_signature
from .nl_parse import parse_nl_hints
from .prompt import build_agent_turn_prompt
from .registry_catalog import build_keyword_catalog
from .repeat import RepeatWatch
from .step_runner import StepExecutor, execute_keyword_step
from .turn_trace import AuthoringTrace, TurnTraceRecord
from .vision_fallback import enrich_empty_page_via_vision


ProgressFn = Callable[[str], None]

#: 连续失败到此次数就收手，避免在同一个卡点上反复烧 AI 调用
MAX_CONSECUTIVE_FAILURES = 3
#: 失败重规划的额外调用余量（在 max_turns 之上）
LLM_CALL_HEADROOM = 4
HARD_MAX_LLM_CALLS_PER_CASE = 48
#: 单用例累计 prompt 上限：只防跑飞，不该成为业务长度限制
DEFAULT_MAX_PROMPT_CHARS_PER_CASE = 1_200_000

#: 入口关键字：同一目标（包名/URL）通常只启动一次；跨 App / 多 URL 允许再次入口
ENTRY_KEYWORD_IDS = frozenset({
    "mobile_app_start",
    "web_browser_open",
})

#: 截图类：仅当用户明确要求留证时才固化；否则视为模型「想看一眼」
SNAPSHOT_KEYWORD_IDS = frozenset({
    "mobile_app_snapshot",
    "web_browser_snapshot",
})

#: 执行后几乎必然改变页面，本回合应停下来重新采页（Midscene observe-act）
PAGE_CHANGING_KEYWORD_IDS = frozenset({
    "mobile_app_start",
    "mobile_element_click",
    "mobile_element_long_click",
    "mobile_swipe",
    "mobile_swipe_up",
    "mobile_swipe_down",
    "mobile_back",
    "ios_alert_accept",
    "ios_alert_dismiss",
    "web_browser_open",
    "web_browser_locate",
    "web_element_click",
    "web_element_dblclick",
    "elementClick",
})

#: 带 locator 参数、必须落在当前页摘要内的关键字
LOCATOR_BOUND_KEYWORD_IDS = frozenset({
    "mobile_element_click",
    "mobile_element_long_click",
    "mobile_element_text_input",
    "mobile_element_clear",
    "mobile_wait_element",
    "web_element_click",
    "web_element_dblclick",
    "web_element_type",
    "web_element_clear",
    "elementClick",
    "wait_element",
    "wait_for_element",
})

_SNAPSHOT_INTENT_RE = re.compile(
    r"截图|截屏|screenshot|snapshot|留证|截取",
    re.IGNORECASE,
)
_ASSERT_INTENT_RE = re.compile(
    r"确认|检查|验证|断言|校验|应当|应该|必须.*显示|可见|verify|assert|check\b",
    re.IGNORECASE,
)

#: 断言类关键字前缀 / 精确 id（用于软警告）
_ASSERT_KEYWORD_MARKERS = (
    "_verify_",
    "verify_",
    "_assert_",
    "assert_",
)


def _bounded_env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int((os.environ.get(name) or str(default)).strip())))
    except ValueError:
        return default


def _max_llm_calls(max_turns: int) -> int:
    """单用例 AI 调用上限：跟着回合预算走，不能反过来卡死业务。"""
    default = min(HARD_MAX_LLM_CALLS_PER_CASE, max_turns + LLM_CALL_HEADROOM)
    return _bounded_env_int(
        "AUTOPILOT_AUTHORING_MAX_LLM_CALLS_PER_CASE",
        default,
        1,
        HARD_MAX_LLM_CALLS_PER_CASE,
    )


def _page_locators(elements_text: str) -> set[str]:
    """页面摘要里 ``l`` 字段给出的可用定位串集合。"""
    try:
        items = json.loads(elements_text or "[]")
    except (TypeError, ValueError):
        return set()
    if not isinstance(items, list):
        return set()
    out: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            loc = str(item.get("l") or "").strip()
            if loc:
                out.add(loc)
    return out


def _step_locator(step: GeneratedStep) -> str:
    for key in ("locator", "loc", "target"):
        val = str((step.params or {}).get(key) or "").strip()
        if val:
            return val
    return ""


def _entry_target(step: GeneratedStep) -> str:
    params = step.params or {}
    return str(
        params.get("packageName")
        or params.get("url")
        or params.get("bundleId")
        or ""
    ).strip().lower()


def _nl_wants_snapshot(natural_language: str) -> bool:
    return bool(_SNAPSHOT_INTENT_RE.search(natural_language or ""))


def _nl_wants_assert(natural_language: str) -> bool:
    return bool(_ASSERT_INTENT_RE.search(natural_language or ""))


def _step_is_assert(step: GeneratedStep) -> bool:
    kid = (step.keyword_id or "").lower()
    return any(m in kid for m in _ASSERT_KEYWORD_MARKERS)


def _empty_page_guidance(element_count: int, elements_text: str) -> str:
    """采页为空时给可执行建议（不默认烧 Vision token）。"""
    if element_count > 0:
        return ""
    raw = (elements_text or "").strip()
    if raw not in ("", "[]"):
        return ""
    return (
        "当前页未采到可交互控件：请确认应用已打开且非纯画布/闪屏；"
        "可稍后重试，或开启检视器确认页面树。复杂无障碍树界面可后续开启 Vision 兜底"
    )


def _missing_assert_warning(
    recorded: list[GeneratedStep], natural_language: str
) -> str:
    if not _nl_wants_assert(natural_language):
        return ""
    if any(_step_is_assert(s) for s in recorded):
        return ""
    return (
        "需求含确认/验证语义，但草稿中尚无断言步骤（verify_*）；"
        "建议补一步断言后再上传"
    )


def _filter_planned_steps(
    steps: list[GeneratedStep],
    *,
    recorded: list[GeneratedStep],
    page_locators: set[str],
    natural_language: str = "",
    locator_cache: Any = None,
    page_sig: str = "",
) -> tuple[list[GeneratedStep], list[str], list[str]]:
    """丢掉不该固化的步骤，返回 ``(可执行步骤, 跳过原因, 提醒)``。

    - 重复入口：仅拦截「同一包名/URL」再次启动；跨 App 允许
    - 截图：无用户意图时丢弃
    - 定位：摘要外定位符对 locator 绑定关键字默认拒绝（防编造）；
      同页缓存可先改写再判定
    """
    done_entries = {
        (s.keyword_id, _entry_target(s))
        for s in recorded
        if s.keyword_id in ENTRY_KEYWORD_IDS
    }
    seen = {(s.keyword_id, tuple(sorted((s.params or {}).items()))) for s in recorded}
    want_snap = _nl_wants_snapshot(natural_language)
    kept: list[GeneratedStep] = []
    skipped: list[str] = []
    notes: list[str] = []
    for step in steps:
        kid = step.keyword_id
        if locator_cache is not None and page_sig:
            hit = locator_cache.rewrite_step_locator(
                step, page_sig=page_sig, page_locators=page_locators
            )
            if hit:
                notes.append(hit)
        if kid in SNAPSHOT_KEYWORD_IDS and not want_snap:
            skipped.append(
                f"跳过截图步骤 {kid}：用户未要求留证；采页由编写器负责"
            )
            continue
        if kid in ENTRY_KEYWORD_IDS:
            target = _entry_target(step)
            if (kid, target) in done_entries:
                skipped.append(
                    f"跳过重复入口 {kid}（目标 {target or '默认'}）："
                    "请基于当前页面继续"
                )
                continue
        sig = (kid, tuple(sorted((step.params or {}).items())))
        if sig in seen:
            skipped.append(f"跳过重复步骤 {kid}：参数与已固化步骤完全相同")
            continue
        loc = _step_locator(step)
        if (
            kid in LOCATOR_BOUND_KEYWORD_IDS
            and loc
            and page_locators
            and loc not in page_locators
        ):
            skipped.append(
                f"拒绝摘要外定位符 {loc}（{kid}）："
                "请只用当前页 ``l`` 字段，或先导航到目标页"
            )
            continue
        seen.add(sig)
        if kid in ENTRY_KEYWORD_IDS:
            done_entries.add((kid, _entry_target(step)))
        kept.append(step)
    return kept, skipped, notes


def _bootstrap_start_step(request: AuthoringRequest, platform: str) -> GeneratedStep | None:
    pkg = (request.package_name or "").strip()
    url = (request.start_url or "").strip()
    if platform in ("android", "ios") and pkg:
        params = {
            "type": platform,
            "packageName": pkg,
            "activityName": (request.activity_name or "").strip(),
        }
        label = (request.app_label or pkg).strip()
        return GeneratedStep(
            keyword_id="mobile_app_start",
            params=params,
            comment=f"启动 {label}",
        )
    if platform == "web" and url:
        return GeneratedStep(
            keyword_id="web_browser_open",
            params={"url": url, "type": _web_browser_type()},
            comment=f"打开 {url}",
        )
    return None


def _web_browser_type() -> str:
    """浏览器类型交给 IDE 设置，取不到时留空由关键字用默认值。"""
    try:
        from ..runtime import settings

        return str(settings.web_browser() or "").strip()
    except (ImportError, AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return ""


def run_session_authoring(
    request: AuthoringRequest,
    *,
    ctx: Any,
    chat: ChatFn | None = None,
    executor: StepExecutor | None = None,
    on_progress: ProgressFn | None = None,
) -> AuthoringDraft:
    """正式主路径：驱动会话完成 NL 目标，返回已验证可执行的传统步骤草稿。"""
    nl = (request.natural_language or "").strip()
    if not nl:
        raise AuthoringError("请输入自然语言需求")
    if ctx is None:
        raise AuthoringError("请先连接设备或打开检视器，再开始 AI 编写")

    platform = normalize_platform(request.platform)
    max_steps = clamp_max_steps(request.max_steps)
    max_turns = turns_for_steps(max_steps, request.max_turns)
    catalog = build_keyword_catalog(platform)
    if not catalog:
        raise AuthoringError(f"平台 {platform} 无可用关键字白名单")

    run_step = executor or execute_keyword_step
    hints = parse_nl_hints(nl)
    input_text = "、".join(request.input_texts or hints.input_texts)
    recorded: list[GeneratedStep] = []
    warnings: list[str] = []
    title = (request.title or nl[:40]).strip()
    history: list[dict[str, Any]] = []
    consecutive_failures = 0
    goal_completed = False
    llm_calls = 0
    prompt_chars_used = 0
    max_llm_calls = _max_llm_calls(max_turns)
    max_prompt_chars = _bounded_env_int(
        "AUTOPILOT_AUTHORING_MAX_PROMPT_CHARS_PER_CASE",
        DEFAULT_MAX_PROMPT_CHARS_PER_CASE,
        100_000,
        5_000_000,
    )
    loc_cache = PageLocatorCache()
    repeat_watch = RepeatWatch()
    repeat_stopped = False
    trace = AuthoringTrace(
        title=title,
        platform=platform,
        natural_language=nl,
    )

    def _progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    boot = _bootstrap_start_step(request, platform)
    if boot is not None:
        _progress(f"执行入口：{boot.keyword_id}")
        try:
            run_step(boot, ctx)
            recorded.append(boot)
            history.append(boot.to_dict())
        except AuthoringError as exc:
            warnings.append(f"入口步失败，改由模型规划：{exc}")

    for turn in range(1, max_turns + 1):
        if len(recorded) >= max_steps:
            warnings.append(f"已达步数上限 {max_steps}")
            break
        turn_rec = TurnTraceRecord(turn=turn)
        try:
            # 首轮等稳定：冷启动闪屏会污染第一轮规划
            cap = (
                capture_settled_ui_context(ctx, platform)
                if turn == 1
                else capture_ui_context(ctx, platform)
            )
            el_text = str(cap.get("elements_text") or "[]")
            screen = str(cap.get("screen") or "")
            page_locators = _page_locators(el_text)
            page_sig = page_signature(el_text)
            turn_rec.page_sig = page_sig
            turn_rec.element_count = int(cap.get("element_count") or 0)
            turn_rec.screen = screen
            empty_tip = _empty_page_guidance(turn_rec.element_count, el_text)
            if empty_tip:
                warnings.append(f"第 {turn} 回合：{empty_tip}")
                vis_text, vis_count, vis_notes = enrich_empty_page_via_vision(
                    ctx=ctx,
                    platform=platform,
                    natural_language=nl,
                )
                warnings.extend(vis_notes)
                if vis_count > 0:
                    el_text = vis_text
                    page_locators = _page_locators(el_text)
                    page_sig = page_signature(el_text)
                    turn_rec.page_sig = page_sig
                    turn_rec.element_count = vis_count
        except AuthoringError as exc:
            el_text = "[]"
            screen = ""
            page_locators = set()
            page_sig = "empty"
            turn_rec.page_sig = page_sig
            warnings.append(f"第 {turn} 回合采页：{exc}")
            tip = _empty_page_guidance(0, "[]")
            if tip:
                warnings.append(f"第 {turn} 回合：{tip}")
                vis_text, vis_count, vis_notes = enrich_empty_page_via_vision(
                    ctx=ctx,
                    platform=platform,
                    natural_language=nl,
                )
                warnings.extend(vis_notes)
                if vis_count > 0:
                    el_text = vis_text
                    page_locators = _page_locators(el_text)
                    page_sig = page_signature(el_text)
                    turn_rec.page_sig = page_sig
                    turn_rec.element_count = vis_count

        remaining = max_steps - len(recorded)
        repeat_note = repeat_watch.prompt_warning(page_sig)
        repeat_verdict = repeat_watch.assess()
        turn_rec.repeat_level = repeat_verdict.level
        turn_rec.repeat_note = repeat_note
        if repeat_verdict.should_stop:
            warnings.append(
                f"同一操作在未变化的页面上连续 {repeat_verdict.consecutive} 次，停止编写"
            )
            trace.add_turn(turn_rec)
            break
        prompt = build_agent_turn_prompt(
            natural_language=nl,
            platform=platform,
            elements_text=el_text,
            keyword_catalog=catalog,
            history=history,
            package_name=request.package_name,
            start_url=request.start_url,
            remaining_steps=remaining,
            input_text=input_text,
            screen=screen,
            repeat_warning=repeat_note,
        )
        if llm_calls >= max_llm_calls:
            warnings.append(f"已达单用例 AI 调用上限 {max_llm_calls}，停止继续规划")
            break
        if prompt_chars_used + len(prompt) > max_prompt_chars:
            warnings.append(
                f"已达单用例 prompt 预算 {max_prompt_chars} 字符，停止继续规划"
            )
            break
        _progress(f"第 {turn}/{max_turns} 回合规划…")
        llm_calls += 1
        prompt_chars_used += len(prompt)
        data = complete_json(prompt, chat=chat, purpose="authoring")
        done = bool(data.get("done"))
        turn_rec.done = done
        turn_rec.notes = str(data.get("notes") or "").strip()
        # 只在模型宣告完成时采纳标题，避免中途「下一步描述」覆盖用例名
        if done and data.get("title"):
            title = str(data.get("title") or title).strip() or title
        raw_steps = data.get("steps")
        if done and (not isinstance(raw_steps, list) or not raw_steps):
            goal_completed = True
            trace.add_turn(turn_rec)
            break
        draft = parse_llm_draft(
            data,
            platform=platform,
            max_steps=min(MAX_STEPS_PER_TURN, remaining),
            fallback_title=title,
        )
        if draft.warnings:
            warnings.extend(draft.warnings)
        # 两阶段定位：先按 target/comment 解析 locator，再走缓存与摘要校验
        draft.steps, locate_notes = resolve_planned_locators(
            draft.steps,
            el_text,
            page_locators=page_locators,
            chat=chat,
        )
        warnings.extend(locate_notes)
        planned, skipped, notes = _filter_planned_steps(
            draft.steps,
            recorded=recorded,
            page_locators=page_locators,
            natural_language=nl,
            locator_cache=loc_cache,
            page_sig=page_sig,
        )
        warnings.extend(notes)
        turn_rec.cache_hits = [
            n for n in (locate_notes + notes) if ("定位" in n or "缓存" in n)
        ]
        turn_rec.planned = [s.to_dict() for s in planned]
        for note in skipped:
            warnings.append(f"第 {turn} 回合{note}")
            history.append({"skipped": note})
            turn_rec.skipped.append(note)
        if not planned:
            if done:
                goal_completed = True
                trace.add_turn(turn_rec)
                break
            stuck_hit = False
            if skipped and repeat_watch.page_stuck(page_sig):
                for step in draft.steps:
                    stuck = repeat_watch.note_stuck_retry(
                        step.keyword_id, _step_locator(step), page_sig
                    )
                    turn_rec.repeat_level = stuck.level
                    turn_rec.repeat_note = stuck.message
                    if stuck.level in {"warn", "severe"} and stuck.message:
                        warnings.append(stuck.message)
                    if stuck.should_stop:
                        warnings.append(
                            f"同一操作在未变化的页面上连续 {stuck.consecutive} 次，停止编写"
                        )
                        repeat_stopped = True
                        stuck_hit = True
                        break
            # 模型给了步骤但全被过滤（如重复入口）≠「没给出步骤」
            if skipped:
                warnings.append(
                    f"第 {turn} 回合规划步骤均被过滤，继续下一回合"
                )
            else:
                warnings.append(f"第 {turn} 回合未给出可执行步骤")
            notes = str(data.get("notes") or "").strip()
            if notes:
                warnings.append(f"模型备注：{notes}")
            trace.add_turn(turn_rec)
            if repeat_stopped or stuck_hit:
                break
            if skipped:
                continue
            break

        turn_failed = False
        for step in planned:
            if len(recorded) >= max_steps:
                break
            if repeat_watch.page_stuck(page_sig):
                preview = repeat_watch.note_stuck_retry(
                    step.keyword_id, _step_locator(step), page_sig
                )
                if preview.should_stop:
                    warnings.append(
                        f"同一操作在未变化的页面上连续 {preview.consecutive} 次，停止编写"
                    )
                    repeat_stopped = True
                    break
            _progress(f"执行：{step.comment or step.keyword_id}")
            try:
                run_step(step, ctx)
            except AuthoringError as exc:
                turn_failed = True
                consecutive_failures += 1
                reason = str(exc)
                warnings.append(f"步骤失败已跳过：{step.keyword_id} → {reason}")
                fail_row = {**step.to_dict(), "failed": True, "error": reason[:200]}
                history.append(fail_row)
                turn_rec.failed.append(fail_row)
                break
            consecutive_failures = 0
            recorded.append(step)
            history.append(step.to_dict())
            turn_rec.executed.append(step.to_dict())
            loc = _step_locator(step)
            if loc and loc in page_locators:
                loc_cache.remember(
                    page_sig,
                    hint=step.comment or loc,
                    locator=loc,
                    page_locators=page_locators,
                )
            repeat_watch.record_executed(
                step.keyword_id,
                loc,
                page_sig,
                page_changing=step.keyword_id in PAGE_CHANGING_KEYWORD_IDS,
            )
            # 页面可能已变：停本回合，下一回合重新观察后再规划
            if step.keyword_id in PAGE_CHANGING_KEYWORD_IDS:
                break

        trace.add_turn(turn_rec)
        if repeat_stopped:
            break
        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            warnings.append(f"连续 {consecutive_failures} 次步骤失败，停止编写")
            break
        if turn_failed:
            continue
        if done:
            goal_completed = True
            break
    else:
        warnings.append("达到回合上限，可能未完全完成目标")

    if not recorded:
        raise AuthoringError("会话驱动未产生任何成功步骤：" + "；".join(warnings[:5]))

    miss = _missing_assert_warning(recorded, nl)
    if miss:
        warnings.append(miss)

    judge = judge_authoring_goal(
        natural_language=nl,
        recorded=recorded,
        goal_completed=goal_completed,
        warnings=warnings,
        chat=chat,
    )
    # 事后裁判只加注：不得据此改 goal_completed / 已记录步骤
    if judge:
        trace.goal_judge = judge
        src = str(judge.get("source") or "heuristic")
        reason = str(judge.get("reason") or "").strip()
        if reason:
            warnings.append(f"事后裁判（{src}，不改步骤结果）：{reason}")

    trace.title = title
    trace.goal_completed = goal_completed
    return AuthoringDraft(
        title=title,
        platform=platform,
        steps=recorded,
        warnings=warnings,
        raw_llm="",
        mode="session",
        session_verified=True,
        goal_completed=goal_completed,
        decision_trace=trace.to_dict(),
    )


def try_page_nl(
    request: AuthoringRequest,
    *,
    ctx: Any,
    chat: ChatFn | None = None,
    executor: StepExecutor | None = None,
    on_progress: ProgressFn | None = None,
) -> AuthoringDraft:
    """检视器/对话框「试一句」：当前页最多 1 回合、少量步骤，不追求完整用例。

    用于确认模型是否理解当前页，结果可预览；正式编写仍走 ``run_session_authoring``。
    """
    trial = AuthoringRequest(
        natural_language=request.natural_language,
        platform=request.platform,
        title=request.title or "试跑当前页",
        max_steps=min(4, clamp_max_steps(request.max_steps)),
        max_turns=1,
        include_screenshot=request.include_screenshot,
        draft_only=True,
        mode="session",
        package_name=request.package_name,
        activity_name=request.activity_name,
        start_url=request.start_url,
        app_label=request.app_label,
        input_texts=request.input_texts,
    )
    draft = run_session_authoring(
        trial,
        ctx=ctx,
        chat=chat,
        executor=executor,
        on_progress=on_progress,
    )
    draft.warnings = list(draft.warnings) + ["试跑当前页：未写入工程，仅预览"]
    draft.mode = "try_page"
    return draft
