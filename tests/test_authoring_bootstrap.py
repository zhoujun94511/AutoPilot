"""NL 解析与应用匹配（链路 3 自动化前置）。"""

from __future__ import annotations

import json

import pytest

from autopilot.authoring import app_resolve as app_resolve_mod
from autopilot.authoring.app_resolve import InstalledApp
from autopilot.authoring.contract import AuthoringError, AuthoringRequest
from autopilot.authoring.nl_parse import parse_nl_hints
from autopilot.authoring.session_bootstrap import prepare_authoring_session

_best_app_match = getattr(app_resolve_mod, "_best_app_match")


def test_parse_nl_platform_app_and_input():
    hints = parse_nl_hints("打开iOS手机上的Demo应用在输入栏输入alice并提交")
    assert hints.platform == "ios"
    assert hints.app_name.lower() == "demo"
    assert hints.input_text == "alice"


def test_parse_settings_for_smoke_default():
    hints = parse_nl_hints("打开iOS手机上的设置应用，进入无线局域网")
    assert hints.platform == "ios"
    assert hints.app_name == "设置"


def test_best_app_match_prefers_display_name():
    apps = [
        InstalledApp("com.other.foo", "Foo", "ios"),
        InstalledApp("com.acme.demo", "Demo", "ios"),
        InstalledApp("com.acme.demo.dev", "Demo Dev", "ios"),
    ]
    hit = _best_app_match(apps, "demo", platform="ios")
    assert hit is not None
    assert hit.package_name == "com.acme.demo"


def test_ios_settings_alias_matches_english_display_name(monkeypatch):
    """中文「设置」应对英文系统上的 Settings / Preferences。"""
    from autopilot.authoring import app_resolve as ar

    monkeypatch.setattr(
        ar,
        "list_ios_installed_apps",
        lambda udid="": [
            InstalledApp("com.other.app", "Aquario", "ios"),
            InstalledApp("com.apple.Preferences", "Settings", "ios"),
        ],
    )
    hit = ar.resolve_installed_app("ios", udid="U1", app_name="设置")
    assert hit.package_name == "com.apple.Preferences"


def test_ios_settings_alias_works_when_missing_from_user_list(monkeypatch):
    from autopilot.authoring import app_resolve as ar

    monkeypatch.setattr(ar, "list_ios_installed_apps", lambda udid="": [])
    hit = ar.resolve_installed_app("ios", udid="U1", app_name="Settings")
    assert hit.package_name == "com.apple.Preferences"


def test_android_settings_uses_intent_component(monkeypatch):
    from autopilot.authoring import app_resolve as ar

    monkeypatch.setattr(ar, "list_android_installed_packages", lambda udid="": [])
    monkeypatch.setattr(
        ar, "android_settings_component", lambda udid="": ("com.miui.securitycenter", "")
    )
    hit = ar.resolve_installed_app("android", udid="S1", app_name="设置")
    assert hit.package_name == "com.miui.securitycenter"


def test_ios_system_catalog_matches_calendar_across_languages(monkeypatch):
    from autopilot.authoring import app_resolve as ar

    monkeypatch.setattr(
        ar,
        "list_ios_installed_apps",
        lambda udid="": [
            InstalledApp("com.apple.mobilecal", "Calendar", "ios"),
        ],
    )
    hit = ar.resolve_installed_app("ios", udid="U1", app_name="日历")
    assert hit.package_name == "com.apple.mobilecal"


def test_popular_app_alias_requires_installed_package(monkeypatch):
    from autopilot.authoring import app_resolve as ar

    monkeypatch.setattr(
        ar,
        "list_ios_installed_apps",
        lambda udid="": [
            InstalledApp("com.tencent.xin", "WeChat", "ios"),
        ],
    )
    hit = ar.resolve_installed_app("ios", udid="U1", app_name="微信")
    assert hit.package_name == "com.tencent.xin"

    monkeypatch.setattr(ar, "list_ios_installed_apps", lambda udid="": [])
    with pytest.raises(AuthoringError, match="未找到匹配"):
        ar.resolve_installed_app("ios", udid="U1", app_name="微信")


def test_popular_catalog_handles_natural_language_suffix(monkeypatch):
    from autopilot.authoring import app_resolve as ar
    from autopilot.authoring.system_app_aliases import alias_entry

    assert alias_entry("ios", "打开微信应用").app_id == "wechat"
    assert alias_entry("android", "小红书客户端").app_id == "xiaohongshu"
    # 完整别名优先，不能把 WhatsApp 的 app 尾部误删
    assert alias_entry("android", "WhatsApp").app_id == "whatsapp"

    monkeypatch.setattr(
        ar,
        "list_android_installed_packages",
        lambda udid="": [
            InstalledApp("com.xingin.xhs", "REDnote", "android"),
        ],
    )
    hit = ar.resolve_installed_app("android", udid="A1", app_name="小红书应用")
    assert hit.package_name == "com.xingin.xhs"


