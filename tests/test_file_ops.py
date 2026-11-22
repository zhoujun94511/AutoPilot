"""阶段11.1 文件/工程操作回归（离屏 GUI，走纯逻辑助手，不弹对话框）。

覆盖：新建 用例/测试套/对象库/数据配置/文件夹、打开工程、重命名、删除。
"""

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# 把应用设置重定向到临时目录，避免 open_project/记住工程写到用户 ~/.autopilot
os.environ["AUTOPILOT_CONFIG_DIR"] = tempfile.mkdtemp(prefix="autopilot_cfg_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import autopilot.keywords  # noqa: F401
from autopilot.model import serializer


_APP = None  # 持有 QApplication 引用，防止被 GC（否则离屏插件会硬崩溃）


def _win(tmp):
    global _APP
    from PyQt6.QtWidgets import QApplication
    from autopilot.ui.main_window import MainWindow
    _APP = QApplication.instance() or QApplication([])
    return MainWindow(project_dir=tmp, config_dir="")


def test_create_resources() -> bool:
    try:
        with tempfile.TemporaryDirectory() as tmp:
            win = _win(tmp)
            paths = {k: win.create_resource(k, tmp, f"demo_{k}")
                     for k in ("case", "suite", "map", "dataconfig")}
            # 每个文件都生成且能被对应方式读回
            tc = serializer.load(paths["case"])
            mf = serializer.load(paths["map"])
            ts = serializer.load(paths["suite"])
            ok = (all(os.path.exists(p) for p in paths.values())
                  and tc.name == "demo_case" and mf.name == "demo_map"
                  and ts.name == "demo_suite"
                  and paths["dataconfig"].endswith(".properties"))
            win.close()
    except ImportError as e:
        print("新建资源: ⏭ 跳过(", e, ")")
        return True
    print("新建 用例/套件/对象库/数据配置:", "✅" if ok else "❌")
    return ok


def test_folder_rename_delete() -> bool:
    try:
        with tempfile.TemporaryDirectory() as tmp:
            win = _win(tmp)
            folder = win.create_folder(tmp, "sub")
            case = win.create_resource("case", folder, "c1")
            renamed = win.rename_path(case, "c2.tc.yaml")
            ok_rename = (not os.path.exists(case) and os.path.exists(renamed))
            win.delete_path(renamed)
            ok_del_file = not os.path.exists(renamed)
            win.delete_path(folder)
            ok_del_dir = not os.path.exists(folder)
            win.close()
        ok = ok_rename and ok_del_file and ok_del_dir
    except ImportError as e:
        print("文件夹/重命名/删除: ⏭ 跳过(", e, ")")
        return True
    print("文件夹/重命名/删除:", "✅" if ok else "❌")
    return ok


def test_open_project() -> bool:
    try:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            win = _win(tmp)
            win.create_resource("case", other, "x")
            win.open_project(other)
            ok = win.project_dir == other
            win.close()
    except ImportError as e:
        print("打开工程: ⏭ 跳过(", e, ")")
        return True
    print("打开工程:", "✅" if ok else "❌")
    return ok


def test_new_project_and_remember() -> bool:
    """空工作区启动 → 新建工程建目录并打开 → 记入「上次工程/最近列表」。"""
    try:
        from autopilot.runtime import settings
        with tempfile.TemporaryDirectory() as parent:
            win = _win("")                       # 不预设工程
            no_proj_ok = (win.project_dir or "") == ""
            path = win.create_project(parent, "proj1")
            win.open_project(path)
            # 自动骨架：config/DataConfig.properties（空模板）
            cfg = os.path.join(path, "config", "DataConfig.properties")
            ok = (no_proj_ok and os.path.isdir(path) and win.project_dir == path
                  and os.path.isfile(cfg)
                  and settings.last_project() == path
                  and path in settings.recent_projects())
            win.close()
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("新建工程/记住工程: ⏭ 跳过(", e, ")")
        return True
    print("新建工程 + 记住上次工程:", "✅" if ok else "❌")
    return ok


def test_keyword_resource_and_project_guard() -> bool:
    """新增：create_resource 支持 keyword(.ks.yaml)；无工程时落文件类新建被拦(不写 cwd)。"""
    try:
        from autopilot.model import serializer
        from autopilot.ui.main_window import MainWindow
        with tempfile.TemporaryDirectory() as proj:
            win = _win(proj)
            # keyword 资源：建 .ks.yaml 并能读回为 KeywordDef
            kp = win.create_resource("keyword", proj, "login_flow")
            kd = serializer.load(kp)
            kw_ok = kp.endswith(".ks.yaml") and os.path.exists(kp) and kd.ks_id == "login_flow"
            win.close()
        # 全新「无工程」窗口：_target_dir 不回退 cwd、_require_project 拦截
        w2 = MainWindow(project_dir="", config_dir="")
        target_ok = w2._target_dir() == ""
        guard_ok = w2._require_project() is False
        w2.close()
        ok = kw_ok and target_ok and guard_ok
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("关键字资源/无工程拦截: ⏭ 跳过(", e, ")")
        return True
    print("新建关键字(.ks)+无工程拦截:", "✅" if ok else "❌")
    return ok


def test_explorer_panel() -> bool:
    """工程浏览器(对标 VSCode)，纯组件级（不经主窗口，避免弹模态框）：
    头部新建/禁用、键盘 F2/Delete 信号、类型图标。"""
    try:
        import time
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QKeyEvent
        from PyQt6.QtWidgets import QApplication
        from autopilot.ui.widgets.project_panel import ProjectPanel
        from autopilot.ui.widgets.project_tree import ProjectTree, _file_icon, _suffix_kind
        app = QApplication.instance() or QApplication([])
        # 头部「新建▾」菜单 → newRequested(kind)（独立面板，不接主窗口 → 不弹框）
        panel = ProjectPanel()
        got = []
        # noinspection PyUnresolvedReferences
        panel.newRequested.connect(got.append)
        # noinspection PyProtectedMember
        for act in panel.toolbar._new_menu.actions():
            act.trigger()
        new_ok = got == ["case", "suite", "map", "dataconfig", "testplan", "keyword"]
        # 无工程禁用新建类
        panel.set_actions_enabled(False)
        disabled_ok = not panel.toolbar.btn_new.isEnabled() and not panel.toolbar.btn_folder.isEnabled()
        panel.set_actions_enabled(True)
        enabled_ok = panel.toolbar.btn_new.isEnabled()
        # 类型图标：归一后缀 + 各类型/文件夹有图标、未知后缀无
        ic_ok = (_suffix_kind("a.tc.yaml") == ".tc" and _suffix_kind("x.properties") == ".properties"
                 and _file_icon("a.tc.yaml", False) is not None
                 and _file_icon("d", True) is not None
                 and _file_icon("note.txt", False) is not None
                 and _file_icon("unknown.bin", False) is None)
        # 键盘 F2/Delete → 信号（独立树，选中根节点）
        with tempfile.TemporaryDirectory() as proj:
            open(os.path.join(proj, "k1.tc.yaml"), "w").close()
            t = ProjectTree()
            t.set_root(proj)
            deadline = time.monotonic() + 3
            while t._proxy.rowCount(t.rootIndex()) == 0 and time.monotonic() < deadline:
                app.processEvents(); time.sleep(0.02)
            sig = {"rename": 0, "delete": 0}
            # noinspection PyUnresolvedReferences
            t.renameRequested.connect(lambda: sig.__setitem__("rename", 1))
            # noinspection PyUnresolvedReferences
            t.deleteRequested.connect(lambda: sig.__setitem__("delete", 1))
            t.setCurrentIndex(t._proxy.index(0, 0, t.rootIndex()))   # 选工程根节点
            for key in (Qt.Key.Key_F2, Qt.Key.Key_Delete):
                t.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key,
                                          Qt.KeyboardModifier.NoModifier))
            key_ok = sig["rename"] == 1 and sig["delete"] == 1
        ok = new_ok and disabled_ok and enabled_ok and ic_ok and key_ok
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("工程浏览器(工具条/键盘/图标): ⏭ 跳过(", e, ")")
        return True
    print("工程浏览器(工具条/键盘/图标/禁用):", "✅" if ok else "❌")
    return ok


