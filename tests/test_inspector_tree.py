"""阶段16.1/16.2 控件检视器：快照解析 + 命中测试 + 定位符生成（离线）。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# noinspection PyPep8Naming
from autopilot.inspector import tree as T

_ANDROID = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node class="android.widget.Button" resource-id="com.x:id/login"
          content-desc="登录" text="登录" bounds="[100,200][300,280]"/>
    <node class="android.widget.EditText" resource-id="com.x:id/user"
          text="" bounds="[100,300][980,380]"/>
  </node>
</hierarchy>"""

_IOS = """<?xml version="1.0" encoding="UTF-8"?>
<XCUIElementTypeApplication type="XCUIElementTypeApplication" name="App"
    x="0" y="0" width="390" height="844">
  <XCUIElementTypeButton type="XCUIElementTypeButton" name="Login" label="Login"
      x="20" y="100" width="120" height="44"/>
</XCUIElementTypeApplication>"""


def test_parse_android() -> bool:
    root = T.parse_android(_ANDROID)
    nodes = list(root.iter_all())
    btn = next(n for n in nodes if n.attrs.get("resource-id", "").endswith("login"))
    ok = (root.tag == "android.widget.FrameLayout" and len(nodes) == 3
          and btn.bounds == (100, 200, 200, 80))
    print("解析 Android page_source:", "✅" if ok else "❌")
    return ok


def test_parse_ios() -> bool:
    root = T.parse_ios(_IOS)
    btn = next(n for n in root.iter_all() if n.attrs.get("name") == "Login")
    ok = (root.tag == "XCUIElementTypeApplication" and btn.bounds == (20, 100, 120, 44))
    print("解析 iOS WDA source:", "✅" if ok else "❌")
    return ok


def test_hit_test() -> bool:
    root = T.parse_android(_ANDROID)
    hit = T.hit_test(root, 200, 240)        # 落在 Button 内
    miss = T.hit_test(root, 5, 5)           # 只在最外层 FrameLayout
    ok = (hit is not None and hit.attrs.get("resource-id", "").endswith("login")
          and miss is not None and miss.tag.endswith("FrameLayout"))
    print("点选命中最小控件:", "✅" if ok else "❌")
    return ok


def test_locators_android() -> bool:
    root = T.parse_android(_ANDROID)
    btn = next(n for n in root.iter_all() if n.attrs.get("resource-id", "").endswith("login"))
    locs = dict(T.generate_locators(root, btn, "android"))
    vals = list(locs.values())
    ok = ("id::com.x:id/login" in vals
          and any(v.startswith("xpath:://*[@content-desc=") for v in vals)
          and any(v.startswith("xpath:://*[@text=") for v in vals)
          and any(v.startswith("xpath::/") for v in vals))   # 绝对 xpath 兜底
    print("Android 候选定位符:", "✅" if ok else "❌", vals[:3])
    return ok


def test_locators_ios() -> bool:
    root = T.parse_ios(_IOS)
    btn = next(n for n in root.iter_all() if n.attrs.get("name") == "Login")
    vals = list(dict(T.generate_locators(root, btn, "ios")).values())
    ok = ("name::Login" in vals and any(v.startswith("xpath::") for v in vals))
    print("iOS 候选定位符:", "✅" if ok else "❌", vals[:3])
    return ok


def test_locators_ios_label_only() -> bool:
    """系统弹窗等控件常只有 label、无 name，不应推荐 name::。"""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<XCUIElementTypeApplication type="XCUIElementTypeApplication" x="0" y="0" width="390" height="844">
  <XCUIElementTypeAlert type="XCUIElementTypeAlert" x="0" y="0" width="390" height="844">
    <XCUIElementTypeButton type="XCUIElementTypeButton" label="WLAN &amp; Cellular"
        x="51" y="405" width="288" height="49"/>
  </XCUIElementTypeAlert>
