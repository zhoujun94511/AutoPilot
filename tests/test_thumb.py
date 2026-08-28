"""报告缩略图：空输入不崩；有图则压小。"""

from __future__ import annotations

import base64

from autopilot.report.thumb import thumbnail_b64


def test_thumbnail_empty_and_invalid():
    assert thumbnail_b64("") == ""
    assert thumbnail_b64("not-base64!!!") == "not-base64!!!"


def test_thumbnail_shrinks_when_opencv_available():
    try:
        import cv2
        import numpy as np
    except ImportError:
        assert thumbnail_b64("AAAA") == "AAAA"
        return
    canvas = np.full((800, 1200, 3), (160, 80, 12), dtype=np.uint8)
    ok, buf = cv2.imencode(".png", canvas)
    assert ok
    raw = base64.b64encode(bytes(buf)).decode("ascii")
    out = thumbnail_b64(raw, max_side=480)
    decoded = base64.b64decode(out)
    image = cv2.imdecode(np.frombuffer(decoded, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    assert max(image.shape[0], image.shape[1]) <= 480
