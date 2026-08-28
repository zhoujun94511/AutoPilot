"""链路 3：AI 辅助编写 — NL 驱动会话 → 传统关键字用例。

正式主路径为会话驱动编写（observe-act），生成物回归链路 1。
"""

from __future__ import annotations

from .agent import run_session_authoring
from .pipeline import AuthoringResult, generate_traditional_case
from .session_bootstrap import prepare_authoring_session, release_authoring_session

__all__ = [
    "AuthoringResult",
    "generate_traditional_case",
    "prepare_authoring_session",
    "release_authoring_session",
    "run_session_authoring",
]
