"""统一的「是/否」确认弹框。

Qt 的 QMessageBox 标准按钮(Yes/No/Ok/Cancel)用系统英文文案，与中文界面混用很违和。
这里用自定义按钮文案(默认「确定」/「取消」)统一收口，所有确认操作都走 confirm()，
点「确定」返回 True，「取消」或关闭返回 False。
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import QMessageBox, QWidget

from .branding import app_icon


def confirm(parent: Optional[QWidget], title: str, text: str, *,
            danger: bool = False, yes_text: str = "确定", no_text: str = "取消") -> bool:
    """弹确认框；用户确认返回 True，否则 False。

    danger=True：用警告图标，且默认焦点落在「取消」（防误删等破坏性操作手滑回车）。
    """
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setWindowIcon(app_icon())
    box.setIcon(QMessageBox.Icon.Warning if danger else QMessageBox.Icon.Question)
    yes = box.addButton(yes_text, QMessageBox.ButtonRole.AcceptRole)
    no = box.addButton(no_text, QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(no if danger else yes)
    box.exec()
    return box.clickedButton() is yes


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
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setWindowIcon(app_icon())
    box.setIcon(QMessageBox.Icon.Warning if danger else QMessageBox.Icon.Question)
    yes = box.addButton(yes_text, QMessageBox.ButtonRole.AcceptRole)
    no = box.addButton(no_text, QMessageBox.ButtonRole.ActionRole)
    cancel = box.addButton(cancel_text, QMessageBox.ButtonRole.RejectRole)
    if default == "no":
        box.setDefaultButton(no)
    elif default == "cancel":
        box.setDefaultButton(cancel)
    else:
        box.setDefaultButton(yes)
    box.exec()
    clicked = box.clickedButton()
    if clicked is yes:
        return "yes"
    if clicked is no:
        return "no"
    return "cancel"


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
