"""将 Authoring 草稿写入传统 ``.tc.yaml``（对齐链路 1 正式序列化）。"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..metadata.keyword_meta import KeywordCatalog, load_catalog
from ..model.serializer import save_testcase, testcase_to_dict
from ..model.testcase import Desc, ParamValue, Shell, Step, TestCase
from .contract import (
    is_authoring_blocked_keyword,
    AuthoringDraft,
    AuthoringError,
    GeneratedStep,
    clamp_max_steps,
)
from .registry_catalog import allowed_keyword_ids

#: 规划阶段常用、但不在关键字 XML schema 内的键 → 并入 remark
_HINT_PARAM_KEYS = frozenset({"target", "hint", "label"})
_AUTHORING_REMARK = "authoring:chain3"


@lru_cache(maxsize=1)
def _catalog() -> KeywordCatalog:
    return load_catalog()


def parse_llm_draft(
    data: dict[str, Any],
    *,
    platform: str,
    max_steps: int,
    fallback_title: str = "",
) -> AuthoringDraft:
    allowed = allowed_keyword_ids(platform)
    limit = clamp_max_steps(max_steps)
    title = str(data.get("title") or fallback_title or "AI 辅助用例").strip()
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise AuthoringError("LLM 未返回 steps")
    warnings: list[str] = []
    steps: list[GeneratedStep] = []
    for i, item in enumerate(raw_steps[:limit]):
        if not isinstance(item, dict):
            warnings.append(f"跳过第 {i + 1} 步：非对象")
            continue
        kid = str(item.get("keyword_id") or item.get("step") or "").strip()
        if not kid:
            warnings.append(f"跳过第 {i + 1} 步：缺少 keyword_id")
            continue
        if is_authoring_blocked_keyword(kid):
            warnings.append(f"拒绝 {kid}（链路 3 禁止 Data/SSH / intent_act，AUD-2026-15）")
            continue
        if kid not in allowed:
            warnings.append(f"拒绝非白名单关键字：{kid}")
            continue
        params_raw = item.get("params") or {}
        params: dict[str, str] = {}
        if isinstance(params_raw, dict):
            for k, v in params_raw.items():
                params[str(k)] = "" if v is None else str(v)
        comment = str(item.get("comment") or item.get("text") or "").strip()
        steps.append(GeneratedStep(keyword_id=kid, params=params, comment=comment))
    if not steps:
        raise AuthoringError("校验后无合法步骤：" + "；".join(warnings[:5]))
    note = str(data.get("notes") or "").strip()
    if note:
        warnings.append(f"notes: {note}")
    if len(raw_steps) > limit:
        warnings.append(f"已截断至 {limit} 步")
    return AuthoringDraft(title=title, platform=platform, steps=steps, warnings=warnings)


def _safe_filename(title: str) -> str:
    base = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", (title or "ai_case").strip())
    base = base.strip("._") or "ai_case"
    return f"{base[:80]}.tc.yaml"


def normalize_step_params(
    keyword_id: str,
    params: dict[str, str] | None,
    *,
    platform: str = "",
) -> tuple[dict[str, str], list[str]]:
    """按关键字元数据补默认、剥离 schema 外参数。

    返回 ``(规范 params, 并入 remark 的提示文案列表)``。
    """
    raw = {str(k): "" if v is None else str(v) for k, v in (params or {}).items()}
    hints: list[str] = []
    for key in list(raw.keys()):
        if key in _HINT_PARAM_KEYS:
            val = raw.pop(key).strip()
            if val:
                hints.append(val)

    meta = _catalog().get(keyword_id)
    if meta is None or not meta.params:
        return raw, hints

    allowed_ids = {p.param_id for p in meta.params if p.param_id}
    for key in list(raw.keys()):
        if key not in allowed_ids:
            raw.pop(key, None)

    plat = (platform or "").strip().lower()
    out: dict[str, str] = {}
    for pm in meta.params:
        pid = (pm.param_id or "").strip()
        if not pid:
            continue
        cur = raw.get(pid)
        if cur is not None and str(cur).strip() != "":
            out[pid] = str(cur)
            continue
        # 移动端 type 优先用用例平台，避免 XML 默认 android 盖住 iOS
        if (
            pid == "type"
            and plat in ("ios", "android")
            and keyword_id.startswith(("mobile_", "appium_", "native_"))
        ):
            out[pid] = plat
            continue
        default = str(pm.default or "")
        if default:
            out[pid] = default
            continue
        if pm.required:
            out[pid] = ""
    return out, hints


def _step_remark(hints: list[str]) -> str:
    parts = [_AUTHORING_REMARK]
    for h in hints:
        text = (h or "").strip()
        if text and text not in parts:
            parts.append(text)
    return " | ".join(parts)


def _tag_for_steps(steps: list[GeneratedStep]) -> str:
    tags: list[str] = []
    for s in steps:
        kid = (s.keyword_id or "").lower()
        if kid.startswith(("mobile_", "appium_", "native_")):
            label = "MOBILE"
        elif kid.startswith("web_"):
            label = "WEB"
        elif kid.startswith("http_") or kid.startswith("json_"):
            label = "HTTP"
        else:
            continue
        if label not in tags:
            tags.append(label)
    return ",".join(tags)


def draft_to_testcase(draft: AuthoringDraft) -> TestCase:
    """把 Authoring 草稿建成正式 ``TestCase`` 模型。"""
    case_steps: list[Step] = []
    platform = (draft.platform or "").strip().lower()
    for s in draft.steps:
        params, hints = normalize_step_params(
            s.keyword_id, s.params, platform=platform
        )
        case_steps.append(
            Step(
                keyword_id=s.keyword_id,
                comment=s.comment or s.keyword_id,
                remark=_step_remark(hints),
                is_run=True,
                params=[ParamValue(param_id=k, value=v) for k, v in params.items()],
            )
        )
    title = (draft.title or "AI 辅助用例").strip() or "AI 辅助用例"
    tc = TestCase(
        name=title,
        data_id="",
        tag=_tag_for_steps(draft.steps),
        platform=platform,
        is_execute=True,
        able_invoked=False,
        datapool="DATATABLE(NONE,false)",
        desc=Desc(description="AI 辅助编写（链路3）"),
    )
    tc.case = Shell(name="case", steps=case_steps)
    tc.before = Shell(name="before", steps=[])
    tc.after = Shell(name="after", steps=[])
    tc.fault = Shell(name="fault", steps=[])
    return tc


def draft_to_tc_dict(draft: AuthoringDraft) -> dict[str, Any]:
    return testcase_to_dict(draft_to_testcase(draft))


def save_draft_tc(
    draft: AuthoringDraft,
    project_dir: str | Path,
    *,
    subdir: str = "authored",
) -> Path:
    root = Path(project_dir)
    if not root.is_dir():
        raise AuthoringError(f"工程目录不存在：{project_dir}")
    out_dir = root / subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / _safe_filename(draft.title)
    # 避免覆盖：同名加后缀
    if path.exists():
        stem = path.stem
        for i in range(2, 100):
            cand = out_dir / f"{stem}_{i}.tc.yaml"
            if not cand.exists():
                path = cand
                break
    save_testcase(draft_to_testcase(draft), str(path))
    if isinstance(getattr(draft, "decision_trace", None), dict) and draft.decision_trace:
        from .turn_trace import write_authoring_trace

        write_authoring_trace(path, draft.decision_trace)
    return path
