"""链路 3：执行单步传统关键字（会话驱动编写用）。"""

from __future__ import annotations

from typing import Any, Callable

from ..keywords.registry import REGISTRY, KeywordError
from .contract import AuthoringError, GeneratedStep

StepExecutor = Callable[[GeneratedStep, Any], None]

#: 旧 compact 前缀 → 执行引擎可解析前缀（防止模型照抄历史摘要）
_COMPACT_LOCATOR_PREFIXES = (
    ("i:", "id::"),
    ("a:", "name::"),
    ("lb:", "name::"),
    ("x:", "xpath::"),
    ("c:", "css::"),
    ("d:", "css::"),
)


def _normalize_locator_param(key: str, value: str, *, platform: str = "") -> str:
    """把 compact/裸值定位符收成 ``id::`` / ``name::`` 等可 resolve 形式。"""
    if key not in ("locator", "loc", "by", "target") or not value:
        return value
    raw = value.strip()
    if "::" in raw.split("||", 1)[0]:
        return raw
    low = raw.lower()
    for compact, full in _COMPACT_LOCATOR_PREFIXES:
        if low.startswith(compact):
            body = raw[len(compact):]
            # iOS 上历史 ``i:`` 实际塞的是 accessibility name
            if compact == "i:" and platform == "ios":
                return f"name::{body}"
            return f"{full}{body}"
    # 无前缀：移动端按平台默认成 name/id，避免再被当成裸 XPath
    if platform == "ios":
        return f"name::{raw}"
    if platform == "android" and ("/" in raw or raw.startswith("com.")):
        return f"id::{raw}"
    return raw


def _session_platform(ctx: Any) -> str:
    """从移动会话管理器读平台；无会话返回空串。"""
    try:
        mgr = getattr(ctx, "appium", None)
        return str(getattr(mgr, "platform", "") or "").lower()
    except (AttributeError, TypeError):
        return ""


def execute_keyword_step(step: GeneratedStep, ctx: Any) -> None:
    """在现有 ExecutionContext 上执行一步 REGISTRY 关键字。"""
    kid = (step.keyword_id or "").strip()
    if not kid:
        raise AuthoringError("步骤缺少 keyword_id")
    from .contract import is_authoring_blocked_keyword

    # AUD-2026-15：Data/SSH 前缀黑名单（不依赖 XML risk 标记）
    if is_authoring_blocked_keyword(kid):
        raise AuthoringError(
            f"链路 3 拒绝执行 {kid}（Data/SSH / 禁止关键字，AUD-2026-15）"
        )
    # 纵深防御：再拦 irreversible（与 Intent 共用 risk 闸门）
    try:
        from ..intent.risk import assert_intent_keyword_allowed

        assert_intent_keyword_allowed(kid, source="authoring")
    except KeywordError as exc:
        raise AuthoringError(str(exc)) from exc
    # 确保关键字实现已加载
    try:
        import autopilot.keywords  # noqa: F401
    except ImportError:
        pass
    kwdef = REGISTRY.get(kid)
    if kwdef is None:
        raise AuthoringError(f"关键字未注册: {kid}")
    platform = _session_platform(ctx)
    kwargs: dict[str, Any] = {}
    for key, val in (step.params or {}).items():
        raw = "" if val is None else str(val)
        raw = _normalize_locator_param(str(key), raw, platform=platform)
        if hasattr(ctx, "resolve"):
            kwargs[str(key)] = ctx.resolve(raw)
        else:
            kwargs[str(key)] = raw
    try:
        kwdef.func(ctx, **kwargs)
    except TypeError as exc:
        # 过滤未知 kwargs 再试一次（LLM 偶发多余参数）
        import inspect

        try:
            sig = inspect.signature(kwdef.func)
            allowed = {
                n
                for n, p in sig.parameters.items()
                if n != "ctx" and p.kind in (
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.KEYWORD_ONLY,
                )
            }
            if any(k not in allowed and k != "kwargs" for k in kwargs):
                filtered = {k: v for k, v in kwargs.items() if k in allowed}
                kwdef.func(ctx, **filtered)
                return
        except (TypeError, ValueError):
            pass
        raise AuthoringError(f"执行 {kid} 参数不匹配: {exc}") from exc
    except KeywordError as exc:
        raise AuthoringError(f"执行失败 {kid}: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        # driver 层异常（WebDriverException 等）统一收敛成编写错误，交给上层降级重规划
        raise AuthoringError(f"执行异常 {kid}: {exc}") from exc