def test_tree_filter() -> bool:
    """工程树名称过滤(名称实时过滤)：嵌套文件也能过滤(预取整树+递归保留父目录)。"""
    try:
        import time
        from PyQt6.QtWidgets import QApplication
        from autopilot.ui.widgets.project_panel import ProjectPanel
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as base:
            proj = os.path.join(base, "AIID")
            os.makedirs(os.path.join(proj, "login"))
            open(os.path.join(proj, "login", "登录.tc.yaml"), "w").close()
            open(os.path.join(proj, "smoke.ts.yaml"), "w").close()
            panel = ProjectPanel()
            panel.tree.set_root(proj)

            def settle(s=2.0):
                end = time.monotonic() + s
                while time.monotonic() < end:
                    app.processEvents(); time.sleep(0.02)

            settle()
            panel.tree.expandAll(); settle()

            def leaves():
                out = []

                def walk(idx):
                    for i in range(panel.tree._proxy.rowCount(idx)):
                        c = panel.tree._proxy.index(i, 0, idx)
                        src = panel.tree._proxy.mapToSource(c)
                        if not panel.tree._fs.isDir(src):
                            out.append(panel.tree._proxy.data(c))
                        walk(c)
                walk(panel.tree.rootIndex())
                return sorted(out)

            all_ok = leaves() == ["smoke", "登录"]
            panel.filter.setText("登录"); settle()
            hit_ok = leaves() == ["登录"]          # 嵌套文件命中、smoke 被滤掉
            panel.filter.setText(""); settle()
            clear_ok = leaves() == ["smoke", "登录"]
        ok = all_ok and hit_ok and clear_ok
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("工程树过滤: ⏭ 跳过(", e, ")")
        return True
    print("工程树名称过滤(嵌套/递归保留):", "✅" if ok else "❌")
    return ok


def test_tree_resource_visibility() -> bool:
    """工程树只留工程根、用例目录和可编辑资源；安装包/日志/报告不进树。"""
    try:
        import time
        from PyQt6.QtWidgets import QApplication
        from autopilot.ui.widgets.project_panel import ProjectPanel
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as proj:
            os.makedirs(os.path.join(proj, "apk"))
            os.makedirs(os.path.join(proj, "ipa"))
            os.makedirs(os.path.join(proj, "reports"))
            os.makedirs(os.path.join(proj, "logs", "ios_monkey", "20260705_120000"))
            os.makedirs(os.path.join(proj, "diag_onboarding"))
            os.makedirs(os.path.join(proj, "config"))
            os.makedirs(os.path.join(proj, "login"))
            open(os.path.join(proj, "TEST001.tc.yaml"), "w").close()
            open(os.path.join(proj, "login", "登录.tc.yaml"), "w").close()
            open(os.path.join(proj, "smoke.ts.yaml"), "w").close()
            open(os.path.join(proj, "config", "DataConfig.properties"), "w").close()
            open(os.path.join(proj, "config", "api_env.yaml"), "w").close()
            open(os.path.join(proj, "TEST002_run.log"), "w").close()
            open(os.path.join(proj, "autopilot_report.html"), "w").close()
            open(os.path.join(proj, "autopilot_report_latest.html"), "w").close()
            open(os.path.join(proj, "apk", "app.apk"), "w").close()
            open(os.path.join(proj, "ipa", "app.ipa"), "w").close()
            open(os.path.join(proj, "reports", "r.html"), "w").close()
            open(os.path.join(proj, "diag_onboarding", "snap.png"), "w").close()
            open(os.path.join(proj, "logs", "ios_monkey", "latest.json"), "w").close()
            open(os.path.join(proj, "logs", "ios_monkey", "20260705_120000", "summary.json"), "w").close()
            open(os.path.join(proj, "logs", "ios_monkey", "20260705_120000", "events.jsonl"), "w").close()

            panel = ProjectPanel()
            panel.tree.set_root(proj)

            def settle(s=3.0):
                end = time.monotonic() + s
                while time.monotonic() < end:
                    app.processEvents()
                    time.sleep(0.02)

            settle()
            panel.tree.expandAll()
            settle()

            def dir_names():
                names = set()

                def walk(idx):
                    for i in range(panel.tree._proxy.rowCount(idx)):
                        c = panel.tree._proxy.index(i, 0, idx)
                        src = panel.tree._proxy.mapToSource(c)
                        name = panel.tree._fs.fileName(src)
                        if panel.tree._fs.isDir(src):
                            names.add(name)
                        walk(c)

                walk(panel.tree.rootIndex())
                return names

            def file_basenames():
                out = []

                def walk(idx):
                    for i in range(panel.tree._proxy.rowCount(idx)):
                        c = panel.tree._proxy.index(i, 0, idx)
                        src = panel.tree._proxy.mapToSource(c)
                        if not panel.tree._fs.isDir(src):
                            out.append(panel.tree._fs.fileName(src))
                        walk(c)

                walk(panel.tree.rootIndex())
                return sorted(out)

            dirs = dir_names()
            files = file_basenames()
            ok = (
                "apk" not in dirs and "ipa" not in dirs and "reports" not in dirs
                and "logs" not in dirs and "ios_monkey" not in dirs
                and "20260705_120000" not in dirs
                and "diag_onboarding" not in dirs
                and "login" in dirs and "config" in dirs
                and "app.apk" not in files and "app.ipa" not in files and "r.html" not in files
                and "TEST002_run.log" not in files
                and "autopilot_report.html" not in files
                and "autopilot_report_latest.html" not in files
                and "api_env.yaml" not in files
                and "latest.json" not in files and "summary.json" not in files
                and "events.jsonl" not in files
                and "TEST001.tc.yaml" in files and "登录.tc.yaml" in files
                and "smoke.ts.yaml" in files and "DataConfig.properties" in files
            )
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("工程树资源可见性: ⏭ 跳过(", e, ")")
        return True
    print("工程树资源可见性(只留用例资源/隐藏产物目录):", "✅" if ok else "❌", dirs, files)
    return ok


