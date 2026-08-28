"""iOS 已装应用枚举：CLI 非 JSON 不得再阻断 AI 编写。"""

from __future__ import annotations

import json
import subprocess

import pytest

from autopilot.authoring import app_resolve as ar
from autopilot.authoring.contract import AuthoringError


def test_extract_json_object_tolerates_log_noise():
    blob = ar._extract_json_object('WARN\n{"com.demo.app": {"CFBundleDisplayName": "Demo"}}\n')
    data = json.loads(blob)
    assert "com.demo.app" in data


def test_apps_from_pmd3_dict_reads_display_name():
    apps = ar._apps_from_pmd3_dict(
        {
            "com.birds.song.identifier.ai": {
                "CFBundleDisplayName": "BirdScope",
                "CFBundleName": "BirdScope",
            },
            "": {"CFBundleDisplayName": "skip"},
        }
    )
    assert [(a.package_name, a.app_label) for a in apps] == [
        ("com.birds.song.identifier.ai", "BirdScope")
    ]


def test_list_ios_apps_prefers_inproc(monkeypatch):
    monkeypatch.setattr(
        ar,
        "_list_ios_apps_inproc",
        lambda udid: [ar.InstalledApp("com.demo.app", "Demo", "ios")],
    )
    monkeypatch.setattr(
        ar,
        "_list_ios_apps_cli",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应再走 CLI")),
    )
    apps = ar.list_ios_installed_apps("UDID")
    assert apps[0].app_label == "Demo"


def test_list_ios_apps_cli_user_then_goios_on_non_json(monkeypatch):
    monkeypatch.setattr(ar, "_list_ios_apps_inproc", lambda udid: None)

    def fake_cli(_udid, *, app_type="User"):
        _ = _udid, app_type
        return [], "返回非 JSON：Usage: python -m pymobiledevice3"

    monkeypatch.setattr(ar, "_list_ios_apps_cli", fake_cli)
    monkeypatch.setattr(
        ar,
        "_list_ios_apps_goios",
        lambda udid: [ar.InstalledApp("com.birds.song.identifier.ai", "BirdScope", "ios")],
    )
    apps = ar.list_ios_installed_apps("UDID")
    assert apps[0].package_name == "com.birds.song.identifier.ai"


def test_list_ios_apps_cli_parses_noisy_stdout(monkeypatch):
    payload = b'boot log\n{"com.a.app": {"CFBundleDisplayName": "A"}}\n'

    def fake_run(cmd, **kwargs):
        assert "--type" in cmd and "User" in cmd
        assert "text" not in kwargs
        return subprocess.CompletedProcess(cmd, 0, payload, b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    apps, err = ar._list_ios_apps_cli("UDID", app_type="User")
    assert err == ""
    assert apps[0].app_label == "A"


def test_list_ios_apps_raises_actionable_error(monkeypatch):
    monkeypatch.setattr(ar, "_list_ios_apps_inproc", lambda udid: None)
    monkeypatch.setattr(ar, "_list_ios_apps_cli", lambda *a, **k: ([], "返回非 JSON：oops"))
    monkeypatch.setattr(ar, "_list_ios_apps_goios", lambda udid: [])
    with pytest.raises(AuthoringError, match="无法列举 iOS 应用：返回非 JSON"):
        ar.list_ios_installed_apps("UDID")


def test_goios_line_parser(monkeypatch):
    class _Proc:
        returncode = 0
        stdout = (
            b"com.birds.song.identifier.ai BirdScope 1.4.1\n"
            b"xyz.plantin.app PlantIn 2.0.0\n"
        )
        stderr = b""

    monkeypatch.setattr(
        "autopilot.mobile.ios_bootstrap.resolve_go_ios",
        lambda: "ios.exe",
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc())
    apps = ar._list_ios_apps_goios("UDID")
    assert {a.app_label: a.package_name for a in apps} == {
        "BirdScope": "com.birds.song.identifier.ai",
        "PlantIn": "xyz.plantin.app",
    }


def test_birdscope_alias_resolves_when_installed(monkeypatch):
    from autopilot.authoring.system_app_aliases import alias_entry

    entry = alias_entry("ios", "BirdScope")
    assert entry is not None
    assert "com.birds.song.identifier.ai" in entry.packages

    monkeypatch.setattr(
        ar,
        "list_ios_installed_apps",
        lambda udid="": [
            ar.InstalledApp("com.birds.song.identifier.ai", "BirdScope", "ios"),
        ],
    )
    hit = ar.resolve_installed_app("ios", udid="UDID", app_name="BirdScope")
    assert hit.package_name == "com.birds.song.identifier.ai"
