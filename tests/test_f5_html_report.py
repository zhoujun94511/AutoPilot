"""UX-P2-002：F5 单用例运行应生成 HTML 报告。"""

from __future__ import annotations

import re
from pathlib import Path

RUN_PY = Path(__file__).resolve().parents[1] / "autopilot" / "ui" / "main_window" / "run.py"


def _method_block(text: str, name: str) -> str:
    m = re.search(rf"def {name}\(self\)[\s\S]*?(?=\n def |\Z)", text)
    assert m, f"{name} 未找到"
    return m.group(0)


def test_f5_run_current_case_enables_html_report():
    block = _method_block(RUN_PY.read_text(encoding="utf-8"), "run_current_case")
    assert "report=True" in block
    assert "report=False" not in block


def test_single_step_debug_still_skips_report():
    block = _method_block(RUN_PY.read_text(encoding="utf-8"), "run_selected_step")
    assert "report=False" in block
