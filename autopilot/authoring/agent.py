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
from .goal_judge import (
    completion_evidence,
    goal_content_tokens,
    high_stakes_goal,
    judge_authoring_goal,
    page_has_goal_token,
)
from .secrets import (
    collect_secret_map,
    mask_history_row,
    mask_text,
    restore_step_params,
)
from .vision_fallback import enrich_empty_page_via_vision, vision_fallback_enabled
from .contract import (
    MAX_STEPS_PER_TURN,
    AuthoringDraft,
    AuthoringError,
    AuthoringRequest,
    GeneratedStep,
    NavigationRole,
    clamp_max_steps,
    normalize_platform,
    turns_for_steps,
)
from .llm_client import ChatFn, complete_json
from .locate_resolve import resolve_planned_locators
from .locator_cache import PageLocatorCache, page_signature
from .nl_parse import parse_nl_hints
from .navigation import (
    NavigationLedger,
    build_navigation_plan,
    infer_navigation_role,
    role_for_step_data,
)
from .app_task import belongs_to_target, is_overlay_package, packages_from_elements, task_ownership_note
from .prompt import build_agent_turn_prompt
from .registry_catalog import build_keyword_catalog
from .repeat import RepeatWatch
from .step_runner import StepExecutor, execute_keyword_step
from .turn_trace import AuthoringTrace, TurnTraceRecord


ProgressFn = Callable[[str], None]


def _is_cancelled(cancel_event: Any) -> bool:
    try:
        return bool(cancel_event is not None and cancel_event.is_set())
    except (AttributeError, TypeError):
        return False


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
    "http_session_begin",
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
    "mobile_swipe_direction",
    "mobile_define_swipe_direction",
    "mobile_presskey",
    "mobile_slip_for_element",
    "mobile_define_slip_for_element",
    "mobile_back",
    "ios_alert_accept",
    "ios_alert_dismiss",
    "web_browser_open",
    "web_browser_locate",
    "web_browser_back",
    "web_browser_forward",
    "web_browser_refresh",
    "web_browser_scroll_vertical_bar",
    "web_element_click",
    "web_element_JSclick",
    "web_element_check_click",
    "web_element_scroll_click",
    "web_element_click_and_switch",
    "web_element_double_click",
    "web_element_checkbox_click",
    "web_element_radio_click",
    "elementClick",
})

