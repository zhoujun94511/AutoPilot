"""本地执行调度：定时 / 周期 / 条件触发地运行用例套件（非平台/云调度）。

纯逻辑（Schedule 模型 + should_continue 判定）便于离线测试；
UI 侧用 QTimer 按 delay→interval 节拍触发执行，并据 should_continue 决定是否继续。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Schedule:
    """一次计划执行的配置。

    delay_sec: 首次执行前的延迟秒数（0 = 立即）。
    interval_sec: 两次执行的间隔秒数（0 = 仅执行一次，不重复）。
    repeat: 计划执行总次数（0 = 不限次，直到手动停止 / 条件触发停止）。
    stop_on_fail: 条件触发的轻量形式——某次执行未通过则停止后续计划。
    """

    delay_sec: int = 0
    interval_sec: int = 0
    repeat: int = 1
    stop_on_fail: bool = False

    def is_valid(self) -> bool:
        return self.delay_sec >= 0 and self.interval_sec >= 0 and self.repeat >= 0

    def repeats(self) -> bool:
        """是否需要周期重复（interval>0 且 (不限次 或 次数>1)）。"""
        return self.interval_sec > 0 and (self.repeat == 0 or self.repeat > 1)


def should_continue(schedule: Schedule, runs_done: int,
                    last_passed: Optional[bool]) -> bool:
    """判断是否还应触发下一次执行。

    - 达到 repeat 次数（repeat>0）→ 停止。
    - stop_on_fail 且上次未通过 → 停止。
    - 非周期（interval_sec==0）→ 跑完第一次即停止。
    """
    if not schedule.repeats() and runs_done >= 1:
        return False
    if schedule.repeat and runs_done >= schedule.repeat:
        return False
    if schedule.stop_on_fail and last_passed is False:
        return False
    return True


def first_delay_ms(schedule: Schedule) -> int:
    return max(0, int(schedule.delay_sec * 1000))


def interval_ms(schedule: Schedule) -> int:
    return max(0, int(schedule.interval_sec * 1000))
