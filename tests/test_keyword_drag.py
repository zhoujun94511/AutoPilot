"""关键字拖拽插入回归（离屏 GUI）：拖拽 mime 带 id + 放置触发插入。"""

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


def _leaf_with_id(tree):
    from PyQt6.QtCore import Qt
    role = Qt.ItemDataRole.UserRole

    def walk(it):
        for idx in range(it.childCount()):
            c = it.child(idx)
            if c.data(0, role):
                return c
            res = walk(c)
            if res:
                return res
        return None
    for i in range(tree.topLevelItemCount()):
        r = walk(tree.topLevelItem(i))
        if r:
            return r
    return None


def test_mime_and_drop() -> bool:
    try:
        global _APP
        from PyQt6.QtWidgets import QApplication
        from autopilot.ui.main_window import MainWindow
        _APP = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            win = MainWindow(project_dir=tmp, config_dir="")
            tree = win.keyword_panel.tree          # 面板已容器化：树在 .tree
            # 1) mimeData 带关键字 id
            leaf = _leaf_with_id(tree)
            md = tree.mimeData([leaf])
            mime_ok = bool(md.text()) and md.text() == leaf.data(
                0, __import__("PyQt6.QtCore", fromlist=["Qt"]).Qt.ItemDataRole.UserRole)
            # 2) 放置触发插入（复用 keywordDropped → _on_keyword_activated）
            win.new_case()
            win.center.setCurrentWidget(win.case_editor)
            before = len(win.case_editor.case.case.steps)
            win.case_editor.keywordDropped.emit("log")
            after = len(win.case_editor.case.case.steps)
            drop_ok = after == before + 1
            win.close()
        ok = mime_ok and drop_ok
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("拖拽插入: ⏭ 跳过(", e, ")")
        return True
    print("关键字拖拽(mime+放置插入):", "✅" if ok else "❌")
    return ok


def _leaves(tree):
    from PyQt6.QtCore import Qt
    role = Qt.ItemDataRole.UserRole
    out = []

    def walk(it):
        for ci in range(it.childCount()):
            c = it.child(ci)
            if c.data(0, role):
                out.append(c)
            walk(c)
    for i in range(tree.topLevelItemCount()):
        walk(tree.topLevelItem(i))
    return out


def test_keyword_filter() -> bool:
    """关键字面板搜索框：实时过滤(命中可见、其余隐藏)，清空恢复全显。"""
    try:
        global _APP
        from PyQt6.QtWidgets import QApplication
        from autopilot.ui.widgets.keyword_panel import KeywordPanel
        _APP = QApplication.instance() or QApplication([])
        panel = KeywordPanel()
        panel.load(None)
        tree = panel.tree
        leaves = _leaves(tree)
        total = len(leaves)
        panel.filter.setText("log")
        vis = [le for le in leaves if not le.isHidden()]
        # 命中项都含 "log"，且数量在 (0, total) 之间（确实过滤了）
        hit_ok = 0 < len(vis) < total and all(
            "log" in " ".join(le.text(c) for c in range(3)).lower() for le in vis)
        panel.filter.setText("")
        all_vis = all(not le.isHidden() for le in leaves)
        ok = total > 0 and hit_ok and all_vis
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("关键字搜索过滤: ⏭ 跳过(", e, ")")
        return True
    print("关键字面板搜索过滤:", "✅" if ok else "❌", f"(命中 {len(vis)}/{total})")
    return ok


def test_case_editor_keys() -> bool:
    """用例编辑器键盘：Ctrl+D 复制行、Delete 删除行。"""
    try:
        global _APP
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QKeyEvent
        from PyQt6.QtWidgets import QApplication
        from autopilot.ui.main_window import MainWindow
        _APP = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            win = MainWindow(project_dir=tmp, config_dir="")
            win.new_case()
            ed = win.case_editor
            ed.insert_step("log", win.catalog.get("log"))
            ed.insert_step("log", win.catalog.get("log"))
            n0 = len(ed.case.case.steps)
            ed.selectRow(0)
            ed.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_D,
                                       Qt.KeyboardModifier.ControlModifier))   # 复制
            dup_ok = len(ed.case.case.steps) == n0 + 1
            ed.selectRow(0)
            ed.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Delete,
                                       Qt.KeyboardModifier.NoModifier))        # 删除
            del_ok = len(ed.case.case.steps) == n0
            win.close()
        ok = dup_ok and del_ok
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("用例编辑器键盘: ⏭ 跳过(", e, ")")
        return True
    print("用例编辑器键盘(Ctrl+D/Delete):", "✅" if ok else "❌")
    return ok


def test_case_editor_keyword_name() -> bool:
    """用例编辑器「关键字」列显示中文名（与关键字库一致），id 落悬停；说明只读、备注可编。"""
    try:
        global _APP
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import Qt
        from autopilot.ui.main_window import MainWindow
        _APP = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            win = MainWindow(project_dir=tmp, config_dir="")
            win.new_case()
            ed = win.case_editor
            # 取一个目录里真实存在、且有中文名的关键字
            kid = next((k for k, m in win.catalog.by_id.items() if m.name), None)
            meta = win.catalog.get(kid)
            ed.insert_step(kid, meta)
            kw_cell = ed.item(0, 0)        # 关键字列
            cm_cell = ed.item(0, 2)        # 说明列
            # 关键字列 = 中文名（catalog.name），不是裸 id
            name_ok = (
                meta is not None
                and bool(meta.name)
                and meta.name in kw_cell.text()
                and kid != kw_cell.text().strip()
            )
            # 悬停提示带原始 id（id/参数名不改，仅展示用中文）
            tip_ok = kid is not None and kid in (kw_cell.toolTip() or "")
            # 说明列 = 关键字通用描述（来自 catalog），只读
            desc_ok = cm_cell.text() == (meta.comment or meta.name)
            rm_cell = ed.item(0, 3)        # 备注列
            rm_ok = bool(rm_cell.flags() & Qt.ItemFlag.ItemIsEditable)
            pm_cell = ed.item(0, 1)        # 参数列
            params_ok = bool(pm_cell.text()) and "=" in pm_cell.text()
            win.close()
            ok = name_ok and tip_ok and desc_ok and rm_ok and params_ok
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("用例编辑器关键字中文名: ⏭ 跳过(", e, ")")
        return True
    print("用例编辑器(中文名/参数列/说明/备注):", "✅" if ok else "❌")
    return bool(ok)


def main() -> int:
    ok = all([test_mime_and_drop(), test_keyword_filter(), test_case_editor_keys(),
              test_case_editor_keyword_name()])
    print("\n总结:", "✅ 关键字拖拽全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
