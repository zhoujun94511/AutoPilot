"""Web dual-engine parametrized live white-box (selenium | playwright).

Run:
  python -m pytest -p no:xonsh tests/test_web_live.py -q
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autopilot.keywords.context import ExecutionContext
from autopilot.keywords.registry import KeywordError
from autopilot.keywords.web import browser as br_mod
from autopilot.keywords.web import element as el_mod
from autopilot.keywords.web import image as img_mod
from autopilot.keywords.web import verify as verify_mod
from autopilot.keywords.web.driver import get_manager, require_selenium_feature
from autopilot.model.mapfile import Locator
from tests.web_live_fixtures import (
    browser_type_matches,
    confirm_cancel,
    confirm_ok,
)
from tests.web_live_support import (
    MARK_PNG,
    css as _css,
    driver,
    elem_id as _id,
    page_events as _events,
    page_js as _js,
)

# ---- 浏览器 ----


def test_live_browser_nav_title_url_refresh(live_ctx, http_origin):
    out = br_mod.browser_get_title(live_ctx, title="t")
    assert "PW Suite" in out["t"]
    out = br_mod.browser_get_url(live_ctx, outVar="u")
    assert "web_pw_suite.html" in out["u"]
    br_mod.browser_maximize(live_ctx)
    br_mod.browser_locate(live_ctx, url=f"{http_origin}/web_pw_suite_b.html")
    assert "PW Suite B" in br_mod.browser_get_title(live_ctx, title="t")["t"]
    assert el_mod.get_element_text(live_ctx, locator=_id("title-b"), outVar="h")["h"] == "Page B"
    br_mod.browser_back(live_ctx)
    assert "web_pw_suite.html" in br_mod.browser_get_url(live_ctx, outVar="u")["u"]
    br_mod.browser_forward(live_ctx)
    assert "web_pw_suite_b.html" in br_mod.browser_get_url(live_ctx, outVar="u")["u"]
    br_mod.browser_back(live_ctx)
    br_mod.browser_refresh(live_ctx)
    verify_mod.verify_current_url(live_ctx, url="web_pw_suite.html", matched="true", mode="模糊匹配")


def test_live_browser_snapshot_and_js(live_ctx, tmp_path):
    path = tmp_path / "shot.png"
    out = br_mod.browser_snapshot(
        live_ctx, fileName=str(path.with_suffix("")), select_if_timestamp="否", outVar="p"
    )
    assert Path(out["p"]).is_file()
    assert Path(out["p"]).stat().st_size > 0
    out = br_mod.browser_execute_js(live_ctx, script="return 1+2;", var_value="v")
    assert out["v"] == 3


def test_live_cookies(live_ctx):
    br_mod.browser_add_cookie(live_ctx, key="k1", value="v1")
    out = br_mod.browser_get_cookie_value(live_ctx, cookieName="k1", cookieValue="cv")
    assert out["cv"] == "v1"
    br_mod.browser_delete_cookie_named(live_ctx, cookieName="k1")
    out = br_mod.browser_get_cookie_value(live_ctx, cookieName="k1", cookieValue="cv")
    assert out.get("cv") in ("", None) or out["cv"] == ""
    br_mod.browser_add_cookie(live_ctx, key="k2", value="v2")
    br_mod.browser_delete_all_cookies(live_ctx)
    assert driver(live_ctx).get_cookie("k2") is None


def test_live_click_input_getters(live_ctx):
    el_mod.element_click(live_ctx, locator=_id("btn"), isScroll="否")
    assert _events(live_ctx).get("click") == 1
    el_mod.text_input(live_ctx, locator=_id("inp"), isClear="是", text="hello")
    assert el_mod.get_element_text(live_ctx, locator=_id("title"), outVar="t")["t"] == "Suite"
    assert el_mod.get_element_attribute(
        live_ctx, locator=_id("inp"), name="value", outVar="v"
    )["v"] == "hello"
    assert el_mod.get_element_exist(live_ctx, locator=_id("btn"), outVar="e")["e"] is True
    assert el_mod.get_element_exist(live_ctx, locator=_id("nope"), outVar="e")["e"] is False
    assert el_mod.get_element_visible(live_ctx, locator=_id("btn"), outVar="v")["v"] is True
    assert el_mod.get_element_visible(live_ctx, locator=_id("hidden"), outVar="v")["v"] is False
    assert el_mod.get_element_enabled(live_ctx, locator=_id("btn"), outVar="e")["e"] is True
    assert el_mod.get_element_enabled(live_ctx, locator=_id("disabled"), outVar="e")["e"] is False
    n = el_mod.get_elements_number(live_ctx, locator=_css(".item"), outVar="n")["n"]
    assert n == 3


def test_live_js_check_scroll_click(live_ctx, monkeypatch):
    monkeypatch.setattr(el_mod.time, "sleep", lambda *_: None)
    el_mod.element_js_click(live_ctx, locator=_id("btn-js"))
    assert _js(live_ctx, "document.getElementById('btn-js').dataset.js") == "1"
    el_mod.element_check_and_click(live_ctx, locator=_id("btn"), timeout="2000")
    el_mod.element_scroll_and_click(live_ctx, locator=_id("offscreen"))
    el_mod.text_check_and_input(live_ctx, locator=_id("inp"), text="typed", timeout="2000")
    assert el_mod.get_element_attribute(
        live_ctx, locator=_id("inp"), name="value", outVar="v"
    )["v"] == "typed"


def test_live_checkbox_radio_selected(live_ctx):
    el_mod.check_click(live_ctx, locator=_id("chk"), isChecked="true", isScroll="否")
    assert el_mod.get_element_selected(live_ctx, locator=_id("chk"), outVar="s")["s"] is True
    el_mod.check_click(live_ctx, locator=_id("chk"), isChecked="false", isScroll="否")
    assert el_mod.get_element_selected(live_ctx, locator=_id("chk"), outVar="s")["s"] is False
    el_mod.radio_click(live_ctx, locator=_id("rad2"), isSelected="true", isScroll="否")
    assert el_mod.get_element_selected(live_ctx, locator=_id("rad2"), outVar="s")["s"] is True


def test_live_set_attribute_and_upload(live_ctx, tmp_path):
    el_mod.set_element_attribute(live_ctx, locator=_id("btn"), name="data-x", value="99")
    assert el_mod.get_element_attribute(
        live_ctx, locator=_id("btn"), name="data-x", outVar="a"
    )["a"] == "99"
    f = tmp_path / "up.txt"
    f.write_text("upload-me", encoding="utf-8")
    el_mod.upload_file(live_ctx, locator=_id("file"), text=str(f))
    name = _js(
        live_ctx,
        "document.getElementById('file').files[0] && document.getElementById('file').files[0].name",
    )
    assert name == "up.txt"


def test_live_combo_and_verify_combo(live_ctx):
    loc = _id("combo")
    el_mod.combo_select(live_ctx, locator=loc, type="文本", value="Bravo")
    verify_mod.verify_combo_select(live_ctx, locator=loc, text="Bravo", matched="true")
    st = verify_mod.set_combo_select_status(
        live_ctx, locator=loc, text="Bravo", matched="true", outVar="ok"
    )
    assert st["ok"] == "true"
    el_mod.combo_select(live_ctx, locator=loc, type="value", value="c")
    el_mod.combo_select(live_ctx, locator=loc, type="索引", value="0")
    assert "Alpha" in verify_mod._combo_texts(live_ctx, loc)


def test_live_verify_surface(live_ctx):
    verify_mod.verify_element_visible(live_ctx, locator=_id("btn"), isVisible="true")
    verify_mod.verify_element_visible(live_ctx, locator=_id("hidden"), isVisible="false")
    verify_mod.verify_element_enabled(live_ctx, locator=_id("btn"), isEnabled="true")
    verify_mod.verify_element_enabled(live_ctx, locator=_id("disabled"), isEnabled="false")
    verify_mod.verify_element_existed(live_ctx, locator=_id("btn"), isExisted="true")
    verify_mod.verify_element_existed(live_ctx, locator=_id("missing"), isExisted="false")
    verify_mod.verify_element_text(
        live_ctx, locator=_id("title"), text="Suite", matched="true", mode="精确匹配"
    )
    verify_mod.verify_element_attribute(
        live_ctx, locator=_id("inp"), attribute="id", value="inp", matched="true", mode="精确匹配"
    )
    assert verify_mod.set_element_visible_status(
        live_ctx, locator=_id("btn"), isVisible="true", outVar="r"
    )["r"] == "true"


def test_live_gestures_and_keys(live_ctx, monkeypatch):
    monkeypatch.setattr(el_mod.time, "sleep", lambda *_: None)
    btn = _id("btn")
    el_mod.element_move(live_ctx, locator=btn)
    el_mod.element_context_click(live_ctx, locator=btn)
    el_mod.element_double_click(live_ctx, locator=btn)
    ev = _events(live_ctx)
    assert ev.get("hov") == 1 and ev.get("ctx") == 1 and ev.get("dbl") == 1
    el_mod.element_drag(live_ctx, source=_id("src"), target=_id("dst"))
    assert _events(live_ctx).get("drop") == 1
    before = _js(live_ctx, "document.getElementById('slider').offsetLeft")
    el_mod.puzzle_drag_by_offset(live_ctx, locator=_id("slider"), xOffset="100", yOffset="0")
    after = _js(live_ctx, "document.getElementById('slider').offsetLeft")
    assert int(after) > int(before)
    el_mod.element_drag_by_offset_for_login(
        live_ctx, source=_id("slider"), xOffset="60", yOffset="0"
    )
    el_mod.key_press_with_selenium(
        live_ctx, locator=_id("inp"), modifierkey="Ctrl", key="a", count="1"
    )
    assert _events(live_ctx).get("ctrl_a") == 1


def test_live_table_cell(live_ctx):
    out = el_mod.get_table_element(
        live_ctx, locator=_id("tbl"), outVar="c", row="2", col="1"
    )
    assert out["c"] == "r2c1"


def test_live_iframe_switch(live_ctx):
    br_mod.browser_switch_frame(live_ctx, locator=_id("fr"))
    assert el_mod.get_element_text(
        live_ctx, locator=_id("in-frame"), outVar="t"
    )["t"] == "inside-frame"
    br_mod.browser_switch_frame(live_ctx, locator=None)
    assert el_mod.get_element_exist(live_ctx, locator=_id("title"), outVar="e")["e"] is True


def test_live_window_switch(live_ctx, monkeypatch):
    monkeypatch.setattr(el_mod.time, "sleep", lambda *_a, **_k: None)
    before = len(driver(live_ctx).window_handles)
    el_mod.element_click_and_switch(live_ctx, locator=_id("btn-new"))
    after = len(driver(live_ctx).window_handles)
    assert after >= before
    br_mod.browser_switch_window(live_ctx, title="PW Suite B", mode="模糊匹配")
    assert "PW Suite B" in br_mod.browser_get_title(live_ctx, title="t")["t"]
    assert el_mod.get_element_text(live_ctx, locator=_id("title-b"), outVar="h")["h"] == "Page B"
    br_mod.browser_close_and_switch(live_ctx)
    assert "PW Suite Fixture" in br_mod.browser_get_title(live_ctx, title="t")["t"]


def test_live_alert(live_ctx):
    el_mod.element_click(live_ctx, locator=_id("btn-alert"), isScroll="否")
    out = br_mod.browser_get_alert_txt(live_ctx, alertTxt="a")
    assert out.get("a") == "hello-alert"
    verify_mod.verify_alert_text(live_ctx, text="hello-alert", matched="true", mode="精确匹配")
    assert verify_mod.set_alert_text(
        live_ctx, text="hello-alert", matched="true", mode="精确匹配", outVar="r"
    )["r"] == "true"
    br_mod.browser_click_alert(live_ctx, isAccept="true")


def test_live_confirm_and_prompt(live_ctx, engine):
    confirm_ok(live_ctx, engine)
    assert _events(live_ctx).get("confirm") == "ok"
    confirm_cancel(live_ctx, engine)
    assert _events(live_ctx).get("confirm") == "cancel"
    if engine == "playwright":
        br_mod.browser_set_prompt_value(live_ctx, inputValue="alice")
        el_mod.element_click(live_ctx, locator=_id("btn-prompt"), isScroll="否")
        assert br_mod.browser_get_alert_txt(live_ctx, alertTxt="a").get("a") == "enter-name"
        br_mod.browser_click_alert(live_ctx, isAccept="true")
    else:
        el_mod.element_click(live_ctx, locator=_id("btn-prompt"), isScroll="否")
        assert br_mod.browser_get_alert_txt(live_ctx, alertTxt="a").get("a") == "enter-name"
        br_mod.browser_set_prompt_value(live_ctx, inputValue="alice")
        br_mod.browser_click_alert(live_ctx, isAccept="true")
    assert _events(live_ctx).get("prompt_val") == "alice"


def test_live_wait_exist_visible(live_ctx, monkeypatch):
    monkeypatch.setattr(br_mod.time, "sleep", lambda *_: None)
    br_mod.browser_wait_for_exist(live_ctx, locator=_id("btn"), isExist="true")
    br_mod.browser_wait_for_visible(live_ctx, locator=_id("btn"), isVisible="true")
    br_mod.browser_wait_for_text(live_ctx, locator=_id("title"), text="Suite", isMatched="true")
    br_mod.browser_wait_alert(live_ctx, isAccept="false", timeout="500")
    el_mod.element_click(live_ctx, locator=_id("btn-alert"), isScroll="否")
    br_mod.browser_wait_alert(live_ctx, isAccept="true", timeout="2000")
    br_mod.browser_click_alert(live_ctx, isAccept="true")


def test_live_scroll_source_type_cookie_complex(live_ctx, engine):
    br_mod.browser_scroll_vertical_bar(live_ctx, height="200")
    y = _js(live_ctx, "window.scrollY")
    assert float(y) >= 100
    br_mod.browser_scroll_vertical_bar(live_ctx, height="-1")
    src = br_mod.browser_get_page_source(live_ctx, outValue="s")["s"]
    assert "PW Suite Fixture" in src or "Suite" in src
    bt = br_mod.browser_get_browser_type(live_ctx, type="t")["t"]
    assert browser_type_matches(engine, bt)
    br_mod.browser_add_cookie_complex(
        live_ctx, key="ck", value="cv", domain="127.0.0.1", path="/"
    )
    assert br_mod.browser_get_cookie_value(live_ctx, cookieName="ck", cookieValue="v")["v"] == "cv"


def test_live_verify_status_variants(live_ctx):
    el_mod.check_click(live_ctx, locator=_id("chk"), isChecked="true", isScroll="否")
    assert verify_mod.set_element_selected_status(
        live_ctx, locator=_id("chk"), isSelected="true", outVar="r"
    )["r"] == "true"
    assert verify_mod.set_element_enabled_status(
        live_ctx, locator=_id("disabled"), isEnabled="false", outVar="r"
    )["r"] == "true"
    assert verify_mod.set_element_existed_status(
        live_ctx, locator=_id("btn"), isExisted="true", outVar="r"
    )["r"] == "true"
    assert verify_mod.set_element_text_status(
        live_ctx, locator=_id("title"), text="Suite", matched="true", mode="精确匹配", outVar="r"
    )["r"] == "true"
    assert verify_mod.set_element_attribute_status(
        live_ctx, locator=_id("inp"), attribute="id", value="inp", matched="true",
        mode="精确匹配", outVar="r",
    )["r"] == "true"
    assert verify_mod.set_current_url_status(
        live_ctx, url="web_pw_suite.html", matched="true", mode="模糊匹配", outVar="r"
    )["r"] == "true"
    verify_mod.verify_element_selected(live_ctx, locator=_id("chk"), isSelected="true")


def test_live_browser_open_activate_quit(http_origin, engine):
    ctx = ExecutionContext()
    ctx.set_var("__web_engine__", engine)
    br_mod.browser_open(
        ctx, url=f"{http_origin}/web_pw_suite.html", type="headless", alias="a"
    )
    br_mod.browser_open(
        ctx, url=f"{http_origin}/web_pw_suite_b.html", type="headless", alias="b"
    )
    try:
        br_mod.browser_activate(ctx, alias="a")
        assert "web_pw_suite.html" in br_mod.browser_get_url(ctx, outVar="u")["u"]
        br_mod.browser_activate(ctx, alias="b")
        assert "PW Suite B" in br_mod.browser_get_title(ctx, title="t")["t"]
        br_mod.browser_close(ctx)
        br_mod.browser_activate(ctx, alias="a")
        assert "Suite" in br_mod.browser_get_title(ctx, title="t")["t"]
    finally:
        get_manager(ctx).quit_all()


def test_live_image_keywords(live_ctx, monkeypatch):
    assert MARK_PNG.is_file()
    monkeypatch.setattr(img_mod.time, "sleep", lambda *_: None)
    path = str(MARK_PNG)
    assert img_mod.image_exists(
        live_ctx, imagePath=path, timeout="3000", expectExist="true", outVar="e"
    )["e"] is True
    img_mod.image_wait(live_ctx, imagePath=path, timeout="3000")
    img_mod.image_click(live_ctx, imagePath=path)
    assert _events(live_ctx).get("img_click") == 1
    img_mod.image_double_click(live_ctx, imagePath=path)
    assert _events(live_ctx).get("img_dbl") == 1
    img_mod.image_right_click(live_ctx, imagePath=path)
    assert _events(live_ctx).get("img_ctx") == 1
    _js(live_ctx, "document.getElementById('img-mark').style.display='none'")
    img_mod.image_type(live_ctx, imagePath=path, text="via-img")
    assert el_mod.get_element_attribute(
        live_ctx, locator=_id("img-inp"), name="value", outVar="v"
    )["v"] == "via-img"
    _js(live_ctx, "document.getElementById('img-inp').style.display='none'")
    img_mod.image_wait_vanish(live_ctx, imagePath=path, timeout="5000")
    assert img_mod.image_exists(
        live_ctx, imagePath=path, timeout="800", expectExist="false", outVar="e"
    )["e"] is False


def test_live_locator_strategies(live_ctx):
    assert el_mod.get_element_text(
        live_ctx, locator=Locator(type="XPATH", value="//h1[@id='title']"), outVar="t"
    )["t"] == "Suite"
    assert el_mod.get_element_attribute(
        live_ctx, locator=Locator(type="NAME", value="user"), name="id", outVar="a"
    )["a"] == "inp"
    assert el_mod.get_element_text(
        live_ctx, locator=Locator(type="CLASS", value="cls-mark"), outVar="t"
    )["t"] == "ClassMark"
    assert el_mod.get_element_exist(
        live_ctx, locator=Locator(type="TEXT", value="ExactLink"), outVar="e"
    )["e"] is True
    assert el_mod.get_element_exist(
        live_ctx, locator=Locator(type="ROLE", value="button"), outVar="e"
    )["e"] is True
    out = el_mod.get_table_element(
        live_ctx, locator=_id("tbl"), outVar="c", xpath=".//tr[1]/td[2]", row="1", col="1"
    )
    assert out["c"] == "r1c2"


def test_live_negative_verify_and_wait(live_ctx, monkeypatch):
    monkeypatch.setattr(br_mod.time, "sleep", lambda *_: None)
    verify_mod.verify_element_text(
        live_ctx, locator=_id("title"), text="Nope", matched="false", mode="精确匹配"
    )
    verify_mod.verify_element_attribute(
        live_ctx, locator=_id("inp"), attribute="id", value="wrong",
        matched="false", mode="精确匹配",
    )
    verify_mod.verify_current_url(
        live_ctx, url="never-this-host", matched="false", mode="模糊匹配"
    )
    br_mod.browser_wait_for_exist(live_ctx, locator=_id("missing-el"), isExist="false")
    br_mod.browser_wait_for_visible(live_ctx, locator=_id("hidden"), isVisible="false")
    br_mod.browser_wait_for_text(
        live_ctx, locator=_id("title"), text="Nope", isMatched="false"
    )


def test_live_keys_and_switch_last_window(live_ctx, monkeypatch):
    monkeypatch.setattr(el_mod.time, "sleep", lambda *_a, **_k: None)
    el_mod.key_press_with_selenium(
        live_ctx, locator=_id("inp"), modifierkey="", key="Enter", count="1"
    )
    before = len(driver(live_ctx).window_handles)
    el_mod.element_click_and_switch(live_ctx, locator=_id("btn-new"))
    assert len(driver(live_ctx).window_handles) >= before
    br_mod.browser_switch_window(live_ctx, title="", mode="模糊匹配")
    assert "PW Suite B" in br_mod.browser_get_title(live_ctx, title="t")["t"]
    br_mod.browser_close_and_switch(live_ctx)


def test_live_quit_alias_and_kill_all(http_origin, engine):
    ctx = ExecutionContext()
    ctx.set_var("__web_engine__", engine)
    br_mod.browser_open(
        ctx, url=f"{http_origin}/web_pw_suite.html", type="headless", alias="x"
    )
    br_mod.browser_quit(ctx, alias="x")
    with pytest.raises(KeywordError):
        get_manager(ctx).driver()
    br_mod.browser_open(
        ctx, url=f"{http_origin}/web_pw_suite.html", type="headless", alias=""
    )
    verify_mod.web_browser_kill_all(ctx)
    with pytest.raises(KeywordError):
        get_manager(ctx).driver()


def test_live_engine_and_feature_gate(live_ctx, engine):
    assert get_manager(live_ctx).engine == engine
    if engine == "playwright":
        with pytest.raises(KeywordError):
            require_selenium_feature(live_ctx, "未映射的 Selenium 专有能力")
    else:
        require_selenium_feature(live_ctx, "Selenium 原生能力")


# ---- 分支 / 负向矩阵（P0–P2）----


def test_live_wait_exist_timeout_raises(live_ctx, monkeypatch):
    monkeypatch.setattr(br_mod.time, "sleep", lambda *_: None)
    with pytest.raises(KeywordError, match="超时"):
        br_mod.browser_wait_for_exist(
            live_ctx, locator=_id("missing-el"), isExist="true", timeout="400"
        )
    with pytest.raises(KeywordError, match="超时"):
        br_mod.browser_wait_for_visible(
            live_ctx, locator=_id("hidden"), isVisible="true", timeout="400"
        )
    with pytest.raises(KeywordError, match="超时"):
        br_mod.browser_wait_for_text(
            live_ctx, locator=_id("title"), text="NeverAppear", isMatched="true",
            timeout="400",
        )


def test_live_verify_assert_failure_raises(live_ctx):
    with pytest.raises(KeywordError, match="校验失败"):
        verify_mod.verify_element_text(
            live_ctx, locator=_id("title"), text="Nope", matched="true", mode="精确匹配"
        )
    with pytest.raises(KeywordError, match="校验失败"):
        verify_mod.verify_element_visible(
            live_ctx, locator=_id("hidden"), isVisible="true"
        )
    with pytest.raises(KeywordError, match="校验失败"):
        verify_mod.verify_element_existed(
            live_ctx, locator=_id("missing-el"), isExisted="true"
        )
    assert verify_mod.set_element_text_status(
        live_ctx, locator=_id("title"), text="Nope", matched="true",
        mode="精确匹配", outVar="r",
    )["r"] == "false"
    with pytest.raises(KeywordError, match="校验失败"):
        verify_mod.verify_element_text(
            live_ctx, locator=_id("title"), text="^No.+", matched="true", mode="正则"
        )


def test_live_find_element_not_found_raises(live_ctx):
    with pytest.raises(KeywordError, match="未找到"):
        el_mod.element_click(live_ctx, locator=_id("nope-missing"), isScroll="否")
    with pytest.raises(KeywordError, match="未找到"):
        el_mod.get_element_text(live_ctx, locator=_css("#still-missing"), outVar="t")


def test_live_switch_window_title_miss_raises(live_ctx, monkeypatch):
    monkeypatch.setattr(el_mod.time, "sleep", lambda *_a, **_k: None)
    el_mod.element_click_and_switch(live_ctx, locator=_id("btn-new"))
    stay = br_mod.browser_get_title(live_ctx, title="t")["t"]
    with pytest.raises(KeywordError, match="未找到标题"):
        br_mod.browser_switch_window(live_ctx, title="___no_such_title___", mode="精确匹配")
    assert stay == br_mod.browser_get_title(live_ctx, title="t")["t"]


def test_live_wait_alert_appear_timeout_raises(live_ctx, monkeypatch):
    monkeypatch.setattr(br_mod.time, "sleep", lambda *_: None)
    with pytest.raises(KeywordError, match="等待弹框超时"):
        br_mod.browser_wait_alert(live_ctx, isAccept="true", timeout="600")


def test_live_combo_multi_and_bad_index(live_ctx):
    el_mod.combo_select(live_ctx, locator=_id("multi"), type="文本", value="M1;M2")
    verify_mod.verify_combo_select(live_ctx, locator=_id("multi"), text="M1;M2", matched="true")
    with pytest.raises(KeywordError, match="校验失败"):
        verify_mod.verify_combo_select(live_ctx, locator=_id("multi"), text="M9", matched="true")
    with pytest.raises(KeywordError, match="下拉选择失败"):
        el_mod.combo_select(live_ctx, locator=_id("combo"), type="索引", value="99")


def test_live_upload_missing_path(live_ctx):
    with pytest.raises(KeywordError, match="上传文件不存在"):
        el_mod.upload_file(live_ctx, locator=_id("file"), text=r"D:\no\such\upload.bin")


def test_live_image_not_found_and_wait_timeout(live_ctx, monkeypatch, tmp_path):
    monkeypatch.setattr(img_mod.time, "sleep", lambda *_: None)
    missing = str(tmp_path / "no_such_template.png")
    with pytest.raises(KeywordError, match="模板图不存在|屏幕未找到"):
        img_mod.image_click(live_ctx, imagePath=missing)
    import numpy as np
    import cv2

    fake = tmp_path / "no_match.png"
    noise = np.random.default_rng(42).integers(0, 255, (72, 72, 3), dtype=np.uint8)
    cv2.imwrite(str(fake), noise)
    with pytest.raises(KeywordError, match="等待图像出现超时"):
        img_mod.image_wait(live_ctx, imagePath=str(fake), timeout="600")
    with pytest.raises(KeywordError, match="等待图像消失超时"):
        img_mod.image_wait_vanish(live_ctx, imagePath=str(MARK_PNG), timeout="600")


def test_live_execute_js_exception(live_ctx):
    with pytest.raises(KeywordError, match="执行JS失败"):
        br_mod.browser_execute_js(live_ctx, script="throw new Error('boom')", var_value="v")


def test_live_iframe_nested_default(live_ctx):
    br_mod.browser_switch_frame(live_ctx, locator=_id("fr-nest"))
    br_mod.browser_switch_frame(live_ctx, locator=_id("inner"))
    assert el_mod.get_element_text(
        live_ctx, locator=_id("in-nested"), outVar="t"
    )["t"] == "nested-deep"
    br_mod.browser_switch_frame(live_ctx, locator=None)
    assert el_mod.get_element_text(live_ctx, locator=_id("title"), outVar="t")["t"] == "Suite"
    with pytest.raises(KeywordError, match="不是 frame"):
        br_mod.browser_switch_frame(live_ctx, locator=_id("btn"))


def test_live_cookie_bad_domain(live_ctx):
    with pytest.raises(KeywordError, match="增加 cookie 失败"):
        br_mod.browser_add_cookie_complex(
            live_ctx, key="bad", value="x", domain="not-the-page.invalid", path="/"
        )


def test_live_text_input_no_clear_and_snapshot_ts(live_ctx, tmp_path):
    el_mod.text_input(live_ctx, locator=_id("inp"), isClear="否", text="-tail")
    assert el_mod.get_element_attribute(
        live_ctx, locator=_id("inp"), name="value", outVar="v"
    )["v"] == "init-tail"
    out = br_mod.browser_snapshot(
        live_ctx,
        fileName=str(tmp_path / "snap"),
        select_if_timestamp="是",
        outVar="p",
    )
    path = Path(out["p"])
    assert path.is_file() and path.stat().st_size > 0
    assert "_" in path.stem


def test_live_check_click_timeout_and_no_popup(live_ctx, monkeypatch):
    monkeypatch.setattr(el_mod.time, "sleep", lambda *_: None)
    with pytest.raises(KeywordError, match="未变为可点击"):
        el_mod.element_check_and_click(live_ctx, locator=_id("disabled"), timeout="400")
    with pytest.raises(KeywordError, match="未检测到新打开"):
        el_mod.element_click_and_switch(live_ctx, locator=_id("btn"), timeout="800")


def test_live_hidden_slider_and_bad_alias(live_ctx, engine):
    _js(live_ctx, "document.getElementById('slider').style.display='none'")
    if engine == "playwright":
        with pytest.raises(KeywordError, match="bounding_box"):
            el_mod.puzzle_drag_by_offset(live_ctx, locator=_id("slider"), xOffset="10", yOffset="0")
    else:
        from selenium.common.exceptions import ElementNotInteractableException

        with pytest.raises(ElementNotInteractableException):
            el_mod.puzzle_drag_by_offset(live_ctx, locator=_id("slider"), xOffset="10", yOffset="0")
    with pytest.raises(KeywordError, match="无此别名"):
        br_mod.browser_activate(live_ctx, alias="__no_such_alias__")

# ---- P3: AND/OR Locator + scrollMode ----


def _loc_and_inp():
    return Locator(
        type="AND",
        tag="input",
        properties=[
            {"name": "id", "value": "inp"},
            {"name": "name", "value": "user"},
        ],
    )


def _loc_or_inp():
    return Locator(
        type="OR",
        tag="input",
        properties=[
            {"name": "id", "value": "inp"},
            {"name": "id", "value": "missing-id"},
        ],
    )


def test_live_and_or_locator(live_ctx):
    assert el_mod.get_element_attribute(
        live_ctx, locator=_loc_and_inp(), name="value", outVar="v"
    )["v"] == "init"
    assert el_mod.get_element_exist(
        live_ctx, locator=_loc_or_inp(), outVar="e"
    )["e"] is True
    with pytest.raises(KeywordError, match="未找到"):
        el_mod.element_click(
            live_ctx,
            locator=Locator(
                type="AND",
                tag="input",
                properties=[
                    {"name": "id", "value": "inp"},
                    {"name": "name", "value": "wrong"},
                ],
            ),
            isScroll="否",
        )


def test_live_scroll_mode_offscreen_click(live_ctx):
    _js(live_ctx, "window.scrollTo(0, 0)")
    el_mod.element_click(
        live_ctx, locator=_id("offscreen"), isScroll="是", scrollMode="顶部"
    )
    assert _events(live_ctx).get("off_click") == 1
    y = float(_js(live_ctx, "window.scrollY"))
    assert y >= 500
