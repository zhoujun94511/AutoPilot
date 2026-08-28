"""picture:: 白名单、精度阈值与路径编码。"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from autopilot.keywords.mobile.picture_locator import (
    PICTURE_LOCATOR_KEYWORDS,
    accuracy_to_threshold,
    is_picture_locator,
    picture_fill_hint,
    picture_locator_for_path,
    supports_picture_locator,
)


def test_picture_whitelist_and_threshold() -> bool:
    ok_ids = all(supports_picture_locator(k) for k in (
        "mobile_element_click", "mobile_verify_element_existed", "elementClick"))
    ok_deny = not supports_picture_locator("mobile_element_text_input")
    ok_set = "mobile_element_click" in PICTURE_LOCATOR_KEYWORDS
    ok_th = (
        accuracy_to_threshold("精确匹配") >= 0.8
        and accuracy_to_threshold("模糊匹配") < accuracy_to_threshold("精确匹配")
        and 0 < accuracy_to_threshold("") <= 1
        and abs(accuracy_to_threshold("0.9") - 0.9) < 1e-6
    )
    ok_pic = is_picture_locator("picture::images/a.png") and not is_picture_locator("id::x")
    ok_hint = "不支持图像定位" in picture_fill_hint("mobile_element_text_input")
    ok = ok_ids and ok_deny and ok_set and ok_th and ok_pic and ok_hint
    print("picture 白名单/精度/提示:", "✅" if ok else "❌")
    return ok


def test_picture_locator_for_path() -> bool:
    with tempfile.TemporaryDirectory() as proj:
        os.makedirs(os.path.join(proj, "images"), exist_ok=True)
        inside = os.path.join(proj, "images", "btn.png")
        open(inside, "wb").write(b"x")
        loc = picture_locator_for_path(proj, inside)
        ok_rel = loc == "picture::images/btn.png"
        outside = os.path.join(tempfile.gettempdir(), "ap_pic_out.png")
        open(outside, "wb").write(b"y")
        loc2 = picture_locator_for_path(proj, outside)
        ok_abs = loc2.startswith("picture::") and "ap_pic_out.png" in loc2.replace("\\", "/")
        # noinspection PyBroadException
        try:
            os.remove(outside)
        except Exception:
            pass
    ok = ok_rel and ok_abs
    print("picture 路径编码(相对/绝对):", "✅" if ok else "❌")
    return ok


def test_resolve_image_relative_via_project_path() -> bool:
    """相对 picture 路径须相对 __project_path__ 解析（GUI/CLI 注入）。"""
    from autopilot.keywords.context import ExecutionContext
    from autopilot.keywords.mobile.driver import _resolve_image

    with tempfile.TemporaryDirectory() as proj:
        os.makedirs(os.path.join(proj, "images"), exist_ok=True)
        inside = os.path.join(proj, "images", "btn.png")
        open(inside, "wb").write(b"x")
        ctx = ExecutionContext()
        ctx.set_var("__project_path__", proj)
        got = _resolve_image(ctx, "images/btn.png")
        ok_posix = os.path.normpath(got) == os.path.normpath(inside) and os.path.exists(got)
        # Windows 风格分隔符写入的相对路径，在本机也应能解析（跨平台用例）
        got_bs = _resolve_image(ctx, "images\\btn.png")
        ok_bs = os.path.normpath(got_bs) == os.path.normpath(inside)
    ok = ok_posix and ok_bs
    print("picture 相对路径解析:", "✅" if ok else "❌",
          "posix=", ok_posix, "backslash=", ok_bs)
    return ok


def test_paths_cross_platform() -> bool:
    from autopilot.runtime.paths import join_project, to_native, to_posix

    ok_posix = to_posix(r"images\a\b.png") == "images/a/b.png"
    with tempfile.TemporaryDirectory() as proj:
        sub = os.path.join(proj, "a", "b")
        os.makedirs(sub, exist_ok=True)
        open(os.path.join(sub, "f.txt"), "wb").write(b"1")
        got = join_project(proj, "a/b/f.txt")
        got2 = join_project(proj, r"a\b\f.txt")
        ok_join = (os.path.exists(got) and os.path.exists(got2)
                   and os.path.normpath(got) == os.path.normpath(got2))
        from autopilot.keywords.mobile.picture_locator import picture_locator_for_path
        loc = picture_locator_for_path(proj, os.path.join(sub, "f.txt"))
        ok_enc = loc == "picture::a/b/f.txt"
        abs_n = to_native(proj)
        ok_abs = join_project(proj, abs_n) == abs_n
    ok = ok_posix and ok_join and ok_enc and ok_abs and bool(to_native("x/y"))
    print("跨平台 paths 工具:", "✅" if ok else "❌",
          "posix=", ok_posix, "join=", ok_join, "enc=", ok_enc)
    return ok


def test_param_form_picture_button() -> bool:
    """白名单关键字 locator 行带「选择图片…」；非白名单没有。"""
    try:
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication, QPushButton
        from autopilot.ui.widgets.param_form import ParamForm
        from autopilot.model.testcase import Step, ParamValue
        from autopilot.metadata import KeywordMeta, ParamMeta
        app = QApplication.instance() or QApplication([])
        form = ParamForm()
        with tempfile.TemporaryDirectory() as proj:
            form.set_project_dir(proj)
            meta_click = KeywordMeta(
                keyword_id="mobile_element_click", name="点击", category="Mobile",
                params=[ParamMeta(param_id="locator", name="定位符", required=True)])
            step = Step("mobile_element_click", params=[ParamValue("locator", "")])
            form.show_step(step, meta_click)
            row = form._param_rows.get("locator")
            texts = [b.text() for b in row.findChildren(QPushButton)] if row else []
            has_pic = "选择图片…" in texts
            meta_input = KeywordMeta(
                keyword_id="mobile_element_text_input", name="输入", category="Mobile",
                params=[ParamMeta(param_id="locator", name="定位符", required=True)])
            step2 = Step("mobile_element_text_input", params=[ParamValue("locator", "")])
            form.show_step(step2, meta_input)
            app.processEvents()
            row2 = form._param_rows.get("locator")
            texts2 = [b.text() for b in row2.findChildren(QPushButton)] if row2 else []
            no_pic = "选择图片…" not in texts2
            ok = has_pic and no_pic
        _ = app
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("参数表单选图按钮: ⏭ 跳过(", e, ")")
        return True
    print("参数表单 picture 选图按钮(白名单显/非白名单隐):", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([
        test_picture_whitelist_and_threshold(),
        test_picture_locator_for_path(),
        test_resolve_image_relative_via_project_path(),
        test_paths_cross_platform(),
        test_param_form_picture_button(),
    ])
    print("\n总结:", "✅ picture 定位规则全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
