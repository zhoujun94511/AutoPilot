"""mgmt 打包：仅纳入远程批跑必要资源。"""

from __future__ import annotations

import io
import zipfile

from autopilot.mgmt.pack import zip_project_dir


def test_zip_project_dir_keeps_needed_skips_redundant(tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    (root / "a.tc.yaml").write_text("name: a\n", encoding="utf-8")
    (root / "suite.ts.yaml").write_text("name: s\n", encoding="utf-8")
    (root / "config").mkdir()
    (root / "config" / "DataConfig.properties").write_text("k=v\n", encoding="utf-8")
    (root / "images").mkdir()
    (root / "images" / "btn.png").write_bytes(b"\x89PNG\r\n")
    (root / "data.csv").write_text("a,b\n", encoding="utf-8")

    # 冗余 / 噪声
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("x", encoding="utf-8")
    (root / "reports").mkdir()
    (root / "reports" / "x.html").write_text("h", encoding="utf-8")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "a.pyc").write_bytes(b"\0")
    (root / "app.apk").write_bytes(b"APK")
    (root / "payload.ipa").write_bytes(b"IPA")
    (root / "note.md").write_text("# doc\n", encoding="utf-8")
    (root / "debug.log").write_text("log\n", encoding="utf-8")
    (root / "logs").mkdir()
    (root / "logs" / "run.txt").write_text("x\n", encoding="utf-8")
    (root / "huge.png").write_bytes(b"x" * (26 * 1024 * 1024))

    data = zip_project_dir(str(root))
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = [n.replace("\\", "/") for n in zf.namelist()]

        assert any(n.endswith("a.tc.yaml") for n in names)
        assert any(n.endswith("suite.ts.yaml") for n in names)
        assert any(n.endswith("DataConfig.properties") for n in names)
        assert any(n.endswith("images/btn.png") for n in names)
        assert any(n.endswith("data.csv") for n in names)

        joined = "\n".join(names)
        assert ".git/" not in joined
        assert "/reports/" not in joined
        assert "__pycache__" not in joined
        assert not any(n.endswith(".apk") for n in names)
        assert not any(n.endswith(".ipa") for n in names)
        assert not any(n.endswith(".md") for n in names)
        assert not any(n.endswith(".log") for n in names)
        assert not any("/logs/" in n for n in names)
        assert not any(n.endswith("huge.png") for n in names)

        # 默认写入 ArtifactManifest
        man_names = [n for n in names if n.endswith("manifest.json")]
        assert len(man_names) == 1
        import json

        man = json.loads(zf.read(man_names[0]))
        assert man.get("schema_version") == "1.0"
        assert "sha256" in man and len(man["sha256"]) == 64
        assert isinstance(man.get("case_index"), list)


def test_zip_includes_bindings_and_manifest_glob(tmp_path):
    import json

    root = tmp_path / "demo"
    root.mkdir()
    (root / "a.tc.yaml").write_text(
        "type: testcase\nname: a\nlogical_case_id: lc-1\n",
        encoding="utf-8",
    )
    bdir = root / "bindings"
    bdir.mkdir()
    (bdir / "lc-1.json").write_text(
        '{"schema_version":"1.0","logical_case_id":"lc-1","steps":{}}',
        encoding="utf-8",
    )
    data = zip_project_dir(str(root))
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = [n.replace("\\", "/") for n in zf.namelist()]
        assert any(n.endswith("bindings/lc-1.json") for n in names)
        man_name = next(n for n in names if n.endswith("manifest.json"))
        man = json.loads(zf.read(man_name))
        assert man.get("bindings_glob") == "bindings/*.json"
        ready = man.get("intent_readiness") or {}
        assert ready.get("logical_case_count") == 1
        assert ready.get("binding_file_count") == 1
        assert ready.get("missing_binding_case_ids") == []


def test_zip_intent_readiness_flags_missing_binding(tmp_path):
    import json

    root = tmp_path / "demo"
    root.mkdir()
    (root / "a.tc.yaml").write_text(
        "type: testcase\nname: a\nlogical_case_id: lc-missing\n",
        encoding="utf-8",
    )
    data = zip_project_dir(str(root))
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        man_name = next(
            n for n in zf.namelist() if n.replace("\\", "/").endswith("manifest.json")
        )
        man = json.loads(zf.read(man_name))
    ready = man.get("intent_readiness") or {}
    assert ready.get("logical_case_count") == 1
    assert ready.get("binding_file_count") == 0
    assert "lc-missing" in (ready.get("missing_binding_case_ids") or [])
    assert ready.get("hint")
