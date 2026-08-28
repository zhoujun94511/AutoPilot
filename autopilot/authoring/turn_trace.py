"""链路 3 编写回合决策轨迹（sidecar，供回放/排查）。

不上传截图时仍记录：页签名、模型 notes、计划/执行/跳过步骤。
保存草稿时与 ``_authoring.json`` 同目录写入 ``_authoring_trace.json``。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

AUTHORING_TRACE_FILE = "_authoring_trace.json"


@dataclass
class TurnTraceRecord:
    turn: int
    page_sig: str = ""
    element_count: int = 0
    screen: str = ""
    notes: str = ""
    done: bool = False
    planned: list[dict[str, Any]] = field(default_factory=list)
    executed: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[dict[str, Any]] = field(default_factory=list)
    cache_hits: list[str] = field(default_factory=list)
    repeat_level: str = ""
    repeat_note: str = ""


@dataclass
class AuthoringTrace:
    title: str = ""
    platform: str = ""
    natural_language: str = ""
    goal_completed: bool = False
    goal_judge: dict[str, Any] | None = None
    turns: list[TurnTraceRecord] = field(default_factory=list)

    def add_turn(self, rec: TurnTraceRecord) -> None:
        self.turns.append(rec)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "platform": self.platform,
            "natural_language": self.natural_language,
            "goal_completed": self.goal_completed,
            "goal_judge": self.goal_judge,
            "turns": [asdict(t) for t in self.turns],
        }


def write_authoring_trace(
    case_path: str | Path,
    trace: AuthoringTrace | dict[str, Any],
) -> Path:
    """写到草稿同目录的 ``_authoring_trace.json``（整份覆盖为最近一次编写）。"""
    path = Path(case_path)
    out = path.parent / AUTHORING_TRACE_FILE
    if isinstance(trace, AuthoringTrace):
        payload = trace.to_dict()
    else:
        payload = dict(trace)
    payload["case_file"] = path.name
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return out


def read_authoring_trace(project_or_case: str | Path) -> dict[str, Any] | None:
    p = Path(project_or_case)
    if p.is_file():
        trace_path = p.parent / AUTHORING_TRACE_FILE
    else:
        trace_path = p / "authored" / AUTHORING_TRACE_FILE
    if not trace_path.is_file():
        return None
    try:
        data = json.loads(trace_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None
