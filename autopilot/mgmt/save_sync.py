"""保存用例后的 Platform 同步辅助（UX-P2-001：保存≠自动同步）。

纯逻辑层：从 TestCase 提取 intent_steps 并 PATCH 设计域；UI 提示在 mgmt Mixin。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..model.testcase import Step, StepNode, TestCase


def is_platform_configured() -> bool:
    from ..runtime import settings

    return settings.mc_is_logged_in()


def save_sync_prompt_enabled() -> bool:
    from ..runtime import settings

    return bool(settings.mc_save_sync_prompt())


def should_offer_save_sync(tc: "TestCase | None") -> bool:
    """是否应在保存后弹出「是否同步 Platform」提示。"""
    if tc is None:
        return False
    if not is_platform_configured() or not save_sync_prompt_enabled():
        return False
    # 已绑定 Platform 逻辑用例，或工程已配置项目空间（可上传制品）
    if str(getattr(tc, "logical_case_id", "") or "").strip():
        return True
    from ..runtime import settings

    return bool(settings.mc_project_id())


def _is_intent_step(node: "StepNode") -> bool:
    from ..model.testcase import Step

    if not isinstance(node, Step):
        return False
    kid = str(node.keyword_id or "").strip()
    remark = str(node.remark or "")
    return kid == "intent_act" or remark.startswith("intent:")


def _intent_from_step(step: "Step") -> dict[str, Any]:
    params = {p.param_id: (p.value or "") for p in step.params}
    sid = str(params.get("intent_id") or "").strip()
    if not sid:
        remark = str(step.remark or "")
        if remark.startswith("intent:"):
            sid = remark.split("|", 1)[0].removeprefix("intent:").strip()
    if not sid:
        sid = "s1"
    channel = str(params.get("channel") or "").strip().lower()
    platform_hint = "any"
    if channel == "http":
        platform_hint = "web"
    elif channel == "ui":
        platform_hint = "mobile"
    text = str(params.get("text") or step.comment or "").strip()
    return {
        "id": sid,
        "action": str(params.get("action") or "custom").strip() or "custom",
        "target": str(params.get("target") or "").strip(),
        "value": str(params.get("value") or "").strip(),
        "platform_hint": platform_hint,
        "text": text or sid,
    }


def extract_intent_steps_from_testcase(tc: "TestCase") -> list[dict[str, Any]]:
    """从用例 case shell 提取 intent_act 步骤，供 Platform PATCH。"""
    from ..model.testcase import Step, StepSet

    out: list[dict[str, Any]] = []

    def walk(nodes: list) -> None:
        for node in nodes or []:
            if isinstance(node, StepSet):
                walk(node.children)
                continue
            if _is_intent_step(node) and isinstance(node, Step):
                out.append(_intent_from_step(node))

    walk(tc.case.steps)
    return out


def build_logical_case_patch(tc: "TestCase") -> dict[str, Any]:
    """构造 PATCH /design/logical-cases/{id} 请求体。"""
    body: dict[str, Any] = {}
    title = str(tc.name or "").strip()
    if title:
        body["title"] = title
    desc = str(getattr(getattr(tc, "desc", None), "description", "") or "").strip()
    if desc:
        body["description"] = desc
    pre = str(getattr(getattr(tc, "desc", None), "precondition", "") or "").strip()
    if pre:
        body["preconditions"] = [pre]
    steps = extract_intent_steps_from_testcase(tc)
    if steps:
        body["intent_steps"] = steps
    return body


def push_logical_case_update(client, tc: "TestCase") -> dict[str, Any]:
    """将已保存用例回写到 Platform 设计域。"""
    cid = str(getattr(tc, "logical_case_id", "") or "").strip()
    if not cid:
        raise ValueError("logical_case_id 为空，无法回写设计域")
    body = build_logical_case_patch(tc)
    if not body:
        raise ValueError("无可同步字段（title / intent_steps 均为空）")
    return client.update_logical_case(cid, body)


def save_sync_action_label(tc: "TestCase | None") -> str:
    """提示文案中的动作说明。"""
    if tc and str(getattr(tc, "logical_case_id", "") or "").strip():
        return "回写 intent 步骤到 Platform 设计域"
    return "上传工程制品到 Platform"
