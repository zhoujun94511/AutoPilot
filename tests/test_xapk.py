"""XAPK 解压与 Android 安装。"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from autopilot.mobile.xapk import (
    extract_xapk_apks,
    install_android_package,
    primary_apk_for_parse,
)


def test_extract_xapk_apks_nested(tmp_path: Path) -> None:
    xapk_path = tmp_path / "bundle.xapk"
    with zipfile.ZipFile(xapk_path, "w") as archive:
        archive.writestr("base.apk", b"base")
        archive.writestr("split/config.apk", b"split")
    apks = extract_xapk_apks(str(xapk_path), str(tmp_path / "work"))
    assert len(apks) == 2
    assert any(path.endswith("base.apk") for path in apks)


def test_install_android_package_xapk_uses_install_multiple(tmp_path: Path) -> None:
    xapk_path = tmp_path / "game.xapk"
    with zipfile.ZipFile(xapk_path, "w") as archive:
        archive.writestr("a.apk", b"a")
        archive.writestr("b.apk", b"b")

    calls: list[list[str]] = []

    def fake_run_adb(args, serial="", timeout=0):
        _ = serial, timeout
        calls.append(list(args))
        return "Success"

    with patch("autopilot.mobile.xapk.run_adb", fake_run_adb):
        out = install_android_package(str(xapk_path), serial="dev-1", replace=True)

    assert out == "Success"
    assert calls[0][0] == "install-multiple"
    assert "-r" in calls[0]
    assert "-t" in calls[0]
    assert len(calls[0]) == 5


def test_install_android_package_single_apk(tmp_path: Path) -> None:
    apk_path = tmp_path / "solo.apk"
    apk_path.write_bytes(b"apk")

    calls: list[list[str]] = []

    def fake_run_adb(args, serial="", timeout=0):
        _ = serial, timeout
        calls.append(list(args))
        return "Success"

    with patch("autopilot.mobile.xapk.run_adb", fake_run_adb):
        install_android_package(str(apk_path), serial="dev-1")

    assert calls[0] == ["install", "-t", str(apk_path)]


def test_primary_apk_for_parse_prefers_base(tmp_path: Path) -> None:
    xapk_path = tmp_path / "bundle.xapk"
    with zipfile.ZipFile(xapk_path, "w") as archive:
        archive.writestr("split.apk", b"x" * 20)
        archive.writestr("base.apk", b"y")

    with primary_apk_for_parse(str(xapk_path)) as parse_path:
        assert os.path.basename(parse_path) == "base.apk"


def test_extract_xapk_empty_raises(tmp_path: Path) -> None:
    xapk_path = tmp_path / "empty.xapk"
    with zipfile.ZipFile(xapk_path, "w") as archive:
        archive.writestr("readme.txt", b"no apk")
    with pytest.raises(Exception, match="未包含 APK"):
        extract_xapk_apks(str(xapk_path), str(tmp_path / "work"))
