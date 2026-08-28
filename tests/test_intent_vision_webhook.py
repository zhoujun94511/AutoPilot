"""Vision 插件与 webhook 接收单测。"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from autopilot.intent.config import (
    vision_accepts_images,
    vision_provider_is_text_only,
)
from autopilot.intent.vision_plugin import (
    build_vision_payload,
    call_vision_api,
    candidates_from_hints,
    flatten_text_content,
    looks_like_unsupported_image,
    normalize_user_content,
    parse_vision_response,
    text_parts_only,
)
from autopilot.intent.webhook_server import handle_design_event, verify_signature


def test_deepseek_detected_as_text_only():
    assert vision_provider_is_text_only("https://api.deepseek.com", "deepseek-v4-flash")
    assert vision_provider_is_text_only("https://api.deepseek.com/anthropic", "deepseek-v4-pro")
    assert vision_provider_is_text_only("https://api.openai.com/v1", "deepseek-v4-flash")
    assert not vision_provider_is_text_only(
        "https://api.deepseek.com", "deepseek-v4-flash-vision-exp"
    )
    assert vision_provider_is_text_only(
        "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"
    )
    assert not vision_provider_is_text_only(
        "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-vl-plus"
    )
    assert not vision_provider_is_text_only("https://api.openai.com/v1", "gpt-5.4-mini")


def test_vision_accepts_images_modes(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_VISION_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("AUTOPILOT_VISION_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("AUTOPILOT_VISION_IMAGE_MODE", "auto")
    assert vision_accepts_images() is False
    monkeypatch.setenv("AUTOPILOT_VISION_IMAGE_MODE", "force")
    assert vision_accepts_images() is False, "force 不能绕过 DeepSeek 文本型号的能力"
    monkeypatch.setenv("AUTOPILOT_VISION_MODEL", "deepseek-v4-flash-vision-exp")
    monkeypatch.setenv("AUTOPILOT_VISION_IMAGE_MODE", "auto")
    assert vision_accepts_images() is True
    monkeypatch.setenv("AUTOPILOT_VISION_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("AUTOPILOT_VISION_MODEL", "gpt-5.4-mini")
    assert vision_accepts_images() is True
    monkeypatch.setenv("AUTOPILOT_VISION_IMAGE_MODE", "off")
    assert vision_accepts_images() is False


def test_deepseek_payload_skips_screenshot(monkeypatch):
    import cv2
    import numpy as np

    img = np.zeros((96, 64, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    png = bytes(buf)

    monkeypatch.setenv("AUTOPILOT_VISION_SCREENSHOT", "1")
    monkeypatch.setenv("AUTOPILOT_VISION_DOM", "1")
    monkeypatch.setenv("AUTOPILOT_VISION_IMAGE_MODE", "auto")
    monkeypatch.setenv("AUTOPILOT_VISION_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("AUTOPILOT_VISION_MODEL", "deepseek-v4-flash")

    from autopilot.intent import vision_plugin as vp

    monkeypatch.setattr(
        vp,
        "collect_ui_elements",
        lambda ctx, platform: [
            {
                "tag": "TextView",
                "text": "Wi-Fi",
                "clickable": True,
                "bounds": [0, 0, 100, 40],
                "locators": {"text": "Wi-Fi"},
            }
        ],
    )
    parts, meta = build_vision_payload(
        action="assert",
        target="Wi-Fi",
        value="",
        platform="android",
        ctx=object(),
        png=png,
    )
    assert meta["text_only_provider"] is True
    assert meta["screenshot"] is False
    assert meta["image_skipped_reason"] == "provider_text_only"
    assert all(p.get("type") == "text" for p in parts)
    content = normalize_user_content(parts, accepts_images=False)
    assert isinstance(content, str)
    assert "Wi-Fi" in content
    assert "data:image" not in content


def test_deepseek_vision_model_attaches_screenshot(monkeypatch):
    import cv2
    import numpy as np

    img = np.zeros((400, 300, 3), dtype=np.uint8)
    cv2.rectangle(img, (20, 30), (120, 90), (200, 200, 255), -1)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    png = bytes(buf)

    monkeypatch.setenv("AUTOPILOT_VISION_SCREENSHOT", "1")
    monkeypatch.setenv("AUTOPILOT_VISION_DOM", "1")
    monkeypatch.setenv("AUTOPILOT_VISION_IMAGE_MODE", "auto")
    monkeypatch.setenv("AUTOPILOT_VISION_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("AUTOPILOT_VISION_MODEL", "deepseek-v4-flash-vision-exp")

    from autopilot.intent import vision_plugin as vp

    monkeypatch.setattr(
        vp,
        "collect_ui_elements",
        lambda ctx, platform: [
            {
                "tag": "TextView",
                "text": "Wi-Fi",
                "clickable": True,
                "bounds": [20, 30, 100, 60],
                "locators": {"text": "Wi-Fi"},
            }
        ],
    )
    parts, meta = build_vision_payload(
        action="assert",
        target="Wi-Fi",
        value="",
        platform="android",
        ctx=object(),
        png=png,
    )
    assert meta["text_only_provider"] is False
    assert meta["screenshot"] is True
    assert meta["image_crop"].get("cropped") is True
    assert meta["image_crop"]["box"][2] <= 160
    assert meta["image_crop"]["box"][3] <= 120
    assert any(p.get("type") == "image_url" for p in parts)
    assert "data:image" not in parts[0]["text"]
    assert ";base64," not in parts[0]["text"]
    content = normalize_user_content(parts, accepts_images=True)
    assert isinstance(content, list)
    assert any(p.get("type") == "image_url" for p in content)


def test_vision_model_defaults_deepseek_chat_to_vision(monkeypatch):
    from autopilot.intent.config import vision_model
    from autopilot.intent.provider_profile import DEFAULT_DEEPSEEK_VISION_MODEL

    monkeypatch.delenv("AUTOPILOT_VISION_MODEL", raising=False)
    monkeypatch.delenv("AP_AI_LOCATE_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.setenv("AUTOPILOT_VISION_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("AP_AI_MODEL", "deepseek-v4-flash")
    assert vision_model() == DEFAULT_DEEPSEEK_VISION_MODEL
    monkeypatch.setenv("AUTOPILOT_VISION_MODEL", "deepseek-v4-flash")
    assert vision_model() == "deepseek-v4-flash"


def test_normalize_and_unsupported_image_helpers():
    parts = [
        {"type": "text", "text": "hello"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,xx"}},
    ]
    assert text_parts_only(parts) == [{"type": "text", "text": "hello"}]
    assert flatten_text_content(parts) == "hello"
    assert looks_like_unsupported_image("[Unsupported Image]")
    assert looks_like_unsupported_image('unknown variant `image_url`, expected `text`')


def test_call_vision_api_retries_text_only_on_unsupported_image(monkeypatch):
    calls: list[object] = []

    def _fake_post(*, content, _key):
        # 与 _post_vision_chat 契约一致：(text, data, usage)
        calls.append(content)
        if isinstance(content, list):
            return "[Unsupported Image]", {}, {}
        return '{"candidates":[{"locator":"id=wifi","confidence":0.8}]}', {}, {}

    monkeypatch.setenv("AUTOPILOT_VISION_API_KEY", "sk-test")
    monkeypatch.setenv("AUTOPILOT_VISION_IMAGE_MODE", "force")
    monkeypatch.setenv("AUTOPILOT_VISION_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("AUTOPILOT_VISION_MODEL", "gpt-4o-mini")
    monkeypatch.setattr(
        "autopilot.intent.vision_plugin._post_vision_chat",
        _fake_post,
    )
    parts = [
        {"type": "text", "text": "find wifi"},
        {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,aa", "detail": "low"},
        },
    ]
    out = call_vision_api(
        action="click",
        target="Wi-Fi",
        value="",
        platform="android",
        content_parts=parts,
    )
    assert len(calls) == 2
    assert isinstance(calls[0], list)
    assert isinstance(calls[1], str)
    assert "candidates" in out


def test_parse_vision_response_json():
    content = json.dumps(
        {
            "candidates": [
                {"locator": "//*[@text='登录']", "confidence": 0.9, "reason": "按钮"},
                {"locator": "id=login", "confidence": 0.7},
            ]
        },
        ensure_ascii=False,
    )
    hints = parse_vision_response(content)
    assert len(hints) == 2
    assert hints[0]["locator"].startswith("//")


def test_parse_vision_response_fenced():
    content = '```json\n{"candidates":[{"locator":"css::.btn","confidence":0.5}]}\n```'
    hints = parse_vision_response(content)
    assert hints[0]["locator"] == "css::.btn"


def test_candidates_from_hints_prefix_xpath():
    rows = candidates_from_hints(
        [{"locator": "//button[text()='OK']", "confidence": 0.8}],
        action="click",
        value="",
        platform="web",
    )
    assert rows[0]["params"]["locator"].startswith("xpath::")
    assert rows[0]["resolver"] == "vision"
    assert rows[0]["keyword_id"] == "web_element_click"


def test_verify_signature():
    body = b'{"event":"logical_case.approved"}'
    secret = "s3cret"
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_signature(body, secret, sig) is True
    assert verify_signature(body, secret, "sha256=dead") is False
    assert verify_signature(body, "", "") is False
    assert verify_signature(body, "", "", allow_insecure=True) is True


def test_serve_webhook_requires_secret_or_insecure(tmp_path: Path):
    from autopilot.intent.webhook_server import serve_webhook

    try:
        serve_webhook(project_dir=str(tmp_path), secret="", allow_insecure=False, blocking=False)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "secret" in str(exc).lower() or "密钥" in str(exc)


def test_handle_design_event_imports(tmp_path: Path):
    payload = {
        "event": "logical_case.approved",
        "project_id": "p1",
        "case": {
            "logical_case_id": "lc-wh",
            "case_key": "LC-WH",
            "title": "Webhook导入",
            "intent_steps": [
                {
                    "id": "s1",
                    "action": "click",
                    "target": "登录",
                    "text": "点击登录",
                    "value": "",
                    "platform_hint": "any",
                }
            ],
            "logical_steps": ["点击登录"],
            "expected_results": ["ok"],
        },
    }
    out = handle_design_event(payload, project_dir=str(tmp_path))
    assert out["ok"] is True
    assert out["imported"] == 1
    assert (tmp_path / "imported_logical").is_dir()
    assert list((tmp_path / "imported_logical").glob("*.yaml"))
    assert (tmp_path / "bindings" / "lc-wh.json").is_file()
