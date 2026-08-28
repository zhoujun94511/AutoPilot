"""IDE 管理台角色判定 — 对齐 rbac-capability-matrix.md §5。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .actions import ActionSpec


def normalize_mc_role(role: str | None) -> str:
    return (role or "operator").strip().lower()


def is_platform_admin_role(role: str | None = None) -> bool:
    if role is None:
        from ..runtime import settings

        role = settings.mc_user_role()
    return normalize_mc_role(role) == "admin"


def role_meets_min(user_role: str | None, min_role: str | None) -> bool:
    """min_role=operator：任意已登录用户；min_role=admin：仅平台 admin。"""
    need = normalize_mc_role(min_role)
    have = normalize_mc_role(user_role)
    if need == "admin":
        return have == "admin"
    return True


def action_allowed_for_role(spec: "ActionSpec", user_role: str | None) -> bool:
    return role_meets_min(user_role, getattr(spec, "min_role", "operator"))


def connect_settings_banner(is_platform_admin: bool) -> str:
    if is_platform_admin:
        return (
            "平台管理员：启动本机 Runner 时可自动签发当前组织作用域 Token"
            "（不必先选项目）；也可在此预填 Runner Token。"
        )
    return (
        "Operator：不能自行签发 Runner Token。"
        "请让平台管理员在 Web「设备与执行 → 执行节点」签发后，"
        "将 Token 填入下方 API Token。"
    )


def connect_token_placeholder(is_platform_admin: bool) -> str:
    if is_platform_admin:
        return "Runner 用；可选（启动 Runner 时可自动签发）"
    return "必填：平台管理员签发的 Runner Token（启动本机 Runner 依赖此项）"
