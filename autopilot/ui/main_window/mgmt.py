"""管理台入口 Mixin（AUD-2026-17）。

拆分：
- ``mgmt_session`` — 登录 / 会话 UI
- ``mgmt_runner_web`` — 本机 Runner / 打开网页
- ``mgmt_delivery`` — 工程上传与远程投递
- ``mgmt_errors`` — 共享 SESSION_ERRS

``window.py`` 仍只 ``from .mgmt import MgmtMixin``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .mgmt_session import MgmtSessionMixin

if TYPE_CHECKING:
    from .window import MainWindow
    _Base = MainWindow
else:
    _Base = MgmtSessionMixin


class MgmtMixin(_Base):
    """管理台门禁与远程投递入口（由 MainWindow 混入）。"""

    # 在 Mixin 上声明，避免「仅在方法内赋值」的实例特性告警；MainWindow.__init__ 也会置 None。
    _mgmt_http_worker = None
