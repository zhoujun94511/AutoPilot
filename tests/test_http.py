"""阶段4 Http/协议关键字测试（本地 HTTP 服务，无外网）。

验证：http_get/http_post + OUT 回写、JSON jsonpath 取值/校验/存在、XML xpath 取值/校验、add_header。
"""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from autopilot.keywords.context import ExecutionContext
from autopilot.model.testcase import TestCase, Step, ParamValue
from autopilot.engine import Executor, FaultStrategy


# noinspection PyPep8Naming
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_a):  # 静音
        pass

    def do_GET(self):
        body = json.dumps({"msg": "pong", "data": {"id": 42, "name": "auto"}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"echo": ' + (raw or b'null') + b"}")


def run_server():
    # noinspection PyTypeChecker
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


XML_SAMPLE = "<root><user id='42'><name>auto</name></user></root>"


def test_kept_impls() -> bool:
    """新补的保留项：MQ_get_UID / Hessian 取值·校验 / Mock 桩模式，且已脱离灰显。"""
    from autopilot.keywords.http.client import (
        mq_get_uid, get_hessian_field, verify_hessian_field,
        http_set_mock_mode, http_get_mock_mode)
    from autopilot.keywords.registry import KeywordError
    from autopilot.metadata import load_catalog
    ctx = ExecutionContext()
    uid = mq_get_uid(ctx, UID="u")["u"]
    uid_ok = len(uid) == 48 and uid.isalnum()
    hv = get_hessian_field(ctx, text="a=1;b=hello\nc=3", fieldName="b", varFieldValue="v")["v"]
    hv_ok = hv == "hello"
    verify_hessian_field(ctx, text="x=1;y=2", expect="y=2", mode="模糊匹配")   # 不抛=通过
    raised = False
    try:
        verify_hessian_field(ctx, text="x=1", expect="zzz", mode="精确匹配")
    except KeywordError:
        raised = True
    http_set_mock_mode(ctx, mode="exception")
    mode_ok = http_get_mock_mode(ctx, mode="m")["m"] == "exception"
    # 实现后不再灰显
    cat = load_catalog(None)
    ungrey = not any(cat.get(k) and cat.get(k).unsupported
                     for k in ("MQ_get_UID", "getHessianField", "verifyHessianField",
                               "http_startMockStubServer", "http_setMockMode"))
    ok = uid_ok and hv_ok and raised and mode_ok and ungrey
    print("保留项实现(UID/Hessian取值校验/Mock模式/脱离灰显):", "✅" if ok else "❌")
    return ok


def main() -> int:
    kept_ok = test_kept_impls()
    srv = run_server()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    ctx = ExecutionContext()
    tc = TestCase(name="http_demo")
    tc.case.steps = [
        Step("http_get", "GET", params=[
            ParamValue("url", base + "/ping"), ParamValue("encode", "UTF-8"),
            ParamValue("cache", "false"),
            ParamValue("resp_code", "code"), ParamValue("resp_body", "body"),
            ParamValue("response_time", "rt")]),
        Step("json_get_json_value_byjsonpath", "取msg", params=[
            ParamValue("json", "${body}"), ParamValue("jsonpath", "$.msg"),
            ParamValue("value", "msg")]),
        Step("json_get_json_value_byjsonpath", "取id", params=[
            ParamValue("json", "${body}"), ParamValue("jsonpath", "$.data.id"),
            ParamValue("value", "uid")]),
        Step("json_verify_json_value_ByJsonPath", "校验name", params=[
            ParamValue("json", "${body}"), ParamValue("jsonpath", "$.data.name"),
            ParamValue("text", "auto"), ParamValue("matched", "是")]),
        Step("json_exist_key_byjsonpath", "msg存在", params=[
            ParamValue("json", "${body}"), ParamValue("jsonpath", "$.msg"),
            ParamValue("matched", "是")]),
        Step("http_add_header", "建头", params=[
            ParamValue("key", "X-Token"), ParamValue("value", "abc"),
            ParamValue("reference", "hdr")]),
        Step("http_post", "POST带头", params=[
            ParamValue("url", base + "/submit"), ParamValue("encode", "UTF-8"),
            ParamValue("cache", "false"), ParamValue("header", "${hdr}"),
            ParamValue("request", "hello"), ParamValue("resp_code", "pcode"),
            ParamValue("resp_body", "pbody")]),
        Step("xml_get_xml_value", "取xml name", params=[
            ParamValue("xml", XML_SAMPLE), ParamValue("xpath", "//user/name/text()"),
            ParamValue("value", "xname"), ParamValue("separator", ",")]),
        Step("xml_verify_xml_value", "校验xml id", params=[
            ParamValue("xml", XML_SAMPLE), ParamValue("xpath", "//user/@id"),
            ParamValue("text", "42"), ParamValue("matched", "是"),
            ParamValue("mode", "精确"), ParamValue("separator", ",")]),
    ]

    res = Executor(ctx, fault_strategy=FaultStrategy.CONTINUE).run_testcase(tc)
    for r in res.results:
        print(f"  [{r.status:6}] {r.keyword_id:34} {r.comment} {r.message}")

    checks = {
        "GET code=200": ctx.get_var("code") == 200,
        "json msg": ctx.get_var("msg") == "pong",
        "json id=42": str(ctx.get_var("uid")) == "42",
        "POST code=201": ctx.get_var("pcode") == 201,
        "POST echo含hello": "hello" in str(ctx.get_var("pbody")),
        "xml name=auto": ctx.get_var("xname") == "auto",
        "无FAIL": res.counts().get("FAIL", 0) == 0,
    }
    print("  关键变量:", {k: ctx.get_var(k) for k in ("code", "msg", "uid", "pcode", "xname")})
    ok = all(checks.values()) and kept_ok
    for k, v in checks.items():
        if not v:
            print("   ❌", k)
    print("\n总结:", "✅ 全部通过" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
