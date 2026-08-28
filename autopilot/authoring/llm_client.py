"""Authoring LLM 客户端：企业默认 Platform 持钥网关；本机 AP_AI_* 为逃生口。"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

from ..intent.config import vision_api_key, vision_base_url, vision_model, vision_timeout_sec
from ..runtime.log import get_logger
from .contract import AuthoringError

log = get_logger("authoring.llm")

ChatFn = Callable[[str], str]

#: 单次 prompt 上限（与 Platform ``MAX_AI_PROMPT_CHARS`` 对齐），本地先拦以省一次往返
MAX_PROMPT_CHARS = 60000
#: 未接管理台又没有本机 Key 时的统一提示。环境变量名只在日志里出现，
#: 界面上给用户能执行的动作（登录 / 找管理员）。
NO_LOCAL_KEY_MESSAGE = "AI 服务尚未就绪：请登录管理台，或联系管理员开通 AI 能力。"
_LAST_PLATFORM_CAPABILITIES: dict[str, Any] = {}


def platform_llm_capabilities() -> dict[str, Any]:
    """读取平台当前模型能力；仅访问本平台，不调用厂商、不会消耗 token。

    走 ``ensure_user_session``：access token 过期会自动用 refresh_token 续期，
    否则每次 token 到期都得人工重登一遍才能开始编写。
    """
    from ..mgmt.auth_api import ensure_user_session
    from ..mgmt.client import MgmtClientError
    from ..runtime import settings

    if not settings.mc_is_logged_in():
        raise AuthoringError("请先登录管理台再读取 AI 模型能力")
    try:
        client, _ = ensure_user_session()
        try:
            out = client.ai_codegen_capabilities()
        finally:
            client.close()
    except MgmtClientError as exc:
        raise AuthoringError(f"平台 AI 能力预检失败：{exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise AuthoringError(f"平台 AI 能力预检异常：{exc}") from exc
    if not isinstance(out, dict):
        raise AuthoringError("平台 AI 能力预检返回格式异常")
    if not bool(out.get("enabled")):
        raise AuthoringError("管理台尚未开通 AI 能力，请联系管理员配置后再试。")
    _LAST_PLATFORM_CAPABILITIES.clear()
    _LAST_PLATFORM_CAPABILITIES.update(out)
    return dict(out)


def last_platform_llm_capabilities() -> dict[str, Any]:
    """最近一次平台预检/调用返回的能力快照（不含 Key）。"""
    return dict(_LAST_PLATFORM_CAPABILITIES)


def assert_llm_ready() -> str:
    """调用前预检：platform 模式须已登录，local 模式须有本机 Key；返回生效模式。

    目的是在建会话、采页之前失败，避免拉起设备/浏览器后才发现无法调用 AI。
    """
    mode = llm_mode()
    if mode == "platform":
        from ..runtime import settings

        if not settings.mc_is_logged_in():
            raise AuthoringError("请先登录管理台，再使用 AI 辅助编写。")
        platform_llm_capabilities()
    elif not vision_api_key():
        raise AuthoringError(NO_LOCAL_KEY_MESSAGE)
    return mode


def llm_mode() -> str:
    """local | platform。

    优先级：
    1. 显式 ``AUTOPILOT_AUTHORING_LLM_MODE``
    2. 企业部署锁定 Platform URL → platform
    3. 否则 local（开源/单机开发）
    """
    raw = (os.environ.get("AUTOPILOT_AUTHORING_LLM_MODE") or "").strip().lower()
    if raw in ("platform", "remote", "mgmt"):
        return "platform"
    if raw in ("local", "direct", "ide"):
        return "local"
    try:
        from ..runtime.platform_deploy import platform_url_locked

        if platform_url_locked():
            return "platform"
    except (ImportError, OSError, AttributeError, TypeError, RuntimeError):
        pass
    # 用户已经登录平台时优先使用平台持钥网关。此前「未锁 URL → local」会误报 IDE
    # 缺 Key，即使平台 DeepSeek Key 已配置；显式 local 仍可覆盖这一默认值。
    try:
        from ..runtime import settings

        if settings.mc_is_logged_in():
            return "platform"
    except (ImportError, OSError, AttributeError, TypeError, RuntimeError):
        pass
    return "local"


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise AuthoringError("LLM 返回为空")
    fence = re.search(r"```(?:json)?\s*(\{.*?})\s*```", raw, re.DOTALL | re.IGNORECASE)
    if fence:
        raw = fence.group(1)
    else:
        start = raw.find("{")
        end = raw.rfind("}")
        if 0 <= start < end:
            raw = raw[start : end + 1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AuthoringError(f"LLM 返回非 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise AuthoringError("LLM JSON 根须为对象")
    return data


def normalize_llm_purpose(purpose: str | None) -> str:
    """authoring | planning | locate | nl → 规范化用途名。"""
    raw = (purpose or "authoring").strip().lower()
    if raw in ("locate", "location", "deep_think", "deep-think"):
        return "locate"
    if raw in ("planning", "plan", "nl", "nl_bootstrap", "bootstrap"):
        return "planning"
    if raw in ("authoring", "codegen", "agent", "session"):
        return "authoring"
    return "authoring"


def model_for_purpose(purpose: str | None = "authoring") -> str:
    """本机按用途选模型：locate → PLANNING → 默认 Vision/AP_AI_MODEL。

    - ``AP_AI_LOCATE_MODEL`` / ``AUTOPILOT_AUTHORING_LOCATE_MODEL``
    - ``AP_AI_PLANNING_MODEL`` / ``AUTOPILOT_AUTHORING_PLANNING_MODEL``
    未配置时回落 ``vision_model()``（与 AP_AI_MODEL 同源）。
    """
    kind = normalize_llm_purpose(purpose)
    if kind == "locate":
        for key in ("AP_AI_LOCATE_MODEL", "AUTOPILOT_AUTHORING_LOCATE_MODEL"):
            val = (os.environ.get(key) or "").strip()
            if val:
                return val
    if kind in ("locate", "planning", "authoring"):
        for key in ("AP_AI_PLANNING_MODEL", "AUTOPILOT_AUTHORING_PLANNING_MODEL"):
            val = (os.environ.get(key) or "").strip()
            if val:
                return val
    return vision_model()


def chat_local(prompt: str, *, purpose: str = "authoring") -> str:
    """直连 OpenAI 兼容 Chat Completions（AP_AI_* / Vision 同源配置；开发逃生口）。"""
    key = vision_api_key()
    if not key:
        log.warning(
            "本机未配置 AI Key（AP_AI_API_KEY / AUTOPILOT_VISION_API_KEY），"
            "且未登录管理台"
        )
        raise AuthoringError(NO_LOCAL_KEY_MESSAGE)
    import httpx

    from ..intent.provider_profile import (
        apply_max_output_tokens,
        apply_reasoning_to_body,
        detect_provider,
        should_omit_temperature,
    )
    from ..intent.config import vision_reasoning_effort, vision_temperature

    model = model_for_purpose(purpose)
    base = vision_base_url()
    provider = detect_provider("", model, base)
    url = f"{base.rstrip('/')}/chat/completions"
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你只输出合法 JSON，不要 Markdown。"},
            {"role": "user", "content": prompt},
        ],
    }
    apply_max_output_tokens(body, model, 2000)
    apply_reasoning_to_body(
        body,
        provider=provider,
        model=model,
        effort=vision_reasoning_effort(),
        base_url=base,
    )
    if not should_omit_temperature(provider, model):
        body["temperature"] = vision_temperature()

    with httpx.Client(timeout=vision_timeout_sec()) as client:
        resp = client.post(
            url,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
    try:
        return str(data["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError) as exc:
        raise AuthoringError(f"LLM 响应结构异常: {exc}") from exc


def _current_project_id() -> str:
    """当前登录项目号（用于平台侧分账）；取不到时返回空串。"""
    from ..runtime import settings

    try:
        return str(settings.mc_project_id() or "").strip()
    except (AttributeError, TypeError, RuntimeError):
        return ""


def chat_platform(prompt: str, *, purpose: str = "authoring") -> str:
    """经 Platform ``POST /ops/ai/codegen``（需已登录；Key 仅服务端）。

    ``project_id`` 可空：平台走 ``__authoring__`` 合成计费桶，不要求已绑项目。
    """
    from ..mgmt.auth_api import ensure_user_session
    from ..mgmt.client import MgmtClientError
    from ..runtime import settings

    if not settings.mc_is_logged_in():
        raise AuthoringError("请先登录管理台，再使用 AI 辅助编写。")
    project_id = _current_project_id()
    purpose_norm = normalize_llm_purpose(purpose)
    try:
        # 多回合编写可能跨过 access token 有效期：这里统一走会话续期，
        # 避免编写到一半因 401 中断，已跑过的真机步骤白扔
        client, _ = ensure_user_session()
        try:
            out = client.ai_codegen(
                prompt, purpose=purpose_norm, project_id=project_id
            )
        finally:
            client.close()
    except MgmtClientError as exc:
        raise AuthoringError(f"AI 服务暂时不可用：{exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise AuthoringError(f"AI 服务调用失败：{exc}") from exc
    if not isinstance(out, dict):
        raise AuthoringError("AI 服务返回格式异常")
    capabilities = out.get("capabilities")
    if isinstance(capabilities, dict):
        _LAST_PLATFORM_CAPABILITIES.clear()
        _LAST_PLATFORM_CAPABILITIES.update(capabilities)
    content = out.get("content") or out.get("text") or ""
    if not content and isinstance(out.get("steps"), list):
        return json.dumps(out, ensure_ascii=False)
    if not content:
        raise AuthoringError("AI 服务未返回内容")
    return str(content)


def complete_json(
    prompt: str,
    *,
    chat: ChatFn | None = None,
    purpose: str = "authoring",
) -> dict[str, Any]:
    if len(prompt or "") > MAX_PROMPT_CHARS:
        log.warning("prompt 过长：%d > %d 字符", len(prompt), MAX_PROMPT_CHARS)
        raise AuthoringError("当前页面内容过多，AI 无法一次处理：请把需求拆成更小的步骤")
    if chat is not None:
        text = chat(prompt)
    elif llm_mode() == "platform":
        text = chat_platform(prompt, purpose=purpose)
    else:
        text = chat_local(prompt, purpose=purpose)
    return _extract_json_object(text)
