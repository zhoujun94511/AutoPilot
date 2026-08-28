"""Intent Vision 上下文预算单测（截图压缩 / compact / 过滤）。"""

from __future__ import annotations

import json

import numpy as np

from autopilot.intent.context_budget import (
    compact_signature,
    compress_screenshot,
    crop_focus_elements,
    filter_elements,
    precrop_screenshot,
    serialize_elements,
    strip_embedded_images_from_text,
    text_has_embedded_image,
    union_element_bounds,
)
from autopilot.intent.vision_plugin import build_vision_payload


def _fake_png(w: int = 800, h: int = 1200) -> bytes:
    import cv2

    rng = np.random.default_rng(0)
    img = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
    cv2.rectangle(img, (50, 50), (300, 120), (200, 200, 255), -1)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return bytes(buf)


def test_precrop_screenshot_uses_element_union():
    raw = _fake_png(800, 1200)
    els = [{"tag": "button", "text": "登录", "clickable": True, "bounds": [50, 50, 250, 70]}]
    assert crop_focus_elements(els, prompt="点击登录") == els
    box = union_element_bounds(els, 800, 1200)
    assert box is not None
    # 250×70 + 16px/8% padding，不能扩到整屏 18%
    assert box[2] <= 300
    assert box[3] <= 110
    out, mime, meta = precrop_screenshot(raw, els)
    assert mime == "image/png"
    assert meta["cropped"] is True
    assert meta["box"][2] <= 300
    assert meta.get("dst_wh", [9999, 9999])[0] <= 384
    assert len(out) < len(raw)


def test_crop_focus_skips_without_intent_hit():
    els = [
        {"tag": "button", "text": "广告", "clickable": True, "bounds": [0, 0, 200, 80]},
        {"tag": "button", "text": "登录", "clickable": True, "bounds": [50, 50, 80, 30]},
    ]
    assert crop_focus_elements(els, prompt="") == []
    assert crop_focus_elements(els, prompt="打开设置") == []
    hits = crop_focus_elements(els, prompt="点击登录")
    assert len(hits) == 1
    assert hits[0]["text"] == "登录"
    # 中英同义：Sign in / login 应对上「登录」
    cross = crop_focus_elements(els, prompt="click Sign in")
    assert len(cross) == 1 and cross[0]["text"] == "登录"


def test_intent_synonym_table_expands_cn_en():
    from autopilot.intent.context_budget import _tokenize_prompt
    from autopilot.intent.synonyms import target_aliases

    toks = _tokenize_prompt("点击登录")
    assert "登录" in toks
    assert "login" in toks or "signin" in toks
    toks2 = _tokenize_prompt("open Settings")
    assert "设置" in toks2
    assert "settings" in toks2
    aliases = target_aliases("Wi-Fi")
    assert aliases[0] == "Wi-Fi"
    joined = " ".join(aliases).lower()
    assert "wifi" in joined or "wlan" in joined
    assert any("无线" in a for a in aliases)


def test_union_bounds_skips_almost_full_frame():
    els = [{"bounds": [0, 0, 800, 1200]}]
    assert union_element_bounds(els, 800, 1200, skip_cover=0.70) is None


def test_dom_json_strips_embedded_base64():
    blob = "data:image/png;base64," + ("A" * 200)
    assert text_has_embedded_image(blob)
    assert "[image omitted]" in strip_embedded_images_from_text("x " + blob)
    rows = serialize_elements(
        [
            {
                "tag": "img",
                "text": blob,
                "clickable": True,
                "bounds": [1, 1, 10, 10],
                "locators": {"id": "shot"},
            }
        ]
    )
    dumped = json.dumps(rows, ensure_ascii=False)
    assert "data:image" not in dumped
    assert ";base64," not in dumped


def test_compress_screenshot_shrinks():
    raw = _fake_png()
    assert len(raw) > 100_000
    out, mime = compress_screenshot(raw, target_short_side=480, max_kb=80, quality=85)
    assert mime == "image/jpeg"
    assert len(out) < len(raw)
    assert len(out) <= 80 * 1024


def test_compact_signature_short_keys():
    el = {
        "tag": "button",
        "text": "这是一个很长的登录按钮文案超过十六字",
        "class": "btn-primary foo-hash-abc123 other",
        "clickable": True,
        "bounds": [10, 20, 100, 40],
        "locators": {"id": "loginBtn"},
    }
    sig = compact_signature(el)
    assert sig["t"] == "button"
    assert len(sig["tx"]) <= 16
    assert sig["l"].startswith("id::")
    assert sig["l"] == "id::loginBtn"
    assert sig["ck"] == 1
    assert "p" in sig


