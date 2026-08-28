"""工程内检索逻辑回归（纯函数，无 GUI 搜索页）。"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import autopilot.keywords  # noqa: F401
from autopilot.ui.widgets.search_view import (
    search_project, find_references, find_in_project, resolve_keyword_ids,
)


def _mk_project(tmp):
    with open(os.path.join(tmp, "login.tc.yaml"), "w", encoding="utf-8") as f:
        f.write("type: testcase\nname: login\nshells:\n  case:\n"
                "    - step: web_element_click\n      params:\n        locator: id::loginBtn\n")
    with open(os.path.join(tmp, "home.tc.yaml"), "w", encoding="utf-8") as f:
        f.write("type: testcase\nname: home\nshells:\n  case:\n"
                "    - step: web_browser_open\n      params:\n        url: http://x\n")


def test_search_logic() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        _mk_project(tmp)
        hits_click = search_project(tmp, "web_element_click")
        hits_open = search_project(tmp, "browser_open")
        hits_none = search_project(tmp, "不存在的词xyz")
    ok = (len(hits_click) == 1 and hits_click[0][0].endswith("login.tc.yaml")
          and len(hits_open) == 1 and hits_open[0][0].endswith("home.tc.yaml")
          and hits_none == [])
    print("检索逻辑:", "✅" if ok else "❌")
    return ok


def test_find_references() -> bool:
    """查找引用：内建关键字按 step: 引用、ks:: 按 stepverbs 引用、map:: 字面引用；
    且避开注释里的同名子串（全文会命中、引用不命中）。"""
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "a.tc.yaml"), "w", encoding="utf-8") as f:
            f.write("type: testcase\nname: a\nshells:\n  case:\n"
                    "    - step: web_element_click\n      params:\n        locator: map::pg::btn\n"
                    "    - stepverbs: helper\n")
        with open(os.path.join(tmp, "b.tc.yaml"), "w", encoding="utf-8") as f:
            f.write("type: testcase\nname: b\nshells:\n  case:\n"
                    "    - step: log\n      comment: 调用 web_element_click 之前先等待\n")
        ref_click = find_references(tmp, "web_element_click")
        ref_ks = find_references(tmp, "ks::helper")
        ref_map = find_references(tmp, "map::pg::btn")
        full_click = search_project(tmp, "web_element_click")
        # 精确语义仍避开注释；底栏统一入口对同名全文会回退命中注释行
        unified_exact = find_in_project(tmp, "web_element_click")
        unified_comment = find_in_project(tmp, "调用 web_element_click")
    ok = (len(ref_click) == 1 and ref_click[0][0].endswith("a.tc.yaml")
          and len(ref_ks) == 1 and len(ref_map) == 1
          and len(full_click) == 2
          and len(unified_exact) == 1
          and len(unified_comment) >= 1)
    print("查找引用(step/ks::/map:: 精准，避开注释):", "✅" if ok else "❌",
          f"ref={len(ref_click)} full={len(full_click)}")
    return ok


def test_find_in_project_resolve() -> bool:
    """中文名/id 子串解析后查引用；无引用时回退全文。"""
    kids = resolve_keyword_ids("安装")
    ok_resolve = any("install" in k.lower() for k in kids)
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "m.tc.yaml"), "w", encoding="utf-8") as f:
            f.write("type: testcase\nname: m\nshells:\n  case:\n"
                    "    - step: mobile_app_install_and_open\n"
                    "      params:\n        appFile: /a.ipa\n"
                    "    - step: log\n      params:\n        message: hello mobile world\n")
        by_cn = find_in_project(tmp, "安装")
        by_sub = find_in_project(tmp, "mobile")
        by_text = find_in_project(tmp, "hello mobile")
    ok_cn = any("mobile_app_install_and_open" in (h[2] or "") for h in by_cn)
    ok_sub = any("mobile_app_install_and_open" in (h[2] or "") for h in by_sub)
    ok_text = len(by_text) >= 1
    ok = ok_resolve and ok_cn and ok_sub and ok_text
    print("中文名/子串/全文回退:", "✅" if ok else "❌",
          dict(resolve=len(kids), cn=len(by_cn), sub=len(by_sub), text=len(by_text)))
    return ok


def main() -> int:
    ok = all([test_search_logic(), test_find_references(), test_find_in_project_resolve()])
    print("\n总结:", "✅ 工程检索逻辑全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
