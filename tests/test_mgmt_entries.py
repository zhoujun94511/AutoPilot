"""制品可执行入口清单：仅用例/套件/计划。"""

from __future__ import annotations

from autopilot.mgmt.entries import list_runnable_entries, list_runnable_entries_in_zip
from autopilot.mgmt.pack import zip_project_dir


def test_list_runnable_entries_skips_noise(tmp_path):
    root = tmp_path / "AIID"
    root.mkdir()
    (root / "TEST001.tc.yaml").write_text("name: t1\n", encoding="utf-8")
    (root / "TEST002.tc.yaml").write_text("name: t2\n", encoding="utf-8")
    (root / "smoke.ts.yaml").write_text("name: s\n", encoding="utf-8")
    (root / "nightly.tp.yaml").write_text("name: p\nmembers: []\n", encoding="utf-8")
    (root / "config").mkdir()
    (root / "config" / "DataConfig.properties").write_text("k=v\n", encoding="utf-8")
    (root / "images").mkdir()
    (root / "images" / "btn.png").write_bytes(b"\x89PNG")
    (root / "apk").mkdir()
    (root / "apk" / "app.apk").write_bytes(b"APK")
    (root / "lib.map.yaml").write_text("name: m\n", encoding="utf-8")

    entries = list_runnable_entries(str(root))
    paths = [e["path"] for e in entries]
    assert paths == [
        "TEST001.tc.yaml",
        "TEST002.tc.yaml",
        "smoke.ts.yaml",
        "nightly.tp.yaml",
    ]
    assert all(e["kind"] in ("case", "suite", "plan") for e in entries)
    assert not any("apk" in p or "images" in p or "map" in p for p in paths)


def test_list_runnable_entries_in_zip_strips_arcroot(tmp_path):
    root = tmp_path / "AIID"
    root.mkdir()
    (root / "TEST001.tc.yaml").write_text("name: t1\n", encoding="utf-8")
    (root / "TEST003.tc.yaml").write_text("name: t3\n", encoding="utf-8")
    data = zip_project_dir(str(root))
    entries = list_runnable_entries_in_zip(data)
    assert [e["path"] for e in entries] == ["TEST001.tc.yaml", "TEST003.tc.yaml"]
    assert [e["name"] for e in entries] == ["TEST001", "TEST003"]


def test_load_entry_cases_filters(tmp_path):
    from autopilot.engine import load_entry_cases

    root = tmp_path / "proj"
    root.mkdir()
    minimal = (
        "type: testcase\n"
        "format_version: 1\n"
        "name: {name}\n"
        "shells:\n"
        "  before: []\n"
        "  case: []\n"
        "  after: []\n"
    )
    (root / "a.tc.yaml").write_text(minimal.format(name="a"), encoding="utf-8")
    (root / "b.tc.yaml").write_text(minimal.format(name="b"), encoding="utf-8")
    cases = load_entry_cases(str(root), ["b.tc.yaml"])
    assert len(cases) == 1
    assert cases[0].name == "b"
