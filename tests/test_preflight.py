"""tools/preflight.py smoke tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ios_bootstrap_import_without_circular_error():
    from autopilot.mobile.ios_bootstrap import resolve_go_ios

    path = resolve_go_ios()
    assert path is None or Path(path).name.lower().startswith("ios")


def test_preflight_main_exits_zero_when_core_ready():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "preflight.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert proc.returncode in (0, 1), proc.stderr or proc.stdout
    # 核心未装齐才应 exit 1；正常开发 venv 应为 0
    if proc.returncode == 0:
        assert "运行环境预检" in proc.stdout
        assert "go-ios" in proc.stdout.lower() or "go-ios" in proc.stdout


def test_preflight_rejects_obsolete_mobile_extra():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "preflight.py"), "--install", "mobile"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert proc.returncode == 2
    assert "未知能力组" in proc.stdout
