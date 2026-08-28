"""iOS parity JSON 报告解析与逐步 diff（Mac Appium vs Win WDA 等）。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 视为「通过」的状态
_PASS_STATUSES = frozenset({"PASS", "OK"})
# 视为「未通过」的状态（strict 模式下与 PASS 对比即 mismatch）
_FAIL_STATUSES = frozenset({"FAIL", "ERROR", "NOIMPL", "SKIP"})


@dataclass(frozen=True)
class StepSignature:
    case_name: str
    step_index: int
    keyword_id: str

    def key(self) -> str:
        return f"{self.case_name}::{self.step_index}::{self.keyword_id}"


@dataclass
class StepRecord:
    signature: StepSignature
    status: str
    message: str = ""

    @property
    def normalized(self) -> str:
        return normalize_step_status(self.status)


@dataclass
class StepMismatch:
    key: str
    keyword_id: str
    case_name: str
    left_status: str
    right_status: str
    left_message: str = ""
    right_message: str = ""


@dataclass
class ParityDiffResult:
    ok: bool
    left_label: str
    right_label: str
    compared: int = 0
    matched: int = 0
    mismatches: list[StepMismatch] = field(default_factory=list)
    only_left: list[str] = field(default_factory=list)
    only_right: list[str] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        lines = [
            f"对照：{self.left_label}  vs  {self.right_label}",
            f"逐步比对 {self.compared}，一致 {self.matched}，不一致 {len(self.mismatches)}",
        ]
        if self.only_left:
            lines.append(f"仅左侧 {len(self.only_left)} 步")
        if self.only_right:
            lines.append(f"仅右侧 {len(self.only_right)} 步")
        lines.append("结果：" + ("OK" if self.ok else "FAIL"))
        return lines


def normalize_step_status(status: str) -> str:
    s = (status or "").strip().upper()
    if s in _PASS_STATUSES:
        return "PASS"
    if s in _FAIL_STATUSES or s:
        return "FAIL"
    return "UNKNOWN"


def load_parity_report(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"parity 报告根节点须为 object: {p}")
    return data


def _runs_from_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    runs = report.get("runs")
    if isinstance(runs, list) and runs:
        return [r for r in runs if isinstance(r, dict)]
    # 单 run 扁平格式兼容
    if report.get("cases") or report.get("case_ids"):
        return [report]
    return []


def select_run(
    report: dict[str, Any],
    *,
    backend: str = "",
    udid: str = "",
    run_index: int = -1,
) -> dict[str, Any] | None:
    """从报告（含 dual 多 run）中选取一条 run。"""
    runs = _runs_from_report(report)
    if not runs:
        return None
    if run_index >= 0:
        return runs[run_index] if run_index < len(runs) else None
    backend_l = (backend or "").strip().lower()
    udid_s = (udid or "").strip()
    filtered = runs
    if backend_l:
        filtered = [r for r in filtered if str(r.get("backend_mode", "")).lower() == backend_l]
    if udid_s:
        filtered = [r for r in filtered if str(r.get("udid", "")) == udid_s]
    if len(filtered) == 1:
        return filtered[0]
    if len(filtered) > 1 and not backend_l and not udid_s:
        return filtered[0]
    return filtered[0] if filtered else runs[0]


def flatten_run_steps(run: dict[str, Any]) -> dict[str, StepRecord]:
    """将单条 run 展平为 step_key → StepRecord。"""
    out: dict[str, StepRecord] = {}
    for case in run.get("cases") or []:
        if not isinstance(case, dict):
            continue
        case_name = str(case.get("name") or "")
        steps = case.get("steps") or []
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            kid = str(step.get("keyword_id") or "")
            if not case_name or not kid:
                continue
            sig = StepSignature(case_name, i, kid)
            out[sig.key()] = StepRecord(
                signature=sig,
                status=str(step.get("status") or ""),
                message=str(step.get("message") or ""),
            )
    return out


def diff_step_maps(
    left: dict[str, StepRecord],
    right: dict[str, StepRecord],
    *,
    left_label: str = "left",
    right_label: str = "right",
    strict: bool = False,
) -> ParityDiffResult:
    """对比两侧逐步状态（默认按 PASS/FAIL 归一化）。"""
    keys_left = set(left)
    keys_right = set(right)
    common = sorted(keys_left & keys_right)
    only_left = sorted(keys_left - keys_right)
    only_right = sorted(keys_right - keys_left)
    mismatches: list[StepMismatch] = []
    matched = 0
    for k in common:
        lrec, rrec = left[k], right[k]
        if strict:
            same = lrec.status.upper() == rrec.status.upper()
        else:
            same = lrec.normalized == rrec.normalized
        if same:
            matched += 1
        else:
            mismatches.append(StepMismatch(
                key=k,
                keyword_id=lrec.signature.keyword_id,
                case_name=lrec.signature.case_name,
                left_status=lrec.status,
                right_status=rrec.status,
                left_message=lrec.message[:200],
                right_message=rrec.message[:200],
            ))
    ok = not mismatches and not only_left and not only_right
    return ParityDiffResult(
        ok=ok,
        left_label=left_label,
        right_label=right_label,
        compared=len(common),
        matched=matched,
        mismatches=mismatches,
        only_left=only_left,
        only_right=only_right,
    )


def diff_parity_reports(
    left_report: dict[str, Any],
    right_report: dict[str, Any],
    *,
    left_label: str = "left",
    right_label: str = "right",
    left_backend: str = "",
    right_backend: str = "",
    left_udid: str = "",
    right_udid: str = "",
    strict: bool = False,
) -> ParityDiffResult:
    lrun = select_run(left_report, backend=left_backend, udid=left_udid)
    rrun = select_run(right_report, backend=right_backend, udid=right_udid)
    if lrun is None:
        raise ValueError("左侧报告无可用 run")
    if rrun is None:
        raise ValueError("右侧报告无可用 run")
    return diff_step_maps(
        flatten_run_steps(lrun),
        flatten_run_steps(rrun),
        left_label=left_label,
        right_label=right_label,
        strict=strict,
    )


def diff_result_to_dict(result: ParityDiffResult) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "left_label": result.left_label,
        "right_label": result.right_label,
        "compared": result.compared,
        "matched": result.matched,
        "mismatches": [
            {
                "key": m.key,
                "case": m.case_name,
                "keyword_id": m.keyword_id,
                "left_status": m.left_status,
                "right_status": m.right_status,
                "left_message": m.left_message,
                "right_message": m.right_message,
            }
            for m in result.mismatches
        ],
        "only_left": result.only_left,
        "only_right": result.only_right,
    }


def find_latest_reports(
    logs_dir: str | Path,
    *,
    host: str = "",
    backend: str = "",
) -> list[Path]:
    """按修改时间列出 logs 下 parity*.json（可选 host/backend 过滤）。"""
    root = Path(logs_dir)
    if not root.is_dir():
        return []
    host_l = (host or "").lower()
    backend_l = (backend or "").lower()
    out: list[Path] = []
    for p in sorted(root.glob("parity*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        if backend_l and backend_l not in p.name.lower():
            continue
        if host_l:
            # noinspection PyBroadException
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if str(data.get("host", "")).lower() != host_l:
                    continue
            except Exception:
                continue
        out.append(p)
    return out