#: 带 locator 参数、必须落在当前页摘要内的关键字
LOCATOR_BOUND_KEYWORD_IDS = frozenset({
    "mobile_element_click",
    "mobile_element_long_click",
    "mobile_element_text_input",
    "mobile_element_clear",
    "mobile_element_text_clear",
    "mobile_wait_element",
    "mobile_wait_element_visible",
    "web_element_click",
    "web_element_JSclick",
    "web_element_check_click",
    "web_element_scroll_click",
    "web_element_click_and_switch",
    "web_element_double_click",
    "web_element_text_input",
    "web_element_checkbox_click",
    "web_element_radio_click",
    "web_element_combo_select",
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
_EXPLICIT_REPEAT_INTENT_RE = re.compile(
    r"重复|再次|再来|两次|二次|[2-9]\s*次|twice|repeat|[2-9]\s*times?",
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


def _ambiguous_page_locators(elements_text: str) -> set[str]:
    """页面摘要中无法唯一命中的定位符（重复 ``l`` 或序列化器显式 ``dup``）。"""
    try:
        items = json.loads(elements_text or "[]")
    except (TypeError, ValueError):
        return set()
    if not isinstance(items, list):
        return set()
    counts: dict[str, int] = {}
    explicit: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        loc = str(item.get("l") or "").strip()
        if not loc:
            continue
        counts[loc] = counts.get(loc, 0) + 1
        try:
            if int(item.get("dup") or 0) > 1:
                explicit.add(loc)
        except (TypeError, ValueError):
            pass
    return explicit | {loc for loc, count in counts.items() if count > 1}


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
        or params.get("base_url")
        or ""
    ).strip().lower()


def _nl_wants_snapshot(natural_language: str) -> bool:
    return bool(_SNAPSHOT_INTENT_RE.search(natural_language or ""))


def _nl_wants_assert(natural_language: str) -> bool:
    return bool(_ASSERT_INTENT_RE.search(natural_language or ""))


def _nl_allows_business_repeat(natural_language: str) -> bool:
    return bool(_EXPLICIT_REPEAT_INTENT_RE.search(natural_language or ""))


def _step_is_assert(step: GeneratedStep) -> bool:
    kid = (step.keyword_id or "").lower()
    return any(m in kid for m in _ASSERT_KEYWORD_MARKERS)


def _normalize_assertion_step(
    step: GeneratedStep,
    *,
    role: NavigationRole,
    assertion_requested: bool,
) -> str:
    """把模型作为 Assert 输出的移动端可见性等待规范成正式 verify 步骤。"""
    if (
        assertion_requested
        and role == "assert"
        and step.keyword_id == "mobile_wait_element_visible"
    ):
        step.keyword_id = "mobile_verify_element_visible"
        return "断言规范化：mobile_wait_element_visible → mobile_verify_element_visible"
    return ""


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
    recorded: list[GeneratedStep], natural_language: str, platform: str = ""
) -> str:
    plat = (platform or "").strip().lower()
    has_assert = any(_step_is_assert(s) for s in recorded)
    if plat == "http":
        if has_assert:
            return ""
        return (
            "HTTP 用例尚无断言步骤（http_assert_* / json_assert_*）；"
            "建议补一步断言后再上传"
        )
    if not _nl_wants_assert(natural_language):
        return ""
    if has_assert:
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
    target_package: str = "",
    current_packages: tuple[str, ...] | list[str] = (),
) -> tuple[list[GeneratedStep], list[str], list[str]]:
    """丢掉不该固化的步骤，返回 ``(可执行步骤, 跳过原因, 提醒)``。

    - 重复入口：仅拦截「同一包名/URL」再次启动；跨 App 允许
    - 目标任务内的系统叠加层：禁止再 mobile_app_start
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
    allow_business_repeat = _nl_allows_business_repeat(natural_language)
    current_pkgs = tuple(
        str(p).strip() for p in (current_packages or ()) if str(p).strip()
    )
    target_pkg = (target_package or "").strip()
    # 空采页不算「已在目标任务内」，否则首回合会把合法的启动步骤丢掉。
    in_target_task = bool(target_pkg and current_pkgs) and belongs_to_target(
        current_pkgs, target_pkg
    )
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
            if (
                kid == "mobile_app_start"
                and in_target_task
                and (
                    not target
                    or target == target_pkg.lower()
                    or is_overlay_package(target)
                )
            ):
                skipped.append(
                    "跳过目标任务内再次启动（当前为系统叠加层或仍在目标应用）"
                )
                continue
        sig = (kid, tuple(sorted((step.params or {}).items())))
        if sig in seen and not allow_business_repeat:
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
    if getattr(request, "use_current_app", False):
        return None
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
    if platform == "http":
        params = {}
        if url:
            params["base_url"] = url
        return GeneratedStep(
            keyword_id="http_session_begin",
            params=params,
            comment="开启 HTTP 会话" + (f"（{url}）" if url else ""),
        )
    return None


def _web_browser_type() -> str:
    """浏览器类型交给 IDE 设置，取不到时留空由关键字用默认值。"""
    try:
        from ..runtime import settings

        return str(settings.web_browser() or "").strip()
    except (ImportError, AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return ""


def _replay_navigation_steps(
    steps: list[GeneratedStep],
    *,
    ctx: Any,
    run_step: StepExecutor,
    platform: str = "",
    checkpoints: dict[int, str] | None = None,
    check_trace: list[dict[str, Any]] | None = None,
) -> tuple[bool, str]:
    """从入口重放，并在已确认的导航边逐层校验页面语义。"""
    if not any(s.keyword_id in ENTRY_KEYWORD_IDS for s in steps):
        return False, "最终路径没有可重放入口，无法恢复确定起点"
    expected_by_step = checkpoints or {}
    for index, step in enumerate(steps, start=1):
        try:
            run_step(step, ctx)
        except AuthoringError as exc:
            return False, f"第 {index} 步 {step.keyword_id} 重放失败：{exc}"
        expected_sig = expected_by_step.get(index)
        if not expected_sig:
            continue
        try:
            cap = capture_settled_ui_context(ctx, platform)
        except AuthoringError as exc:
            return False, f"第 {index} 步重放后采页失败：{exc}"
        meta = cap.get("_meta")
        timed_out = isinstance(meta, dict) and bool(meta.get("timed_out"))
        observed_sig = page_signature(str(cap.get("elements_text") or "[]"))
        passed = not timed_out and observed_sig == expected_sig
        if check_trace is not None:
            check_trace.append({
                "step_index": index,
                "keyword_id": step.keyword_id,
                "expected_page_sig": expected_sig,
                "observed_page_sig": observed_sig,
                "settle_timed_out": timed_out,
                "passed": passed,
            })
        if timed_out:
            return False, f"第 {index} 步重放后页面稳定等待超时"
        if observed_sig != expected_sig:
            return (
                False,
                f"第 {index} 步重放页面不一致："
                f"expected={expected_sig}, observed={observed_sig}",
            )
    return True, ""


_PREFLIGHT_LOCATOR_KEYWORDS = frozenset({
    "mobile_element_click",
    "mobile_element_long_click",
    "mobile_element_text_input",
    "mobile_element_text_clear",
    "web_element_click",
    "web_element_JSclick",
    "web_element_check_click",
    "web_element_scroll_click",
    "web_element_click_and_switch",
    "web_element_double_click",
    "web_element_text_input",
    "web_element_checkbox_click",
    "web_element_radio_click",
    "web_element_combo_select",
    "elementClick",
})


def _preflight_locator_step(
    step: GeneratedStep,
    *,
    ctx: Any,
    platform: str,
    expected_page_sig: str,
) -> tuple[bool, str, str]:
    """执行前短重试 live tree；区分页面漂移与控件消失。"""
    if platform not in ("android", "ios", "web"):
        return True, "", expected_page_sig
    if step.keyword_id not in _PREFLIGHT_LOCATOR_KEYWORDS:
        return True, "", expected_page_sig
    locator = _step_locator(step)
    if not locator:
        return False, "Safety Net：控件动作缺少 locator", expected_page_sig
    retry_count = _bounded_env_int(
        "AUTOPILOT_AUTHORING_PREFLIGHT_DRIFT_RETRIES",
        2,
        0,
        3,
    )
    live_sig = expected_page_sig
    for attempt in range(retry_count + 1):
        try:
            live = capture_ui_context(ctx, platform)
        except AuthoringError as exc:
            if attempt >= retry_count:
                return False, f"Safety Net：执行前采页失败：{exc}", live_sig
            continue
        live_text = str(live.get("elements_text") or "[]")
        live_sig = page_signature(live_text)
        if live_sig == expected_page_sig:
            if locator in _page_locators(live_text):
                if locator in _ambiguous_page_locators(live_text):
                    return (
                        False,
                        f"Safety Net locator_ambiguous：定位符 {locator} "
                        "在当前 live tree 命中多个控件，拒绝执行",
                        live_sig,
                    )
                return True, "", live_sig
            return (
                False,
                f"Safety Net locator_missing：当前 live tree 已找不到 locator {locator}",
                live_sig,
            )
    return (
        False,
        "Safety Net page_drift：执行前页面与规划页面不一致，"
        f"expected={expected_page_sig}, live={live_sig}",
        live_sig,
    )


def _call_capture(fn: Callable[..., dict[str, Any]], ctx: Any, platform: str, **kwargs: Any) -> dict[str, Any]:
    """兼容测试里只接收 (ctx, platform) 的采页桩。"""
    try:
        return fn(ctx, platform, **kwargs)
    except TypeError:
        return fn(ctx, platform)


def _observe_terminal_target(
    *,
    ctx: Any,
    platform: str,
    expected_before_sig: str,
    natural_language: str = "",
) -> tuple[bool, str, dict[str, Any]]:
    """target 只执行一次；随后稳定观察其可见后果用于收尾门禁。"""
    tokens = goal_content_tokens(natural_language)
    try:
        cap = _call_capture(
            capture_settled_ui_context,
            ctx,
            platform,
            prefer_texts=tokens or None,
        )
    except AuthoringError as exc:
        return False, f"target 执行后采页失败：{exc}", {}
    meta = cap.get("_meta")
    timed_out = isinstance(meta, dict) and bool(meta.get("timed_out"))
    elements_text = str(cap.get("elements_text") or "[]")
    page_sig = page_signature(elements_text)
    semantic_hit = page_has_goal_token(elements_text, tokens) if tokens else None
    evidence = {
        "page_sig": page_sig,
        "page_sig_before": expected_before_sig,
        "page_changed": page_sig != expected_before_sig,
        "settled": not timed_out,
        "timed_out": timed_out,
        "element_count": int(cap.get("element_count") or 0),
        "semantic_hit": semantic_hit,
        "semantic_tokens": tokens[:8],
    }
    if timed_out:
        return False, "target 执行后页面稳定等待超时", evidence
    if page_sig == "empty":
        return False, "target 执行后未获得有效页面语义", evidence
    if expected_before_sig and page_sig == expected_before_sig:
        return False, "target 执行后页面语义未变化，无法确认目标动作生效", evidence
    if high_stakes_goal(natural_language) and tokens and semantic_hit is False:
        return False, "target 执行后页面未出现与需求匹配的文案，无法确认目标动作生效", evidence
    return True, "", evidence


def run_session_authoring(
    request: AuthoringRequest,
    *,
    ctx: Any,
    chat: ChatFn | None = None,
    executor: StepExecutor | None = None,
    on_progress: ProgressFn | None = None,
    cancel_event: Any = None,
) -> AuthoringDraft:
    """正式主路径：驱动会话完成 NL 目标，返回已验证可执行的传统步骤草稿。"""
    nl = (request.natural_language or "").strip()
    if not nl:
        raise AuthoringError("请输入自然语言需求")
    platform = normalize_platform(request.platform)
    if ctx is None:
        if platform == "http":
            raise AuthoringError("接口编写缺少执行上下文，请从编写对话框重新开始")
        raise AuthoringError("请先连接设备或打开检视器，再开始 AI 编写")

    max_steps = clamp_max_steps(request.max_steps)
    max_turns = turns_for_steps(max_steps, request.max_turns)
    catalog = build_keyword_catalog(platform)
    if not catalog:
        raise AuthoringError(f"平台 {platform} 无可用关键字白名单")

    run_step = executor or execute_keyword_step
    hints = parse_nl_hints(nl)
    raw_inputs = tuple(request.input_texts or hints.input_texts)
    secret_map = collect_secret_map(nl, raw_inputs)
    input_text = "、".join(mask_text(t, secret_map) for t in raw_inputs if t)
    prompt_nl = mask_text(nl, secret_map)
    prefer_texts = goal_content_tokens(nl)
    recorded: list[GeneratedStep] = []
    warnings: list[str] = []
    title = (request.title or nl[:40]).strip()
    history: list[dict[str, Any]] = []
    consecutive_failures = 0
    empty_observations = 0
    goal_completed = False
    target_confirmed = False
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

    if _is_cancelled(cancel_event):
        warnings.append("已停止编写")
        return AuthoringDraft(
            title=title,
            platform=platform,
            steps=[],
            warnings=warnings,
            mode="session",
            session_verified=False,
            goal_completed=False,
        )

    boot = _bootstrap_start_step(request, platform)
    if boot is not None:
        _progress(f"执行入口：{boot.keyword_id}")
        try:
            run_step(boot, ctx)
            recorded.append(boot)
            history.append(mask_history_row(boot.to_dict(), secret_map))
        except AuthoringError as exc:
            warnings.append(f"入口步失败，改由模型规划：{exc}")

    nav_ledger = (
        NavigationLedger(
            build_navigation_plan(nl, platform=platform),
            initial_steps=recorded,
        )
        if platform in ("android", "ios", "web")
        else None
    )

    for turn in range(1, max_turns + 1):
        if _is_cancelled(cancel_event):
            warnings.append("已停止编写")
            goal_completed = False
            break
        if len(recorded) >= max_steps:
            warnings.append(f"已达步数上限 {max_steps}")
            break
        turn_rec = TurnTraceRecord(turn=turn)
        observation_valid = True
        observation_error = ""
        cap: dict[str, Any] = {}
        try:
            # 首轮和 pending 结算都等稳定：避免动画/Activity 中间态误判 transition。
            require_settled = bool(
                turn == 1
                or (
                    nav_ledger is not None
                    and (nav_ledger.pending is not None or not nav_ledger.frames)
                )
            )
            cap = (
                _call_capture(
                    capture_settled_ui_context,
                    ctx,
                    platform,
                    prefer_texts=prefer_texts,
                )
                if require_settled
                else _call_capture(
                    capture_ui_context,
                    ctx,
                    platform,
                    prefer_texts=prefer_texts,
                )
            )
            settle_meta = cap.get("_meta")
            if (
                require_settled
                and isinstance(settle_meta, dict)
                and bool(settle_meta.get("timed_out"))
            ):
                observation_valid = False
                observation_error = "页面稳定等待超时，本回合观察不用于结算 transition"
            el_text = str(cap.get("elements_text") or "[]")
            screen = str(cap.get("screen") or "")
            page_locators = _page_locators(el_text)
            page_sig = page_signature(el_text)
            turn_rec.page_sig = page_sig
            turn_rec.element_count = int(cap.get("element_count") or 0)
            turn_rec.screen = screen
            empty_tip = (
                ""
                if platform == "http"
                else _empty_page_guidance(turn_rec.element_count, el_text)
            )
            if empty_tip:
                empty_observations += 1
                warnings.append(f"第 {turn} 回合：{empty_tip}")
                if empty_observations >= 2 and not vision_fallback_enabled():
                    warnings.append(
                        "连续两回合未采到可交互控件。"
                        "可设置 AUTOPILOT_AUTHORING_VISION_FALLBACK=1 启用视觉兜底"
                    )
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
            observation_valid = False
            observation_error = str(exc)
            el_text = "[]"
            screen = ""
            page_locators = set()
            page_sig = "empty"
            turn_rec.page_sig = page_sig
            warnings.append(f"第 {turn} 回合采页：{exc}")
            tip = "" if platform == "http" else _empty_page_guidance(0, "[]")
            if tip:
                warnings.append(f"第 {turn} 回合：{tip}")
                vis_text, vis_count, vis_notes = enrich_empty_page_via_vision(
                    ctx=ctx,
                    platform=platform,
                    natural_language=nl,
                )
                warnings.extend(vis_notes)
                if vis_count > 0:
                    observation_valid = True
                    observation_error = ""
                    el_text = vis_text
                    page_locators = _page_locators(el_text)
                    page_sig = page_signature(el_text)
                    turn_rec.page_sig = page_sig
                    turn_rec.element_count = vis_count

        if nav_ledger is not None:
            previous_sig = nav_ledger.current_page_sig
            nav_outcome = nav_ledger.begin_page(
                page_sig,
                valid=observation_valid,
                error=observation_error,
            )
            turn_rec.page_sig_before = previous_sig
            turn_rec.page_sig_after = page_sig
            turn_rec.observation_valid = nav_outcome.observation_valid
            turn_rec.navigation = {
                "depth": max(0, len(nav_ledger.frames) - 1),
                "scrolls": nav_ledger.scroll_count,
                "backtracks": nav_ledger.backtrack_count,
                "active_strategy": nav_ledger.plan.active_strategy,
                "tried_strategies": list(nav_ledger.plan.tried_strategies),
                "last_closed_incident": nav_ledger.last_closed_incident,
            }
            if nav_outcome.pruned:
                turn_rec.pruned = [s.to_dict() for s in nav_outcome.pruned]
                warnings.append(
                    f"第 {turn} 回合返回历史页面，已从最终用例裁掉 "
                    f"{len(nav_outcome.pruned)} 个错误分支步骤"
                )
            if nav_outcome.incident is not None:
                turn_rec.incident = nav_outcome.incident.to_dict()
                warnings.append(
                    f"第 {turn} 回合导航反馈：{nav_outcome.incident.reason}"
                )
            recorded = list(nav_ledger.steps)
            if nav_ledger.stop_reason:
                trace.stop_reason = nav_ledger.stop_reason
                trace.add_turn(turn_rec)
                break
            if not nav_outcome.observation_valid:
                # 无有效观测时不调用 LLM、不执行任何动作；下一回合只重试采页。
                trace.add_turn(turn_rec)
                continue

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
            natural_language=prompt_nl,
            platform=platform,
            elements_text=el_text,
            keyword_catalog=catalog,
            history=[mask_history_row(row, secret_map) for row in history],
            package_name=request.package_name,
            start_url=request.start_url,
            remaining_steps=remaining,
            input_text=input_text,
            screen=screen,
            repeat_warning=repeat_note,
            navigation_context=(
                nav_ledger.prompt_context() if nav_ledger is not None else ""
            ),
            app_label=request.app_label,
            task_note=task_ownership_note(
                tuple(cap.get("packages") or ())
                or packages_from_elements(cap.get("elements")),
                request.package_name,
            ),
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
        if nav_ledger is not None and isinstance(data.get("navigation"), dict):
            nav_ledger.set_strategy(
                str(data["navigation"].get("strategy") or "").strip()
            )
        turn_rec.done = done
        turn_rec.notes = str(data.get("notes") or "").strip()
        # 只在模型宣告完成时采纳标题，避免中途「下一步描述」覆盖用例名
        if done and data.get("title"):
            title = str(data.get("title") or title).strip() or title
        raw_steps = data.get("steps")
        if done and (not isinstance(raw_steps, list) or not raw_steps):
            goal_completed = bool(
                nav_ledger is None
                or (
                    nav_ledger.pending is None
                    and nav_ledger.open_incident is None
                    and not nav_ledger.stop_reason
                )
            )
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
        step_roles: dict[int, NavigationRole] = {}
        for index, step in enumerate(draft.steps):
            step_roles[id(step)] = role_for_step_data(
                data, index, step, turn_done=done
            )
        # 两阶段定位：HTTP 观察的是响应而不是控件，跳过 locator 解析
        if platform == "http":
            locate_notes = []
        else:
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
            target_package=request.package_name or "",
            current_packages=(
                tuple(cap.get("packages") or ())
                or packages_from_elements(cap.get("elements"))
            ),
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
                goal_completed = bool(
                    nav_ledger is None
                    or (
                        nav_ledger.pending is None
                        and nav_ledger.open_incident is None
                        and not nav_ledger.stop_reason
                    )
                )
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
            role: NavigationRole = step_roles.get(
                id(step),
                infer_navigation_role(step, turn_done=done),
            )
            assertion_note = _normalize_assertion_step(
                step,
                role=role,
                assertion_requested=_nl_wants_assert(nl),
            )
            if assertion_note:
                warnings.append(assertion_note)
                turn_rec.notes = (
                    f"{turn_rec.notes}；{assertion_note}"
                    if turn_rec.notes
                    else assertion_note
                )
            loc = _step_locator(step)
            if nav_ledger is not None and nav_ledger.open_incident is not None:
                incident = nav_ledger.open_incident
                failed_locator = str(incident.evidence.get("target_locator") or "")
                if (
                    incident.kind == "navigation_unchanged"
                    and incident.keyword_id == step.keyword_id
                    and failed_locator == loc
                ):
                    turn_failed = True
                    consecutive_failures += 1
                    reason = "重复操作：上次相同动作后页面未变化，拒绝再次执行"
                    warnings.append(reason)
                    repeat_fail_row: dict[str, Any] = {
                        **step.to_dict(),
                        "action_role": role,
                        "failed": True,
                        "error": reason,
                        "incident": incident.to_dict(),
                    }
                    history.append(repeat_fail_row)
                    turn_rec.failed.append(repeat_fail_row)
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
            if nav_ledger is not None and role == "target":
                nav_ledger.prepare_target(loc)
            if (
                nav_ledger is not None
                and role == "target"
                and nav_ledger.requires_replay
            ):
                if request.use_current_app:
                    turn_failed = True
                    reason = (
                        "最终路径已被裁剪或归一化，但当前前台应用没有确定入口；"
                        "为避免 target 副作用，不执行该目标动作"
                    )
                    incident = nav_ledger.record_failure(
                        step, role, reason, kind="safety_net"
                    )
                    warnings.append(reason)
                    turn_rec.incident = incident.to_dict()
                    trace.replay = {"required": True, "passed": False, "reason": reason}
                    nav_ledger.stop_reason = "target_replay_unavailable"
                    break
                replay_steps, replay_reason = nav_ledger.replayable_prefix()
                target_replay_checks: list[dict[str, Any]] = []
                if replay_reason:
                    replay_ok = False
                else:
                    _progress("重放到目标动作前的稳定检查点…")
                    replay_ok, replay_reason = _replay_navigation_steps(
                        replay_steps,
                        ctx=ctx,
                        run_step=run_step,
                        platform=platform,
                        checkpoints=nav_ledger.replay_frame_checkpoints(),
                        check_trace=target_replay_checks,
                    )
                trace.replay = {
                    "required": True,
                    "passed": replay_ok,
                    "reason": replay_reason,
                    "scope": "target_ready_prefix",
                    "checkpoints": target_replay_checks,
                }
                if not replay_ok:
                    turn_failed = True
                    incident = nav_ledger.record_failure(
                        step,
                        role,
                        replay_reason or "target-ready 路径重放失败",
                        kind="replay_failed",
                    )
                    warnings.append(incident.reason)
                    turn_rec.incident = incident.to_dict()
                    break
                nav_ledger.mark_replayed()
            preflight_ok, preflight_reason, live_sig = _preflight_locator_step(
                step,
                ctx=ctx,
                platform=platform,
                expected_page_sig=page_sig,
            )
            if not preflight_ok:
                turn_failed = True
                consecutive_failures += 1
                if nav_ledger is not None:
                    preflight_kind = (
                        "page_drift"
                        if "page_drift" in preflight_reason
                        else "safety_net"
                    )
                    incident = nav_ledger.record_failure(
                        step, role, preflight_reason, kind=preflight_kind
                    )
                    turn_rec.incident = incident.to_dict()
                preflight_fail_row: dict[str, Any] = {
                    **step.to_dict(),
                    "action_role": role,
                    "failed": True,
                    "error": preflight_reason,
                    "expected_page_sig": page_sig,
                    "live_page_sig": live_sig,
                    "failure_category": (
                        "page_drift"
                        if "page_drift" in preflight_reason
                        else (
                            "locator_ambiguous"
                            if "locator_ambiguous" in preflight_reason
                            else "locator_missing"
                        )
                    ),
                }
                warnings.append(preflight_reason)
                history.append(preflight_fail_row)
                turn_rec.failed.append(preflight_fail_row)
                break
            _progress(f"执行：{step.comment or step.keyword_id}")
            if _is_cancelled(cancel_event):
                warnings.append("已停止编写")
                goal_completed = False
                turn_failed = True
                break
            if secret_map:
                step.params = restore_step_params(step.params, secret_map)
            try:
                run_step(step, ctx)
            except AuthoringError as exc:
                turn_failed = True
                consecutive_failures += 1
                reason = str(exc)
                warnings.append(f"步骤失败已跳过：{step.keyword_id} → {reason}")
                execution_fail_row: dict[str, Any] = {
                    **step.to_dict(),
                    "action_role": role,
                    "failed": True,
                    "error": reason[:200],
                }
                if nav_ledger is not None:
                    incident = nav_ledger.record_failure(step, role, reason)
                    execution_fail_row["incident"] = incident.to_dict()
                    turn_rec.incident = incident.to_dict()
                history.append(execution_fail_row)
                turn_rec.failed.append(execution_fail_row)
                break
            consecutive_failures = 0
            step_row: dict[str, Any] = {
                **step.to_dict(),
                "action_role": role,
            }
            if nav_ledger is not None and role in {
                "navigate",
                "scroll",
                "backtrack",
            }:
                nav_ledger.stage(step, role, target_locator=loc)
            elif nav_ledger is not None:
                nav_ledger.commit_immediate(step, role, target_locator=loc)
                recorded = list(nav_ledger.steps)
            else:
                recorded.append(step)
            if nav_ledger is not None and role == "target":
                post_ok, post_reason, post_evidence = _observe_terminal_target(
                    ctx=ctx,
                    platform=platform,
                    expected_before_sig=live_sig,
                    natural_language=nl,
                )
                turn_rec.navigation["terminal_post_observe"] = {
                    **post_evidence,
                    "passed": post_ok,
                    "reason": post_reason,
                }
                if post_ok:
                    target_confirmed = True
                if not post_ok:
                    turn_failed = True
                    consecutive_failures += 1
                    incident = nav_ledger.record_failure(
                        step,
                        role,
                        post_reason,
                        kind="target_post_observe",
                    )
                    turn_rec.incident = incident.to_dict()
                    warnings.append(post_reason)
                    nav_ledger.stop_reason = "target_post_observe_failed"
            history.append(step_row)
            turn_rec.executed.append(step_row)
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
            if (
                step.keyword_id in PAGE_CHANGING_KEYWORD_IDS
                or role in {"navigate", "scroll", "backtrack"}
            ):
                break

        if nav_ledger is not None:
            pending = nav_ledger.pending
            turn_rec.navigation["pending_transition"] = (
                {
                    "keyword_id": pending.step.keyword_id,
                    "params": dict(pending.step.params),
                    "action_role": pending.role,
                    "page_sig_before": pending.page_sig_before,
                }
                if pending is not None
                else None
            )
        trace.add_turn(turn_rec)
        if nav_ledger is not None and nav_ledger.stop_reason:
            trace.stop_reason = nav_ledger.stop_reason
            break
        if repeat_stopped:
            break
        if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            warnings.append(f"连续 {consecutive_failures} 次步骤失败，停止编写")
            break
        if turn_failed:
            continue
        if done and (nav_ledger is None or nav_ledger.pending is None):
            goal_completed = True
            break
    else:
        warnings.append("达到回合上限，可能未完全完成目标")

    session_verified = True
    if nav_ledger is not None:
        if nav_ledger.pending is not None:
            goal_completed = False
            session_verified = False
            nav_ledger.stop_reason = nav_ledger.stop_reason or "pending_transition"
            warnings.append("最后一个导航动作尚未完成重观察确认")
        if nav_ledger.open_incident is not None:
            goal_completed = False
            session_verified = False
        if nav_ledger.stop_reason:
            session_verified = False
        recorded = nav_ledger.final_steps()
        trace.stop_reason = nav_ledger.stop_reason
        if nav_ledger.requires_replay:
            if request.use_current_app:
                session_verified = False
                replay_reason = "使用当前前台应用，无法从确定入口重放最终路径"
                warnings.append(replay_reason)
                trace.replay = {"required": True, "passed": False, "reason": replay_reason}
            elif goal_completed:
                _progress("重放裁剪后的最终用例…")
                replay_steps, replay_reason = nav_ledger.replayable_prefix()
                final_replay_checks: list[dict[str, Any]] = []
                replay_ok = False
                if not replay_reason:
                    replay_ok, replay_reason = _replay_navigation_steps(
                        replay_steps,
                        ctx=ctx,
                        run_step=run_step,
                        platform=platform,
                        checkpoints=nav_ledger.replay_frame_checkpoints(),
                        check_trace=final_replay_checks,
                    )
                session_verified = replay_ok
                trace.replay = {
                    "required": True,
                    "passed": replay_ok,
                    "reason": replay_reason,
                    "scope": "final_prefix",
                    "checkpoints": final_replay_checks,
                }
                if not replay_ok:
                    warnings.append(replay_reason)
            else:
                session_verified = False
                trace.replay = {
                    "required": True,
                    "passed": False,
                    "reason": "目标未完成，不执行最终路径重放",
                }
        else:
            if trace.replay is None:
                trace.replay = {"required": False, "passed": True, "reason": ""}

    if not recorded:
        raise AuthoringError("会话驱动未产生任何成功步骤：" + "；".join(warnings[:5]))

    miss = _missing_assert_warning(recorded, nl, platform)
    if miss:
        warnings.append(miss)
        goal_completed = False

    evidence_ok, evidence_reason = completion_evidence(
        recorded,
        platform=platform,
        natural_language=nl,
        model_done=goal_completed,
        target_confirmed=target_confirmed,
    )
    if not evidence_ok:
        goal_completed = False
        if evidence_reason and evidence_reason not in miss:
            warnings.append(evidence_reason)

    judge = judge_authoring_goal(
        natural_language=nl,
        recorded=recorded,
        goal_completed=goal_completed,
        warnings=warnings,
        chat=chat,
        platform=platform,
        target_confirmed=target_confirmed,
    )
    # 事后裁判不改写已记录步骤；passed=false 时禁止把草稿标成已完成
    if judge:
        trace.goal_judge = judge
        src = str(judge.get("source") or "heuristic")
        reason = str(judge.get("reason") or "").strip()
        if reason:
            warnings.append(f"事后裁判（{src}）：{reason}")
        if judge.get("passed") is False:
            goal_completed = False

    trace.title = title
    trace.goal_completed = goal_completed
    return AuthoringDraft(
        title=title,
        platform=platform,
        steps=recorded,
        warnings=warnings,
        raw_llm="",
        mode="session",
        session_verified=session_verified,
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
    cancel_event: Any = None,
) -> AuthoringDraft:
    """检视器/对话框「试一句」：当前页最多 1 回合、少量步骤，不追求完整用例。

    用于确认模型是否理解当前页，结果可预览；正式编写仍走 ``run_session_authoring``。
    """
    trial = AuthoringRequest(
        natural_language=request.natural_language,
        platform=request.platform,
        title=request.title or "当前页理解预览",
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
        cancel_event=cancel_event,
    )
    draft.warnings = list(draft.warnings) + ["当前页理解预览：未写入工程"]
    draft.mode = "try_page"
    return draft
