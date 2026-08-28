"""Platform Web 引擎链路冒烟：Job → Runner base_vars → __web_engine__。"""

from __future__ import annotations

from pathlib import Path


def _platform_root() -> Path | None:
    root = Path(__file__).resolve().parents[1].parent / "Autopilot-Platform"
    return root if root.is_dir() else None


def test_runner_execute_injects_web_engine_selenium():
    from autopilot.runner import execute as ide_exec

    src = Path(ide_exec.__file__).read_text(encoding="utf-8")
    assert '__web_engine__' in src
    assert 'web_engine' in src
    assert "plat == \"web\"" in src or "plat == 'web'" in src


def test_platform_runner_execute_web_engine_parity():
    plat = _platform_root()
    if plat is None:
        return
    ide_src = (
        Path(__file__).resolve().parents[1] / "autopilot" / "runner" / "execute.py"
    ).read_text(encoding="utf-8")
    plat_src = (plat / "autopilot_platform" / "runner" / "execute.py").read_text(
        encoding="utf-8"
    )
    for needle in (
        'base_vars["__web_engine__"]',
        'getattr(job, "web_engine"',
        '("selenium", "playwright")',
        "engine={eng}",
    ):
        assert needle in ide_src, f"IDE runner 缺 {needle!r}"
        assert needle in plat_src, f"Platform runner 缺 {needle!r}"


def test_platform_job_schema_has_web_engine_field():
    plat = _platform_root()
    if plat is None:
        return
    schemas = (plat / "autopilot_platform" / "core" / "schemas.py").read_text(
        encoding="utf-8"
    )
    assert "web_engine" in schemas
    assert "playwright" in schemas