</XCUIElementTypeApplication>"""
    root = T.parse_ios(xml)
    btn = next(n for n in root.iter_all() if n.attrs.get("label") == "WLAN & Cellular")
    vals = list(dict(T.generate_locators(root, btn, "ios")).values())
    ok = ("name::WLAN & Cellular" not in vals
          and "predicate::label == \"WLAN & Cellular\"" in vals
          and "xpath:://*[@label='WLAN & Cellular']" in vals)
    print("iOS 仅 label 不推 name:::", "✅" if ok else "❌", vals)
    return ok


def test_locators_ios_runtime_fallbacks() -> bool:
    """iOS 检视器应展示 link text 运行时回退候选。"""
    root = T.parse_ios(_IOS)
    btn = next(n for n in root.iter_all() if n.attrs.get("name") == "Login")
    labels = [x[0] for x in T.generate_locators(root, btn, "ios", "wda")]
    vals = [x[1] for x in T.generate_locators(root, btn, "ios", "wda")]
    ok = (
        any("[运行时]" in lb for lb in labels)
        and "linktext::label=Login" in vals
    )
    print("iOS 运行时 link text 回退:", "✅" if ok else "❌", labels[-3:])
    return ok


def test_locators_ios_wda_order() -> bool:
    """WDA-direct 与 Appium 对同时有 name/label 的控件推荐顺序不同。"""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<XCUIElementTypeApplication type="XCUIElementTypeApplication" x="0" y="0" width="390" height="844">
  <XCUIElementTypeButton type="XCUIElementTypeButton" name="submit_btn" label="提交"
      x="20" y="100" width="120" height="44"/>
</XCUIElementTypeApplication>"""
    root = T.parse_ios(xml)
    btn = next(n for n in root.iter_all() if n.attrs.get("name") == "submit_btn")
    appium = T.generate_locators(root, btn, "ios", "appium")
    wda = T.generate_locators(root, btn, "ios", "wda")
    ok = appium != wda and len(wda) > 0 and len(appium) > 0
    print("iOS backend 定位符排序差异:", "✅" if ok else "❌",
          [x[0] for x in wda[:3]], "vs", [x[0] for x in appium[:3]])
    return ok


_APPIUM_IOS_MIXED = """<?xml version="1.0" encoding="UTF-8"?>
<AppiumAUT>
  <XCUIElementTypeApplication type="XCUIElementTypeApplication">
    <XCUIElementTypeWindow type="XCUIElementTypeWindow" x="0" y="0" width="1170" height="2532"
        visible="false"/>
    <XCUIElementTypeWindow type="XCUIElementTypeWindow" x="0" y="0" width="390" height="844"
        visible="true">
      <XCUIElementTypeIcon type="XCUIElementTypeIcon" x="24" y="120" width="64" height="64"/>
    </XCUIElementTypeWindow>
  </XCUIElementTypeApplication>
</AppiumAUT>"""


def test_ios_render_scale() -> bool:
    """缩放分支：Appium 混用坐标修复；WDA/Android 保持历史行为。"""
    appium_root = T.parse_ios(_APPIUM_IOS_MIXED)
    wda_root = T.parse_ios(_IOS)
    android_root = T.parse_android(_ANDROID)
    s_appium = T.compute_render_scale("ios", 1170, 2532, appium_root, backend="appium")
    s_appium_sz = T.compute_render_scale(
        "ios", 1170, 2532, appium_root,
        logical_size={"width": 390, "height": 844}, backend="appium",
    )
    s_wda = T.compute_render_scale("ios", 1170, 2532, wda_root, backend="wda")
    s_android = T.compute_render_scale("android", 1080, 2400, android_root)
    ok = (
        abs(s_appium - 3.0) < 0.01
        and abs(s_appium_sz - 3.0) < 0.01
        and abs(s_wda - 3.0) < 0.01
        and abs(s_android - 1.0) < 0.01
    )
    print(
        "检视器缩放分支(Appium/WDA/Android):",
        "✅" if ok else "❌",
        f"appium={s_appium}",
        f"wda={s_wda}",
        f"android={s_android}",
    )
    return ok


def main() -> int:
    ok = all([test_parse_android(), test_parse_ios(), test_hit_test(),
              test_locators_android(), test_locators_ios(), test_locators_ios_label_only(),
              test_locators_ios_runtime_fallbacks(),
              test_locators_ios_wda_order(), test_ios_render_scale()])
    print("\n总结:", "✅ 控件检视器解析/定位符全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
