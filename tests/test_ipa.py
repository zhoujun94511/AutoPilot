"""IPA 解析与装包预检测试（纯 Python，无需真机/go-ios）。

造一个最小合法 .ipa（zip: Payload/x.app/Info.plist [+ embedded.mobileprovision]），
验证 parse_ipa 字段抽取与 ipa_precheck 的过期/设备不在授权列表分支。
"""

import os
import plistlib
import sys
import tempfile
import zipfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from autopilot.mobile.ipa import parse_ipa, ipa_precheck
from autopilot.mobile.errors import PackageError
from autopilot.keywords.registry import KeywordError


def _make_ipa(path: str, info_plist: dict, provision_xml: bytes = b"") -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Payload/Demo.app/Info.plist", plistlib.dumps(info_plist))
        zf.writestr("Payload/Demo.app/Demo", b"\x00binary")   # 占位可执行
        if provision_xml:
            zf.writestr("Payload/Demo.app/embedded.mobileprovision", provision_xml)


def _wrap_provision(plist: dict) -> bytes:
    """模拟 mobileprovision：CMS 前后缀 + 内嵌 XML plist（parse 只截 <?xml…</plist>）。"""
    return b"\x30\x82CMS-HEADER-BYTES" + plistlib.dumps(plist) + b"\x00\x00signature"


def test_parse_ipa_basic() -> bool:
    d = tempfile.mkdtemp()
    ipa = os.path.join(d, "demo.ipa")
    _make_ipa(ipa, {
        "CFBundleIdentifier": "com.example.demo",
        "CFBundleDisplayName": "示例",
        "CFBundleShortVersionString": "1.2.3",
        "CFBundleVersion": "45",
        "MinimumOSVersion": "13.0",
        "UIDeviceFamily": [1, 2],
        "CFBundleURLTypes": [{"CFBundleURLSchemes": ["demoapp", "demo2"]}],
        "NSCameraUsageDescription": "拍照", "NSPhotoLibraryUsageDescription": "相册",
    })
    info = parse_ipa(ipa)
    ok = (info.bundle_id == "com.example.demo" and info.app_name == "示例"
          and info.version_name == "1.2.3" and info.version_code == "45"
          and info.minimum_os == "13.0"
          and info.device_family == "通用（iPhone/iPad）"
          and info.url_schemes == ["demoapp", "demo2"]
          and info.permissions == ["NSCameraUsageDescription", "NSPhotoLibraryUsageDescription"]
          and info.signing_type == "App Store（无内嵌描述文件）"   # 无 mobileprovision
          and len(info.file_md5) == 32 and info.file_size_byte > 0)
    print("parse_ipa 基础+扩展字段:", "✅" if ok else "❌")
    return ok


def test_parse_ipa_provision() -> bool:
    d = tempfile.mkdtemp()
    ipa = os.path.join(d, "demo2.ipa")
    prov = _wrap_provision({
        "Name": "MyProfile", "AppIDName": "MyApp", "TeamName": "ACME",
        "UUID": "1111-2222", "ProvisionedDevices": ["UDID-A", "UDID-B"],
    })
    _make_ipa(ipa, {"CFBundleIdentifier": "com.example.demo"}, provision_xml=prov)
    info = parse_ipa(ipa)
    ok = (info.provision_name == "MyProfile" and info.team_name == "ACME"
          and info.uuid == "1111-2222"
          and info.provisioned_devices == ["UDID-A", "UDID-B"])
    print("parse_ipa 描述文件字段:", "✅" if ok else "❌")
    return ok


def test_parse_ipa_errors() -> bool:
    d = tempfile.mkdtemp()
    miss = os.path.join(d, "nope.ipa")
    raised_missing = False
    try:
        parse_ipa(miss)
    except (KeywordError, PackageError):
        raised_missing = True
    # 非法 zip
    bad = os.path.join(d, "bad.ipa")
    with open(bad, "wb") as f:
        f.write(b"not a zip")
    raised_badzip = False
    try:
        parse_ipa(bad)
    except (KeywordError, PackageError):
        raised_badzip = True
    # zip 但无 Info.plist
    empty = os.path.join(d, "empty.ipa")
    with zipfile.ZipFile(empty, "w") as zf:
        zf.writestr("Payload/x.app/other", b"x")
    raised_noplist = False
    try:
        parse_ipa(empty)
    except (KeywordError, PackageError):
        raised_noplist = True
    ok = raised_missing and raised_badzip and raised_noplist
    print("parse_ipa 错误分支(缺失/非zip/无plist):", "✅" if ok else "❌")
    return ok


def test_ipa_precheck() -> bool:
    from autopilot.mobile.ipa import IpaInfo
    # 干净开发包：设备在授权列表、未过期
    clean = IpaInfo(bundle_id="c.d", expiration_date="2999-01-01T00:00:00",
                    provisioned_devices=["UDID-A"])
    p_ok = ipa_precheck(clean, "UDID-A") == []
    # 设备不在授权列表
    p_dev = any("授权列表" in x for x in ipa_precheck(clean, "UDID-Z"))
    # 过期
    exp = IpaInfo(bundle_id="c.d", expiration_date="2000-01-01T00:00:00")
    p_exp = any("过期" in x for x in ipa_precheck(exp, ""))
    # bundle id 缺失
    nob = IpaInfo(bundle_id="")
    p_nob = any("bundle id" in x for x in ipa_precheck(nob, ""))
    # 分发包（无 ProvisionedDevices）→ 不因设备报错
    dist = IpaInfo(bundle_id="c.d", provisioned_devices=[])
    p_dist = ipa_precheck(dist, "UDID-Z") == []
    ok = (p_ok and p_dev and p_exp and p_nob and p_dist
          and datetime.fromisoformat("2000-01-01") < datetime.now() < datetime.fromisoformat("2999-01-01"))
    print("ipa_precheck(过期/设备/缺bundle/分发包放行):", "✅" if ok else "❌")
    return ok


def test_signing_type_and_display() -> bool:
    from autopilot.mobile.ipa import _signing_type, IpaInfo
    dev = _signing_type(True, {"Entitlements": {"get-task-allow": True},
                               "ProvisionedDevices": ["A"]})
    adhoc = _signing_type(True, {"Entitlements": {"get-task-allow": False},
                                 "ProvisionedDevices": ["A"]})
    ent = _signing_type(True, {"ProvisionsAllDevices": True})
    appstore = _signing_type(True, {})
    none = _signing_type(False, {})
    types_ok = (dev == "开发（Development）" and adhoc == "Ad Hoc"
                and ent == "企业（In-House）" and appstore == "App Store"
                and none == "App Store（无内嵌描述文件）")
    # display 友好占位 + expires_in_days
    disp = (IpaInfo.display("") == "—" and IpaInfo.display(None) == "—"
            and IpaInfo.display([]) == "—" and IpaInfo.display(["a", "b"]) == "a，b"
            and IpaInfo.display("x") == "x")
    exp_future = IpaInfo(expiration_date="2999-01-01T00:00:00").expires_in_days
    exp_none = IpaInfo(expiration_date="").expires_in_days
    exp_ok = exp_future is not None and exp_future > 0 and exp_none is None
    ok = types_ok and disp and exp_ok
    print("分发类型推断/display占位/过期天数:", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([test_parse_ipa_basic(), test_parse_ipa_provision(),
              test_parse_ipa_errors(), test_ipa_precheck(),
              test_signing_type_and_display()])
    print("\n总结:", "✅ IPA 解析/预检全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
