"""阶段13.2 通用 Mock Server 中性替代回归（无外网，进程内 mock 服务）。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import httpx
import autopilot.keywords  # noqa: F401
from autopilot.keywords.registry import REGISTRY
from autopilot.keywords.context import ExecutionContext
from autopilot.keywords.http.mock_server import get_mock_server


def test_set_and_serve() -> bool:
    ctx = ExecutionContext()
    REGISTRY["http_cleanMock"].func(ctx)   # 清空起点
    REGISTRY["http_setMock"].func(ctx, serviceCode="order", operation="query",
                                  httpBody='{"ok":true}')
    base = ctx.get_var("mock_base_url")
    url = ctx.get_var("mock_last_url")
    # 桩可被真实 HTTP 命中
    r = httpx.get(url, timeout=5.0)
    ok = (base and url.endswith("/order/query")
          and r.status_code == 200 and r.text == '{"ok":true}')
    print("setMock 登记并服务桩:", "✅" if ok else "❌")
    return ok


def test_post_mock_records() -> bool:
    ctx = ExecutionContext()
    REGISTRY["http_cleanMock"].func(ctx)
    REGISTRY["http_setMock"].func(ctx, serviceCode="pay", operation="do", httpBody="OK")
    url = ctx.get_var("mock_last_url")
    out = REGISTRY["http_post_mock"].func(
        ctx, url=url, request='{"amount":100}',
        resp_code="code", resp_body="body", mock_info="seen")
    ok = (out.get("code") == 200 and out.get("body") == "OK"
          and out.get("seen") == '{"amount":100}')   # mock 回读到请求报文
    print("post_mock 发送并回读请求报文:", "✅" if ok else "❌")
    return ok


def test_clean() -> bool:
    ctx = ExecutionContext()
    REGISTRY["http_setMock"].func(ctx, serviceCode="x", operation="y", httpBody="z")
    url = ctx.get_var("mock_last_url")
    REGISTRY["http_cleanMock"].func(ctx)
    r = httpx.get(url, timeout=5.0)
    ok = r.status_code == 404 and len(get_mock_server().stubs) == 0
    print("cleanMock 清桩:", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([test_set_and_serve(), test_post_mock_records(), test_clean()])
    print("\n总结:", "✅ 通用 Mock Server 全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
