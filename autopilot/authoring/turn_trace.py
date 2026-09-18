"""链路 3 编写回合决策轨迹（sidecar，供回放/排查）。

不上传截图时仍记录：页签名、模型 notes、计划/执行/跳过步骤。
保存草稿时写逐用例 ``<case>.authoring.trace.json``，并维护旧版最近一次别名。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

AUTHORING_TRACE_FILE = "_authoring_trace.json"


def trace_path_for_case(case_path: str | Path) -> Path:
    """每个用例独立的权威轨迹文件；旧文件仅作为最近一次兼容别名。"""
    path = Path(case_path)
    return path.parent / f"{path.name}.authoring.trace.json"


@dataclass
class TurnTraceRecord:
    turn: int
    page_sig: str = ""
    page_sig_before: str = ""
    page_sig_after: str = ""
    observation_valid: bool = True
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
    navigation: dict[str, Any] = field(default_factory=dict)
    incident: dict[str, Any] | None = None
    pruned: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AuthoringTrace:
    title: str = ""
    platform: str = ""
    natural_language: str = ""
    goal_completed: bool = False
    goal_judge: dict[str, Any] | None = None
    stop_reason: str = ""
    replay: dict[str, Any] | None = None
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
            "stop_reason": self.stop_reason,
            "replay": self.replay,
            "turns": [asdict(t) for t in self.turns],
        }


def write_authoring_trace(
    case_path: str | Path,
    trace: AuthoringTrace | dict[str, Any],
) -> Path:
    """写逐用例轨迹，并同步旧版“最近一次”兼容别名。"""
    path = Path(case_path)
    out = path.parent / AUTHORING_TRACE_FILE
    if isinstance(trace, AuthoringTrace):
        payload = trace.to_dict()
    else:
        payload = dict(trace)
    payload["case_file"] = path.name
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    canonical = trace_path_for_case(path)
    canonical.write_text(
        text,
        encoding="utf-8",
    )
    # 兼容旧版调用方与已有工程：保留“最近一次”别名，但读取优先逐用例文件。
    out.write_text(text, encoding="utf-8")
    return canonical


def read_authoring_trace(project_or_case: str | Path) -> dict[str, Any] | None:
    p = Path(project_or_case)
    if p.is_file():
        canonical = trace_path_for_case(p)
        trace_path = canonical if canonical.is_file() else p.parent / AUTHORING_TRACE_FILE
    else:
        trace_path = p / "authored" / AUTHORING_TRACE_FILE
    if not trace_path.is_file():
        return None
    try:
        data = json.loads(trace_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None
