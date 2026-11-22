"""在与 pytest 相同的离屏对话框默认值下执行旧式 main 测试脚本。"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import os
from pathlib import Path
import runpy
import sys
import tempfile
from unittest.mock import patch


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="要执行的测试脚本路径")
    args = parser.parse_args()
    path = Path(args.path).resolve()
    if not path.is_file():
        parser.error(f"测试脚本不存在：{path}")
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["AUTOPILOT_NO_DOTENV"] = "1"
    from tests.headless_dialogs import isolate_main_window_startup, stub_modal_dialogs

    with ExitStack() as environment:
        config_dir = environment.enter_context(tempfile.TemporaryDirectory(prefix="autopilot_test_config_"))
        environment.enter_context(patch.dict(os.environ, {"AUTOPILOT_CONFIG_DIR": config_dir}))
        environment.enter_context(stub_modal_dialogs())
        if "MainWindow" in path.read_text(encoding="utf-8-sig"):
            environment.enter_context(isolate_main_window_startup())
        runpy.run_path(str(path), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
