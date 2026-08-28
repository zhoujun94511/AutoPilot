"""ScopePolicy 源码对齐：登录/闲聊/Runner 不强绑项目；写入仍要项目。"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts: str) -> str:
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def test_connect_dialog_allows_empty_project():
    text = _read("autopilot", "ui", "widgets", "mgmt_connect_dialog.py")
    assert "请填写或选择默认项目空间" not in text
    assert "不选仍可登录" in text


def test_capability_matrix_scope_policy_v14():
    text = _read("docs", "rbac-capability-matrix.md")
    assert "版本**：1.4" in text
    assert "合成计费桶" in text
    assert "已登录即可" in text


def test_runner_start_does_not_require_current_project():
    web = _read("autopilot", "ui", "main_window", "mgmt_runner_web.py")
    sess = _read("autopilot", "ui", "main_window", "mgmt_session.py")
    assert "Runner Token 必须绑定 project_id" not in web
    assert "Runner Token 必须绑定 project_id" not in sess
    assert "not running and logged_in" in sess
    assert "project_ids=list(project_ids or [])" in web


def test_mgmt_writes_still_require_project():
    sess = _read("autopilot", "ui", "main_window", "mgmt_session.py")
    assert "mgmt.upload" in sess
    assert "require_cached_project_id" in _read("autopilot", "ui", "main_window", "mgmt_delivery.py")


def test_project_transfer_requires_explicit_local_mapping_confirmation():
    delivery = _read("autopilot", "ui", "main_window", "mgmt_delivery.py")
    assert "def _mgmt_confirm_project_mapping(" in delivery
    assert "本地工程：" in delivery
    assert "Platform 项目：" in delivery
    assert "if bound == pid:" in delivery
    assert "settings.set_mc_bound_project_id(local, pid)" in delivery
    for action in (
        "同步逻辑用例",
        "上传工程",
        "导入逻辑用例",
        "逻辑用例一键入队",
        "提交远程批跑",
    ):
        assert f'action="{action}"' in delivery
    assert "当前用例绑定项目" in delivery
    assert "为避免跨项目误写" in delivery

    dialog = _read("autopilot", "ui", "widgets", "mgmt_submit_job_dialog.py")
    assert "self.project_id.setReadOnly(True)" in dialog
    assert "如需切换，请先返回连接设置" in dialog


def test_project_gate_comment_excludes_runner_scope():
    context = _read("autopilot", "mgmt", "project_context.py")
    assert "Runner 使用独立的组织/多项目 scope" in context


def test_authoring_codegen_project_id_optional():
    text = _read("autopilot", "authoring", "llm_client.py")
    assert "mc_is_logged_in" in text
    assert "require_cached_project_id" not in text
    assert "__authoring__" in text or "project_id 可空" in text
