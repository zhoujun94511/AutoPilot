"""AutoPilot 启动入口（薄）。

用法：
    .venv/Scripts/python.exe run.py [工程目录] [关键字config目录]

实际逻辑在 autopilot.app；关键字定义默认用包内 autopilot/metadata/keyword_defs/。
"""

import os
import sys

# macOS Dock/菜单栏：尽早把进程显示名从「Python」改成应用名（须在 QApplication 前）
if sys.platform == "darwin":
    sys.argv[0] = "AutoPilot"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from autopilot.runtime.env_file import load_project_dotenv

    load_project_dotenv(os.path.dirname(os.path.abspath(__file__)))
except (ImportError, OSError, ValueError, TypeError, RuntimeError):
    pass

# noinspection PyPep8
from autopilot.app import run  # noqa: E402  (须先注入 sys.path)

if __name__ == "__main__":
    raise SystemExit(run())
