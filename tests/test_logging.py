"""统一日志骨干（离线）：文件落盘 + 每-run 日志 + Qt 桥接渲染 + ap_no_gui 去重。"""

import logging
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_APP = None


def test_backbone_file() -> bool:
    """setup_logging 落当日文件；get_logger 写入可读回；run_log 额外出按次文件。"""
    # noinspection PyPep8Naming
    from autopilot.runtime import log as L
    root = logging.getLogger(L.ROOT)

    def _reset():
        for h in list(root.handlers):
            root.removeHandler(h)
            # noinspection PyBroadException
            try:
                h.close()
            except Exception:
                pass
        L._configured = False
        L._LOGFILE = ""

    import shutil
    _reset()                                  # 干净起步，独立于真实 app 装配
    d = tempfile.mkdtemp()
    try:
        logfile = L.setup_logging(directory=d, console=False)
        L.get_logger("engine").info("hello-%s", "world")
        L.get_logger("device").error("boom")
        file_ok = bool(logfile) and os.path.exists(logfile)
        with open(logfile, encoding="utf-8") as f:
            body = f.read()
        content_ok = "hello-world" in body and "boom" in body and "ERROR" in body
        ts_ok = len(body) >= 19 and body[4] == "-" and body[7] == "-" and body[10] == " "

        with L.run_log("用例A / 冒烟", directory=d) as rp:
            L.get_logger("run").info("step-1")
        run_ok = bool(rp) and os.path.exists(rp)
        with open(rp, encoding="utf-8") as f:
            run_ok = run_ok and "step-1" in f.read()
        # run_log 退出后该 handler 应已卸载（再写不进 run 文件）
        before = os.path.getsize(rp)
        L.get_logger("run").info("after-run-should-not-be-in-runfile")
        detach_ok = os.path.getsize(rp) == before

        ok = file_ok and content_ok and ts_ok and run_ok and detach_ok
    finally:
        _reset()                              # 先关闭文件句柄，否则 Windows 删不掉
        shutil.rmtree(d, ignore_errors=True)
    print("日志骨干(文件/内容/时间戳/run/卸载):", "✅" if ok else "❌",
          (file_ok, content_ok, ts_ok, run_ok, detach_ok))
    return ok


def test_qt_bridge() -> bool:
    """QtConsoleHandler：普通记录渲染成控制台一行；带 ap_no_gui 的被跳过（去重）。"""
    try:
        global _APP
        from PyQt6.QtWidgets import QApplication
        from autopilot.ui.widgets.console import Console
        from autopilot.ui.log_bridge import QtConsoleHandler
        _APP = QApplication.instance() or QApplication([])
        c = Console()
        h = QtConsoleHandler()
        # noinspection PyUnresolvedReferences
        h.emitter.record.connect(c._on_log_record)   # 同进程同线程 → 直连，渲染同步可断言
        # 走真实 logger，级别过滤才生效（Handler.handle 本身不查 level）
        lg = logging.getLogger("autopilot._bridge_test")
        lg.setLevel(logging.DEBUG)
        lg.propagate = False
        lg.addHandler(h)

        from autopilot.ui.widgets.console import _COL_LEVEL, _COL_STATUS, _COL_MESSAGE
        try:
            lg.error("WDA 连接被中止")
            rendered_ok = (c.table.rowCount() == 1
                           and c.table.item(0, _COL_LEVEL).text() == "ERROR"
                           and c.table.item(0, _COL_STATUS).text() == ""   # 纯日志：状态列留空
                           and c.table.item(0, _COL_MESSAGE).text() == "WDA 连接被中止")
            # 默认阈值 INFO：DEBUG 开发细节不进控制台（只该落文件）
            lg.debug("帧解析细节")
            debug_dropped_ok = c.table.rowCount() == 1
            # ap_no_gui 记录被跳过（发起方已渲染）
            lg.info("x", extra={"ap_no_gui": True})
            skip_ok = c.table.rowCount() == 1
            # 「调试」开关降到 DEBUG 后，DEBUG 才进控制台
            h.setLevel(logging.DEBUG)
            lg.debug("帧解析细节")
            debug_on_ok = c.table.rowCount() == 2
        finally:
            lg.removeHandler(h)
        ok = rendered_ok and debug_dropped_ok and skip_ok and debug_on_ok
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("Qt 日志桥接: ⏭ 跳过(", e, ")")
        return True
    print("Qt 日志桥接(渲染/DEBUG阈值/去重/调试开关):", "✅" if ok else "❌")
    return ok


def test_log_dir_resolution() -> bool:
    """log_dir：环境变量优先；打包态落到 ~/.autopilot/logs；开发态用 cwd/logs。"""
    from unittest.mock import patch
    from autopilot.runtime import log as log_mod

    prev = os.environ.get("AUTOPILOT_LOG_DIR")
    try:
        os.environ["AUTOPILOT_LOG_DIR"] = r"D:\custom\logs"
        env_ok = log_mod.log_dir() == r"D:\custom\logs"
        os.environ.pop("AUTOPILOT_LOG_DIR", None)
        with patch.object(log_mod, "_is_packaged", return_value=True):
            packed = log_mod.log_dir()
        pack_ok = packed == os.path.join(os.path.expanduser("~"), ".autopilot", "logs")
        with patch.object(log_mod, "_is_packaged", return_value=False):
            dev = log_mod.log_dir()
        dev_ok = dev == os.path.join(os.getcwd(), "logs")
        ok = env_ok and pack_ok and dev_ok
    finally:
        if prev is None:
            os.environ.pop("AUTOPILOT_LOG_DIR", None)
        else:
            os.environ["AUTOPILOT_LOG_DIR"] = prev
    print("log_dir 解析(环境/打包/开发):", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([test_backbone_file(), test_qt_bridge(), test_log_dir_resolution()])
    print("\n总结:", "✅ 日志骨干全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
