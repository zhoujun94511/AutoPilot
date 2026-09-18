"""Android/iOS/Web 深层导航账本。

借鉴 Artemis 的 plan machine-channel、Flash 逐屏循环与 execution incident，
但最终产物仍是 AutoPilot REGISTRY 传统关键字步骤。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, cast

from .contract import (
    GeneratedStep,
    NavigationFrame,
    NavigationIncident,
    NavigationPlan,
    NavigationRole,
    PendingTransition,
)


BACK_KEYWORD_IDS = frozenset({
    "mobile_back",
    "mobile_presskey",
    "web_browser_back",
})
SCROLL_KEYWORD_IDS = frozenset({
    "mobile_swipe",
    "mobile_swipe_up",
    "mobile_swipe_down",
    "mobile_swipe_direction",
    "mobile_define_swipe_direction",
    "web_browser_scroll_vertical_bar",
})
SCROLL_TO_KEYWORD_IDS = frozenset({
    "mobile_slip_for_element",
    "mobile_define_slip_for_element",
})
ASSERT_MARKERS = ("verify", "assert")


def build_navigation_plan(
    natural_language: str,
    *,
    platform: str = "",
    max_depth: int = 8,
    max_scrolls: int = 12,
    max_backtracks: int = 5,
) -> NavigationPlan:
    """建立不依赖具体 App 的搜索优先导航计划。"""
    return NavigationPlan(
        goal=(natural_language or "").strip(),
        platform=(platform or "").strip().lower(),
        max_depth=max(2, int(max_depth)),
        max_scrolls=max(1, int(max_scrolls)),
        max_backtracks=max(1, int(max_backtracks)),
    )


def _is_back_step(step: GeneratedStep) -> bool:
    if step.keyword_id == "web_browser_back":
        return True
    if step.keyword_id == "mobile_back":
        return True
    if step.keyword_id != "mobile_presskey":
        return False
    key = str((step.params or {}).get("oKeys") or "").strip().lower()
    return key in {"back", "返回"}


def infer_navigation_role(
    step: GeneratedStep,
    *,
    declared: str = "",
    turn_done: bool = False,
) -> NavigationRole:
    """模型可声明角色；缺失时按真实关键字保守推断。"""
    raw = (declared or "").strip().lower()
    aliases = {
        "probe": "navigate",
        "commit": "target" if turn_done else "support",
        "rollback": "backtrack",
        "action": "target",
        "verify": "assert",
    }
    raw = aliases.get(raw, raw)
    kid = (step.keyword_id or "").strip().lower()
    # 模型声明不能降低关键字自身的安全语义。
    if _is_back_step(step):
        return "backtrack"
    if kid in SCROLL_KEYWORD_IDS:
        return "scroll"
    if kid in {
        "mobile_app_start",
        "mobile_element_click",
        "mobile_element_long_click",
        "web_browser_open",
        "web_browser_locate",
        "web_browser_forward",
        "web_element_click",
        "web_element_jsclick",
        "web_element_check_click",
        "web_element_scroll_click",
        "web_element_click_and_switch",
        "web_element_double_click",
        "web_element_checkbox_click",
        "web_element_radio_click",
        "elementclick",
    }:
        if raw == "target":
            return "target"
        return "target" if turn_done and raw != "navigate" else "navigate"
    if raw in {"navigate", "scroll", "backtrack", "target", "assert", "support"}:
        return raw  # type: ignore[return-value]
    if kid in SCROLL_TO_KEYWORD_IDS:
        return "support"
    if any(marker in kid for marker in ASSERT_MARKERS):
        return "assert"
    return "support"


def role_for_step_data(
    data: dict[str, Any],
    index: int,
    step: GeneratedStep,
    *,
    turn_done: bool,
) -> NavigationRole:
    """从 LLM 原始 steps 对应项读取 action_role，未知时自动推断。"""
    raw_steps = data.get("steps")
    declared = ""
    if isinstance(raw_steps, list) and index < len(raw_steps):
        item = raw_steps[index]
        if isinstance(item, dict):
            declared = str(item.get("action_role") or item.get("role") or "")
    return infer_navigation_role(step, declared=declared, turn_done=turn_done)


@dataclass
class ObservationOutcome:
    committed: list[GeneratedStep] = field(default_factory=list)
    pruned: list[GeneratedStep] = field(default_factory=list)
    incident: NavigationIncident | None = None
    page_changed: bool = False
    backtracked: bool = False
    observation_valid: bool = True


class NavigationLedger:
    """探索轨迹与最终路径分离的页面签名账本。"""

    def __init__(
        self,
        plan: NavigationPlan,
        *,
        initial_steps: list[GeneratedStep] | None = None,
    ) -> None:
        self.plan = plan
        self.steps: list[GeneratedStep] = list(initial_steps or [])
        self._step_roles = cast(
            list[NavigationRole],
            ["support"] * len(self.steps),
        )
        self.frames: list[NavigationFrame] = []
        self.pending: PendingTransition | None = None
        self.current_page_sig = ""
        self.probe_history: list[dict[str, Any]] = []
        self.pruned_history: list[dict[str, Any]] = []
        self.open_incident: NavigationIncident | None = None
        self.last_closed_incident: dict[str, Any] | None = None
        self.stop_reason = ""
        self.scroll_count = 0
        self.backtrack_count = 0
        self.requires_replay = False
        self._pending_scrolls: dict[str, list[GeneratedStep]] = {}
        self._perception_failures = 0

    def set_strategy(self, strategy: str) -> None:
        """模型只能确认当前策略；迁移由 incident 驱动的 advance_strategy 控制。"""
        if strategy not in self.plan.strategies:
            return
        current = self.plan.active_strategy
        if strategy != current:
            return

    def advance_strategy(self) -> None:
        current = self.plan.active_strategy
        if current not in self.plan.tried_strategies:
            self.plan.tried_strategies.append(current)
        try:
            index = self.plan.strategies.index(current)
        except ValueError:
            index = -1
        if index + 1 < len(self.plan.strategies):
            self.plan.active_strategy = self.plan.strategies[index + 1]

    def _close_incident(self, resolution: str) -> None:
        if self.open_incident is None:
            return
        self.last_closed_incident = {
            **self.open_incident.to_dict(),
            "resolution": resolution,
        }
        self.open_incident = None

    def _record_probe(
        self,
        step: GeneratedStep,
        role: NavigationRole,
        *,
        before: str,
        after: str = "",
        status: str = "executed",
    ) -> None:
        self.probe_history.append({
            **step.to_dict(),
            "action_role": role,
            "page_sig_before": before,
            "page_sig_after": after,
            "status": status,
        })

    def _incident(
        self,
        kind: str,
        reason: str,
        pending: PendingTransition,
        *,
        after: str,
        evidence: dict[str, Any] | None = None,
    ) -> NavigationIncident:
        consecutive = 1
        if self.open_incident and self.open_incident.kind == kind:
            consecutive = self.open_incident.consecutive_failures + 1
        incident = NavigationIncident(
            kind=kind,
            reason=reason,
            role=pending.role,
            keyword_id=pending.step.keyword_id,
            page_sig_before=pending.page_sig_before,
            page_sig_after=after,
            consecutive_failures=consecutive,
            evidence=dict(evidence or {}),
        )
        self.open_incident = incident
        if kind in {
            "navigation_unchanged",
            "scroll_unchanged",
            "backtrack_unchanged",
            "action_error",
            "safety_net",
        }:
            self.advance_strategy()
        return incident

    def begin_page(
        self,
        page_sig: str,
        *,
        valid: bool = True,
        error: str = "",
    ) -> ObservationOutcome:
        """登记新观察，并结算上一个导航动作。"""
        sig = (page_sig or "empty").strip() or "empty"
        outcome = ObservationOutcome()
        if not valid:
            outcome.observation_valid = False
            self._perception_failures += 1
            pending = self.pending or PendingTransition(
                step=GeneratedStep(keyword_id="capture_ui_context"),
                role="support",
                page_sig_before=self.current_page_sig,
            )
            incident_kind = (
                "settlement_timeout"
                if "稳定等待超时" in (error or "")
                else "perception_error"
            )
            outcome.incident = self._incident(
                incident_kind,
                error or "当前回合未获得有效 UI 控件摘要",
                pending,
                after="",
                evidence={"observation_valid": False},
            )
            if self.pending is not None:
                self._record_probe(
                    self.pending.step,
                    self.pending.role,
                    before=self.pending.page_sig_before,
                    status="observation_error",
                )
            if self._perception_failures >= self.plan.max_perception_failures:
                self.stop_reason = "perception_unavailable"
            return outcome
        self._perception_failures = 0
        if not self.frames:
            self.frames.append(
                NavigationFrame(page_sig=sig, path_length=len(self.steps), depth=0)
            )
            self.current_page_sig = sig
            self.plan.visited_pages = 1
            self._close_incident("UI 感知恢复并建立初始页面")
            return outcome

        pending = self.pending
        if pending is None:
            self.current_page_sig = sig
            if self.open_incident and self.open_incident.kind == "perception_error":
                self._close_incident("UI 感知恢复")
            return outcome
        self.pending = None
        outcome.page_changed = sig != pending.page_sig_before
        self._record_probe(
            pending.step,
            pending.role,
            before=pending.page_sig_before,
            after=sig,
            status="confirmed" if outcome.page_changed else "unchanged",
        )

        if pending.role == "scroll":
            if self.scroll_count > self.plan.max_scrolls:
                self.stop_reason = "scroll_budget"
                outcome.incident = self._incident(
                    "scroll_budget",
                    f"滚动次数超过上限 {self.plan.max_scrolls}",
                    pending,
                    after=sig,
                )
            elif not outcome.page_changed:
                outcome.incident = self._incident(
                    "scroll_unchanged",
                    "滚动后页面控件签名未变化，可能已到列表边界",
                    pending,
                    after=sig,
                )
            else:
                frame_key = self.frames[-1].page_sig
                self._pending_scrolls.setdefault(frame_key, []).append(pending.step)
                self._close_incident("滚动后获得新的有效页面指纹")
            self.current_page_sig = sig
            return outcome

        if pending.role == "backtrack":
            self.backtrack_count += 1
            if self.backtrack_count > self.plan.max_backtracks:
                self.stop_reason = "backtrack_budget"
                outcome.incident = self._incident(
                    "backtrack_budget",
                    f"返回次数超过上限 {self.plan.max_backtracks}",
                    pending,
                    after=sig,
                )
            elif not outcome.page_changed:
                outcome.incident = self._incident(
                    "backtrack_unchanged",
                    "返回动作后页面未变化",
                    pending,
                    after=sig,
                )
            else:
                target_idx = next(
                    (i for i in range(len(self.frames) - 1, -1, -1)
                     if self.frames[i].page_sig == sig),
                    -1,
                )
                if target_idx >= 0:
                    target = self.frames[target_idx]
                    outcome.pruned = self.steps[target.path_length:]
                    if outcome.pruned:
                        self.pruned_history.extend(s.to_dict() for s in outcome.pruned)
                    self.steps = self.steps[:target.path_length]
                    self._step_roles = self._step_roles[:target.path_length]
                    self.frames = self.frames[:target_idx + 1]
                    self._pending_scrolls.clear()
                    self.requires_replay = True
                    outcome.backtracked = True
                    self._close_incident("返回到已记录祖先页面并裁剪错误分支")
                else:
                    outcome.incident = self._incident(
                        "backtrack_unknown_page",
                        "返回后到达未记录页面，无法安全裁剪探索路径",
                        pending,
                        after=sig,
                    )
            self.current_page_sig = sig
            return outcome

        if not outcome.page_changed:
            outcome.incident = self._incident(
                "navigation_unchanged",
                "导航动作执行后页面控件签名未变化，请换入口或改用滚动/返回",
                pending,
                after=sig,
                evidence={"target_locator": pending.target_locator},
            )
            self.current_page_sig = sig
            return outcome

        # 点击回到已经访问过的祖先页面，相当于隐式回退；裁掉环路分支。
        ancestor_idx = next(
            (i for i in range(len(self.frames) - 1, -1, -1)
             if self.frames[i].page_sig == sig),
            -1,
        )
        if ancestor_idx >= 0:
            target = self.frames[ancestor_idx]
            outcome.pruned = self.steps[target.path_length:]
            if outcome.pruned:
                self.pruned_history.extend(s.to_dict() for s in outcome.pruned)
            self.steps = self.steps[:target.path_length]
            self._step_roles = self._step_roles[:target.path_length]
            self.frames = self.frames[:ancestor_idx + 1]
            self.requires_replay = True
            outcome.backtracked = True
            self.current_page_sig = sig
            self._close_incident("动作回到祖先页面，按环路分支裁剪")
            return outcome

        next_depth = len(self.frames)
        if next_depth > self.plan.max_depth:
            self.stop_reason = "depth_budget"
            outcome.incident = self._incident(
                "depth_budget",
                f"页面深度超过上限 {self.plan.max_depth}",
                pending,
                after=sig,
            )
            self.current_page_sig = sig
            return outcome

        self._commit_with_scroll(pending.step, pending.target_locator, pending.role)
        outcome.committed.append(pending.step)
        self.frames.append(
            NavigationFrame(
                page_sig=sig,
                path_length=len(self.steps),
                depth=len(self.frames),
            )
        )
        self.plan.visited_pages += 1
        self._close_incident("导航动作获得新的有效页面指纹")
        self.current_page_sig = sig
        return outcome

    def _commit_with_scroll(
        self,
        step: GeneratedStep,
        locator: str,
        role: NavigationRole,
    ) -> None:
        self._flush_scrolls(locator)
        self.steps.append(step)
        self._step_roles.append(role)

    def _flush_scrolls(self, locator: str) -> None:
        # 只消费当前导航 frame 的探索滑动，禁止跨页面、跨方向合并。
        frame_key = self.frames[-1].page_sig if self.frames else self.current_page_sig
        scrolls = self._pending_scrolls.pop(frame_key, [])
        if self.plan.platform == "web":
            # Web 页面滚动参数与移动端不同；保留原始关键字，交给双引擎适配层执行。
            self.steps.extend(scrolls)
            self._step_roles.extend(
                cast(list[NavigationRole], ["support"] * len(scrolls))
            )
            return
        directions = {str(s.params.get("direction") or "上") for s in scrolls}
        sizes = {str(s.params.get("size") or "全屏") for s in scrolls}
        homogeneous = len(directions) == 1 and len(sizes) == 1
        if scrolls and locator and homogeneous:
            times = sum(
                max(1, int(str(s.params.get("count") or "1")))
                if str(s.params.get("count") or "1").isdigit()
                else 1
                for s in scrolls
            )
            self.steps.append(
                GeneratedStep(
                    keyword_id="mobile_slip_for_element",
                    params={
                        "direction": next(iter(directions)),
                        "size": next(iter(sizes)),
                        "times": str(times),
                        "locator": locator,
                    },
                    comment=f"滚动至目标控件 {locator}",
                )
            )
            self._step_roles.append("support")
            self.requires_replay = True
        else:
            self.steps.extend(scrolls)
            self._step_roles.extend(
                cast(list[NavigationRole], ["support"] * len(scrolls))
            )

    def prepare_target(self, locator: str) -> None:
        """在 terminal target 执行前先固化滚动路径，使重放停在 target-ready。"""
        self._flush_scrolls(locator)

    def stage(
        self,
        step: GeneratedStep,
        role: NavigationRole,
        *,
        target_locator: str = "",
    ) -> None:
        """暂存需要下一次观察确认的导航/滚动/返回动作。"""
        if self.pending is not None:
            raise RuntimeError("上一导航动作尚未结算")
        if role == "scroll":
            self.scroll_count += 1
            self.set_strategy("scroll_discover")
        self.pending = PendingTransition(
            step=step,
            role=role,
            page_sig_before=self.current_page_sig,
            target_locator=target_locator,
        )

    def commit_immediate(
        self,
        step: GeneratedStep,
        role: NavigationRole,
        *,
        target_locator: str = "",
    ) -> None:
        """提交不要求页面变化的输入、目标动作和断言。"""
        self._record_probe(
            step,
            role,
            before=self.current_page_sig,
            after=self.current_page_sig,
            status="committed",
        )
        self._commit_with_scroll(step, target_locator, role)
        if role == "target":
            self.set_strategy("target_action")
            self._close_incident("替代目标动作通过 Safety Net 并执行成功")
        elif role == "assert":
            self.set_strategy("assert")
            self._close_incident("断言执行成功")

    def record_failure(
        self,
        step: GeneratedStep,
        role: NavigationRole,
        reason: str,
        *,
        kind: str = "action_error",
    ) -> NavigationIncident:
        pending = PendingTransition(
            step=step,
            role=role,
            page_sig_before=self.current_page_sig,
            target_locator=str((step.params or {}).get("locator") or ""),
        )
        self._record_probe(
            step,
            role,
            before=self.current_page_sig,
            status="failed",
        )
        return self._incident(kind, reason, pending, after=self.current_page_sig)

    def prompt_context(self) -> str:
        """给下一回合的短机读状态，不回灌完整轨迹。"""
        payload = {
            "strategies": list(self.plan.strategies),
            "active_strategy": self.plan.active_strategy,
            "tried_strategies": list(self.plan.tried_strategies),
            "depth": max(0, len(self.frames) - 1),
            "max_depth": self.plan.max_depth,
            "scrolls": self.scroll_count,
            "max_scrolls": self.plan.max_scrolls,
            "backtracks": self.backtrack_count,
            "max_backtracks": self.plan.max_backtracks,
            "visited_page_signatures": [f.page_sig for f in self.frames],
            "open_incident": self.open_incident.to_dict() if self.open_incident else None,
            "last_closed_incident": self.last_closed_incident,
        }
        self.last_closed_incident = None
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    def replayable_prefix(self) -> tuple[list[GeneratedStep], str]:
        """返回 terminal target 之前可安全重放的结构路径。"""
        if any(role == "target" for role in self._step_roles):
            return [], "最终路径已包含已执行 target，禁止自动重放以避免重复副作用"
        return list(self.steps), ""

    def replay_frame_checkpoints(self) -> dict[int, str]:
        """返回重放步骤序号到预期页面指纹的映射（序号从 1 开始）。"""
        return {
            frame.path_length: frame.page_sig
            for frame in self.frames
            if frame.path_length > 0
        }

    def mark_replayed(self) -> None:
        self.requires_replay = False

    def final_steps(self) -> list[GeneratedStep]:
        """返回实际固化路径；已执行的合法重复动作不得在收尾时丢失。"""
        steps = list(self.steps)
        for scrolls in self._pending_scrolls.values():
            steps.extend(scrolls)
        return steps
