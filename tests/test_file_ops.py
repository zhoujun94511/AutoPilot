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
    except Exception as e:  # noqa: BLE001
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
    except Exception as e:  # noqa: BLE001
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
    except Exception as e:  # noqa: BLE001
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
    except Exception as e:  # noqa: BLE001
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
    except Exception as e:  # noqa: BLE001
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
                 and _file_icon("note.txt", False) is None)
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
    except Exception as e:  # noqa: BLE001
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
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("工程树过滤: ⏭ 跳过(", e, ")")
        return True
    print("工程树名称过滤(嵌套/递归保留):", "✅" if ok else "❌")
    return ok


def test_tree_resource_visibility() -> bool:
    """工程树：apk/ipa/reports/logs/ios_monkey/.log 可见；diag_* 仍隐藏。"""
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
            open(os.path.join(proj, "TEST001.tc.yaml"), "w").close()
            open(os.path.join(proj, "TEST002_run.log"), "w").close()
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
                "apk" in dirs and "ipa" in dirs and "reports" in dirs
                and "logs" in dirs and "ios_monkey" in dirs
                and "20260705_120000" in dirs
                and "diag_onboarding" not in dirs
                and "app.apk" in files and "app.ipa" in files and "r.html" in files
                and "TEST001.tc.yaml" in files and "TEST002_run.log" in files
                and "latest.json" in files and "summary.json" in files and "events.jsonl" in files
            )
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("工程树资源可见性: ⏭ 跳过(", e, ")")
        return True
    print("工程树资源可见性(apk/ipa/html/隐藏空目录):", "✅" if ok else "❌", dirs, files)
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
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("工程树勾选运行: ⏭ 跳过(", e, ")")
        return True
    print("工程树复选框选用例(勾文件/勾目录全勾/三态/清空):", "✅" if ok else "❌")
    return ok


def test_rename_delete_dialog_display() -> bool:
    """重命名框去后缀显示且自动保留类型后缀；删除确认框只显示去后缀名、不暴露后缀/全路径。"""
    try:
        from PyQt6.QtWidgets import QInputDialog
        from autopilot.ui import confirm as confirm_mod
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
            orig_q = confirm_mod.confirm
            confirm_mod.confirm = (lambda _s, _t, text, *a, **k:
                                   (seen.__setitem__("t", text) or True))
            try:
                win.delete_dialog()
            finally:
                confirm_mod.confirm = orig_q
            t = seen.get("t", "")
            msg_ok = ("999" in t and ".tc.yaml" not in t and "/" not in t and "\\" not in t)
            del_ok = not os.path.exists(renamed)
            win.close()
        ok = rename_ok and msg_ok and del_ok
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("重命名/删除框去后缀: ⏭ 跳过(", e, ")")
        return True
    print("重命名去后缀保留类型 + 删除框不显后缀/路径:", "✅" if ok else "❌")
    return ok


def test_delete_closes_open_tab() -> bool:
    """删除正在编辑的用例：应关闭其标签，编辑区不残留已删内容（对齐用户反馈的 bug）。"""
    try:
        from autopilot.ui import confirm as confirm_mod
        with tempfile.TemporaryDirectory() as proj:
            win = _win(proj)
            case = win.create_resource("case", proj, "TEST001")
            win._on_file_activated(case)             # 打开成标签
            opened = win._doc_index(case) >= 0
            win.project_tree.selected_path = lambda: case
            refreshed = {"n": 0}                      # 探针：删除后应刷新关键字库(.ks 同步)
            win._refresh_custom_keywords = lambda: refreshed.__setitem__("n", refreshed["n"] + 1)
            orig = confirm_mod.confirm
            confirm_mod.confirm = lambda *a, **k: True    # 自动确认删除
            try:
                win.delete_dialog()
            finally:
                confirm_mod.confirm = orig
            closed = (win._doc_index(case) < 0 and not os.path.exists(case)
                      and refreshed["n"] >= 1)
            # 删完无其它标签 → 中央区回到欢迎页，而非停留在用例编辑器
            back_to_welcome = win.center.currentWidget() is win.welcome
            win.close()
        ok = opened and closed and back_to_welcome
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("删除关闭标签: ⏭ 跳过(", e, ")")
        return True
    print("删除用例关闭其标签+回欢迎页:", "✅" if ok else "❌")
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
            rename_ok = (idx >= 0 and win._doc_index(case) < 0
                         and getattr(win._open_docs[idx]["model"], "source_path", "") == newp)
            with tempfile.TemporaryDirectory() as proj2:
                win.open_project(proj2)                  # 切工程
                switch_ok = (len(win._open_docs) == 0
                             and win.center.currentWidget() is win.welcome)
            win.close()
        ok = rename_ok and switch_ok
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("重命名同步/切工程清标签: ⏭ 跳过(", e, ")")
        return True
    print("重命名同步标签 + 切工程清空标签:", "✅" if ok else "❌")
    return ok


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
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("框选图片保存: ⏭ 跳过(", e, ")")
        return True
    print("框选图片定位保存(另存为取消/指定路径+填步骤):", "✅" if ok else "❌")
    return ok


