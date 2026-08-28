"""阶段19 Web 检视（离线）：DOM 快照 JSON → 控件树 / 命中 / 候选定位符。"""

import json
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

_SNAP = json.dumps({
    "viewport": [1000, 800], "dpr": 2,
    "tree": {"tag": "html", "attrs": {}, "rect": [0, 0, 1000, 800], "children": [
        {"tag": "body", "attrs": {}, "rect": [0, 0, 1000, 800], "children": [
            {"tag": "input", "attrs": {"name": "user", "class": "field"},
             "rect": [100, 100, 200, 30], "children": []},
            {"tag": "button", "attrs": {"id": "login", "class": "btn primary", "text": "登录"},
             "rect": [100, 200, 120, 40], "children": []},
            {"tag": "a", "attrs": {"class": "btn", "text": "注册"},
             "rect": [100, 300, 60, 20], "children": []},
        ]},
    ]},
})


def test_parse_and_hit() -> bool:
    root = T.parse_snapshot(_SNAP, "web")
    cnt = sum(1 for _ in root.iter_all())
    root_ok = root.bounds == (0, 0, 1000, 800)
    # 命中按钮（最小包含控件）
    hit = T.hit_test(root, 160, 220)
    hit_ok = hit is not None and hit.tag == "button" and hit.attrs.get("id") == "login"
    ok = root_ok and cnt == 5 and hit_ok
    print("Web 解析+命中:", "✅" if ok else "❌", f"({cnt} 节点)")
    return ok


def test_web_locators() -> bool:
    root = T.parse_snapshot(_SNAP, "web")
    btn = next(n for n in root.iter_all() if n.attrs.get("id") == "login")
    inp = next(n for n in root.iter_all() if n.attrs.get("name") == "user")
    a = next(n for n in root.iter_all() if n.tag == "a")
    blocs = [loc for _, loc in T.generate_locators(root, btn, "web")]
    ilocs = [loc for _, loc in T.generate_locators(root, inp, "web")]
    alocs = [loc for _, loc in T.generate_locators(root, a, "web")]
    btn_ok = "id::login" in blocs and "css::#login" in blocs and "css::.primary" in blocs
    inp_ok = "css::[name='user']" in ilocs
    # class "btn" 非唯一(button+a 都有) → 不应作为唯一 class；text→xpath
    a_ok = any("normalize-space()='注册'" in s for s in alocs) and "css::.btn" not in alocs
    # 末尾都有绝对 xpath 兜底
    fallback = all(any(s.startswith("xpath::/") for s in g) for g in (blocs, ilocs, alocs))
    ok = btn_ok and inp_ok and a_ok and fallback
    print("Web 候选定位符:", "✅" if ok else "❌", blocs[:3])
    return ok


def test_zero_size_container_keeps_children() -> bool:
    """父级 rect 为 0 但子链接可见时，子节点仍应进树（百度顶栏类布局）。"""
    snap = json.dumps({
        "viewport": [800, 600], "dpr": 1,
        "tree": {"tag": "html", "attrs": {}, "rect": [0, 0, 800, 600], "children": [
            {"tag": "body", "attrs": {}, "rect": [0, 0, 800, 600], "children": [
                {"tag": "div", "attrs": {"class": "s_top_container"}, "rect": [0, 0, 0, 0],
                 "children": [
                     {"tag": "a", "attrs": {"class": "mnav", "text": "新闻", "href": "http://news"},
                      "rect": [24, 19, 26, 23],
                      "loc": {"css": "a.mnav", "xpath": "//a[normalize-space()='新闻']"}, "children": []},
                 ]},
            ]},
        ]},
    })
    root = T.parse_snapshot(snap, "web")
    a = next((n for n in root.iter_all() if n.tag == "a"), None)
    hit = T.hit_test(root, 30, 25)
    ok = (a is not None and a.attrs.get("text") == "新闻"
          and hit is not None and hit.tag == "a")
    print("零尺寸容器保留子链接:", "✅" if ok else "❌")
    return ok


def test_browser_validated_loc() -> bool:
    """浏览器内已校验的 loc{id,css,xpath} 应被原样带上并优先于启发式。"""
    snap = json.dumps({
        "viewport": [800, 600], "dpr": 1,
        "tree": {"tag": "html", "attrs": {}, "rect": [0, 0, 800, 600], "children": [
            {"tag": "button", "attrs": {"id": "go"}, "rect": [10, 10, 80, 30],
             "loc": {"id": "go", "css": "#go", "xpath": "//*[@id='go']"}, "children": []},
        ]},
    })
    root = T.parse_snapshot(snap, "web")
    btn = next(n for n in root.iter_all() if n.tag == "button")
    carried = btn.locators == [("id", "id::go"), ("css", "css::#go"), ("xpath", "xpath:://*[@id='go']")]
    locs = [loc for _, loc in T.generate_locators(root, btn, "web")]
    prefer = locs[:3] == ["id::go", "css::#go", "xpath:://*[@id='go']"]
    ok = carried and prefer
    print("浏览器校验定位符直采:", "✅" if ok else "❌")
    return ok


def test_nested_span_text_for_automation() -> bool:
    """<a><span>文案</span></a>：自动化常用，父节点应带上可定位文案。"""
    snap = json.dumps({
        "viewport": [400, 300], "dpr": 1,
        "tree": {"tag": "html", "attrs": {}, "rect": [0, 0, 400, 300], "children": [
            {"tag": "a", "attrs": {"href": "/x", "text": "登录"}, "rect": [10, 10, 50, 20],
             "loc": {"xpath": "//a[normalize-space()='登录']"}, "children": [
                {"tag": "span", "attrs": {"text": "登录"}, "rect": [12, 12, 40, 16], "children": []},
            ]},
        ]},
    })
    root = T.parse_snapshot(snap, "web")
    a = next(n for n in root.iter_all() if n.tag == "a")
    locs = [loc for _, loc in T.generate_locators(root, a, "web")]
    ok = a.attrs.get("text") == "登录" and any("normalize-space()='登录'" in s for s in locs)
    print("嵌套 span 文案定位:", "✅" if ok else "❌")
    return ok


def test_data_attr_locator() -> bool:
    root = T.parse_snapshot(json.dumps({
        "viewport": [400, 300], "dpr": 1,
        "tree": {"tag": "html", "attrs": {}, "rect": [0, 0, 400, 300], "children": [
            {"tag": "div", "attrs": {"data-role": "submit", "class": "x"},
             "rect": [0, 0, 10, 10], "children": []},
        ]},
    }), "web")
    div = next(n for n in root.iter_all() if n.tag == "div")
    locs = [loc for _, loc in T.generate_locators(root, div, "web")]
    ok = "css::[data-role='submit']" in locs
    print("data-* 候选定位符:", "✅" if ok else "❌", locs)
    return ok


def main() -> int:
    ok = all([test_parse_and_hit(), test_web_locators(),
              test_zero_size_container_keeps_children(),
              test_nested_span_text_for_automation(), test_data_attr_locator(),
              test_browser_validated_loc()])
    print("\n总结:", "✅ Web 检视全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
