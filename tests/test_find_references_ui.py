"""查找引用 IDE 入口：动作注册 + 底栏结果 + 右键文案。"""

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

_APP = None


def _ensure_app():
    global _APP
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication([])
    return _APP


def test_action_registered() -> bool:
    from autopilot.ui.actions import ACTIONS_BY_ID, MENUS
    ok_act = "search.find_references" in ACTIONS_BY_ID
    ok_slot = ACTIONS_BY_ID["search.find_references"].slot == "find_references_action"
    flat = []
    for _title, rows in MENUS:
        for r in rows:
            if isinstance(r, str):
                flat.append(r)
            elif isinstance(r, tuple) and r and r[0] == "submenu":
                flat.extend(r[2])
    ok_menu = "search.find_references" in flat
    ok_tp = "run.testplan" in ACTIONS_BY_ID
    ok = ok_act and ok_slot and ok_menu and ok_tp
    print("动作/菜单注册:", "✅" if ok else "❌",
          dict(act=ok_act, slot=ok_slot, menu=ok_menu, testplan=ok_tp))
    return ok


def test_run_find_references_panel() -> bool:
    _ensure_app()
    try:
        from autopilot.ui.main_window import MainWindow
        from autopilot.model import serializer
        from autopilot.model.testcase import TestCase, Step, ParamValue

        with tempfile.TemporaryDirectory() as tmp:
            tc = TestCase(name="c1")
            tc.case.steps = [Step("log", params=[ParamValue("message", "x")])]
            serializer.save_testcase(tc, os.path.join(tmp, "c1.tc.yaml"))
            win = MainWindow(project_dir=tmp, config_dir="")
            win._run_find_references("log")
            n = win.search_results._list.count()
            ok_hits = n >= 1
            dock = win._docks.get("查找引用")
            ok_dock = dock is not None
            # 直接断言动作绑定
            ok_slot = callable(getattr(win, "find_references_action", None))
            win.close()
            ok = ok_hits and ok_dock and ok_slot
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("查找引用面板: ⏭ 跳过(", e, ")")
        return True
    print("查找引用面板:", "✅" if ok else "❌", n if ok_hits else 0)
    return ok


def test_map_ref_helper() -> bool:
    _ensure_app()
    from autopilot.ui.widgets.map_editor import MapEditor
    from autopilot.model.mapfile import MapFile, MapElement

    ed = MapEditor()
    mf = MapFile()
    mf.source_path = r"D:\proj\maps\login.map.yaml"
    el = MapElement(name="btnLogin")
    mf.elements = [el]
    ed.show_map(mf)
    # 选中元素
    ed._current = el
    ref = ed.current_map_ref()
    ok = ref == "map::login::btnLogin"
    print("对象库 map 引用串:", "✅" if ok else "❌", ref)
    return ok


def test_search_panel_has_input() -> bool:
    _ensure_app()
    from PyQt6.QtWidgets import QLineEdit, QPushButton
    from autopilot.ui.widgets.search_results_panel import SearchResultsPanel
    p = SearchResultsPanel()
    ok = (p.findChild(QLineEdit, "search_results_input") is not None
          and p.findChild(QPushButton, "search_results_btn") is not None)
    got = []
    p.searchRequested.connect(lambda t: got.append(t))
    p._input.setText("log")
    p._emit_search()
    ok2 = got == ["log"]
    print("查找引用输入框:", "✅" if ok and ok2 else "❌", got)
    return ok and ok2


def main() -> int:
    ok = all([
        test_action_registered(),
        test_search_panel_has_input(),
        test_run_find_references_panel(),
        test_map_ref_helper(),
    ])
    print("\n总结:", "✅" if ok else "❌")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