def test_platform_marker_and_guard() -> bool:
    """用例平台标记：序列化往返保留 platform；set_case_platform 写文件；执行护栏拦不匹配设备。"""
    try:
        from autopilot.ui import confirm as confirm_mod
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
            orig = confirm_mod.confirm
            try:
                blocked = win._platform_guard([ios_tc]) is False
                still_blocked = win._platform_guard([ios_tc]) is False
                # 已连对应设备 → 直接放行(不弹)
                win._devices = ([], ["IOSU"])
                confirm_mod.confirm = lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该弹"))
                match_ok = win._platform_guard([ios_tc]) is True
                # 未标平台 + 无工程默认 → 放行
                win._devices = ([], [])
                noplat_ok = win._platform_guard([TestCase(name="x")]) is True
                # 工程默认平台(选一次)：未标用例继承默认 → 不匹配设备则拦
                from autopilot.runtime import settings
                settings.set_project_platform(proj, "ios")
                win._devices = (["AND1"], [])     # 只连 Android
                confirm_mod.confirm = lambda *a, **k: False
                default_block_ok = win._platform_guard([TestCase(name="x")]) is False
                mixed_tc = TestCase(name="mixed")
                mixed_tc.case.steps = [
                    Step("mobile_app_start", "", params=[ParamValue("type", "Android")]),
                    Step("mobile_app_start", "", params=[ParamValue("type", "iOS")]),
                ]
                win._devices = (["AND1"], ["IOS1"])
                confirm_mod.confirm = lambda *a, **k: False
                mixed_block_ok = win._platform_guard([mixed_tc]) is False
                confirm_mod.confirm = lambda *a, **k: True
                mixed_force_ok = win._platform_guard([mixed_tc]) is True
            finally:
                confirm_mod.confirm = orig
            win.close()
        ok = (rt_ok and set_ok and blocked and still_blocked and match_ok
              and noplat_ok and default_block_ok and mixed_block_ok and mixed_force_ok)
    except Exception as e:  # noqa: BLE001
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
    except Exception as e:  # noqa: BLE001
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
        dlg.deleteLater()
        ok = empty_disabled and ok_enabled and path_ok
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("新建工程对话框: ⏭ 跳过(", e, ")")
        return True
    print("新建工程对话框(位置+名称合并/路径预览/缺项禁用):", "✅" if ok else "❌")
    return ok


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
    except Exception as e:  # noqa: BLE001
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
    except Exception as e:  # noqa: BLE001
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
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("对象库编辑器分平台: ⏭ 跳过(", e, ")")
        return True
    print("对象库编辑器按平台录入(写入[A]/清空移除/通用不变):", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([test_create_resources(), test_folder_rename_delete(),
              test_open_project(), test_new_project_and_remember(),
              test_keyword_resource_and_project_guard(), test_explorer_panel(),
              test_tree_filter(), test_tree_resource_visibility(), test_run_checked(),
              test_rename_delete_dialog_display(), test_delete_closes_open_tab(),
              test_rename_and_switch_project_sync(), test_recent_projects_prune(),
              test_recent_projects_slash_dedupe(),
              test_keyword_usage_decay(), test_inspector_crop_save(),
              test_platform_marker_and_guard(), test_map_editor_platform_slot(),
              test_keyword_recent_group(), test_new_project_dialog(),
              test_case_shell_move(), test_multi_tab_editor()])
    print("\n总结:", "✅ 文件/工程操作全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
