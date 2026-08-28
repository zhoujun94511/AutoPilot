"""计划执行参数输入对话框（薄封装，便于主窗口调用与单测分离）。"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import QInputDialog

from ..engine.scheduler import Schedule
from .confirm import confirm


def ask_schedule(parent) -> Optional[Schedule]:
    """依次询问 延迟/间隔/次数/失败即停，返回 Schedule；任一步取消则返回 None。"""
    delay, ok = QInputDialog.getInt(parent, "计划执行", "首次延迟（秒）：", 0, 0, 86400, 1)
    if not ok:
        return None
    interval, ok = QInputDialog.getInt(parent, "计划执行", "重复间隔（秒，0=只跑一次）：", 0, 0, 86400, 1)
    if not ok:
        return None
    repeat, ok = QInputDialog.getInt(parent, "计划执行", "执行次数（0=不限）：", 1, 0, 100000, 1)
    if not ok:
        return None
    stop_on_fail = confirm(parent, "计划执行", "失败即停（某次未通过则停止后续）？",
                           yes_text="失败即停", no_text="继续执行")
    return Schedule(delay_sec=delay, interval_sec=interval, repeat=repeat,
                    stop_on_fail=stop_on_fail)
