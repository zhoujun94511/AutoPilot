"""用例平台内容校验（Phase 3）：扫描步骤关键字与定位符的平台冲突，非阻塞警告。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..model.testcase import Step, StepNode, TestCase
from ..runtime.job_platforms import JOB_PLATFORMS
from .keyword_meta import KeywordCatalog, KeywordMeta
from .keyword_platforms import platform_mismatch_reason, target_platforms
from .locator_platform_lint import (
    _looks_like_locator,
    build_maps_index,
    locator_mismatch_reason,
    locator_param_ids,
    map_ref_lint_reason,
    parse_map_ref,
)

if TYPE_CHECKING:
    from ..model.mapfile import MapFile


@dataclass
class PlatformLintIssue:
    keyword_id: str
    reason: str
    shell: str = "case"
    comment: str = ""
    param_id: str = ""
    issue_type: str = "keyword"  # keyword | locator | map


def _resolve_platform(case: TestCase, default: str = "") -> str:
    plat = (getattr(case, "platform", "") or "").strip().lower()
    if plat in JOB_PLATFORMS:
        return plat
    d = (default or "").strip().lower()
    return d if d in JOB_PLATFORMS else ""


def _scan_step_locators(
    node: Step,
    *,
    shell: str,
    meta: KeywordMeta,
    platform: str,
    maps_index: dict[str, "MapFile"],
    ios_backend_mode: str,
    out: list[PlatformLintIssue],
) -> None:
    scan_ids = locator_param_ids(meta)
    for pv in node.params or []:
        pid = pv.param_id or ""
        raw = (pv.value or "").strip()
        if not raw:
            continue
        if pid not in scan_ids and not _looks_like_locator(raw):
            continue

        if parse_map_ref(raw):
            reason = map_ref_lint_reason(platform, raw, maps_index, ios_backend_mode)
            issue_type = "map"
        else:
            reason = locator_mismatch_reason(platform, raw)
            issue_type = "locator"

        if reason:
            out.append(PlatformLintIssue(
                keyword_id=node.keyword_id,
                reason=reason,
                shell=shell,
                comment=node.comment or meta.name,
                param_id=pid or "?",
                issue_type=issue_type,
            ))


def _visit_steps(
    nodes: list[StepNode],
    *,
    shell: str,
    catalog: KeywordCatalog,
    platform: str,
    maps_index: dict[str, "MapFile"],
    ios_backend_mode: str,
    out: list[PlatformLintIssue],
) -> None:
    for node in nodes or []:
        if isinstance(node, Step):
            if not node.is_run:
                continue
            meta = catalog.get(node.keyword_id)
            if meta is None:
                _visit_steps(node.children, shell=shell, catalog=catalog,
                             platform=platform, maps_index=maps_index,
                             ios_backend_mode=ios_backend_mode, out=out)
                continue
            reason = platform_mismatch_reason(platform, meta)
            if reason:
                out.append(PlatformLintIssue(
                    keyword_id=node.keyword_id,
                    reason=reason,
                    shell=shell,
                    comment=node.comment or meta.name,
                ))
            _scan_step_locators(node, shell=shell, meta=meta, platform=platform,
                                maps_index=maps_index, ios_backend_mode=ios_backend_mode,
                                out=out)
            _visit_steps(node.children, shell=shell, catalog=catalog,
                           platform=platform, maps_index=maps_index,
                           ios_backend_mode=ios_backend_mode, out=out)
        elif hasattr(node, "steps"):
            _visit_steps(getattr(node, "steps", []), shell=shell,
                           catalog=catalog, platform=platform,
                           maps_index=maps_index, ios_backend_mode=ios_backend_mode,
                           out=out)


def lint_testcase(
    case: TestCase,
    catalog: KeywordCatalog,
    platform: str = "",
    *,
    default_platform: str = "",
    maps: list["MapFile"] | None = None,
    ios_backend_mode: str = "",
) -> list[PlatformLintIssue]:
    """扫描用例各 shell 步骤，返回平台冲突列表（空 platform 则跳过）。"""
    plat = _resolve_platform(case, default_platform) or (platform or "").strip().lower()
    if plat not in JOB_PLATFORMS:
        return []
    maps_index = build_maps_index(maps)
    bm = (ios_backend_mode or "").strip().lower()
    if bm not in ("wda", "appium"):
        bm = ""
    issues: list[PlatformLintIssue] = []
    for shell in getattr(case, "shells", []) or []:
        _visit_steps(shell.steps, shell=shell.name, catalog=catalog,
                       platform=plat, maps_index=maps_index,
                       ios_backend_mode=bm, out=issues)
    return issues


def lint_testcases(
    cases: list[TestCase],
    catalog: KeywordCatalog,
    *,
    default_platform: str = "",
    maps: list["MapFile"] | None = None,
    ios_backend_mode: str = "",
) -> list[tuple[TestCase, list[PlatformLintIssue]]]:
    out: list[tuple[TestCase, list[PlatformLintIssue]]] = []
    for case in cases:
        issues = lint_testcase(
            case, catalog, default_platform=default_platform, maps=maps,
            ios_backend_mode=ios_backend_mode,
        )
        if issues:
            out.append((case, issues))
    return out


def keyword_allowed_on_platform(meta: KeywordMeta, platform: str) -> bool:
    if not platform:
        return True
    return not platform_mismatch_reason(platform, meta)


def keyword_target_platforms(meta: KeywordMeta) -> frozenset[str]:
    return target_platforms(meta)
