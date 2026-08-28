"""阶段10.3 自定义关键字(.ks)编辑器 + 库视图回归。

覆盖：KeywordDef 的 YAML 序列化 round-trip、.ks.yaml 被仓库发现、
以及离屏 GUI 下的编辑器流程（新建→插入步骤→改 id→保存→重载；用例里插入 StepVerbs）。
"""

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # 必须在导入 PyQt 前设置
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import autopilot.keywords  # noqa: F401
from autopilot.model import serializer
from autopilot.model.keyworddef import KeywordDef, LocalParam
from autopilot.model.testcase import Step, StepVerbs, ParamValue
from autopilot.engine.keyword_store import discover_keywords


def test_serializer_roundtrip() -> bool:
    kd = KeywordDef(ks_id="login_verb", tag="WEB",
                    params=[LocalParam("user", default="admin"), LocalParam("pwd")])
    kd.steps = [Step("log", comment="打日志", params=[ParamValue("message", "${user}")]),
                Step("set_var", params=[ParamValue("name", "x"), ParamValue("value", "1")])]
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "login.ks.yaml")
        serializer.save_keyword(kd, p)
        kd2 = serializer.load(p)
    ok = (kd2.ks_id == "login_verb" and kd2.tag == "WEB"
          and len(kd2.params) == 2 and kd2.param("user").default == "admin"
          and len(kd2.steps) == 2 and isinstance(kd2.steps[0], Step)
          and kd2.steps[0].param("message") == "${user}")
    print("KeywordDef 序列化 round-trip:", "✅" if ok else "❌")
    return ok


def test_discovery() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        serializer.save_keyword(KeywordDef(ks_id="greet_verb"),
                                os.path.join(tmp, "greet.ks.yaml"))
        store = discover_keywords(tmp)
    ok = store.get("greet_verb") is not None
    print(".ks.yaml 被仓库发现:", "✅" if ok else "❌")
    return ok


def test_gui_flow() -> bool:
    try:
        from PyQt6.QtWidgets import QApplication
        from autopilot.ui.main_window import MainWindow
    except Exception as e:  # noqa: BLE001  无 GUI 平台则跳过
        print("GUI 编辑器流程: ⏭ 跳过(", e, ")")
        return True
    _app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        # 预置一个自定义关键字，验证库视图能挂载
        serializer.save_keyword(KeywordDef(ks_id="greet_verb"),
                                os.path.join(tmp, "greet.ks.yaml"))
        win = MainWindow(project_dir=tmp, config_dir="")
        custom_top = getattr(win.keyword_panel.tree, "_custom_top", None)
        has_custom = custom_top is not None and custom_top.childCount() >= 1
        # 关键字库分栏：关键字 / ID / 说明（3 列）——面板已容器化，列在 .tree 上
        assert win.keyword_panel.tree.columnCount() == 3, "关键字库应为 3 列分栏"

        # 新建自定义关键字 → 插入步骤 → 改 id → 保存 → 重载
        win.new_custom_keyword()
        win.keyword_editor.insert_step("log", None)
        win.keyword_editor.ed_id.setText("my_verb")
        win._save_keyword()
        out = os.path.join(tmp, "my_verb.ks.yaml")
        reloaded = serializer.load(out) if os.path.exists(out) else None
        edit_ok = (reloaded is not None and reloaded.ks_id == "my_verb"
                   and len(reloaded.steps) == 1)

        # 用例里插入自定义关键字调用(StepVerbs)
        win.new_case()
        win.center.setCurrentWidget(win.case_editor)
        win._on_keyword_activated("ks::greet_verb")
        sv = [n for n in win.case_editor.case.case.steps if isinstance(n, StepVerbs)]
        insert_ok = len(sv) == 1 and sv[0].ks_id == "greet_verb"
        win.close()
    ok = has_custom and edit_ok and insert_ok
    print("GUI 编辑器流程:", "✅" if ok else "❌",
          f"(库挂载={has_custom} 编辑保存={edit_ok} 插入调用={insert_ok})")
    return ok


def main() -> int:
    ok = all([test_serializer_roundtrip(), test_discovery(), test_gui_flow()])
    print("\n总结:", "✅ 自定义关键字编辑器全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
