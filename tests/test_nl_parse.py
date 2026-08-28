"""自然语言前置线索解析（链路 3 bootstrap，非步骤规划）。"""

from __future__ import annotations

from autopilot.authoring.nl_parse import parse_nl_hints


def test_parse_settings_app_not_blocked():
    """「设置」是真实系统 App，不能被停用词误拦。"""
    hints = parse_nl_hints("打开iOS手机上的设置应用，进入无线局域网")
    assert hints.platform == "ios"
    assert hints.app_name == "设置"


def test_parse_open_settings_without_app_suffix():
    hints = parse_nl_hints("打开设置，进入无线局域网并打开开关")
    assert hints.app_name == "设置"


def test_parse_demo_input_and_platform():
    hints = parse_nl_hints("打开iOS手机上的Demo应用在输入栏输入alice并提交")
    assert hints.platform == "ios"
    assert hints.app_name.lower() == "demo"
    assert hints.input_text == "alice"
    assert hints.input_texts == ("alice",)


def test_parse_multiple_inputs():
    hints = parse_nl_hints("打开登录页，输入 alice 并填写 secret123 然后点击登录")
    assert hints.input_texts == ("alice", "secret123")


def test_parse_package_name():
    hints = parse_nl_hints("启动 com.acme.demo 并点击首页")
    assert hints.package_name == "com.acme.demo"
    assert hints.app_name == "demo"


def test_parse_api_url_infers_http():
    hints = parse_nl_hints("调用 https://api.example.com/v1/users")
    assert hints.platform == "http"
    assert hints.start_url.startswith("https://api.example.com")


def test_parse_interface_keyword_is_http():
    hints = parse_nl_hints("接口测试 GET /orders 并校验 200")
    assert hints.platform == "http"


def test_parse_web_url_infers_platform():
    hints = parse_nl_hints("打开 https://example.com/login 并输入 alice")
    assert hints.platform == "web"
    assert hints.start_url == "https://example.com/login"
    assert hints.input_text == "alice"


def test_parse_web_visit_without_scheme():
    hints = parse_nl_hints("访问 www.example.org/path")
    assert hints.platform == "web"
    assert hints.start_url == "https://www.example.org/path"


def test_parse_english_open_app():
    hints = parse_nl_hints("open the Demo app and type alice")
    assert hints.app_name.lower() == "demo"


def test_parse_does_not_treat_navigation_as_app():
    """路径描述留给 Agent；这里只抽启动线索。"""
    hints = parse_nl_hints("在首页点击更多")
    # 「首页」是停用词；不应误当成应用名
    assert hints.app_name == ""
