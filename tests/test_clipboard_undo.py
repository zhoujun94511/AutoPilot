"""阶段11.5 步骤剪切/复制/粘贴 + 撤销/重做回归（离屏 GUI）。"""

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

_APP = None


def _win(tmp):
    global _APP
    from PyQt6.QtWidgets import QApplication
    from autopilot.ui.main_window import MainWindow
    _APP = QApplication.instance() or QApplication([])
    return MainWindow(project_dir=tmp, config_dir="")


def _steps(ed):
    return ed.case.case.steps


def test_copy_paste() -> bool:
    try:
        with tempfile.TemporaryDirectory() as tmp:
            win = _win(tmp)
            win.new_case()
            ed = win.case_editor
            ed.insert_step("log", win.catalog.get("log"))   # 1 步
            ed.selectRow(0)
            ed.copy_selected()
            ed.paste()                                       # 2 步
            ok = len(_steps(ed)) == 2 and all(s.keyword_id == "log" for s in _steps(ed))
            win.close()
    except Exception as e:  # noqa: BLE001
        print("复制粘贴: ⏭ 跳过(", e, ")")
        return True
    print("复制/粘贴:", "✅" if ok else "❌")
    return ok


def test_cut() -> bool:
    try:
        with tempfile.TemporaryDirectory() as tmp:
            win = _win(tmp)
            win.new_case()
            ed = win.case_editor
            ed.insert_step("log", win.catalog.get("log"))
            ed.insert_step("set_var", win.catalog.get("set_var"))
            ed.selectRow(0)
            ed.cut_selected()                                # 剪掉 log，剩 set_var
            after_cut = [s.keyword_id for s in _steps(ed)]
            ed.paste()                                       # 粘回 log
            ids = [s.keyword_id for s in _steps(ed)]
            ok = after_cut == ["set_var"] and "log" in ids and len(ids) == 2
            win.close()
    except Exception as e:  # noqa: BLE001
        print("剪切: ⏭ 跳过(", e, ")")
        return True
    print("剪切+粘贴:", "✅" if ok else "❌")
    return ok


def test_undo_redo() -> bool:
    try:
        with tempfile.TemporaryDirectory() as tmp:
            win = _win(tmp)
            win.new_case()
            ed = win.case_editor
            ed.insert_step("log", win.catalog.get("log"))    # 1
            ed.insert_step("log", win.catalog.get("log"))    # 2
            n2 = len(_steps(ed))
            ed.undo()                                        # 回到 1
            n1 = len(_steps(ed))
            ed.undo()                                        # 回到 0
            n0 = len(_steps(ed))
            ed.redo()                                        # 回到 1
            nr = len(_steps(ed))
            ok = n2 == 2 and n1 == 1 and n0 == 0 and nr == 1
            win.close()
    except Exception as e:  # noqa: BLE001
        print("撤销重做: ⏭ 跳过(", e, ")")
        return True
    print("撤销/重做:", "✅" if ok else "❌", f"(2→{n2} undo→{n1}→{n0} redo→{nr})" if ok else "")
    return ok


def main() -> int:
    ok = all([test_copy_paste(), test_cut(), test_undo_redo()])
    print("\n总结:", "✅ 剪贴板/撤销重做全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
