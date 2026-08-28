"""API 测试能力：Session / Auth / Assert / Env（本地 HTTPServer，无外网）。"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import cast

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autopilot.keywords.context import ExecutionContext
from autopilot.keywords.registry import REGISTRY, KeywordError
from autopilot.keywords.http import session as http_session
from autopilot.keywords.http import auth as http_auth
from autopilot.keywords.http import assert_kw as http_assert
from autopilot.keywords.http import env as http_env
from autopilot.keywords.http import client as http_client


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_a):
        pass

    def _read(self) -> bytes:
        n = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(n) if n else b""

    def _json(self, code: int, obj: dict) -> None:
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/secure"):
            auth = self.headers.get("Authorization", "")
            key = self.headers.get("X-API-Key", "")
            if auth.startswith("Bearer good") or key == "k-1":
                self._json(200, {"ok": True})
            else:
                self._json(401, {"ok": False})
            return
        if self.path.startswith("/login"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie", "sid=abc123; Path=/")
            self.end_headers()
            self.wfile.write(b'{"token":"t1"}')
            return
        if self.path.startswith("/me"):
            cookie = self.headers.get("Cookie", "")
            if "sid=abc123" in cookie:
                self._json(200, {"user": "u1"})
            else:
                self._json(401, {"user": None})
            return
        self._json(200, {"msg": "pong"})

    def do_POST(self):  # noqa: N802
        self._read()
        self._json(201, {"created": True})

    def do_PATCH(self):  # noqa: N802
        self._read()
        self._json(200, {"patched": True})

    def do_HEAD(self):  # noqa: N802
        self.send_response(204)
        self.end_headers()

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Allow", "GET,POST,PATCH,HEAD,OPTIONS")
        self.end_headers()


def _serve():
    srv = HTTPServer(("127.0.0.1", 0), cast(type[BaseHTTPRequestHandler], _Handler))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_keywords_registered():
    for kid in (
        "http_session_begin",
        "http_session_end",
        "http_patch",
        "http_head",
        "http_options",
        "http_set_auth_bearer",
        "http_assert_status",
        "json_assert_schema",
        "api_env_use",
    ):
        assert kid in REGISTRY, kid


def test_session_cookie_chain():
    srv = _serve()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    ctx = ExecutionContext()
    http_session.http_session_begin(ctx, base_url=base)
    out = http_client.http_get(ctx, url="/login", resp_code="c", resp_body="b")
    assert out["c"] == 200
    me = http_client.http_get(ctx, url="/me", resp_code="c2", resp_body="b2")
    assert me["c2"] == 200
    assert "u1" in me["b2"]
    http_assert.http_assert_status(ctx, expected="200")
    http_session.http_session_end(ctx)
    assert ctx.http_session is None
    srv.shutdown()


def test_patch_head_options_and_proxy_ephemeral():
    srv = _serve()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    ctx = ExecutionContext()
    p = http_client.http_patch(ctx, url=f"{base}/x", request={"a": 1}, resp_code="c")
    assert p["c"] == 200
    h = http_client.http_head(ctx, url=f"{base}/x", resp_code="c")
    assert h["c"] == 204
    o = http_client.http_options(ctx, url=f"{base}/x", resp_code="c", resp_header="hdr")
    assert o["c"] == 204
    assert "allow" in {k.lower() for k in o["hdr"]}
    # 代理配置对象可生成；无效代理不在本测发请求
    proxy = http_client.http_set_proxy(ctx, host="127.0.0.1", port="9", out_proxy="px")
    assert proxy["px"]["host"] == "127.0.0.1"
    srv.shutdown()


def test_auth_bearer_and_apikey():
    srv = _serve()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    ctx = ExecutionContext()
    http_session.http_session_begin(ctx, base_url=base)
    http_auth.http_set_auth_bearer(ctx, token="good-token")
    r = http_client.http_get(ctx, url="/secure", resp_code="c")
    assert r["c"] == 200
    http_session.http_session_end(ctx)

    ctx2 = ExecutionContext()
    http_session.http_session_begin(ctx2, base_url=base)
    http_auth.http_set_auth_apikey(ctx2, name="X-API-Key", value="k-1")
    r2 = http_client.http_get(ctx2, url="/secure", resp_code="c")
    assert r2["c"] == 200
    http_session.http_session_end(ctx2)
    srv.shutdown()


def test_assert_status_time_schema_body(tmp_path: Path):
    srv = _serve()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    ctx = ExecutionContext()
    ctx.project_path = str(tmp_path)
    http_client.http_get(ctx, url=f"{base}/ping", resp_code="c", response_time="rt")
    http_assert.http_assert_status(ctx, expected="200-299")
    http_assert.http_assert_time_lt(ctx, max_ms="60000")
    http_assert.http_assert_body_contains(ctx, text="pong")
    schema = {"type": "object", "properties": {"msg": {"type": "string"}}, "required": ["msg"]}
    (tmp_path / "s.json").write_text(json.dumps(schema), encoding="utf-8")
    http_assert.json_assert_schema(ctx, schema="s.json")
    try:
        http_assert.http_assert_status(ctx, expected="500")
        raise AssertionError("should fail")
    except KeywordError:
        pass
    srv.shutdown()


def test_api_env_use(tmp_path: Path):
    path = tmp_path / "api_env.yaml"
    path.write_text(
        "profiles:\n  dev:\n    base_url: http://example.local\n    vars:\n      token: t-dev\n",
        encoding="utf-8",
    )
    ctx = ExecutionContext()
    ctx.project_path = str(tmp_path)
    http_env.api_env_use(ctx, profile="dev")
    assert ctx.get_var("base_url") == "http://example.local"
    assert ctx.get_var("token") == "t-dev"
    assert ctx.get_var("api_env_profile") == "dev"


def test_api_env_use_falls_back_to_injected_profile(tmp_path: Path):
    (tmp_path / "api_env.yaml").write_text(
        "profiles:\n  staging:\n    base_url: http://stg.local\n    vars:\n      token: t-stg\n",
        encoding="utf-8",
    )
    ctx = ExecutionContext()
    ctx.set_var("__project_path__", str(tmp_path))
    ctx.set_var("__http_env_profile__", "staging")
    http_env.api_env_use(ctx)
    assert ctx.get_var("base_url") == "http://stg.local"
    assert ctx.get_var("token") == "t-stg"


def test_http_session_begin_uses_ctx_base_url():
    ctx = ExecutionContext()
    ctx.set_var("base_url", "https://api.example.test")
    http_session.http_session_begin(ctx)
    assert ctx.http_session.base_url == "https://api.example.test"
    http_session.http_session_end(ctx)
