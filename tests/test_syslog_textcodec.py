"""syslog 文本解码：GBK 进程名 + UTF-8 正文混排。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autopilot.mobile.ios.monkey.device_logs.textcodec import (
    decode_syslog_line,
    decode_syslog_text,
)


def test_gbk_process_name() -> bool:
    # 爱投屏 in GBK
    proc = "爱投屏".encode("gbk")
    raw = b"2026-07-05 19:04:45.822873 " + proc + b"{CoreFoundation}[1017] <DEBUG>: hello"
    text = decode_syslog_line(raw)
    ok = "爱投屏" in text and "CoreFoundation" in text and "\ufffd" not in text
    print("GBK 进程名:", "✅" if ok else "❌", text[:80])
    return ok


def test_utf8_passthrough() -> bool:
    raw = "2026-07-05 19:04:45.822873 locationd{CoreFoundation}[76] <DEBUG>: 中文消息".encode(
        "utf-8")
    text = decode_syslog_line(raw)
    ok = "locationd" in text and "中文消息" in text
    print("UTF-8 直通:", "✅" if ok else "❌")
    return ok


def test_real_ostrace_sample() -> bool:
    sample = Path(r"d:\plantscope\AIID\logs\ios_monkey\20260705_190444\device\syslog.ostrace.txt")
    if not sample.is_file():
        print("真实样本: ⏭ 跳过(无文件)")
        return True
    data = sample.read_bytes()
    # 取含 [1017] 的一行
    line = next((ln for ln in data.splitlines() if b"[1017]" in ln and b"CoreFoundation" in ln), b"")
    if not line:
        print("真实样本: ⏭ 跳过(无匹配行)")
        return True
    text = decode_syslog_line(line)
    ok = "爱投屏" in text and "\ufffd" not in text
    print("真实 ostrace 行:", "✅" if ok else "❌", text[:90])
    return ok


def test_multiline_text() -> bool:
    proc = "爱投屏".encode("gbk")
    blob = (
        b"2026-07-05 19:04:45.822873 " + proc + b"{CoreFoundation}[1017] <DEBUG>: a\n"
        b"2026-07-05 19:04:45.822988 locationd{CoreFoundation}[76] <DEBUG>: b\n"
    )
    text = decode_syslog_text(blob)
    ok = text.count("爱投屏") == 1 and "locationd" in text and text.count("\n") >= 2
    print("多行解码:", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([
        test_gbk_process_name(),
        test_utf8_passthrough(),
        test_real_ostrace_sample(),
        test_multiline_text(),
    ])
    print("\n总结:", "✅ syslog 解码全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
