"""HTTP 关键字工程内路径 containment（Runner 任意文件读取防护）。"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from autopilot.keywords.context import ExecutionContext
from autopilot.keywords.http import assert_kw as http_assert
from autopilot.keywords.http import env as http_env
from autopilot.keywords.registry import KeywordError
from autopilot.runtime.paths import safe_path_under_project


def test_safe_path_under_project_rejects_escape() -> None:
    with tempfile.TemporaryDirectory() as proj:
        with pytest.raises(ValueError, match="invalid|escapes"):
            safe_path_under_project(proj, "../outside.txt")
        with pytest.raises(ValueError, match="invalid|escapes"):
            safe_path_under_project(proj, "..\\outside.txt")


def test_safe_path_under_project_resolves_relative() -> None:
    with tempfile.TemporaryDirectory() as proj:
        schema = os.path.join(proj, "schemas", "ok.json")
        os.makedirs(os.path.dirname(schema), exist_ok=True)
        with open(schema, "w", encoding="utf-8") as f:
            json.dump({"type": "object"}, f)
        got = safe_path_under_project(proj, "schemas/ok.json")
        assert os.path.normpath(got) == os.path.normpath(schema)


def test_load_schema_rejects_absolute_outside_project(tmp_path) -> None:
    outside = tmp_path.parent / "secret_schema.json"
    outside.write_text('{"type":"object"}', encoding="utf-8")
    ctx = ExecutionContext()
    ctx.project_path = str(tmp_path)
    with pytest.raises(KeywordError, match="schema"):
        http_assert._load_schema(ctx, str(outside))


def test_load_schema_rejects_traversal(tmp_path) -> None:
    ctx = ExecutionContext()
    ctx.project_path = str(tmp_path)
    with pytest.raises(KeywordError, match="schema"):
        http_assert._load_schema(ctx, "../outside.json")


def test_json_assert_schema_loads_under_project(tmp_path) -> None:
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
    (tmp_path / "s.json").write_text(json.dumps(schema), encoding="utf-8")
    ctx = ExecutionContext()
    ctx.project_path = str(tmp_path)
    http_assert.json_assert_schema(ctx, json_text='{"x": 1}', schema="s.json")


def test_api_env_use_rejects_env_file_outside_project(tmp_path) -> None:
    outside = tmp_path.parent / "stolen_env.yaml"
    outside.write_text(
        "profiles:\n  dev:\n    base_url: http://evil\n    vars:\n      token: x\n",
        encoding="utf-8",
    )
    ctx = ExecutionContext()
    ctx.project_path = str(tmp_path)
    with pytest.raises(KeywordError, match="未找到"):
        http_env.api_env_use(ctx, profile="dev", env_file=str(outside))


def test_api_env_use_loads_relative_env_file(tmp_path) -> None:
    cfg = tmp_path / "config" / "api_env.yaml"
    cfg.parent.mkdir()
    cfg.write_text(
        "profiles:\n  dev:\n    base_url: http://127.0.0.1:9\n    vars:\n      token: ok\n",
        encoding="utf-8",
    )
    ctx = ExecutionContext()
    ctx.project_path = str(tmp_path)
    http_env.api_env_use(ctx, profile="dev", env_file="config/api_env.yaml")
    assert ctx.get_var("token") == "ok"
