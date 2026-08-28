"""兼容旧入口：本地跑通后回写 EXECUTABLE。

完整能力见 ``run_status_sync``（含失败 → DEBUGGING）。
"""

from __future__ import annotations

from typing import Any, Callable

from .run_status_sync import (
    collect_failed_logical_ids,
    collect_logical_ids_by_outcome,
    collect_passed_logical_ids,
    sync_statuses_after_run,
    try_sync_run_statuses_with_session,
)


def sync_executable_after_run(
    suite: Any,
    *,
    client: Any | None = None,
    log: Callable[[str], None] | None = None,
) -> tuple[int, int]:
    result = sync_statuses_after_run(suite, client=client, log=log)
    return result.get("EXECUTABLE", (0, 0))


def try_sync_executable_with_session(
    suite: Any,
    *,
    log: Callable[[str], None] | None = None,
) -> tuple[int, int]:
    result = try_sync_run_statuses_with_session(suite, log=log)
    return result.get("EXECUTABLE", (0, 0))


__all__ = [
    "collect_passed_logical_ids",
    "collect_failed_logical_ids",
    "collect_logical_ids_by_outcome",
    "sync_executable_after_run",
    "try_sync_executable_with_session",
    "sync_statuses_after_run",
    "try_sync_run_statuses_with_session",
]
