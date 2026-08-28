"""运行控制按钮 tooltip 刷新。"""

from __future__ import annotations

from PyQt6.QtGui import QAction

from ...actions import ACTIONS_BY_ID


def refresh_run_control_tips(
    act_pause: QAction,
    act_stop: QAction,
    *,
    idle: bool,
) -> None:
    if idle:
        act_pause.setToolTip("请先运行用例（F5），再暂停/继续")
        act_stop.setToolTip("请先运行用例（F5），再停止")
        return
    pause = ACTIONS_BY_ID["run.pause"]
    stop = ACTIONS_BY_ID["run.stop"]
    act_pause.setToolTip((pause.tip or pause.text).strip())
    act_stop.setToolTip((stop.tip or stop.text).strip())
