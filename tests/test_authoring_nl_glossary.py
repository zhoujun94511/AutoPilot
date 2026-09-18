"""特殊说法对齐：词表进 Prompt、已装列表约束抽取、叠加层归属。"""

from __future__ import annotations

import json

from autopilot.authoring.app_resolve import (
    InstalledApp,
    pick_installed_app_via_llm,
    resolve_installed_app,
)
from autopilot.authoring.app_task import (
    belongs_to_target,
    is_overlay_package,
    packages_from_elements,
    task_ownership_note,
)
from autopilot.authoring.contract import GeneratedStep, PLATFORM_KEYWORD_PREFIXES
from autopilot.authoring import prompt as prompt_mod
from autopilot.authoring.prompt import build_agent_turn_prompt
from autopilot.authoring.locate_resolve import (
    match_hint_to_locator,
    resolve_planned_locators,
)
from autopilot.authoring.system_app_aliases import (
    clear_alias_caches,
    expand_term_hints,
    prompt_definitions,
)

_catalog_keep_prefixes = getattr(prompt_mod, "_catalog_keep_prefixes")
_compact_keyword_catalog = getattr(prompt_mod, "_compact_keyword_catalog")


def test_compact_catalog_uses_contract_prefixes():
    assert _catalog_keep_prefixes("android") == PLATFORM_KEYWORD_PREFIXES["android"]
    assert _catalog_keep_prefixes("http") == PLATFORM_KEYWORD_PREFIXES["http"]
    raw = _compact_keyword_catalog(
        [
            {"id": "mobile_element_click", "params": []},
            {"id": "public_sleep", "params": []},
            {"id": "web_element_click", "params": []},
        ],
        platform="android",
    )
    assert "mobile_element_click" in raw
    assert "public_sleep" in raw
    assert "web_element_click" not in raw


def test_prompt_definitions_from_catalog_and_terms(tmp_path, monkeypatch):
    path = tmp_path / "app_aliases.json"
    path.write_text(
        json.dumps(
            {
                "ios": [
                    {
                        "id": "portal",
                        "packages": ["com.example.portal"],
                        "aliases": ["工作台", "企业门户"],
                    }
                ],
                "terms": [
                    {"meaning": "无线局域网", "aliases": ["WLAN", "Wi-Fi"]},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTOPILOT_AUTHORING_APP_ALIASES_FILE", str(path))
    clear_alias_caches()
    text = prompt_definitions("ios", hint="工作台", package_name="com.example.portal")
    assert "工作台" in text
    assert "com.example.portal" in text
    assert "WLAN" in text
    assert "无线局域网" in text
    prompt = build_agent_turn_prompt(
        natural_language="打开工作台并进入 WLAN",
        platform="ios",
        elements_text="[]",
        keyword_catalog=[{"id": "mobile_element_click", "params": []}],
        history=[],
        package_name="com.example.portal",
        app_label="工作台",
    )
    assert "【已知定义】" in prompt
    assert "WLAN" in prompt
    assert "无线局域网" in expand_term_hints("WLAN")
    assert (
        match_hint_to_locator(
            "WLAN",
            [{"l": "name::无线局域网", "tx": "无线局域网"}],
        )
        == "name::无线局域网"
    )
    assert (
        match_hint_to_locator(
            "Wi-Fi",
            [{"l": "name::无线局域网", "tx": "无线局域网"}],
        )
        == "name::无线局域网"
    )
    steps = [
        GeneratedStep(
            "mobile_element_click",
            {"locator": "", "target": "WLAN"},
        )
    ]
    out, notes = resolve_planned_locators(
        steps,
        '[{"l":"name::无线局域网","tx":"无线局域网"}]',
        page_locators={"name::无线局域网"},
        allow_deep_think=False,
    )
    assert out[0].params["locator"] == "name::无线局域网"
    assert any("定位解析" in note for note in notes)


def test_expand_term_hints_empty_or_unknown(monkeypatch):
    monkeypatch.delenv("AUTOPILOT_AUTHORING_APP_ALIASES_FILE", raising=False)
    clear_alias_caches()
    assert expand_term_hints("") == ()
    assert expand_term_hints("  ") == ()
    assert expand_term_hints("WLAN") == ("WLAN",)


def test_pick_installed_app_via_llm_must_be_in_list():
    apps = [
        InstalledApp("com.demo.a", "Alpha", "ios"),
        InstalledApp("com.demo.b", "Beta", "ios"),
    ]
    hit = pick_installed_app_via_llm(
        "beta",
        apps,
        chat=lambda _p: json.dumps({"package_name": "com.demo.b"}),
    )
    assert hit is not None
    assert hit.package_name == "com.demo.b"
    assert (
        pick_installed_app_via_llm(
            "beta",
            apps,
            chat=lambda _p: json.dumps({"package_name": "com.not.installed"}),
        )
        is None
    )
    assert pick_installed_app_via_llm("beta", apps, chat=None) is None


def test_pick_installed_app_via_llm_skips_unlabeled():
    apps = [
        InstalledApp("com.demo.a", "", "android"),
        InstalledApp("com.demo.b", "com.demo.b", "android"),
    ]
    called: list[str] = []
    hit = pick_installed_app_via_llm(
        "设置",
        apps,
        chat=lambda prompt: called.append(prompt)
        or json.dumps({"package_name": "com.demo.a"}),
    )
    assert hit is None
    assert called == []


def test_resolve_ambiguous_uses_constrained_llm(monkeypatch):
    monkeypatch.setattr(
        "autopilot.authoring.app_resolve.list_ios_installed_apps",
        lambda udid="": [
            InstalledApp("com.acme.mail", "Demo Mail", "ios"),
            InstalledApp("com.acme.mail2", "Demo Mailbox", "ios"),
        ],
    )
    hit = resolve_installed_app(
        "ios",
        udid="U1",
        app_name="Demo",
        chat=lambda _p: json.dumps({"package_name": "com.acme.mail"}),
    )
    assert hit.package_name == "com.acme.mail"


def test_overlay_packages_still_belong_to_target():
    assert is_overlay_package("com.android.permissioncontroller")
    assert belongs_to_target(
        ["com.android.permissioncontroller"],
        "com.example.app",
    )
    assert belongs_to_target(["com.example.app"], "com.example.app")
    assert not belongs_to_target(["com.other.app"], "com.example.app")
    note = task_ownership_note(
        ["com.android.permissioncontroller"],
        "com.example.app",
    )
    assert "叠加层" in note
    assert packages_from_elements(
        [{"package": "com.example.app"}, {"package": "com.example.app"}]
    ) == ("com.example.app",)