def test_ios_clickable_only_for_real_controls():
    """StaticText/Image 一律标 clickable 会让整页都是 ck:1，等于没信息。"""
    from autopilot.intent.ui_context import _ios_node_to_el

    class _Node:
        def __init__(self, **attrs):
            self.attrs = attrs
            self.tag = attrs.get("type", "")
            self.bounds = (0, 0, 60, 60)

    button = _ios_node_to_el(_Node(type="XCUIElementTypeButton", name="Search"))
    text = _ios_node_to_el(_Node(type="XCUIElementTypeStaticText", name="Search by name"))
    field = _ios_node_to_el(_Node(type="XCUIElementTypeTextField", name="q"))
    assert button and button["clickable"] is True and button["editable"] is False
    assert text and text["clickable"] is False
    assert field and field["editable"] is True
    assert compact_signature(field)["ed"] == 1
    assert "ck" not in compact_signature(text)


def test_android_web_editable_semantics():
    """跨平台 editable 语义：Android EditText / Web input 都应标 ed。"""
    from autopilot.intent.ui_context import _android_node_to_el

    class _N:
        def __init__(self, tag, attrs, bounds=None):
            self.tag = tag
            self.attrs = attrs
            self.bounds = bounds

    edit = _android_node_to_el(
        _N(
            "android.widget.EditText",
            {
                "class": "android.widget.EditText",
                "resource-id": "com.demo:id/q",
                "text": "",
                "clickable": "true",
                "enabled": "true",
            },
            (10, 20, 200, 40),
        )
    )
    assert edit is not None
    assert edit["editable"] is True
    assert compact_signature(edit).get("ed") == 1

    web = {
        "platform": "web",
        "tag": "input",
        "text": "",
        "placeholder": "username",
        "editable": True,
        "clickable": True,
        "bounds": [1, 2, 80, 24],
        "locators": {"id": "user"},
    }
    assert compact_signature(web).get("ed") == 1


def test_compact_locator_ios_uses_name_prefix():
    el = {
        "platform": "ios",
        "tag": "Image",
        "name": "home_search_icon",
        "text": "home_search_icon",
        "clickable": True,
        "locators": {
            "accessibility_id": "home_search_icon",
            "id": "home_search_icon",
        },
    }
    assert compact_signature(el)["l"] == "name::home_search_icon"

    els = [
        {"tag": "div", "text": "广告位", "bounds": [0, 0, 200, 200]},
        {
            "tag": "button",
            "text": "登录",
            "clickable": True,
            "bounds": [10, 10, 80, 30],
            "locators": {"id": "login"},
        },
        {
            "tag": "input",
            "placeholder": "用户名",
            "clickable": True,
            "bounds": [10, 50, 120, 30],
        },
    ]
    got = filter_elements(els, prompt="点击登录", max_count=2)
    assert any("登录" in str(e.get("text") or "") for e in got)
    assert len(got) <= 2


def test_serialize_elements_modes():
    els = [
        {
            "tag": "a",
            "text": "更多",
            "clickable": True,
            "bounds": [1, 1, 20, 10],
            "attrs": {"href": "/more", "id": "more"},
            "locators": {"id": "more"},
        }
    ]
    compact = serialize_elements(els, mode="compact")
    full = serialize_elements(els, mode="full")
    off = serialize_elements(els, mode="off")
    assert compact and "attrs" not in compact[0]
    assert full and "attrs" in full[0]
    assert off == []


