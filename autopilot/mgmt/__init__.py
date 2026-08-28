"""管理台 HTTP 客户端包（C/S：仅调用 Platform API，不 import 服务端实现）。"""

from .auth_api import (
    api_login,
    api_me,
    ensure_user_session,
    login_and_persist,
    logout_and_clear,
    refresh_and_persist,
)
from .client import MgmtClient, MgmtClientError, mgmt_error_message
from .project_context import (
    assert_project_membership,
    ensure_project_selected,
    require_cached_project_id,
)
from .entries import list_runnable_entries, list_runnable_entries_in_zip
from .logical_import import write_logical_cases_as_drafts
from .target_app import TargetAppParams, acquire_target_app
from .manifest import build_artifact_manifest, write_manifest_json
from .pack import zip_project_dir
from .status_sync import (
    collect_logical_case_ids,
    collect_logical_ids_from_project,
    patch_automation_status,
)
from .case_trace import has_mapping_required, logical_case_id_from_path
from .executable_sync import (
    collect_passed_logical_ids,
    sync_executable_after_run,
    try_sync_executable_with_session,
)
from .run_status_sync import (
    collect_failed_logical_ids,
    collect_status_targets,
    sync_statuses_after_run,
    try_sync_run_statuses_with_session,
)

__all__ = [
    "MgmtClient",
    "MgmtClientError",
    "mgmt_error_message",
    "api_login",
    "api_me",
    "login_and_persist",
    "refresh_and_persist",
    "logout_and_clear",
    "ensure_user_session",
    "require_cached_project_id",
    "ensure_project_selected",
    "assert_project_membership",
    "zip_project_dir",
    "list_runnable_entries",
    "list_runnable_entries_in_zip",
    "write_logical_cases_as_drafts",
    "TargetAppParams",
    "acquire_target_app",
    "build_artifact_manifest",
    "write_manifest_json",
    "collect_logical_case_ids",
    "collect_logical_ids_from_project",
    "patch_automation_status",
    "has_mapping_required",
    "logical_case_id_from_path",
    "collect_passed_logical_ids",
    "collect_failed_logical_ids",
    "collect_status_targets",
    "sync_executable_after_run",
    "try_sync_executable_with_session",
    "sync_statuses_after_run",
    "try_sync_run_statuses_with_session",
]
