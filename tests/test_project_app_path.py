"""工程相对路径 / 跨机安装包重定位。"""

from __future__ import annotations

import os
import tempfile

import pytest

from autopilot.runtime.paths import (
    join_project,
    project_relative_or_abs,
    resolve_project_file,
    safe_path_under_project,
    to_posix,
)


def test_join_and_relative() -> None:
    with tempfile.TemporaryDirectory() as d:
        apk = os.path.join(d, "apps", "demo.apk")
        os.makedirs(os.path.dirname(apk), exist_ok=True)
        open(apk, "wb").write(b"x")
        assert join_project(d, "apps/demo.apk") == os.path.normpath(apk)
        assert project_relative_or_abs(d, apk) == "apps/demo.apk"
        outside = os.path.join(tempfile.gettempdir(), "elsewhere.apk")
        assert project_relative_or_abs(d, outside) == os.path.normpath(outside)


def test_resolve_relative_and_cross_machine_abs() -> None:
    with tempfile.TemporaryDirectory() as d:
        apk = os.path.join(d, "apps", "demo.apk")
        os.makedirs(os.path.dirname(apk), exist_ok=True)
        open(apk, "wb").write(b"x")

        # 相对工程根
        got = resolve_project_file(d, "apps/demo.apk")
        assert os.path.normpath(got) == os.path.normpath(apk)

        # 跨机：绝对路径不存在 → 按 basename / 尾段重定位
        ghost = r"D:\other-machine\MyProj\apps\demo.apk"
        if os.name != "nt":
            ghost = "/other-machine/MyProj/apps/demo.apk"
        assert not os.path.exists(ghost)
        got2 = resolve_project_file(d, ghost)
        assert os.path.normpath(got2) == os.path.normpath(apk)

        # 同名文件在工程内唯一
        ghost2 = os.path.join(tempfile.gettempdir(), "nope", "demo.apk")
        got3 = resolve_project_file(d, ghost2)
        assert os.path.normpath(got3) == os.path.normpath(apk)


def test_resolve_apk_path_uses_project() -> None:
    from autopilot.keywords.mobile.session import _resolve_apk_path
    from autopilot.keywords.registry import KeywordError

    with tempfile.TemporaryDirectory() as d:
        apk = os.path.join(d, "apps", "a.apk")
        os.makedirs(os.path.dirname(apk), exist_ok=True)
        open(apk, "wb").write(b"x")
        assert _resolve_apk_path("apps/a.apk", d) == os.path.normpath(apk)

        ghost = r"Z:\phantom\apps\a.apk" if os.name == "nt" else "/phantom/apps/a.apk"
        assert _resolve_apk_path(ghost, d) == os.path.normpath(apk)

        try:
            _resolve_apk_path("apps/missing.apk", d)
            raise AssertionError("expected KeywordError")
        except KeywordError:
            pass


def test_safe_path_under_project_blocks_absolute() -> None:
    with tempfile.TemporaryDirectory() as d:
        outside = os.path.join(tempfile.gettempdir(), "outside-only.json")
        with open(outside, "w", encoding="utf-8") as f:
            f.write("{}")
        with pytest.raises(ValueError):
            safe_path_under_project(d, outside)


def test_to_posix_storage() -> None:
    assert to_posix(r"apps\a.apk") == "apps/a.apk"