def test_build_vision_payload_no_base64_in_text(monkeypatch):
    png = _fake_png(640, 960)

    monkeypatch.setenv("AUTOPILOT_VISION_SCREENSHOT", "1")
    monkeypatch.setenv("AUTOPILOT_VISION_DOM", "0")
    monkeypatch.setenv("AUTOPILOT_VISION_IMAGE_MAX_KB", "100")
    # 避免本机 DEEPSEEK_* 使 auto 模式跳过截图
    monkeypatch.setenv("AUTOPILOT_VISION_IMAGE_MODE", "force")
    monkeypatch.setenv("AUTOPILOT_VISION_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("AUTOPILOT_VISION_MODEL", "gpt-4o-mini")

    parts, meta = build_vision_payload(
        action="click",
        target="登录",
        value="",
        platform="web",
        ctx=None,
        png=png,
    )
    assert meta["screenshot"] is True
    assert parts[0]["type"] == "text"
    text = parts[0]["text"]
    assert "base64" not in text.lower() or "不含截图 base64" in text
    assert "data:image" not in text
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/")
    # 无 DOM 时自动升 detail=auto（纯靠图识别）
    assert parts[1]["image_url"]["detail"] == "auto"
    assert meta["image_tier"] == "no_dom"


def test_build_vision_payload_dom_only(monkeypatch):
    class _Ctx:
        pass

    monkeypatch.setenv("AUTOPILOT_VISION_SCREENSHOT", "0")
    monkeypatch.setenv("AUTOPILOT_VISION_DOM", "1")
    monkeypatch.setenv("AUTOPILOT_VISION_DOM_MODE", "compact")
    monkeypatch.setenv("AUTOPILOT_VISION_DOM_MAX", "10")

    from autopilot.intent import vision_plugin as vp

    monkeypatch.setattr(
        vp,
        "collect_ui_elements",
        lambda ctx, platform: [
            {
                "tag": "button",
                "text": "提交",
                "clickable": True,
                "bounds": [5, 5, 60, 24],
                "locators": {"id": "submit"},
            }
        ],
    )
    parts, meta = build_vision_payload(
        action="click",
        target="提交",
        value="",
        platform="web",
        ctx=_Ctx(),
    )
    assert meta["dom"] is True
    assert meta["screenshot"] is False
    assert meta["element_count"] == 1
    assert len(parts) == 1
    import re

    m = re.search(r"\[\{.*?}]", parts[0]["text"])
    assert m
    arr = json.loads(m.group(0))
    assert arr[0]["t"] == "button"
    assert arr[0]["tx"] == "提交"


def test_android_ios_compact_fields():
    from autopilot.intent.ui_context import _android_node_to_el, _ios_node_to_el

    class _N:
        def __init__(self, tag, attrs, bounds=None):
            self.tag = tag
            self.attrs = attrs
            self.bounds = bounds

    and_el = _android_node_to_el(
        _N(
            "android.widget.Button",
            {
                "class": "android.widget.Button",
                "resource-id": "com.demo:id/login",
                "content-desc": "登录按钮",
                "text": "登录",
                "package": "com.demo",
                "clickable": "true",
                "enabled": "true",
                "checkable": "false",
            },
            (10, 20, 100, 40),
        )
    )
    assert and_el is not None
    assert and_el["resource_id"].endswith("login")
    assert and_el["content_desc"] == "登录按钮"
    assert and_el["package"] == "com.demo"
    assert "resource-id" in and_el["attrs"]
    sig_a = compact_signature(and_el)
    assert sig_a["pl"] == "a"
    assert "rid" in sig_a
    assert sig_a["tx"] == "登录"

    ios_el = _ios_node_to_el(
        _N(
            "XCUIElementTypeButton",
            {
                "type": "XCUIElementTypeButton",
                "name": "loginButton",
                "label": "登录",
                "enabled": "true",
                "visible": "true",
                "x": "5",
                "y": "8",
                "width": "60",
                "height": "28",
            },
            (5, 8, 60, 28),
        )
    )
    assert ios_el is not None
    assert ios_el["name"] == "loginButton"
    assert ios_el["label"] == "登录"
    assert ios_el["visible"] is True
    assert "name" in ios_el["attrs"]
    sig_i = compact_signature(ios_el)
    assert sig_i["pl"] == "i"
    assert sig_i.get("nm") == "loginButton" or sig_i.get("tx") == "登录"


def test_image_profile_tiers():
    from autopilot.intent.context_budget import image_profile

    std = image_profile(element_count=10)
    assert std["tier"] == "standard"
    assert std["detail"] == "low"
    assert std["short_side"] == 560

    nodom = image_profile(element_count=0)
    assert nodom["tier"] == "no_dom"
    assert nodom["detail"] == "auto"
    assert nodom["short_side"] >= 640

    enh = image_profile(enhanced=True, element_count=10)
    assert enh["tier"] == "enhanced"
    assert enh["detail"] == "high"
    assert enh["short_side"] >= 720
    assert enh["dom_mode"] == "full"


def test_resolve_fallback_skips_vision_first(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_INTENT_VISION", "1")
    monkeypatch.setenv("AUTOPILOT_VISION_WHEN", "fallback")
    called = {"n": 0}

    def _fake_vision(**_kwargs):
        called["n"] += 1
        return [
            {
                "keyword_id": "web_element_click",
                "params": {"locator": "x"},
                "locator": "x",
                "score": 0.4,
                "resolver": "vision",
            }
        ]

    monkeypatch.setattr("autopilot.intent.vision.vision_candidates", _fake_vision)
    from autopilot.intent.resolve import resolve_candidates

    rows = resolve_candidates(action="click", target="登录", value="", platform="web")
    assert called["n"] == 0
    assert all(r.get("resolver") != "vision" for r in rows)

    rows2 = resolve_candidates(
        action="click", target="登录", value="", platform="web", include_vision=True
    )
    assert called["n"] == 1
    assert any(r.get("resolver") == "vision" for r in rows2)
