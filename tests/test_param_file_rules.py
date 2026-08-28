"""本地文件参数规则与扩展名校验。"""

from __future__ import annotations

from autopilot.model.testcase import Step, ParamValue
from autopilot.ui.widgets.param_file_rules import (
    file_param_spec,
    is_dynamic_path,
    iter_file_param_rules,
    resolve_dialog_filter,
    resolve_extensions,
    validate_literal_path,
)


def test_app_file_spec_registered() -> None:
    spec = file_param_spec("mobile_app_install_and_open", "appFile")
    assert spec is not None
    assert spec.kind == "mobile_app"


def test_mobile_app_extensions_by_platform() -> None:
    spec = file_param_spec("mobile_app_install_and_open", "appFile")
    assert spec is not None
    ios_step = Step(keyword_id="mobile_app_install_and_open", params=[
        ParamValue("type", "ios"),
    ])
    android_step = Step(keyword_id="mobile_app_install_and_open", params=[
        ParamValue("type", "android"),
    ])
    assert resolve_extensions(spec, ios_step) == (".ipa",)
    assert resolve_extensions(spec, android_step) == (".apk", ".apex", ".xapk")
    assert ".ipa" in resolve_dialog_filter(spec, ios_step)
    assert ".apk" in resolve_dialog_filter(spec, android_step)


def test_validate_literal_path_rejects_wrong_ext() -> None:
    spec = file_param_spec("mobile_app_install_and_open", "appFile")
    assert spec is not None
    step = Step(keyword_id="mobile_app_install_and_open", params=[
        ParamValue("type", "ios"),
    ])
    assert validate_literal_path("/tmp/foo.apk", spec, step) is not None
    assert validate_literal_path("/tmp/foo.ipa", spec, step) is None


def test_dynamic_path_skips_validation() -> None:
    spec = file_param_spec("mobile_app_install_and_open", "appFile")
    assert spec is not None
    assert is_dynamic_path("COLUMN(pkg_path,)")
    assert validate_literal_path("COLUMN(pkg_path,)", spec) is None
    assert validate_literal_path("${app_path}", spec) is None


def test_registry_covers_mobile_app_file_keywords() -> None:
    kids = {kid for kid, pid, _ in iter_file_param_rules() if pid == "appFile"}
    assert kids == {
        "mobile_app_install_and_open",
        "mobile_app_get_package_and_activity",
        "mobile_SDK_ergodic",
    }
