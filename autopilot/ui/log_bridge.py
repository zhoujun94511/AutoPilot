"""把 logging 记录桥接到 GUI 控制台。

线程安全：worker 线程里 `logger.x()` → Handler.emit 在该线程被调用 → 通过 Qt 信号
（跨线程自动走队列连接）投递到 GUI 线程的槽里渲染，绝不在非 GUI 线程碰控件。

带 `extra={"ap_no_gui": True}` 的记录会被跳过——表示发起方（如 Console 自己的
log()/add_step()、引擎逐步结果）已在 GUI 渲染过，避免控制台重复出现。
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, pyqtSignal


class _Emitter(QObject):
    # (created 时间戳, levelname, 来源短名, message)——级别→状态/色由 Console 统一处理
    record = pyqtSignal(float, str, str, str)


class QtConsoleHandler(logging.Handler):
    """logging.Handler：经 Qt 信号把记录投递到 GUI 线程。

    # noinspection PyUnresolvedReferences
    用法：handler = QtConsoleHandler(); handler.emitter.record.connect(slot);
    runtime.log.attach_handler(handler)。带 ap_no_gui 的记录跳过（发起方已渲染过）。"""

    def __init__(self) -> None:
        super().__init__()
        # 前端控制台是「业务视图」：默认只收 INFO+；DEBUG 开发细节仅进 terminal/文件。
        # 排查时可由控制台「调试」开关临时降到 DEBUG。
        self.setLevel(logging.INFO)
        self.emitter = _Emitter()

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, "ap_no_gui", False):
            return
        # noinspection PyBroadException
        try:
            short = record.name.split(".", 1)[-1] if "." in record.name else record.name
            # noinspection PyUnresolvedReferences
            self.emitter.record.emit(record.created, record.levelname, short,
                                     record.getMessage())
        except Exception:
            pass
