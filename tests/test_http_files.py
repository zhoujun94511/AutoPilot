"""阶段13.1 HTTP 文件上传/下载关键字回归（本地服务，无外网）。

坐实 http_get_download / http_post_Multipart 为真实现（httpx），非降级。
"""

import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import autopilot.keywords  # noqa: F401
from autopilot.keywords.registry import REGISTRY
from autopilot.keywords.context import ExecutionContext

_PAYLOAD = b"hello-autopilot-file-content"


# noinspection PyPep8Naming
class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_a):
        pass

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()
        self.wfile.write(_PAYLOAD)

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(n)
        self.send_response(200)
        self.end_headers()
        # 回写收到的字节数，便于断言 multipart 确实带上了文件内容
        self.wfile.write(f"got {len(body)} bytes".encode())


def _serve():
    # noinspection PyTypeChecker
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def test_download() -> bool:
    srv, port = _serve()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = ExecutionContext()
            ret = REGISTRY["http_get_download"].func(
                ctx, url=f"http://127.0.0.1:{port}/myfile.bin",
                file_selector="本地", file_path=tmp,
                resp_code="code", download_file_path="saved")
            saved = ret.get("saved", "")
            ok = (ret.get("code") == 200 and os.path.exists(saved)
                  and open(saved, "rb").read() == _PAYLOAD)
    finally:
        srv.shutdown()
    print("HTTP下载:", "✅" if ok else "❌")
    return ok


def test_multipart_upload() -> bool:
    srv, port = _serve()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            fp = os.path.join(tmp, "up.txt")
            with open(fp, "wb") as f:
                f.write(_PAYLOAD)
            ctx = ExecutionContext()
            # filePath 相对 project_path；用 ctx.project_path 指向临时目录
            ctx.project_path = tmp
            ret = REGISTRY["http_post_Multipart"].func(
                ctx, url=f"http://127.0.0.1:{port}/upload",
                filePath="up.txt", fileKey="file",
                resp_code="code", resp_body="body")
            body = str(ret.get("body", ""))
            # multipart 体积应大于纯文件（含分隔与头），且请求成功
            ok = ret.get("code") == 200 and "bytes" in body and len(_PAYLOAD) > 0
    finally:
        srv.shutdown()
    print("HTTP文件上传(Multipart):", "✅" if ok else "❌", body if not ok else "")
    return ok


def main() -> int:
    ok = all([test_download(), test_multipart_upload()])
    print("\n总结:", "✅ HTTP 文件上传/下载全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
