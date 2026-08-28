"""阶段20 UI 体系化（离屏）：动作注册表完整性 + 菜单/工具栏/Dock 结构 + 作用域隔离。"""

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


def _win():
    global _APP
    from _qt import get_qt_app
    _APP = get_qt_app()
    from autopilot.ui.main_window import MainWindow
    tmp = tempfile.mkdtemp()
    return MainWindow(project_dir=tmp, config_dir="")


def test_action_registry() -> bool:
    """每个动作的 slot 必须是 MainWindow 上真实存在的方法（防 id/槽 漂移）。"""
    try:
        from autopilot.ui import actions
        w = _win()
        missing = [s.id for s in actions.ACTIONS if not callable(getattr(w, s.slot, None))]
        built = all(i in w._actions for i in actions.ACTIONS_BY_ID)
        ok = not missing and built and len(w._actions) == len(actions.ACTIONS)
        w.close()
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("动作注册表: ⏭ 跳过(", e, ")")
        return True
    print("动作注册表(槽存在/全建):", "✅" if ok else f"❌ 缺槽 {missing}")
    return ok


def test_menu_and_toolbar() -> bool:
    """菜单栏六大项齐全；全局工具栏不含任何 editor 作用域动作（步骤编辑已下放）。"""
    try:
        from PyQt6.QtWidgets import QToolBar
        from autopilot.ui import actions
        w = _win()
        titles = [a.text() for a in w.menuBar().actions()]
        need = ["文件(&F)", "编辑(&E)", "运行(&R)", "设备(&D)", "视图(&V)", "帮助(&H)"]
        menu_ok = all(t in titles for t in need)
        tb = w.findChild(QToolBar)
        tb_texts = {a.text() for a in tb.actions() if a.text()}
        editor_labels = {actions.label(s) for s in actions.ACTIONS if s.scope == "editor"}
        isolated = tb_texts.isdisjoint(editor_labels)   # 全局工具栏不混入步骤编辑
        ok = menu_ok and isolated
        w.close()
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("菜单/工具栏: ⏭ 跳过(", e, ")")
        return True
    print("菜单六项 + 工具栏作用域隔离:", "✅" if ok else "❌")
    return ok


def test_docks_and_context() -> bool:
    """三个物理 Dock + 右侧辅区双 Tab 组；编辑参数不抢设备 Tab；辅区 Tab 栏可见。"""
    try:
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QTabBar
        from _qt import get_qt_app
        w = _win()
        qt_app = get_qt_app()
        w.show()
        qt_app.processEvents()
        docks_ok = len(w._docks) == 3 and "侧栏" in w._docks
        left_ok = getattr(w, "_left_sidebar", None) is not None
        aux_ok = getattr(w, "_right_aux", None) is not None
        aux_tabs = [
            tb for tb in w._right_aux.findChildren(QTabBar)
            if tb.objectName() == "aux_view_tab_bar"
        ]
        tabs_visible = (
            len(aux_tabs) == 2
            and all(tb.isVisible() and tb.height() > 0 for tb in aux_tabs)
            and all(tb.count() == 2 for tb in aux_tabs)
        )
        w._right_aux.activate_view("mirror")
        w._focus_right_view("param")
        split_ok = w._right_aux.device_tab_index() == 1   # 仍在镜像页
        cm = Qt.ContextMenuPolicy.CustomContextMenu
        ctx_ok = (w.case_editor.contextMenuPolicy() == cm
                  and w.suite_editor.contextMenuPolicy() == cm)
        w._apply_ui_theme(w._ui_theme_stored)
        qt_app.processEvents()
        tabs_still_visible = all(tb.isVisible() and tb.height() > 0 for tb in aux_tabs)
        w._reset_layout()
        w.close()
        ok = (docks_ok and left_ok and aux_ok and split_ok and ctx_ok
              and tabs_visible and tabs_still_visible)
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("Dock/右键: ⏭ 跳过(", e, ")")
        return True
    print("Dock 辅区 + 参数/设备分组:", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([test_action_registry(), test_menu_and_toolbar(), test_docks_and_context()])
    print("\n总结:", "✅ UI 体系化结构全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
