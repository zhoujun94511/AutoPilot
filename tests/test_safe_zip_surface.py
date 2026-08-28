"""AUD-2026-19：IDE safe_zip 拒绝穿越；与 Platform 门禁互补。"""

from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

import pytest

from autopilot.runtime.safe_zip import safe_extractall


def test_safe_zip_rejects_path_traversal():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../x.txt", b"no")
    with tempfile.TemporaryDirectory() as d:
        with zipfile.ZipFile(io.BytesIO(buf.getvalue()), "r") as zf:
            with pytest.raises(ValueError, match="unsafe zip path"):
                safe_extractall(zf, Path(d))


def test_safe_zip_extracts_normal_member():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ok.txt", b"yes")
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d)
        with zipfile.ZipFile(io.BytesIO(buf.getvalue()), "r") as zf:
            safe_extractall(zf, dest)
        assert (dest / "ok.txt").read_bytes() == b"yes"