def test_builtin_catalog_has_no_cross_app_alias_conflicts():
    from collections import defaultdict

    from autopilot.authoring.system_app_aliases import _norm, app_catalog

    for platform in ("ios", "android"):
        owners: dict[str, set[str]] = defaultdict(set)
        for entry in app_catalog(platform):
            for alias in entry.aliases:
                owners[_norm(alias)].add(entry.app_id)
        conflicts = {key: ids for key, ids in owners.items() if len(ids) > 1}
        assert conflicts == {}


def test_custom_app_alias_file_extends_catalog(tmp_path, monkeypatch):
    from autopilot.authoring import app_resolve as ar
    from autopilot.authoring import system_app_aliases as aliases

    path = tmp_path / "app_aliases.json"
    path.write_text(
        json.dumps(
            {
                "ios": [
                    {
                        "id": "company_portal",
                        "packages": ["com.example.portal"],
                        "aliases": ["企业门户", "Company Portal"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTOPILOT_AUTHORING_APP_ALIASES_FILE", str(path))
    aliases._load_custom_entries.cache_clear()
    monkeypatch.setattr(
        ar,
        "list_ios_installed_apps",
        lambda udid="": [
            InstalledApp("com.example.portal", "Company Portal", "ios"),
        ],
    )
    hit = ar.resolve_installed_app("ios", udid="U1", app_name="企业门户")
    assert hit.package_name == "com.example.portal"


def test_prepare_session_auto_resolves_app(monkeypatch):
    monkeypatch.setattr(
        "autopilot.authoring.session_bootstrap._pick_udid",
        lambda platform, preferred="", **kw: "UDID-1",
    )
    monkeypatch.setattr(
        "autopilot.authoring.session_bootstrap.resolve_installed_app",
        lambda platform, **kw: InstalledApp("com.acme.demo", "Demo", platform),
    )
    boot = prepare_authoring_session(
        AuthoringRequest(
            natural_language="打开iOS手机上的Demo应用在输入栏输入alice并提交",
            platform="ios",
            mode="session",
        )
    )
    assert boot.udid == "UDID-1"
    assert boot.request.package_name == "com.acme.demo"
    assert boot.request.app_label == "Demo"
    assert boot.ctx.get_var("__device_udid__") == "UDID-1"
    assert boot.reused_ctx is False


def test_android_label_probe_matches_chinese_name(monkeypatch):
    from autopilot.authoring import app_resolve as ar

    monkeypatch.setenv("AUTOPILOT_AUTHORING_LABEL_CACHE", "0")
    ar.clear_label_cache()
    monkeypatch.setattr(
        ar, "android_launchable_packages", lambda udid="": ["com.demo.one", "com.demo.two"]
    )

    def fake_adb(args, _serial):
        if args[:3] == ["shell", "dumpsys", "package"]:
            pkg = args[3]
            return "nonLocalizedLabel=天气助手\n" if pkg == "com.demo.two" else ""
        return ""

    monkeypatch.setattr(ar, "_adb_text", fake_adb)
    hit = ar.resolve_installed_app(
        "android",
        udid="S1",
        app_name="天气助手",
        package_name="",
    )
    assert hit.package_name == "com.demo.two"


def test_android_catalog_alias_prefers_installed_package(monkeypatch):
    """热门目录命中后按候选包校验设备，不再依赖英文 DisplayName。"""
    from autopilot.authoring import app_resolve as ar

    monkeypatch.setattr(
        ar,
        "list_android_installed_packages",
        lambda udid="": [
            InstalledApp("com.tencent.mm", "com.tencent.mm", "android"),
            InstalledApp("com.other.app", "Other", "android"),
        ],
    )
    hit = ar.resolve_installed_app("android", udid="A1", app_name="微信")
    assert hit.package_name == "com.tencent.mm"


def test_android_label_probe_order_prefers_catalog_packages():
    from autopilot.authoring import app_resolve as ar

    apps = [
        InstalledApp("com.other.a", "com.other.a", "android"),
        InstalledApp("com.tencent.mm", "com.tencent.mm", "android"),
    ]
    order = ar._android_label_probe_order(
        apps,
        udid="A1",
        hint="微信",
    )
    assert order[0] == "com.tencent.mm"


def test_android_label_disk_cache_roundtrip(tmp_path, monkeypatch):
    from autopilot.authoring import app_resolve as ar

    cache_file = tmp_path / "labels.json"
    monkeypatch.setenv("AUTOPILOT_AUTHORING_LABEL_CACHE", str(cache_file))
    ar.clear_label_cache()

    calls = {"n": 0}

    def fake_adb(args, _serial):
        if args[:3] == ["shell", "dumpsys", "package"]:
            calls["n"] += 1
            return "applicationLabel=演示应用\n"
        return ""

    monkeypatch.setattr(ar, "_adb_text", fake_adb)
    assert ar.android_app_label("com.demo.app", "S1") == "演示应用"
    assert calls["n"] == 1
    assert cache_file.is_file()

    # 清内存后应命中磁盘，不再打 dumpsys
    ar._LABEL_CACHE.clear()
    ar._DISK_CACHE_LOADED = False
    ar._DISK_CACHE = {}
    assert ar.android_app_label("com.demo.app", "S1") == "演示应用"
    assert calls["n"] == 1


def test_dumpsys_application_label_parsed(monkeypatch):
    from autopilot.authoring import app_resolve as ar

    monkeypatch.setenv("AUTOPILOT_AUTHORING_LABEL_CACHE", "0")
    ar.clear_label_cache()
    monkeypatch.setattr(
        ar,
        "_adb_text",
        lambda args, serial: "ApplicationInfo{abc applicationLabel=相册}\n",
    )
    assert ar._label_from_dumpsys("com.demo.gallery", "S1") == "相册"


def test_custom_alias_overrides_builtin(tmp_path, monkeypatch):
    """企业目录优先于内置（Midscene appNameMapping 同款优先级）。"""
    from autopilot.authoring import app_resolve as ar
    from autopilot.authoring import system_app_aliases as aliases

    path = tmp_path / "app_aliases.json"
    path.write_text(
        json.dumps(
            {
                "android": [
                    {
                        "id": "wechat_enterprise",
                        "packages": ["com.example.wework"],
                        "aliases": ["微信"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTOPILOT_AUTHORING_APP_ALIASES_FILE", str(path))
    aliases._load_custom_entries.cache_clear()
    monkeypatch.setattr(
        ar,
        "list_android_installed_packages",
        lambda udid="": [
            InstalledApp("com.tencent.mm", "WeChat", "android"),
            InstalledApp("com.example.wework", "企业微信定制", "android"),
        ],
    )
    hit = ar.resolve_installed_app("android", udid="A1", app_name="微信")
    assert hit.package_name == "com.example.wework"


def test_android_launch_activity_from_resolve_activity(monkeypatch):
    from autopilot.authoring import app_resolve as ar

    monkeypatch.setattr(
        ar,
        "_adb_text",
        lambda args, serial: "priority=0 preferredOrder=0\n  com.demo.one/.MainActivity\n",
    )
    assert ar.android_launch_activity("com.demo.one", "S1") == ".MainActivity"


def test_prepare_session_uses_project_platform(tmp_path, monkeypatch):
    from autopilot.runtime import settings

    monkeypatch.setenv("AUTOPILOT_CONFIG_DIR", str(tmp_path / "cfg"))
    settings.set_project_platform(str(tmp_path), "android")
    monkeypatch.setattr(
        "autopilot.authoring.session_bootstrap._pick_udid",
        lambda platform, preferred="", **kw: "UDID-A",
    )
    monkeypatch.setattr(
        "autopilot.authoring.session_bootstrap.resolve_installed_app",
        lambda platform, **kw: InstalledApp("com.acme.demo", "Demo", platform),
    )
    boot = prepare_authoring_session(
        AuthoringRequest(
            natural_language="点击登录按钮",
            platform="",
            mode="session",
            project_dir=str(tmp_path),
        ),
        allow_nl_llm=False,
    )
    assert boot.request.platform == "android"
    assert boot.udid == "UDID-A"


def test_prepare_session_api_url_uses_http(tmp_path):
    boot = prepare_authoring_session(
        AuthoringRequest(
            natural_language="调用用户列表",
            platform="",
            start_url="https://api.example.com/v1/users",
            mode="session",
            project_dir=str(tmp_path),
        ),
        allow_nl_llm=False,
    )
    assert boot.request.platform == "http"


def test_prepare_session_http_project_keeps_http_on_page_url(tmp_path, monkeypatch):
    from autopilot.runtime import settings

    monkeypatch.setenv("AUTOPILOT_CONFIG_DIR", str(tmp_path / "cfg"))
    settings.set_project_platform(str(tmp_path), "http")
    boot = prepare_authoring_session(
        AuthoringRequest(
            natural_language="执行一步",
            platform="",
            start_url="https://example.com/login",
            mode="session",
            project_dir=str(tmp_path),
        ),
        allow_nl_llm=False,
    )
    assert boot.request.platform == "http"


def test_prepare_session_start_url_wins_over_project_platform(tmp_path, monkeypatch):
    from autopilot.runtime import settings

    monkeypatch.setenv("AUTOPILOT_CONFIG_DIR", str(tmp_path / "cfg"))
    settings.set_project_platform(str(tmp_path), "ios")
    boot = prepare_authoring_session(
        AuthoringRequest(
            natural_language="执行一步",
            platform="",
            start_url="https://example.com",
            mode="session",
            project_dir=str(tmp_path),
        ),
        allow_nl_llm=False,
    )
    assert boot.request.platform == "web"


def test_prepare_session_empty_platform_raises():
    with pytest.raises(AuthoringError, match="未能识别平台"):
        prepare_authoring_session(
            AuthoringRequest(
                natural_language="点击登录按钮",
                platform="",
                mode="session",
            ),
            allow_nl_llm=False,
        )
