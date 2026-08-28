"""C2：OpenAPI / Postman → HTTP .tc.yaml。"""

from __future__ import annotations

from pathlib import Path

# noinspection PyUnresolvedReferences
import yaml

from autopilot.mgmt.openapi_import import (
    import_spec_to_cases,
    op_to_tc_dict,
    write_cases,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "openapi_mini.json"


def test_import_openapi_mini():
    cases, meta = import_spec_to_cases(FIXTURE)
    assert meta["kind"] == "openapi"
    assert meta["base_url"] == "https://api.example.com"
    assert len(cases) == 3
    methods = {c["shells"]["case"][0]["step"] for c in cases}
    assert "http_get" in methods
    assert "http_post" in methods
    post = next(c for c in cases if c["shells"]["case"][0]["step"] == "http_post")
    assert post["shells"]["case"][1]["params"]["expected"] == "201"


def test_methods_filter_and_write(tmp_path: Path):
    cases, _ = import_spec_to_cases(FIXTURE, methods=["get"], limit=1)
    assert len(cases) == 1
    paths = write_cases(tmp_path, cases, subdir="imported_api")
    assert len(paths) == 1
    data = yaml.safe_load(paths[0].read_text(encoding="utf-8"))
    assert data["shells"]["before"][0]["step"] == "http_session_begin"
    assert data["shells"]["after"][0]["step"] == "http_session_end"


def test_postman_collection_minimal(tmp_path: Path):
    coll = {
        "info": {"name": "Demo", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
        "item": [
            {
                "name": "Ping",
                "request": {"method": "GET", "url": "https://httpbin.org/get"},
            },
            {
                "name": "Folder",
                "item": [
                    {
                        "name": "Nested",
                        "request": {
                            "method": "POST",
                            "url": {"raw": "https://httpbin.org/post", "host": ["httpbin", "org"], "path": ["post"]},
                        },
                    }
                ],
            },
        ],
    }
    spec = tmp_path / "coll.json"
    spec.write_text(__import__("json").dumps(coll), encoding="utf-8")
    cases, meta = import_spec_to_cases(spec)
    assert meta["kind"] == "postman"
    assert len(cases) == 2


def test_op_to_tc_dict_shape():
    tc = op_to_tc_dict(
        {"method": "GET", "path": "/x", "summary": "X", "status_expected": "200"},
        base_url="https://a.test",
        index=1,
    )
    assert tc["tag"] == "API"
    assert tc["platform"] == "http"
    assert tc["shells"]["case"][0]["params"]["url"] == "/x"


def test_with_intent_shell_writes_binding(tmp_path: Path):
    cases, meta = import_spec_to_cases(FIXTURE, methods=["get"], limit=1, with_intent_shell=True)
    assert meta["with_intent_shell"] is True
    assert cases[0]["shells"]["case"][0]["step"] == "intent_act"
    assert cases[0]["shells"]["case"][0]["params"]["channel"] == "http"
    paths = write_cases(tmp_path, cases, subdir="imported_api")
    assert paths
    data = yaml.safe_load(paths[0].read_text(encoding="utf-8"))
    assert data["shells"]["case"][0]["step"] == "intent_act"
    assert "_intent_binding" not in data
    binds = list((tmp_path / "bindings").glob("*.json"))
    assert binds, "应写入 Binding 占位"
