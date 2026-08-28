"""IDE WDA press_button 须与 Platform 一样走 3s 单次超时。"""

from __future__ import annotations

from autopilot.keywords.mobile.wda_client import WdaClient


def test_wda_press_button_timeout_is_short():
    seen: dict[str, object] = {}

    def fake_post(path: str, body: dict, timeout=None):
        seen["path"] = path
        seen["body"] = body
        seen["timeout"] = timeout

    client = WdaClient.__new__(WdaClient)
    client._post = fake_post  # type: ignore[method-assign]
    client.press_button("home")
    assert seen["path"] == "/wda/pressButton"
    assert seen["body"] == {"name": "home"}
    assert seen["timeout"] == 3.0
