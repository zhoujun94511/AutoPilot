"""编写会话：同一定位 + 页面签名不变 → 重复操作升级 / 熔断。

对标 Furiel 的逐级警告，但不把视觉 Agent 循环搬过来。
只看「已成功执行」的 keyword + locator + 当时页签名；页面变了计数清零。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

LEVEL_NONE = ""
LEVEL_INFO = "info"
LEVEL_WARN = "warn"
LEVEL_SEVERE = "severe"
LEVEL_STOP = "stop"

REPEAT_FAILED = "REPEAT_FAILED"

_SKIP_KEYWORDS = frozenset({
    "sleep",
    "wait_element",
    "wait_for_element",
    "mobile_app_snapshot",
    "web_browser_snapshot",
})


@dataclass
class RepeatVerdict:
    level: str
    consecutive: int
    message: str
    fingerprint: str = ""

    @property
    def should_stop(self) -> bool:
        return self.level == LEVEL_STOP


def action_fingerprint(keyword_id: str, locator: str = "", *, page_sig: str = "") -> str:
    """同一操作在同一页上的稳定指纹。"""
    return json.dumps(
        {
            "k": (keyword_id or "").strip(),
            "l": (locator or "").strip(),
            "p": (page_sig or "").strip(),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _action_desc(fingerprint: str) -> str:
    try:
        data = json.loads(fingerprint)
    except (TypeError, ValueError, json.JSONDecodeError):
        return fingerprint or "未知操作"
    if not isinstance(data, dict):
        return fingerprint or "未知操作"
    kid = str(data.get("k") or "未知")
    loc = str(data.get("l") or "").strip()
    return f"{kid}({loc})" if loc else f"{kid}()"


def consecutive_same(recent: list[str], last: str) -> int:
    if not last:
        return 0
    n = 0
    for item in reversed(recent):
        if item == last:
            n += 1
        else:
            break
    return n


def assess_repeat(recent: list[str], last: str = "") -> RepeatVerdict:
    """按连续次数给出 info → warn → severe → stop。"""
    fp = last or (recent[-1] if recent else "")
    n = consecutive_same(recent, fp) if fp else 0
    if n < 2:
        return RepeatVerdict(LEVEL_NONE, n, "", fingerprint=fp)
    desc = _action_desc(fp)
    if n <= 3:
        return RepeatVerdict(
            LEVEL_INFO,
            n,
            f"正在第 {n} 次执行 {desc}，且页面签名未变。请确认是否生效；不要无意义连点。",
            fingerprint=fp,
        )
    if n == 4:
        return RepeatVerdict(
            LEVEL_WARN,
            n,
            f"警告：{desc} 已连续 {n} 次而页面未变。请换控件、换路径或先观察，不要重复同一操作。",
            fingerprint=fp,
        )
    if n == 5:
        return RepeatVerdict(
            LEVEL_SEVERE,
            n,
            f"严重警告：{desc} 已连续 {n} 次无效。必须换完全不同的方法；再重复将被停止。",
            fingerprint=fp,
        )
    return RepeatVerdict(
        LEVEL_STOP,
        n,
        REPEAT_FAILED,
        fingerprint=fp,
    )


def should_track_keyword(keyword_id: str) -> bool:
    kid = (keyword_id or "").strip()
    if not kid or kid in _SKIP_KEYWORDS:
        return False
    low = kid.lower()
    return not (
        low.startswith("mobile_wait_")
        or low.startswith("web_wait_")
        or "wait_element" in low
    )


class RepeatWatch:
    """页面未变时反复同一操作（含过滤器丢掉的重复步）→ 升级 / 熔断。

    编写器会跳过「keyword+参数完全相同」的第二步，因此不能只数成功执行次数。
    """

    def __init__(self, maxlen: int = 10) -> None:
        self.maxlen = max(2, int(maxlen))
        self.recent: list[str] = []
        self.last_changing_fp = ""
        self.last_changing_sig = ""

    def record_executed(
        self,
        keyword_id: str,
        locator: str,
        page_sig: str,
        *,
        page_changing: bool,
    ) -> str:
        if not should_track_keyword(keyword_id):
            return ""
        fp = action_fingerprint(keyword_id, locator, page_sig=page_sig)
        if page_changing:
            self.last_changing_fp = fp
            self.last_changing_sig = page_sig
        return fp

    def page_stuck(self, page_sig: str) -> bool:
        return bool(self.last_changing_sig and page_sig == self.last_changing_sig)

    def note_stuck_retry(self, keyword_id: str, locator: str, page_sig: str) -> RepeatVerdict:
        """当前页签名未变，模型又提交了同一操作（或被当成重复步跳过）。"""
        if not should_track_keyword(keyword_id):
            return RepeatVerdict(LEVEL_NONE, 0, "")
        fp = action_fingerprint(keyword_id, locator, page_sig=page_sig)
        if self.last_changing_fp and not self.recent:
            self.recent.append(self.last_changing_fp)
        self.recent.append(fp)
        if len(self.recent) > self.maxlen:
            self.recent = self.recent[-self.maxlen :]
        return assess_repeat(self.recent)

    def assess(self) -> RepeatVerdict:
        return assess_repeat(self.recent)

    def prompt_warning(self, page_sig: str) -> str:
        if not self.page_stuck(page_sig):
            return self.assess().message
        stuck = self.assess()
        if stuck.message:
            return stuck.message
        desc = _action_desc(self.last_changing_fp)
        return f"上一改页动作 {desc} 执行后页面签名未变。请换控件或换路径，不要重复同一操作。"