def test_run_checked() -> bool:
    """工程树复选框(勾选用例)：勾用例文件/勾目录全勾，面板「运行选中(N)」联动。"""
    try:
        import time
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication
        from autopilot.ui.widgets.project_panel import ProjectPanel
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as base:
            proj = os.path.join(base, "AIID")
            os.makedirs(os.path.join(proj, "cases"))
            tc1 = os.path.join(proj, "cases", "登录.tc.yaml")
            tc2 = os.path.join(proj, "cases", "支付.tc.yaml")
            for p in (tc1, tc2):
                open(p, "w").close()
            open(os.path.join(proj, "smoke.ts.yaml"), "w").close()   # 套件不可勾
            panel = ProjectPanel()
            panel.tree.set_root(proj)
            px = panel.tree._proxy

            def settle(s=2.0):
                end = time.monotonic() + s
                while time.monotonic() < end:
                    app.processEvents(); time.sleep(0.02)

            settle()
            panel.tree.expandAll(); settle()

            def find(name):           # 按显示名找 proxy 索引（深搜）
                def walk(idx):
                    for i in range(px.rowCount(idx)):
                        c = px.index(i, 0, idx)
                        if px.data(c) == name:
                            return c
                        r = walk(c)
                        if r is not None and r.isValid():
                            return r
                    return None
                return walk(panel.tree.rootIndex())

            def keys(paths):
                return sorted(os.path.normcase(os.path.realpath(path)) for path in paths)
            # 套件文件无复选框（flags 不含 Checkable）
            ts_idx = find("smoke")
            ts_no_box = not (px.flags(ts_idx) & Qt.ItemFlag.ItemIsUserCheckable)
            # 勾一个用例 → checked_paths 含它、按钮显计数
            px.setData(find("登录"), Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole)
            one_ok = keys(panel.tree.checked_paths()) == keys([tc1]) and panel.btn_run.isEnabled() \
                and "1" in panel.btn_run.toolTip()
            # 勾父目录 → 其下两个用例全勾、目录显全选态
            px.setData(find("cases"), Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole)
            dir_state = px.data(find("cases"), Qt.ItemDataRole.CheckStateRole)
            all_ok = keys(panel.tree.checked_paths()) == keys([tc1, tc2]) \
                and dir_state == Qt.CheckState.Checked
            # 取消其一 → 目录转三态
            px.setData(find("支付"), Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole)
            tri_ok = px.data(find("cases"), Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.PartiallyChecked
            # 清空 → 空集、按钮禁用
            panel.tree.clear_checks()
            clear_ok = panel.tree.checked_paths() == [] and not panel.btn_run.isEnabled()
            # 全选用例
            panel.tree.check_all_cases()
            all_ok2 = len(panel.tree.checked_paths()) == 2 and panel.btn_run.isEnabled()
            # 反选 → 全清空
            panel.tree.invert_visible_checks()
            invert_clear_ok = panel.tree.checked_paths() == [] and not panel.btn_run.isEnabled()
            # 再反选 → 全勾
            panel.tree.invert_visible_checks()
            invert_all_ok = len(panel.tree.checked_paths()) == 2
            panel.tree.clear_checks()
        ok = ts_no_box and one_ok and all_ok and tri_ok and clear_ok and all_ok2 \
            and invert_clear_ok and invert_all_ok
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("工程树勾选运行: ⏭ 跳过(", e, ")")
        return True
    print("工程树复选框选用例(勾文件/勾目录全勾/三态/清空):", "✅" if ok else "❌")
    return ok


def test_checked_paths_follow_rename_and_delete() -> bool:
    """批量运行勾选集随目录改名迁移，删除后清除旧路径。"""
    try:
        from autopilot.ui.widgets.project_panel import ProjectPanel
        with tempfile.TemporaryDirectory() as base:
            project = os.path.join(base, "project")
            old_dir = os.path.join(project, "cases")
            new_dir = os.path.join(project, "renamed_cases")
            os.makedirs(old_dir)
            old_case = os.path.join(old_dir, "login.tc.yaml")
            new_case = os.path.join(new_dir, "login.tc.yaml")
            open(old_case, "w").close()
            panel = ProjectPanel()
            panel.tree._proxy._checked = {panel.tree._proxy._norm(old_case): old_case}
            panel.tree.rebase_paths(old_dir, new_dir)
            # Simulate the filesystem rename after rebasing the in-memory set.
            os.rename(old_dir, new_dir)
            moved_ok = panel.tree.checked_paths() == [new_case]
            panel.tree.drop_paths(new_dir)
            dropped_ok = panel.tree.checked_paths() == []
            panel.deleteLater()
        ok = moved_ok and dropped_ok
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("勾选路径跟随重命名/删除: ⏭ 跳过(", e, ")")
        return True
    print("勾选路径跟随重命名/删除:", "✅" if ok else "❌")
    return ok


def test_rename_delete_dialog_display() -> bool:
    """重命名框去后缀显示且自动保留类型后缀；删除确认框只显示去后缀名、不暴露后缀/全路径。"""
    try:
        from PyQt6.QtWidgets import QInputDialog
        from autopilot.ui.main_window import files as files_mod
        with tempfile.TemporaryDirectory() as proj:
            win = _win(proj)
            case = win.create_resource("case", proj, "123")     # 123.tc.yaml
            win.project_tree.selected_path = lambda: case        # 跳过树异步加载
            # 重命名：输入去后缀名 "999" → 应自动补回 .tc.yaml
            orig_in = QInputDialog.getText
            QInputDialog.getText = staticmethod(lambda *a, **k: ("999", True))
            try:
                win.rename_dialog()
            finally:
                QInputDialog.getText = orig_in
            renamed = os.path.join(proj, "999.tc.yaml")
            rename_ok = os.path.exists(renamed) and not os.path.exists(case)
            # 删除确认框：捕获文案，应含去后缀名「999」，不含 .tc.yaml / 路径分隔符
            win.project_tree.selected_path = lambda: renamed
            seen = {}
            orig_q = files_mod.confirm
            files_mod.confirm = (lambda _s, _t, text, *a, **k:
                                 (seen.__setitem__("t", text) or True))
            try:
                win.delete_dialog()
            finally:
                files_mod.confirm = orig_q
            t = seen.get("t", "")
            msg_ok = ("999" in t and ".tc.yaml" not in t and "/" not in t and "\\" not in t)
            del_ok = not os.path.exists(renamed)
            win.close()
        ok = rename_ok and msg_ok and del_ok
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("重命名/删除框去后缀: ⏭ 跳过(", e, ")")
        return True
    print("重命名去后缀保留类型 + 删除框不显后缀/路径:", "✅" if ok else "❌")
    return ok


def test_delete_closes_open_tab() -> bool:
    """删除正在编辑的用例：应关闭其标签，编辑区不残留已删内容（对齐用户反馈的 bug）。"""
    try:
        from autopilot.ui.main_window import files as files_mod
        with tempfile.TemporaryDirectory() as proj:
            win = _win(proj)
            case = win.create_resource("case", proj, "TEST001")
            win._on_file_activated(case)             # 打开成标签
            opened = win._doc_index(case) >= 0
            win.project_tree.selected_path = lambda: case
            refreshed = {"n": 0}                      # 探针：删除后应刷新关键字库(.ks 同步)
            win._refresh_custom_keywords = lambda: refreshed.__setitem__("n", refreshed["n"] + 1)
            orig = files_mod.confirm
            files_mod.confirm = lambda *a, **k: True    # 自动确认删除
            try:
                win.delete_dialog()
            finally:
                files_mod.confirm = orig
            closed = (win._doc_index(case) < 0 and not os.path.exists(case)
                      and refreshed["n"] >= 1)
            # 删完无其它标签、工程仍开着 → 空编辑区，而不是欢迎页
            back_to_idle = win.center.currentWidget() is win.empty_workspace
            win.close()
        ok = opened and closed and back_to_idle
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("删除关闭标签: ⏭ 跳过(", e, ")")
        return True
    print("删除用例关闭其标签+回空编辑区:", "✅" if ok else "❌")
    return ok


def test_rename_and_switch_project_sync() -> bool:
    """重命名开着的用例→标签/模型路径同步（不留旧路径）；切换工程→旧标签全清、回欢迎页。"""
    try:
        from PyQt6.QtWidgets import QInputDialog
        with tempfile.TemporaryDirectory() as proj:
            win = _win(proj)
            case = win.create_resource("case", proj, "AAA")
            win._on_file_activated(case)                 # 打开
            win.project_tree.selected_path = lambda: case
            orig_in = QInputDialog.getText
            QInputDialog.getText = staticmethod(lambda *a, **k: ("BBB", True))
            try:
                win.rename_dialog()
            finally:
                QInputDialog.getText = orig_in
            newp = os.path.join(proj, "BBB.tc.yaml")
            idx = win._doc_index(newp)
            rename_ok = (idx >= 0 > win._doc_index(case)
                         and getattr(win._open_docs[idx]["model"], "source_path", "") == newp)
            with tempfile.TemporaryDirectory() as proj2:
                win.open_project(proj2)                  # 切工程
                switch_ok = (len(win._open_docs) == 0
                             and win.center.currentWidget() is win.empty_workspace)
            win.close()
        ok = rename_ok and switch_ok
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("重命名同步/切工程清标签: ⏭ 跳过(", e, ")")
        return True
    print("重命名同步标签 + 切工程清空标签:", "✅" if ok else "❌")
    return ok


def test_rename_project_root_sync() -> bool:
    """重命名工程根后，工程上下文、标签和最近工程路径全部切到新目录。"""
    try:
        import time
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QInputDialog

        def select_tree_path(window, path):
            tree = window.project_tree
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                _APP.processEvents()
                source_index = tree._fs.index(os.path.realpath(path))
                index = tree._proxy.mapFromSource(source_index)
                if index.isValid():
                    tree.setCurrentIndex(index)
                    return index
                time.sleep(0.01)
            raise AssertionError(f"工程树未加载目标路径：{path}")

        with tempfile.TemporaryDirectory() as parent:
            proj = os.path.join(parent, "plantscope")
            os.makedirs(proj)
            win = _win(proj)
            from autopilot.runtime import settings
            settings.set_project_platform(proj, "web")
            settings.set_mc_bound_project_id(proj, "platform-project")
            newp = os.path.join(parent, "renamed_project")
            settings.set_project_platform(newp, "android")
            settings.set_mc_bound_project_id(newp, "stale-platform-project")
            case = win.create_resource("case", proj, "ROOT_CASE")
            emitted_paths = []
            win.project_tree.fileActivated.connect(emitted_paths.append)
            case_index = select_tree_path(win, case)
            win.project_tree._emit_activated(case_index)
            win.project_tree._proxy.setData(case_index, Qt.CheckState.Checked.value,
                                            Qt.ItemDataRole.CheckStateRole)
            paths_before_ok = (emitted_paths == [case] and win.project_tree.checked_paths() == [case])
            select_tree_path(win, proj)
            logical_root_ok = win.project_tree.selected_path() == proj
            orig_in = QInputDialog.getText
            QInputDialog.getText = staticmethod(lambda *a, **k: ("renamed_project", True))
            try:
                win.rename_dialog()
            finally:
                QInputDialog.getText = orig_in
            new_case = os.path.join(newp, "ROOT_CASE.tc.yaml")
            idx = win._doc_index(new_case)
            ok = (paths_before_ok and logical_root_ok and not os.path.exists(proj) and os.path.isdir(newp)
                  and os.path.normpath(win.project_dir) == os.path.normpath(newp)
                  and os.path.normpath(win.project_tree._root) == os.path.normpath(newp)
                  and idx >= 0 and os.path.normpath(win._open_docs[idx]["path"]) == os.path.normpath(new_case)
                  and settings.project_platform(newp) == "web"
                  and settings.project_platform(proj) == ""
                  and settings.mc_bound_project_id(newp) == "platform-project"
                  and settings.mc_bound_project_id(proj) == ""
                  and win.project_tree.checked_paths() == [new_case])
            win.close()
            # 未配置的源工程也不能继承目标路径上旧工程的配置/远端绑定。
            plain = os.path.join(parent, "plain_project")
            reused = os.path.join(parent, "reused_project")
            os.makedirs(plain)
            settings.set_project_platform(reused, "ios")
            settings.set_mc_bound_project_id(reused, "deleted-project-binding")
            win = _win(plain)
            select_tree_path(win, plain)
            QInputDialog.getText = staticmethod(lambda *a, **k: ("reused_project", True))
            try:
                win.rename_dialog()
            finally:
                QInputDialog.getText = orig_in
            ok = (ok and not os.path.exists(plain) and os.path.isdir(reused)
                  and settings.project_platform(reused) == ""
                  and settings.mc_bound_project_id(reused) == "")
            win.close()
        print("重命名工程根同步上下文/标签:", "✅" if ok else "❌")
        return ok
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("重命名工程根同步: ⏭ 跳过(", e, ")")
        return True


def test_rename_rebases_checked_case_paths() -> bool:
    """Renaming a folder keeps batch-run selections on the new paths."""
    try:
        from PyQt6.QtWidgets import QInputDialog
        with tempfile.TemporaryDirectory() as proj:
            win = _win(proj)
            folder = win.create_folder(proj, "suite")
            case = win.create_resource("case", folder, "SELECTED")
            win.project_tree._proxy._checked = {
                win.project_tree._proxy._norm(case): case
            }
            win.project_tree.selected_path = lambda: folder
            orig_in = QInputDialog.getText
            QInputDialog.getText = staticmethod(lambda *a, **k: ("renamed_suite", True))
            try:
                win.rename_dialog()
            finally:
                QInputDialog.getText = orig_in
            new_case = os.path.join(proj, "renamed_suite", "SELECTED.tc.yaml")
            ok = win.project_tree.checked_paths() == [new_case]
            win.close()
        print("重命名同步批量勾选路径:", "✅" if ok else "❌")
        return ok
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("重命名同步批量勾选路径: ⏭ 跳过(", e, ")")
        return True


def test_delete_project_clears_project_state() -> bool:
    """Deleting the open project root exits project mode cleanly."""
    try:
        from autopilot.ui.main_window import files as files_mod
        from autopilot.runtime import settings
        with tempfile.TemporaryDirectory() as parent:
            proj = os.path.join(parent, "to_delete")
            os.makedirs(proj)
            win = _win(proj)
            orig = files_mod.confirm
            files_mod.confirm = lambda *a, **k: True
            try:
                win.project_tree.selected_path = lambda: proj
                win.delete_dialog()
            finally:
                files_mod.confirm = orig
            ok = (not os.path.exists(proj) and (win.project_dir or "") == ""
                  and not win.project_tree._root and settings.last_project() == "")
            win.close()
        print("删除工程根同步工程状态:", "✅" if ok else "❌")
        return ok
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("删除工程根同步工程状态: ⏭ 跳过(", e, ")")
        return True


def test_rename_failure_is_handled() -> bool:
    """目标名称冲突时提示失败，原文件和工程状态保持不变。"""
    try:
        from PyQt6.QtWidgets import QInputDialog, QMessageBox
        with tempfile.TemporaryDirectory() as proj:
            win = _win(proj)
            first = win.create_resource("case", proj, "first")
            second = win.create_resource("case", proj, "second")
            win.project_tree.selected_path = lambda: first
            orig_in, orig_warn = QInputDialog.getText, QMessageBox.warning
            seen = {}
            QInputDialog.getText = staticmethod(lambda *a, **k: ("second", True))
            QMessageBox.warning = staticmethod(lambda *a, **k: seen.setdefault("shown", True))
            try:
                win.rename_dialog()
            finally:
                QInputDialog.getText, QMessageBox.warning = orig_in, orig_warn
            ok = (os.path.exists(first) and os.path.exists(second)
                  and seen.get("shown") is True and win.project_dir == proj)
            win.close()
        print("重命名冲突异常处理:", "✅" if ok else "❌")
        return ok
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("重命名冲突处理: ⏭ 跳过(", e, ")")
        return True


def test_case_only_rename() -> bool:
    """大小写不敏感文件系统上也能完成只改大小写的重命名。"""
    try:
        from autopilot.ui.main_window.files import FilesMixin
        with tempfile.TemporaryDirectory() as proj:
            original = os.path.join(proj, "CaseProject")
            os.makedirs(original)
            renamed = FilesMixin.rename_path(original, "caseproject")
            ok = (os.path.basename(renamed) == "caseproject"
                  and os.path.isdir(renamed)
                  and os.listdir(proj) == ["caseproject"])
        print("大小写重命名:", "✅" if ok else "❌")
        return ok
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("大小写重命名: ⏭ 跳过(", e, ")")
        return True


def test_rename_rejects_foreign_path_separator() -> bool:
    """POSIX must reject Windows separators so names remain portable."""
    try:
        from autopilot.ui.main_window.files import FilesMixin
        with tempfile.TemporaryDirectory() as proj:
            original = os.path.join(proj, "portable")
            os.makedirs(original)
            rejected = True
            for candidate in ("portable/child", r"portable\child", "portable\x00child"):
                try:
                    FilesMixin.rename_path(original, candidate)
                except ValueError:
                    continue
                rejected = False
                break
            ok = rejected and os.path.isdir(original)
        print("跨平台路径分隔符校验:", "✅" if ok else "❌")
        return ok
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("跨平台路径分隔符校验: ⏭ 跳过(", e, ")")
        return True


def test_create_rejects_path_escape_name() -> bool:
    """创建资源/文件夹也必须拒绝能逃逸工程目录的名称。"""
    try:
        from autopilot.ui.main_window.files import FilesMixin
        with tempfile.TemporaryDirectory() as proj:
            checks = []
            for fn, args in (
                (FilesMixin.create_resource, ("case", proj, r"nested\\case")),
                (FilesMixin.create_folder, (proj, "../outside")),
            ):
                try:
                    fn(*args)
                except ValueError:
                    checks.append(True)
                else:
                    checks.append(False)
            first = FilesMixin.create_resource("case", proj, "same")
            try:
                FilesMixin.create_resource("case", proj, "same")
            except FileExistsError:
                duplicate_rejected = True
            else:
                duplicate_rejected = False
            ok = (all(checks) and duplicate_rejected and os.path.isfile(first)
                  and not os.path.exists(os.path.join(proj, "..", "outside")))
        print("创建名称路径逃逸校验:", "✅" if ok else "❌")
        return ok
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("创建名称路径逃逸校验: ⏭ 跳过(", e, ")")
        return True


def test_keyword_usage_decay() -> bool:
    """常用热度带时间衰减：旧的高频若很久没用，会被近期新用的顶下去；且存储裁到上限。"""
    import autopilot.runtime.settings as st
    prev = os.environ.get("AUTOPILOT_CONFIG_DIR")
    try:
        with tempfile.TemporaryDirectory() as cfg:
            os.environ["AUTOPILOT_CONFIG_DIR"] = cfg
            t0 = 1_000_000.0
            # OLD：很久以前高频用 5 次
            for _ in range(5):
                st.bump_keyword_usage("OLD", now=t0)
            # NEW：60 天后（远超 14 天半衰期）只用 2 次
            t1 = t0 + 60 * 24 * 3600
            for _ in range(2):
                st.bump_keyword_usage("NEW", now=t1)
            ranked = st.keyword_usage_ranked(now=t1)
            # OLD 5 次经 ~4 个半衰期衰减到 <0.4，NEW=2 → NEW 应排前
            decay_ok = ranked[:2] == ["NEW", "OLD"]
            # 上限裁剪：灌 60 个不同 kid（同一时刻），应只留 _USAGE_CAP 个
            for i in range(60):
                st.bump_keyword_usage(f"K{i}", now=t1)
            cap_ok = len(st.keyword_usage()) <= st._USAGE_CAP
        ok = decay_ok and cap_ok
    finally:
        if prev is None:
            os.environ.pop("AUTOPILOT_CONFIG_DIR", None)
        else:
            os.environ["AUTOPILOT_CONFIG_DIR"] = prev
    print("常用热度衰减(近期顶掉陈旧)+上限裁剪:", "✅" if ok else "❌")
    return ok


def test_recent_projects_prune() -> bool:
    """最近工程自愈：目录被删后，recent_projects 剔除该项、last_project 回空。"""
    import autopilot.runtime.settings as st
    prev = os.environ.get("AUTOPILOT_CONFIG_DIR")
    try:
        with tempfile.TemporaryDirectory() as cfg:
            os.environ["AUTOPILOT_CONFIG_DIR"] = cfg
            with tempfile.TemporaryDirectory() as proj:
                st.remember_project(proj)
                present = proj in st.recent_projects() and st.last_project() == proj
            # proj 目录已随 with 退出删除
            pruned = st.recent_projects() == [] and st.last_project() == ""
        ok = present and pruned
    finally:
        if prev is None:
            os.environ.pop("AUTOPILOT_CONFIG_DIR", None)
        else:
            os.environ["AUTOPILOT_CONFIG_DIR"] = prev
    print("最近工程失效自愈(剔除+last回空):", "✅" if ok else "❌")
    return ok


def test_recent_projects_slash_dedupe() -> bool:
    """最近工程：同一目录 / 与 \\ 混写应合并为一条。"""
    import autopilot.runtime.settings as st
    prev = os.environ.get("AUTOPILOT_CONFIG_DIR")
    try:
        with tempfile.TemporaryDirectory() as cfg:
            os.environ["AUTOPILOT_CONFIG_DIR"] = cfg
            with tempfile.TemporaryDirectory() as proj:
                base = os.path.normpath(proj)
                slashy = base.replace("\\", "/")
                backslashy = base.replace("/", "\\")
                st.set_value("recent_projects", [slashy, backslashy, slashy])
                st.set_value("last_project", slashy)
                got = st.recent_projects()
                ok_read = len(got) == 1 and os.path.normpath(got[0]) == base
                st.remember_project(backslashy)
                st.remember_project(slashy)
                got2 = st.recent_projects()
                ok_write = len(got2) == 1 and os.path.normpath(got2[0]) == base
        ok = ok_read and ok_write
    finally:
        if prev is None:
            os.environ.pop("AUTOPILOT_CONFIG_DIR", None)
        else:
            os.environ["AUTOPILOT_CONFIG_DIR"] = prev
    print("最近工程斜杠去重:", "✅" if ok else "❌")
    return ok


def test_inspector_crop_save() -> bool:
    """框选图片定位保存：取消另存为→不存；选定路径→存盘且填入 picture:: 相对路径。"""
    try:
        import glob
        from PyQt6.QtGui import QImage
        from PyQt6.QtCore import QBuffer
        from autopilot.keywords.mobile.picture_locator import picture_locator_for_path
        with tempfile.TemporaryDirectory() as proj:
            win = _win(proj)
            case = win.create_resource("case", proj, "crop_case")
            win._on_file_activated(case)
            # 必须用 picture 白名单关键字，否则填入会被门控拒绝
            win.case_editor.insert_step(
                "mobile_element_click", win.catalog.get("mobile_element_click"))
            win.center.setCurrentWidget(win.case_editor)
            win.case_editor.selectRow(0)
            img = QImage(20, 20, QImage.Format.Format_RGB32); img.fill(0x112233)
            qb = QBuffer(); qb.open(QBuffer.OpenModeFlag.WriteOnly); img.save(qb, "PNG")
            png = bytes(qb.data())
            win._pick_crop_image_path = lambda _default: ""
            win._on_inspector_crop(png)
            cancel_ok = len(glob.glob(os.path.join(proj, "images", "*.png"))) == 0
            target = os.path.join(proj, "images", "login_btn.png")
            win._pick_crop_image_path = lambda _default: target
            win._on_inspector_crop(png)
            saved = os.path.isfile(target)
            node = win.case_editor.selected_node()
            loc = next((p.value for p in getattr(node, "params", [])
                        if p.param_id == "locator"), "")
            expect = picture_locator_for_path(proj, target)
            ok = (cancel_ok and saved and loc == expect
                  and loc == "picture::images/login_btn.png")
            win.close()
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("框选图片保存: ⏭ 跳过(", e, ")")
        return True
    print("框选图片定位保存(另存为取消/指定路径+填步骤):", "✅" if ok else "❌")
    return ok


def test_platform_marker_and_guard() -> bool:
    """用例平台标记：序列化往返保留 platform；set_case_platform 写文件；执行护栏拦不匹配设备。"""
    try:
        from autopilot.ui.main_window import run as run_mod
        from autopilot.model.testcase import TestCase, Step, ParamValue
        # 1) 序列化往返保留 platform
        tc = TestCase(name="c", platform="ios")
        rt_ok = serializer.dict_to_testcase(serializer.testcase_to_dict(tc)).platform == "ios"
        with tempfile.TemporaryDirectory() as proj:
            win = _win(proj)
            case = win.create_resource("case", proj, "ios_case")
            # 2) set_case_platform 写入文件
            win.project_tree.selected_path = lambda: case
            win.set_case_platform("ios")
            set_ok = serializer.load(case).platform == "ios"
            # 3) 护栏：标 ios 但只连 android → 硬阻断（不可强制）
            ios_tc = serializer.load(case)
            win._devices = (["AND1"], [])          # 只有 Android
            orig = run_mod.confirm
            try:
                blocked = win._platform_guard([ios_tc]) is False
                still_blocked = win._platform_guard([ios_tc]) is False
                # 已连对应设备 → 直接放行(不弹)
                win._devices = ([], ["IOSU"])
                run_mod.confirm = lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该弹"))
                match_ok = win._platform_guard([ios_tc]) is True
                # 未标平台 + 无工程默认 → 放行
                win._devices = ([], [])
                noplat_ok = win._platform_guard([TestCase(name="x")]) is True
                # 工程默认平台(选一次)：未标用例继承默认 → 不匹配设备则拦
                from autopilot.runtime import settings
                settings.set_project_platform(proj, "ios")
                win._devices = (["AND1"], [])     # 只连 Android
                run_mod.confirm = lambda *a, **k: False
                default_block_ok = win._platform_guard([TestCase(name="x")]) is False
                mixed_tc = TestCase(name="mixed")
                mixed_tc.case.steps = [
                    Step("mobile_app_start", "", params=[ParamValue("type", "Android")]),
                    Step("mobile_app_start", "", params=[ParamValue("type", "iOS")]),
                ]
                win._devices = (["AND1"], ["IOS1"])
                run_mod.confirm = lambda *a, **k: False
                mixed_block_ok = win._platform_guard([mixed_tc]) is False
                run_mod.confirm = lambda *a, **k: True
                mixed_force_ok = win._platform_guard([mixed_tc]) is True
            finally:
                run_mod.confirm = orig
            win.close()
        ok = (rt_ok and set_ok and blocked and still_blocked and match_ok
              and noplat_ok and default_block_ok and mixed_block_ok and mixed_force_ok)
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("用例平台标记/护栏: ⏭ 跳过(", e, ")")
        return True
    print("用例平台标记+执行护栏(往返/写入/硬阻断/匹配/未标):", "✅" if ok else "❌")
    return ok


def test_case_shell_move() -> bool:
    """用例编辑器「移动到段」：把主体步骤移到前置/后置/异常，模型落到对应 shell 且往返保留。"""
    try:
        from PyQt6.QtWidgets import QApplication
        from autopilot.ui.widgets.case_editor import CaseEditor
        from autopilot.model.testcase import TestCase, Step
        QApplication.instance() or QApplication([])
        tc = TestCase(name="c")
        tc.case.steps.append(Step(keyword_id="log", comment="hi"))
        ed = CaseEditor(); ed.show_case(tc)
        ed.selectRow(0)
        # 候选段：主体之外的三段
        targets = {n for n, _ in ed.shell_move_targets()}
        targets_ok = targets == {"before", "after", "fault"}
        moved = ed.move_selected_to_shell("before")
        model_ok = (len(tc.case.steps) == 0 and len(tc.before.steps) == 1
                    and tc.before.steps[0].keyword_id == "log")
        # 序列化往返：before 段步骤保留
        rt = serializer.dict_to_testcase(serializer.testcase_to_dict(tc))
        rt_ok = len(rt.before.steps) == 1 and rt.before.steps[0].keyword_id == "log"
        # 段内步骤(顶层)可再移回主体
        ed.selectRow(0)
        back_ok = ed.move_selected_to_shell("case") and len(tc.case.steps) == 1
        ed.deleteLater()
        ok = targets_ok and moved and model_ok and rt_ok and back_ok
    except ImportError as e:
        import traceback; traceback.print_exc()
        print("用例段移动: ⏭ 跳过(", e, ")")
        return True
    print("用例编辑器移动到段(候选/落段/往返/移回):", "✅" if ok else "❌")
    return ok


def test_new_project_dialog() -> bool:
    """新建工程对话框：位置+名称合并一窗，实时预览最终路径，缺一项则禁用「创建」。"""
    try:
        from PyQt6.QtWidgets import QApplication
        from autopilot.ui.widgets.new_project_dialog import NewProjectDialog
        QApplication.instance() or QApplication([])
        dlg = NewProjectDialog(None, os.path.join("D:", "base"))
        empty_disabled = not dlg.btn_ok.isEnabled()      # 仅有位置、无名称 → 禁用
        dlg.ed_name.setText("MyProj")
        path = dlg.target_path()
        ok_enabled = dlg.btn_ok.isEnabled()
        path_ok = path.endswith(os.path.join("base", "MyProj")) and "MyProj" in dlg.lbl_preview.text()
        dlg.ed_name.setText(r"bad\name")
        portable_invalid_disabled = not dlg.btn_ok.isEnabled()
        dlg.deleteLater()
        ok = empty_disabled and ok_enabled and path_ok and portable_invalid_disabled
    except ImportError as e:
        import traceback; traceback.print_exc()
        print("新建工程对话框: ⏭ 跳过(", e, ")")
        return True
    print("新建工程对话框(位置+名称合并/路径预览/缺项禁用):", "✅" if ok else "❌")
    return ok


def test_save_as_supports_all_editors_and_keeps_suffix() -> bool:
    """另存为应覆盖工程资源编辑器，并为裸名称补回资源后缀。"""
    try:
        from PyQt6.QtWidgets import QFileDialog
        with tempfile.TemporaryDirectory() as proj:
            win = _win(proj)
            suite = win.create_resource("suite", proj, "source")
            win._on_file_activated(suite)
            original = QFileDialog.getSaveFileName
            QFileDialog.getSaveFileName = staticmethod(
                lambda *a, **k: (os.path.join(proj, "copied_suite"), "YAML (*.ts.yaml)"))
            try:
                win.save_as_dialog()
            finally:
                QFileDialog.getSaveFileName = original
            target = os.path.join(proj, "copied_suite.ts.yaml")
            idx = win._doc_index(target)
            ok = (os.path.exists(target) and idx >= 0
                  and win._open_docs[idx]["path"] == target)
            win.close()
        print("另存为资源类型/后缀/标签同步:", "✅" if ok else "❌")
        return ok
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("另存为资源类型/后缀/标签同步: ⏭ 跳过(", e, ")")
        return True


def test_rename_rebases_testplan_members() -> bool:
    """重命名用例目录后，磁盘测试计划成员路径同步更新。"""
    try:
        with tempfile.TemporaryDirectory() as proj:
            win = _win(proj)
            cases = os.path.join(proj, "cases")
            os.makedirs(cases)
            case = win.create_resource("case", cases, "login")
            plan_path = win.create_resource("testplan", proj, "nightly")
            plan = serializer.load(plan_path)
            plan.members = ["cases/login.tc.yaml"]
            serializer.save_testplan(plan, plan_path)
            win._on_file_activated(plan_path)
            opened = win.testplan_editor.testplan
            opened.name = "unsaved name"
            renamed = os.path.join(proj, "smoke_cases")
            os.rename(cases, renamed)
            win._rebase_testplan_refs(cases, renamed)
            updated = serializer.load(plan_path)
            ok = (updated.members == opened.members == ["smoke_cases/login.tc.yaml"]
                  and updated.name == "nightly" and opened.name == "unsaved name"
                  and os.path.exists(os.path.join(renamed, os.path.basename(case))))
            from unittest.mock import patch
            from PyQt6.QtWidgets import QMessageBox
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                win.close()
        print("测试计划成员随目录重命名:", "✅" if ok else "❌")
        return ok
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("测试计划成员随目录重命名: ⏭ 跳过(", e, ")")
        return True


def test_rename_rebases_map_references() -> bool:
    """重命名对象库后，用例和测试套的每个段都同步 map:: 引用。"""
    try:
        from autopilot.model.testcase import ParamValue, Step
        with tempfile.TemporaryDirectory() as proj:
            win = _win(proj)
            case_path = win.create_resource("case", proj, "login")
            suite_path = win.create_resource("suite", proj, "lifecycle")
            map_path = win.create_resource("map", proj, "old_map")
            tc = serializer.load(case_path)
            suite = serializer.load(suite_path)
            for model, path, save in (
                (tc, case_path, serializer.save_testcase),
                (suite, suite_path, serializer.save_testsuite),
            ):
                for shell in model.shells:
                    shell.steps = [Step(keyword_id="mobile_click", params=[
                        ParamValue("locator", f"map::old_map::{shell.name}_submit")])]
                save(model, path)
            renamed = os.path.join(proj, "new_map.map.yaml")
            os.rename(map_path, renamed)
            win._rebase_map_refs(map_path, renamed)
            folder_old = os.path.join(proj, "new_map.map")
            folder_new = os.path.join(proj, "folder_alias.map")
            os.makedirs(folder_old)
            os.rename(folder_old, folder_new)
            win._rebase_map_refs(folder_old, folder_new)
            updated_models = [serializer.load(path) for path in (case_path, suite_path)]
            ok = all(
                shell.steps[0].params[0].value == f"map::new_map::{shell.name}_submit"
                for model in updated_models for shell in model.shells
            )
            win.close()
        print("对象库引用随重命名:", "✅" if ok else "❌")
        return ok
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("对象库引用随重命名: ⏭ 跳过(", e, ")")
        return True


def test_rename_rebases_inner_case_references() -> bool:
    """Renaming a case directory updates StepInnerCase relative paths."""
    try:
        import ntpath
        import posixpath
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from autopilot.model.testcase import StepInnerCase
        from autopilot.runtime import paths as paths_mod
        from autopilot.ui.main_window import files as files_mod
        with tempfile.TemporaryDirectory() as proj:
            win = _win(proj)
            source_dir = os.path.join(proj, "flows")
            target_dir = os.path.join(proj, "shared")
            os.makedirs(source_dir)
            os.makedirs(target_dir)
            source = win.create_resource("case", source_dir, "main")
            win.create_resource("case", target_dir, "child")
            tc = serializer.load(source)
            tc.case.steps = [StepInnerCase(relative_path="../shared/child.tc.yaml")]
            serializer.save_testcase(tc, source)
            open_source = win.create_resource("case", source_dir, "open_main")
            serializer.save_testcase(tc, open_source)
            legacy_source = os.path.join(source_dir, "legacy.tc")
            Path(legacy_source).write_text(
                '<root><case><stepinnercase relativepath="../shared/child.tc.yaml"/>'
                '</case></root>', encoding="utf-8")
            open_models = []
            for path in (open_source, legacy_source):
                win._on_file_activated(path)
                model = win._open_docs[win._doc_index(path)]["model"]
                model.name = "unsaved-name"
                open_models.append(model)
            renamed = os.path.join(proj, "renamed_shared")
            os.rename(target_dir, renamed)
            win._rewrite_project_references(target_dir, renamed)
            updated = serializer.load(source)
            open_saved = serializer.load(open_source)
            expected = "../renamed_shared/child.tc.yaml"
            ok = (updated.case.steps[0].relative_path == expected
                  and all(model.case.steps[0].relative_path == expected
                          and model.name == "unsaved-name" for model in open_models)
                  and open_saved.name == tc.name
                  and open_saved.case.steps[0].relative_path == expected
                  and f'relativepath="{expected}"' in Path(legacy_source).read_text(encoding="utf-8"))
            from PyQt6.QtWidgets import QMessageBox
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
                win.close()
        # 两类宿主路径算法都接受项目中已有的 Windows/POSIX 相对分隔符。
        for path_api, separator, root in (
            (posixpath, "/", "/project"), (ntpath, "\\", "C:\\project"),
        ):
            host_os = SimpleNamespace(path=path_api, sep=separator)
            with patch.object(files_mod, "os", host_os), patch.object(paths_mod, "os", host_os):
                for ref in ("../shared/child.tc.yaml", r"..\shared\child.tc.yaml"):
                    actual = files_mod.FilesMixin._rebase_relative_ref(
                        ref, path_api.join(root, "flows"), path_api.join(root, "flows"),
                        path_api.join(root, "shared"), path_api.join(root, "renamed_shared"))
                    ok = actual == ("../renamed_shared/child.tc.yaml", True) and ok
        print("内嵌用例引用随目录重命名:", "✅" if ok else "❌")
        return ok
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("内嵌用例引用随目录重命名: ⏭ 跳过(", e, ")")
        return True


def test_rename_preserves_legacy_xml_references() -> bool:
    """未打开的旧资源更新引用时保留 XML 和未识别扩展字段。"""
    from pathlib import Path
    from xml.sax.saxutils import escape
    from lxml import etree
    from autopilot.model import loader

    with tempfile.TemporaryDirectory() as parent:
        project = Path(parent, "legacy_project")
        assets = project / "assets"
        assets.mkdir(parents=True)
        (assets / "child.tc").write_text('<root><case/></root>', encoding="utf-8")
        for name in ("button.png", "app.apk", "rows.csv", "DataConfig.properties"):
            (assets / name).write_text("fixture", encoding="utf-8")
        (project / "old_map.map").write_text('<root/>', encoding="utf-8")
        absolute_app = escape(str(assets / "app.apk"))
        steps = (
            '<step id="mobile_click"><param id="locator">map::old_map::submit</param>'
            '<param id="image">picture::assets/button.png</param>'
            f'<param id="appFile">{absolute_app}</param>'
            '<param id="datapool_source_path">assets/rows.csv</param></step>'
            '<stepset name="rows" datapool="DATATABLE(assets/rows.csv,true)"/>'
            '<stepset name="spaced" datapool=" datatable ( assets/rows.csv , true ) "/>'
            '<stepset name="simple" datapool="DATATABLE(assets/rows.csv)"/>'
        )
        extension = '<!--retain--><extension custom="keep"><![CDATA[opaque <data>]]></extension>'
        documents = {
            "main.tc": ('<root db_id="keep-case"><datapool>DATATABLE(assets/rows.csv,false)</datapool>'
                        + ''.join(f'<{shell}>{steps}</{shell}>' for shell in ("before", "case", "after", "fault"))
                        + '<case_extra><stepinnercase relativepath="assets/child.tc"/></case_extra>'
                        + extension + '</root>'),
            "lifecycle.ts": ('<root db_id="keep-suite">'
                             + ''.join(f'<{shell}>{steps}</{shell}>' for shell in ("before", "after", "fault"))
                             + extension + '</root>'),
            "action.ks": '<root><id>action</id><steps>' + steps + '</steps>' + extension + '</root>',
            "nightly.tp": ('<root><testplan><local><name>nightly</name>'
                           '<dataconfig>assets/DataConfig.properties</dataconfig><faulttimes>2</faulttimes>'
                           '</local><member relativepath="assets/child.tc"/>'
                           '<case>assets/child.tc</case></testplan>' + extension + '</root>'),
        }
        # 内嵌用例必须位于真实 case 节点内，且该节点保留全部其他步骤。
        documents["main.tc"] = documents["main.tc"].replace(
            '</case>', '<stepinnercase relativepath="assets/child.tc"/></case>')
        for name, text in documents.items():
            standalone = {"main.tc": ' standalone="yes"', "lifecycle.ts": ' standalone="no"'}.get(name, "")
            (project / name).write_text(f'<?xml version="1.0" encoding="UTF-8"{standalone}?>\n' + text,
                                        encoding="utf-8")
        untouched = project / "untouched.tc"
        untouched.write_text('<root custom="untouched">\n  <case/>\n</root>\n', encoding="utf-8")
        untouched_bytes = untouched.read_bytes()
        win = _win(str(project))
        renamed_assets = project / "resources"
        os.rename(assets, renamed_assets)
        win._rewrite_project_references(str(assets), str(renamed_assets))
        old_map, new_map = project / "old_map.map", project / "new_map.map"
        os.rename(old_map, new_map)
        win._rewrite_project_references(str(old_map), str(new_map))
        renamed_project = Path(parent, "renamed_legacy_project")
        win.project_tree.set_root("")
        _APP.processEvents()
        os.rename(project, renamed_project)
        win.project_dir = str(renamed_project)
        win._rewrite_project_references(str(project), str(renamed_project))
        expected_app = str(renamed_project / "resources" / "app.apk")
        ok = True
        for name, load in (
            ("main.tc", loader.load_testcase), ("lifecycle.ts", loader.load_testsuite),
            ("action.ks", loader.load_keyword), ("nightly.tp", loader.load_testplan),
        ):
            path = renamed_project / name
            load(str(path))
            tree = etree.parse(str(path))
            declaration = path.read_bytes().splitlines()[0]
            if name in {"main.tc", "lifecycle.ts"}:
                expected_standalone = b"yes" if name == "main.tc" else b"no"
                ok = b"standalone='" + expected_standalone + b"'" in declaration and ok
            else:
                ok = b"standalone=" not in declaration and ok
            ok = (tree.find("extension").get("custom") == "keep"
                  and tree.find("extension").text == "opaque <data>"
                  and bool(tree.xpath('//comment()[.="retain"]')) and ok)
            for element in tree.iter("param"):
                expected = {
                    "locator": "map::new_map::submit", "image": "picture::resources/button.png",
                    "appFile": expected_app, "datapool_source_path": "resources/rows.csv",
                }[element.get("id")]
                ok = element.text == expected and ok
            for element in tree.iter("stepset"):
                expected_pool = {
                    "rows": "DATATABLE(resources/rows.csv,true)",
                    "spaced": " datatable ( resources/rows.csv , true ) ",
                    "simple": "DATATABLE(resources/rows.csv)",
                }[element.get("name")]
                ok = element.get("datapool") == expected_pool and ok
        case = loader.load_testcase(str(renamed_project / "main.tc"))
        plan = loader.load_testplan(str(renamed_project / "nightly.tp"))
        ok = (ok and case.datapool == "DATATABLE(resources/rows.csv,false)"
              and case.case.steps[-1].relative_path == "resources/child.tc"
              and plan.members == ["resources/child.tc", "resources/child.tc"]
              and plan.dataconfig == "resources/DataConfig.properties"
              and (renamed_project / "untouched.tc").read_bytes() == untouched_bytes)
        win.close()
    print("旧 XML 引用迁移并保留格式/扩展字段:", "✅" if ok else "❌")
    return ok


def test_rename_rebases_picture_and_datapool_references() -> bool:
    """重命名图片/数据目录后，picture:: 与 DATATABLE 路径同步。"""
    try:
        from autopilot.model.testcase import ParamValue, Step, StepSet
        with tempfile.TemporaryDirectory() as proj:
            win = _win(proj)
            case_path = win.create_resource("case", proj, "login")
            tc = serializer.load(case_path)
            tc.case.steps = [
                Step(keyword_id="mobile_element_click", params=[
                    ParamValue("locator", "picture::data/old/btn.png"),
                    ParamValue("appFile", "apps/old/app.apk"),
                    ParamValue("datapool_source_path", "data/old/data.csv"),
                ]),
                StepSet(datapool="DATATABLE(data/old/data.csv,true)"),
                StepSet(datapool=" datatable ( data/old/data.csv , true ) "),
                StepSet(datapool="DATATABLE(data/old/data.csv)"),
            ]
            serializer.save_testcase(tc, case_path)
            old_dir = os.path.join(proj, "data")
            new_dir = os.path.join(proj, "new_data")
            os.makedirs(os.path.join(old_dir, "old"))
            os.rename(old_dir, new_dir)
            win._rebase_file_references(old_dir, new_dir)
            updated = serializer.load(case_path)
            by_id = {p.param_id: p.value for p in updated.case.steps[0].params}
            ok = (
                by_id["locator"] == "picture::new_data/old/btn.png"
                and by_id["appFile"] == "apps/old/app.apk"
                and by_id["datapool_source_path"] == "new_data/old/data.csv"
                and updated.case.steps[1].datapool == "DATATABLE(new_data/old/data.csv,true)"
                and updated.case.steps[2].datapool == " datatable ( new_data/old/data.csv , true ) "
                and updated.case.steps[3].datapool == "DATATABLE(new_data/old/data.csv)"
            )
            win.close()
        print("图片/数据池引用随目录重命名:", "✅" if ok else "❌")
        return ok
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("图片/数据池引用随目录重命名: ⏭ 跳过(", e, ")")
        return True


def test_keyword_recent_group() -> bool:
    """关键字库「常用」分组：插入累加频次→高频置顶；空记录不显该分组。"""
    try:
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication
        from autopilot.ui.widgets.keyword_panel import KeywordPanel
        from autopilot.runtime import settings
        role = Qt.ItemDataRole.UserRole
        QApplication.instance() or QApplication([])
        panel = KeywordPanel()
        cat = panel.load()                              # 用项目内资源目录
        # 取两个真实关键字 id
        ids = list(cat.by_id.keys())
        if len(ids) < 2:
            print("常用关键字分组: ⏭ 跳过(目录为空)")
            return True
        a, b = ids[0], ids[1]
        # 初始无使用记录 → 无常用分组
        none_ok = panel.tree._recent_top is None
        # b 用 3 次、a 用 1 次 → b 应排在 a 前
        for _ in range(3):
            panel._on_activated(b)
        panel._on_activated(a)
        top = panel.tree._recent_top
        has_group = top is not None and top.text(0) == "常用关键字"
        order_ok = has_group and top.child(0).data(0, role) == b
        usage = settings.keyword_usage()
        count_ok = usage.get(b) == 3 and usage.get(a) == 1
        panel.deleteLater()
        ok = none_ok and has_group and order_ok and count_ok
    except ImportError as e:
        import traceback; traceback.print_exc()
        print("常用关键字分组: ⏭ 跳过(", e, ")")
        return True
    print("关键字库常用分组(频次累加/高频置顶/空不显):", "✅" if ok else "❌")
    return ok


def test_multi_tab_editor() -> bool:
    """多标签编辑器：开多个文件成多标签、切换载入对应模型、编辑跨切换保留、重开不重复、关闭。"""
    try:
        with tempfile.TemporaryDirectory() as proj:
            win = _win(proj)
            c1 = win.create_resource("case", proj, "one")
            c2 = win.create_resource("case", proj, "two")
            win._on_file_activated(c1)
            win._on_file_activated(c2)
            two_tabs = win._tab_bar.count() == 2 and len(win._open_docs) == 2
            # 当前 c2：编辑（加一步）
            win.case_editor.insert_step("log", win.catalog.get("log"))
            c2_edited = len(win._open_docs[1]["model"].case.steps) == 1
            # 切到 c1：编辑器应载入 c1 模型（0 步）
            win._tab_bar.setCurrentIndex(0)
            on_c1 = (win.case_editor.case is win._open_docs[0]["model"]
                     and len(win.case_editor.case.case.steps) == 0)
            # 切回 c2：之前的编辑仍在
            win._tab_bar.setCurrentIndex(1)
            persist = len(win.case_editor.case.case.steps) == 1
            # 重开 c1：不新增标签，切到既有页
            win._on_file_activated(c1)
            no_dup = win._tab_bar.count() == 2 and win._tab_bar.currentIndex() == 0
            # 关闭当前标签 → 剩 1
            win.close_current()
            closed = win._tab_bar.count() == 1 and len(win._open_docs) == 1
            win.close()
        ok = two_tabs and c2_edited and on_c1 and persist and no_dup and closed
    except ImportError as e:
        import traceback; traceback.print_exc()
        print("多标签编辑器: ⏭ 跳过(", e, ")")
        return True
    print("多标签编辑器(多标签/切换载入/编辑保留/去重/关闭):", "✅" if ok else "❌")
    return ok


def test_map_editor_platform_slot() -> bool:
    """对象库编辑器按平台录入：切 Android 槽输入→写入 locators_by_platform+树标记[A]；清空→移除该槽。"""
    try:
        from PyQt6.QtWidgets import QApplication
        from autopilot.ui.widgets.map_editor import MapEditor, _element_summary
        from autopilot.model.mapfile import MapFile, MapElement, Locator
        QApplication.instance() or QApplication([])
        mf = MapFile(name="M", elements=[
            MapElement(name="btn", locator=Locator(type="XPATH", value="//x"))])
        ed = MapEditor(); ed.show_map(mf)
        el = mf.elements[0]
        ed._select_element(el)
        ed.cb_platform.setCurrentIndex(ed.cb_platform.findData("android"))
        ed.cb_type.setCurrentText("ID")
        ed.ed_value.setText("and_id")
        a = el.locators_by_platform.get("android")
        add_ok = a is not None and a.type == "ID" and a.value == "and_id" and "[A]" in _element_summary(el)
        ed.ed_value.setText("")                       # 清空 → 移除该槽
        removed_ok = "android" not in el.locators_by_platform
        # 通用槽不受影响
        common_ok = el.locator.value == "//x"
        ed.close()
        ok = add_ok and removed_ok and common_ok
    except ImportError as e:
        import traceback; traceback.print_exc()
        print("对象库编辑器分平台: ⏭ 跳过(", e, ")")
        return True
    print("对象库编辑器按平台录入(写入[A]/清空移除/通用不变):", "✅" if ok else "❌")
    return ok


def test_idle_center_welcome_vs_workspace() -> bool:
    """无工程→欢迎页；有工程无文档→空编辑区；关最后标签不弹回欢迎页；关闭工程回欢迎页。"""
    try:
        from autopilot.runtime import settings
        with tempfile.TemporaryDirectory() as cfg:
            os.environ["AUTOPILOT_CONFIG_DIR"] = cfg
            win = _win("")
            no_proj = win.center.currentWidget() is win.welcome
            win.close()
            with tempfile.TemporaryDirectory() as proj:
                win = _win(proj)
                with_proj = win.center.currentWidget() is win.empty_workspace
                case = win.create_resource("case", proj, "IDLE01")
                win._on_file_activated(case)
                opened = win.center.currentWidget() is win.case_editor
                win.close_current()
                after_close = win.center.currentWidget() is win.empty_workspace
                win.close_project()
                after_close_proj = (
                    win.center.currentWidget() is win.welcome
                    and (win.project_dir or "") == ""
                    and settings.last_project() == ""
                )
                win.close()
        ok = no_proj and with_proj and opened and after_close and after_close_proj
    except ImportError as e:
        import traceback
        traceback.print_exc()
        print("欢迎页/空编辑区切换: ⏭ 跳过(", e, ")")
        return True
    print("欢迎页/空编辑区切换(无工程欢迎/有工程空区/关标签/关工程):", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([test_create_resources(), test_folder_rename_delete(),
              test_open_project(), test_new_project_and_remember(),
              test_keyword_resource_and_project_guard(), test_explorer_panel(),
              test_tree_filter(), test_tree_resource_visibility(), test_run_checked(),
              test_rename_delete_dialog_display(), test_delete_closes_open_tab(),
              test_rename_and_switch_project_sync(), test_rename_project_root_sync(),
              test_rename_rebases_checked_case_paths(), test_delete_project_clears_project_state(),
              test_rename_failure_is_handled(), test_case_only_rename(),
              test_rename_rejects_foreign_path_separator(),
              test_create_rejects_path_escape_name(), test_recent_projects_prune(),
              test_recent_projects_slash_dedupe(),
              test_keyword_usage_decay(), test_inspector_crop_save(),
              test_platform_marker_and_guard(), test_map_editor_platform_slot(),
              test_keyword_recent_group(), test_new_project_dialog(),
              test_save_as_supports_all_editors_and_keeps_suffix(),
              test_rename_rebases_testplan_members(),
              test_rename_rebases_map_references(),
              test_rename_rebases_inner_case_references(),
              test_rename_preserves_legacy_xml_references(),
              test_rename_rebases_picture_and_datapool_references(),
              test_case_shell_move(), test_multi_tab_editor(),
              test_idle_center_welcome_vs_workspace()])
    print("\n总结:", "✅ 文件/工程操作全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
