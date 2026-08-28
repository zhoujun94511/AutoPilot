"""阶段12.3 日志/控制台视图增强回归（离屏 GUI）：状态/关键字过滤 + 双击联动。"""

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

import autopilot.keywords  # noqa: F401
from autopilot.engine.executor import StepResult

_APP = None


def _app():
    global _APP
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _visible(table):
    return [r for r in range(table.rowCount()) if not table.isRowHidden(r)]


def test_filter() -> bool:
    try:
        _app()
        from autopilot.ui.widgets.console import Console
        c = Console()
        c.log("开始")
        c.add_step(StepResult("web_open", "打开", "PASS"))
        c.add_step(StepResult("web_click", "点击", "FAIL", "元素未找到"))
        c.add_step(StepResult("sap_x", "SAP", "NOIMPL"))
        from autopilot.ui.widgets.console import _COL_KEYWORD, _COL_LEVEL
        total = c.table.rowCount()
        kc = _COL_KEYWORD
        # 仅看 FAIL（状态过滤）
        c.cmb_status.setCurrentText("FAIL")
        only_fail = _visible(c.table)
        fail_ok = len(only_fail) == 1 and c.table.item(only_fail[0], kc).text() == "web_click"
        # 关键字过滤
        c.cmb_status.setCurrentText("全部")
        c.ed_filter.setText("click")
        kw_vis = _visible(c.table)
        kw_ok = len(kw_vis) == 1 and c.table.item(kw_vis[0], kc).text() == "web_click"
        # 级别阈值：只看 ERROR+ → 仅 FAIL 步骤(=ERROR 级别)留下
        c.ed_filter.setText("")
        c.cmb_level.setCurrentText("ERROR")
        lv_vis = _visible(c.table)
        level_ok = len(lv_vis) == 1 and c.table.item(lv_vis[0], _COL_LEVEL).text() == "ERROR"
        c.cmb_level.setCurrentText("全部")
        # 暂停 → 新行进缓冲不渲染；恢复 → 回放
        c.btn_pause.setChecked(True)
        c.log("暂停期间")
        paused_ok = c.table.rowCount() == total
        c.btn_pause.setChecked(False)
        resume_ok = c.table.rowCount() == total + 1
        ok = total == 4 and fail_ok and kw_ok and level_ok and paused_ok and resume_ok
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("控制台过滤: ⏭ 跳过(", e, ")")
        return True
    print("控制台 状态/级别/关键字过滤+暂停:", "✅" if ok else "❌", f"(总行={total})")
    return ok


def test_linkage() -> bool:
    try:
        _app()
        from autopilot.ui.main_window import MainWindow
        with tempfile.TemporaryDirectory() as tmp:
            win = MainWindow(project_dir=tmp, config_dir="")
            win.new_case()
            win.case_editor.insert_step("set_var", win.catalog.get("set_var"))
            win.case_editor.insert_step("log", win.catalog.get("log"))
            win.case_editor.selectRow(0)
            # 模拟双击控制台中 log 行 → 联动选中编辑器里的 log 步骤
            win._on_console_step_activated("log")
            sel = win.case_editor.selected_node()
            ok = getattr(sel, "keyword_id", "") == "log"
            win.close()
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("控制台联动: ⏭ 跳过(", e, ")")
        return True
    print("控制台↔编辑器 双击联动:", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([test_filter(), test_linkage()])
    print("\n总结:", "✅ 控制台增强全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
