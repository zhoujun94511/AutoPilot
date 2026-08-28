"""IDE 侧项目/组织上下文：登录后缓存并校验可见项目，禁止静默写错空间。"""

from __future__ import annotations

from typing import Any, Callable

from .client import MgmtClient, MgmtClientError


def require_cached_project_id() -> str:
    """读取本机已缓存的 project_id；空则明确报错（禁止回退到目录名）。

    仅约束管理台中必须归属项目的**写入/同步**路径（上传、投递、导入等）。
    Runner 使用独立的组织/多项目 scope，不走此门禁。
    IDE 本地编辑与执行不依赖此项。
    """
    from ..runtime import settings

    pid = settings.mc_project_id()
    if not pid:
        raise MgmtClientError(
            "未绑定项目空间，无法使用该管理台功能。\n"
            "请在「Platform 连接」中选择可见项目；若列表为空，请联系管理员将你加入项目成员。"
        )
    return pid


def project_labels(projects: list[dict[str, Any]]) -> list[str]:
    """下拉展示用：name (id) 或仅 id。"""
    labels: list[str] = []
    for p in projects or []:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id") or "").strip()
        if not pid:
            continue
        name = str(p.get("name") or "").strip()
        labels.append(f"{name} ({pid})" if name and name != pid else pid)
    return labels


def project_id_from_label(label: str, projects: list[dict[str, Any]]) -> str:
    text = (label or "").strip()
    if text.endswith(")") and "(" in text:
        maybe = text.rsplit("(", 1)[-1].rstrip(")").strip()
        if maybe:
            return maybe
    for p in projects or []:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id") or "").strip()
        name = str(p.get("name") or "").strip()
        if text == pid or text == name:
            return pid
    return text


def fetch_visible_projects(client: MgmtClient) -> list[dict[str, Any]]:
    rows = client.list_projects()
    return [p for p in rows if isinstance(p, dict) and str(p.get("id") or "").strip()]


def resolve_login_project(
    projects: list[dict[str, Any]],
    *,
    preferred_id: str = "",
) -> tuple[str | None, bool]:
    """登录成功后解析项目空间（对标 VS Code / Postman：登录 ≠ 必须已有 workspace）。

    Returns:
        (project_id, need_picker)
        - 无可见项目：返回 (None, False)，允许进入 IDE（本地可用，管理台写入再拦截）
        - 唯一项目或缓存仍有效：直接返回 id，need_picker=False
        - 多项目且无有效缓存：返回 (None, True)，由 UI 展示列表
    """
    from ..runtime import settings

    ids = [str(p.get("id") or "").strip() for p in projects if isinstance(p, dict)]
    ids = [i for i in ids if i]
    if not ids:
        settings.set_mc_project_id("")
        return None, False

    preferred = (preferred_id or settings.mc_project_id() or "").strip()
    if len(ids) == 1:
        return ids[0], False
    if preferred and preferred in ids:
        return preferred, False
    if preferred and preferred not in ids:
        settings.set_mc_project_id("")
    return None, True


def ensure_project_selected(
    client: MgmtClient,
    *,
    preferred_id: str = "",
    choose: Callable[[list[dict[str, Any]]], str] | None = None,
) -> str:
    """确保本机有一个当前用户可见的 project_id 并写入 settings。

    choose: 多项目且无有效缓存时，由 UI 返回选中的 id；返回空表示取消。
    """
    from ..runtime import settings

    projects = fetch_visible_projects(client)
    ids = [str(p.get("id") or "").strip() for p in projects]
    if not ids:
        settings.set_mc_project_id("")
        raise MgmtClientError(
            "当前账号没有任何可见项目，无法完成需要项目空间的管理台操作。\n"
            "本地编辑与执行仍可使用；请联系管理员将你加入项目成员后再上传/投递。"
        )

    preferred = (preferred_id or settings.mc_project_id() or "").strip()
    if preferred and preferred in ids:
        settings.set_mc_project_id(preferred)
        return preferred
    if len(ids) == 1:
        settings.set_mc_project_id(ids[0])
        return ids[0]

    if choose is not None:
        picked = (choose(projects) or "").strip()
        if not picked:
            raise MgmtClientError("已取消选择项目空间。")
        if picked not in ids:
            raise MgmtClientError(
                f"所选项目「{picked}」不在可见列表中。",
                status_code=403,
            )
        settings.set_mc_project_id(picked)
        return picked

    if preferred and preferred not in ids:
        settings.set_mc_project_id("")
    raise MgmtClientError(
        "请选择管理台项目空间（连接设置或登录后选择）："
        + "、".join(ids[:12])
        + ("…" if len(ids) > 12 else "")
    )


def assert_project_membership(client: MgmtClient, project_id: str) -> None:
    """确认 project_id 在当前用户可见列表中。"""
    pid = (project_id or "").strip()
    if not pid:
        raise MgmtClientError("project_id 不能为空")
    projects = fetch_visible_projects(client)
    ids = {str(p.get("id") or "").strip() for p in projects}
    if pid not in ids:
        raise MgmtClientError(
            f"当前账号不是项目「{pid}」的成员，无法写入该空间。",
            status_code=403,
        )
