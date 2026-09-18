"""统一的「是/否」确认弹框。

不再使用 QMessageBox：Windows 系统按钮 + 全局 QPushButton QSS 会挤成细边框。
所有确认操作走 confirm() / confirm_tri()，内部是 ConfirmDialog + DialogButtonBar。
点主按钮返回确认，「取消」或关闭返回取消。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import QDialog, QWidget

from .widgets.confirm_dialog import ConfirmDialog


def confirm(parent: Optional[QWidget], title: str, text: str, *,
            danger: bool = False, yes_text: str = "确定", no_text: str = "取消") -> bool:
    """弹确认框；用户确认返回 True，否则 False。

    danger=True：警告图标 + 红色描边主按钮，默认焦点落在「取消」（防误删回车）。
    """
    dlg = ConfirmDialog(
        parent,
        title,
        text,
        danger=danger,
        yes_text=yes_text,
        cancel_text=no_text,
        default="cancel" if danger else "yes",
    )
    return dlg.exec() == QDialog.DialogCode.Accepted


def confirm_tri(
    parent: Optional[QWidget],
    title: str,
    text: str,
    *,
    yes_text: str,
    no_text: str,
    cancel_text: str = "取消",
    default: str = "yes",
    danger: bool = False,
) -> str:
    """三按钮确认。返回 ``yes`` / ``no`` / ``cancel``（关闭窗口视为 cancel）。"""
    dlg = ConfirmDialog(
        parent,
        title,
        text,
        danger=danger,
        yes_text=yes_text,
        no_text=no_text,
        cancel_text=cancel_text,
        default=default if default in ("yes", "no", "cancel") else "yes",
    )
    dlg.exec()
    return dlg.choice


def ask_local_runner_prompt(parent: Optional[QWidget], prompt) -> str:
    """弹出 Runner/检视确认，返回 exclude / report_all / cancel。"""
    from ..mgmt.local_runner_guard import (
        ACTION_CANCEL,
        SCENARIO_START_SINGLE,
        resolve_prompt_action,
    )

    if prompt is None:
        return ACTION_CANCEL
    if prompt.scenario == SCENARIO_START_SINGLE or not prompt.no_text:
        ok = confirm(
            parent,
            prompt.title,
            prompt.text,
            danger=True,
            yes_text=prompt.yes_text,
            no_text=prompt.cancel_text or "取消",
        )
        return resolve_prompt_action(prompt.scenario, "yes" if ok else "cancel")
    default = "yes"
    if prompt.default_action == "report_all":
        default = "no"
    elif prompt.default_action == "cancel":
        default = "cancel"
    clicked = confirm_tri(
        parent,
        prompt.title,
        prompt.text,
        yes_text=prompt.yes_text,
        no_text=prompt.no_text,
        cancel_text=prompt.cancel_text or "取消",
        default=default,
        danger=True,
    )
    return resolve_prompt_action(prompt.scenario, clicked)
