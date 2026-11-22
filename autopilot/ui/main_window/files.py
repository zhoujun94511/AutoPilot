"""主窗口·文件/工程操作 Mixin：打开/新建/保存/另存/重命名/删除 + 文件双击路由。

混入 MainWindow（依赖其 center/各编辑器/console/project_tree/project_dir 等属性）。
"""

from __future__ import annotations

import copy
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from typing import TYPE_CHECKING

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QMenu,
    QMessageBox,
)

from ...model.loader import load_keyword, load_mapfile, load_testcase, load_testplan, load_testsuite
from ...model import serializer
from ...model import dataconfig as dataconfig_model
from ...model.keyworddef import KeywordDef
from ...model.mapfile import MapFile
from ...model.testcase import Step, StepInnerCase, StepSet, StepVerbs, TestCase, TestSuite
from ...model.testplan import TestPlan
from ...engine.keyword_store import discover_keywords
from ...metadata.case_platform_lint import lint_testcase
from ..confirm import confirm
from ..platform_labels import (
    PLATFORM_LABELS,
    PLATFORM_MENU_CHOICES,
    SUPPORTED_RUNTIME_PLATFORMS,
    platform_label,
)
from ..widgets.project_tree import display_name
from ..widgets.search_view import find_in_project, keyword_hint_from_line
from ...runtime import settings
from ...runtime.paths import to_native, validate_portable_name


# 仅供静态检查解析 self.* —— 运行时 Mixin 实际由 MainWindow 组合，这里"继承"只在类型检查时生效（运行时为 object，无循环依赖）。
if TYPE_CHECKING:
    from .window import MainWindow
    _Base = MainWindow
else:
    _Base = object


class FilesMixin(_Base):
    project_dir: str   # 由 MainWindow.__init__ 拥有；此处注解声明以满足静态检查

    def _effective_keyword_target_platform(self) -> str:
        """关键字库灰显：用例 platform 优先，否则工程默认。"""
        target, _hint = self._keyword_platform_context()
        return target

    def _keyword_platform_context(self) -> tuple[str, str]:
        """关键字库灰显依据：(目标平台, 面板提示文案)。"""
        _labels = PLATFORM_LABELS
        cur = self.center.currentWidget()
        if cur is self.case_editor and self.case_editor.case is not None:
            case = self.case_editor.case
            plat = (case.platform or "").strip().lower()
            if plat in SUPPORTED_RUNTIME_PLATFORMS:
                name = (case.name or "当前用例").strip() or "当前用例"
                return plat, f"灰显依据：用例「{name}」→ {_labels.get(plat, plat)}"
        proj_plat = ""
        if self.project_dir and os.path.isdir(self.project_dir):
            proj_plat = (settings.project_platform(self.project_dir) or "").strip().lower()
        if proj_plat in SUPPORTED_RUNTIME_PLATFORMS:
            return proj_plat, f"灰显依据：工程默认 → {_labels.get(proj_plat, proj_plat)}"
        return "", "灰显依据：通用（未按平台过滤）"

    def _sync_platform_context(self) -> None:
        proj_plat = settings.project_platform(self.project_dir) if (self.project_dir and os.path.isdir(self.project_dir)) else ""
        default_plat = (proj_plat or "").strip().lower()
        self.case_editor.set_default_platform(default_plat)
        self.suite_editor.set_default_platform(default_plat)
        target, hint = self._keyword_platform_context()
        if not target:
            target = default_plat
        mode = settings.ios_backend_mode() if target == "ios" else ""
        if hasattr(self, "keyword_editor"):
            self.keyword_editor.set_visibility_platform(proj_plat, mode)
        if hasattr(self, "keyword_panel"):
            self.keyword_panel.set_target_platform(target, hint=hint)

    def _effective_case_platform(self, case=None) -> str:
        """用例有效平台：用例 platform → 工程默认 → 空。"""
        tc = case
        if tc is None:
            cur = self.center.currentWidget()
            if cur is self.case_editor and self.case_editor.case is not None:
                tc = self.case_editor.case
            elif cur is self.suite_editor and self.suite_editor.suite is not None:
                tc = self.suite_editor.suite
        if tc is not None:
            plat = (getattr(tc, "platform", "") or "").strip().lower()
            if plat in ("android", "ios", "web", "http"):
                return plat
        if self.project_dir and os.path.isdir(self.project_dir):
            return (settings.project_platform(self.project_dir) or "").strip().lower()
        return ""

    def _lookup_keyword_def(self, ks_id: str):
        """按 ks_id 查工程内自定义关键字定义（缓存于 _keyword_store）。"""
        store = getattr(self, "_keyword_store", None)
        if store is not None:
            return store.get(ks_id)
        if self.project_dir and os.path.isdir(self.project_dir):
            return discover_keywords(self.project_dir).get(ks_id)
        return None

    def _sync_step_editor_context(self, kind: str = "") -> None:
        """切换文档/工程后同步参数面板与平台上下文。"""
        self._sync_platform_context()
        editable = (Step, StepVerbs, StepSet, StepInnerCase)
        if kind in ("case", "suite", "keyword"):
            editor = {"case": self.case_editor, "suite": self.suite_editor, "keyword": self.keyword_editor}[kind]
            node = editor.selected_node() if hasattr(editor, "selected_node") else None
            if isinstance(node, editable):
                self._on_step_selected(node)
            else:
                self.param_form.clear_step()
        else:
            self.param_form.clear_step()

    def _refresh_open_case_platform_ui(self) -> None:
        """工程/用例平台变更后刷新已打开用例表的参数列与参数面板。"""
        cur = self.center.currentWidget()
        if cur not in (self.case_editor, self.suite_editor):
            return
        editor = cur
        if editor.case is None:
            return
        node = editor.selected_node()
        editor.rerender(select_node=node)
        if isinstance(node, Step):
            self._on_step_selected(node)

    def _sync_keyword_editor_platform(self) -> None:
        """兼容旧调用名。"""
        self._sync_platform_context()

    def _warn_case_platform_lint(self, tc: "TestCase") -> None:
        default = (
            settings.project_platform(self.project_dir)
            if self.project_dir and os.path.isdir(self.project_dir)
            else ""
        )
        maps = self._project_maps()
        ios_bm = getattr(self, "_ios_backend_mode", "auto") or "auto"
        for iss in lint_testcase(
            tc, self.catalog, default_platform=default, maps=maps,
            ios_backend_mode=ios_bm if ios_bm in ("wda", "appium") else "",
        ):
            label = iss.comment or iss.keyword_id
            if iss.issue_type in ("locator", "map") and iss.param_id:
                self.console.log(
                    f"平台校验 [{iss.shell}] {label} 参数 {iss.param_id}：{iss.reason}",
                    "文件",
                    "WARNING",
                )
            else:
                self.console.log(
                    f"平台校验 [{iss.shell}] {label} ({iss.keyword_id})：{iss.reason}",
                    "文件",
                    "WARNING",
                )

    # ---- 工程树右键菜单 ----
    def _show_project_menu(self, pos) -> None:
        tree = self.project_tree
        menu = QMenu(self)
        has_proj = bool(self.project_dir) and os.path.isdir(self.project_dir)
        target = self._target_dir()
        # 新建：建到「选中目录 / 选中文件所在目录 / 工程根」；无工程时整体禁用
        # 注：反斜杠不能出现在 f-string 表达式里（Py3.10/3.11 为语法错误），故先算好再插值
        target_label = os.path.basename(target.rstrip("/\\")) or "工程根"
        title = "新建" + (f"（到 {target_label}/）" if has_proj else "")
        new = menu.addMenu(title)
        new.setEnabled(has_proj)
        for kind in ("case", "suite", "map", "dataconfig", "testplan", "keyword"):
            new.addAction(self._RES_LABELS[kind],
                          lambda _=False, k=kind: self._new_resource(k))
        new.addSeparator()
        new.addAction("文件夹", self._new_folder_dialog)
        if has_proj:
            batch = menu.addMenu("批量勾选")
            batch.addAction("全选/反选", self._toggle_case_checks)
        menu.addSeparator()
        # 工程默认平台：选一次，全工程未单独标平台的用例都按它校验
        if has_proj:
            cur_def = settings.project_platform(self.project_dir)
            dm = menu.addMenu("工程默认平台")
            for plat, label in PLATFORM_MENU_CHOICES:
                a = dm.addAction(label, lambda _=False, p=plat: self.set_project_platform(p))
                a.setCheckable(True)
                a.setChecked(plat == cur_def)
            # 选中用例时可单独标记平台（写入 .tc.yaml）
            path = tree.selected_path() or ""
            if path.endswith((".tc.yaml", ".tc.yml")):
                cm = menu.addMenu("标记平台")
                try:
                    cur_case = (serializer.load(path).platform or "").strip().lower()
                except (OSError, ValueError, TypeError, KeyError):
                    cur_case = ""
                for plat, label in PLATFORM_MENU_CHOICES:
                    a = cm.addAction(label, lambda _=False, p=plat: self.set_case_platform(p))
                    a.setCheckable(True)
                    a.setChecked(plat == cur_case)
        menu.addSeparator()
        has_sel = tree.currentIndex().isValid()
        menu.addAction("重命名…", self.rename_dialog).setEnabled(has_sel)
        menu.addAction("删除", self.delete_dialog).setEnabled(has_sel)
        menu.addSeparator()
        menu.addAction("复制路径", self._copy_path).setEnabled(has_sel)
        menu.addAction("刷新", tree.refresh)
        menu.addAction("在资源管理器中显示", self.reveal_in_explorer)
        menu.exec(tree.viewport().mapToGlobal(pos))

    def _toggle_case_checks(self) -> None:
        n = self.project_tree.invert_visible_checks()
        if n:
            self.console.log(f"当前已勾选 {n} 个用例，可点「批量运行」执行", "工程")
        else:
            self.console.log("当前没有已勾选的用例", "工程")

    def set_project_platform(self, plat: str) -> None:
        """设工程默认平台(选一次)：全工程未单独标平台的用例执行校验都按它。"""
        if not (self.project_dir and os.path.isdir(self.project_dir)):
            self.console.log("请先打开工程，再设默认平台", "工程", "WARNING")
            return
        settings.set_project_platform(self.project_dir, plat)
        self._sync_keyword_editor_platform()
        if hasattr(self, "_sync_ios_backend_controls"):
            self._sync_ios_backend_controls()
        label = platform_label(plat)
        self.console.log(f"已设工程默认平台：{label}（未单独标平台的用例按此校验）", "工程")
        eff, hint = self._keyword_platform_context()
        if plat and eff and plat != eff:
            self.console.log(
                f"关键字库仍{hint}，与工程默认 {label} 不一致。"
                f"请工程树右键该用例 →「标记平台」改为 {label}，或切换到未标平台的用例。",
                "工程",
                "WARNING",
            )
        self._refresh_open_case_platform_ui()

    def set_case_platform(self, plat: str) -> None:
        """标记用例目标平台（"" 通用 / android / ios / web）：写入 .tc.yaml。"""
        path = self.project_tree.selected_path()
        if not path or not path.endswith((".tc.yaml", ".tc.yml")):
            self.console.log("请选中一个用例(.tc.yaml)再标记平台", "工程", "WARNING")
            return
        tc = serializer.load(path)
        tc.platform = plat
        serializer.save_testcase(tc, path)
        # 同步内存中已打开的同一用例（避免文件/编辑器不一致）
        opened = self.case_editor.case
        if opened is not None and getattr(opened, "source_path", "") == path:
            opened.platform = plat
        self._sync_platform_context()
        self._refresh_open_case_platform_ui()
        label = platform_label(plat)
        self.console.log(f"已标记用例平台：{display_name(os.path.basename(path))} → {label}", "工程")

    def _copy_path(self) -> None:
        path = self.project_tree.selected_path()
        if path:
            QApplication.clipboard().setText(os.path.normpath(path))
            self.console.log(f"已复制路径：{path}", "工程")

    def reveal_in_explorer(self) -> None:
        """在系统文件管理器中定位当前选中项（跨平台）。"""
        path = self.project_tree.selected_path() or self.project_dir
        self.reveal_path(path)

    # ---- 打开文件标签栏（多文件切换）----
    def _doc_index(self, path: str) -> int:
        if not path:
            return -1
        npath = os.path.normcase(os.path.normpath(path))
        for i, d in enumerate(getattr(self, "_open_docs", [])):
            if d["path"] and os.path.normcase(os.path.normpath(d["path"])) == npath:
                return i
        return -1

    def _select_tab(self, idx: int) -> None:
        self._switching_tab = True
        try:
            self._tab_bar.setCurrentIndex(idx)
        finally:
            self._switching_tab = False

    def _register_open(self, editor, model, kind: str, path, title: str) -> None:
        """把「已 show_X + setCurrentWidget」的文件登记为标签页并激活；已打开则更新+激活。"""
        idx = self._doc_index(path) if path else -1
        if idx >= 0:
            self._open_docs[idx].update(
                editor=editor, model=model, kind=kind, title=title, saved_model=copy.deepcopy(model),
            )
            self._tab_bar.setTabText(idx, title)
            self._select_tab(idx)
            return
        self._open_docs.append({
            "path": path, "kind": kind, "editor": editor, "model": model, "title": title,
            "saved_model": copy.deepcopy(model),
        })
        self._switching_tab = True
        try:
            i = self._tab_bar.addTab(title)
        finally:
            self._switching_tab = False
        self._tab_bar.setTabToolTip(i, path or title)
        self._doc_tab_row.show()
        self._select_tab(i)

    def _show_doc(self, doc: dict) -> None:
        ed, model, kind = doc["editor"], doc["model"], doc["kind"]
        show = {"case": "show_case", "suite": "show_suite", "map": "show_map",
                "keyword": "show_keyworddef", "dataconfig": "show_dataconfig",
                "testplan": "show_testplan"}[kind]
        getattr(ed, show)(model)
        self.center.setCurrentWidget(ed)
        self._sync_step_editor_context(kind)

    def _on_tab_changed(self, idx: int) -> None:
        if self._switching_tab or not (0 <= idx < len(self._open_docs)):
            return
        self._show_doc(self._open_docs[idx])

    def _on_tab_close(self, idx: int) -> None:
        if not (0 <= idx < len(self._open_docs)):
            return
        if self._confirm_close_docs([idx]):
            self._remove_doc(idx)

    def _confirm_close_docs(self, indexes) -> bool:
        active = self._tab_bar.currentIndex()
        save_indexes = []
        buttons = QMessageBox.StandardButton
        for idx in indexes:
            doc = self._open_docs[idx]
            if doc["path"] and doc["model"] == doc.get("saved_model"):
                continue
            choice = QMessageBox.question(
                self, "未保存的修改", f"保存「{doc['title']}」的修改？",
                buttons.Save | buttons.Discard | buttons.Cancel, buttons.Save,
            )
            if choice not in (buttons.Save, buttons.Discard):
                return False
            if choice == buttons.Save:
                save_indexes.append(idx)

        for idx in save_indexes:
            self._select_tab(idx)
            self._show_doc(self._open_docs[idx])
            save = self.save_current if self._open_docs[idx]["path"] else self.save_as_dialog
            if not save():
                return False
        if save_indexes and 0 <= active < len(self._open_docs):
            self._select_tab(active)
            self._show_doc(self._open_docs[active])
        return True

    def _remove_doc(self, idx: int) -> None:
        self._open_docs.pop(idx)
        self._switching_tab = True
        try:
            self._tab_bar.removeTab(idx)
        finally:
            self._switching_tab = False
        if self._open_docs:
            nxt = min(idx, len(self._open_docs) - 1)
            self._select_tab(nxt)
            self._show_doc(self._open_docs[nxt])
        else:
            self._show_idle_center()

    def _resync_active_doc(self) -> None:
        """保存后：把当前标签的 path/标题同步为模型的新 source_path（未命名→已保存）。"""
        idx = self._tab_bar.currentIndex()
        if not (0 <= idx < len(self._open_docs)):
            return
        doc = self._open_docs[idx]
        doc["saved_model"] = copy.deepcopy(doc["model"])
        sp = getattr(doc["model"], "source_path", "") or ""
        if sp:
            doc["path"] = sp
            doc["title"] = display_name(os.path.basename(sp))
            self._tab_bar.setTabText(idx, doc["title"])
            self._tab_bar.setTabToolTip(idx, sp)

    @staticmethod
    def _doc_title(path: str, fallback: str) -> str:
        return display_name(os.path.basename(path)) if path else fallback

    # ---- 业务协调 ----
    def _on_file_activated(self, path: str, line: int = 0) -> None:
        # 已打开则直接切到其标签页，不重载（保住未保存的编辑）
        idx = self._doc_index(path)
        if idx >= 0:
            self._select_tab(idx)
            self._show_doc(self._open_docs[idx])
            if line > 0:
                self._goto_source_line(path, line)
            return
        self._dispatch_open(path)
        if line > 0:
            self._goto_source_line(path, line)

    @staticmethod
    def _read_line_snippet(path: str, line: int) -> str:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for ln, content in enumerate(fh, 1):
                    if ln == line:
                        return content.rstrip("\n")
        except OSError:
            pass
        return ""

    def _goto_source_line(self, path: str, line: int) -> None:
        """搜索命中后：尽量在步骤编辑器选中对应行，否则在控制台展示源行。"""
        snippet = self._read_line_snippet(path, line)
        if not snippet:
            self.console.log(f"无法读取 {os.path.basename(path)} 第 {line} 行", "搜索", "WARNING")
            return
        idx = self._doc_index(path)
        if idx >= 0:
            kind = self._open_docs[idx].get("kind")
            hint = keyword_hint_from_line(snippet)
            if kind == "case" and hint and self.case_editor.select_by_keyword(hint):
                self.case_editor.setFocus()
                self.console.log(
                    f"已定位 {os.path.basename(path)} 第 {line} 行 → 步骤「{hint}」", "搜索")
                return
        short = snippet.strip()[:100]
        self.console.log(f"{os.path.basename(path)} 第 {line} 行：{short}", "搜索")

    def copy_path_text(self, path: str) -> None:
        if path:
            QApplication.clipboard().setText(os.path.normpath(path))
            self.console.log(f"已复制路径：{path}", "搜索")

    def _run_find_references(self, target: str) -> None:
        """查找引用/工程检索：结果写入底栏面板并升起 Dock。

        精确 id / ks:: / map:: 走语义引用；中文名与 id 子串会展开；
        仍无命中时回退全文子串检索。
        """
        t = (target or "").strip()
        if not t:
            self.console.log("查找引用：目标为空", "搜索", "WARNING")
            return
        if not self.project_dir or not os.path.isdir(self.project_dir):
            self.console.log("请先打开工程再查找引用", "搜索", "WARNING")
            return
        hits = find_in_project(self.project_dir, t)
        panel = getattr(self, "search_results", None)
        if panel is not None:
            panel.set_project_dir(self.project_dir)
            panel.show_results(t, hits)
            dock = self._docks.get("查找引用") if hasattr(self, "_docks") else None
            if dock is not None:
                dock.show()
                dock.raise_()
            if hasattr(panel, "focus_input"):
                panel.focus_input(t)
        self.console.log(f"查找引用「{t}」：{len(hits)} 处", "搜索")

    def find_references_action(self) -> None:
        """菜单/快捷键：从当前上下文推断 target，否则弹输入框。"""
        target = ""
        editor = self._current_case_editor() if hasattr(self, "_current_case_editor") else None
        if editor is not None and hasattr(editor, "selected_node"):
            node = editor.selected_node()
            if isinstance(node, StepVerbs):
                target = f"ks::{node.ks_id}"
            elif isinstance(node, Step):
                target = node.keyword_id or ""
        if not target and self.center.currentWidget() is getattr(self, "map_editor", None):
            target = self.map_editor.current_map_ref() if hasattr(self.map_editor, "current_map_ref") else ""
        if not target and hasattr(self, "keyword_panel"):
            # noinspection PyBroadException
            try:
                target = self.keyword_panel.current_keyword_id() or ""
            except Exception:
                target = ""
        if not target:
            # 无上下文时升起底栏并聚焦输入框，而不是再弹对话框
            panel = getattr(self, "search_results", None)
            dock = self._docks.get("查找引用") if hasattr(self, "_docks") else None
            if dock is not None:
                dock.show()
                dock.raise_()
            if panel is not None and hasattr(panel, "focus_input"):
                panel.focus_input("")
                return
            text, ok = QInputDialog.getText(
                self, "查找引用",
                "关键字 id / ks::自定义关键字 / map::文件::元素：")
            if not ok or not str(text).strip():
                return
            target = str(text).strip()
        self._run_find_references(target)

    def reveal_path(self, path: str) -> None:
        """在系统文件管理器中定位指定路径（搜索右键等）。"""
        if not path or not os.path.lexists(path):
            self.console.log("无可定位的路径", "文件", "WARNING")
            return
        # noinspection PyBroadException
        try:
            if sys.platform.startswith("win"):
                if os.path.isdir(path):
                    os.startfile(path)                                  # noqa: S606
                else:
                    subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R" if os.path.isfile(path) else path, path])
            else:
                folder = path if os.path.isdir(path) else os.path.dirname(path)
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:  # noqa: BLE001
            self.console.log(f"打开资源管理器失败：{e}", "文件", "ERROR")

    def _dispatch_open(self, path: str) -> None:
        if path.endswith(".tc.yaml") or path.endswith(".tc.yml"):
            self._open_case(serializer.load(path), path, "新格式")
        elif path.endswith(".tc"):
            self._open_case(load_testcase(path), path, "旧格式")
        elif path.endswith(".map.yaml") or path.endswith(".map.yml"):
            self._open_map(serializer.load(path), path, "新格式")
        elif path.endswith(".map"):
            self._open_map(load_mapfile(path), path, "旧格式")
        elif path.endswith(".ks.yaml") or path.endswith(".ks.yml"):
            self._open_keyword(serializer.load(path), path, "新格式")
        elif path.endswith(".ks"):
            self._open_keyword(load_keyword(path), path, "旧格式")
        elif path.endswith((".ts.yaml", ".ts.yml")):
            self._open_suite(serializer.load(path), path, "新格式")
        elif path.endswith(".ts"):
            self._open_suite(load_testsuite(path), path, "旧格式")
        elif path.endswith((".tp.yaml", ".tp.yml")):
            self._open_testplan(serializer.load(path), path, "新格式")
        elif path.endswith(".tp"):
            self._open_testplan(load_testplan(path), path, "旧格式")
        elif path.endswith(".properties"):
            self._open_dataconfig(dataconfig_model.load(path), path)
        elif path.lower().endswith(".html"):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(path)))
            self.console.log(f"已在浏览器打开报告：{os.path.basename(path)}", "文件")
        elif path.lower().endswith((".apk", ".xapk", ".ipa")):
            self.console.log(
                f"安装包：{os.path.basename(path)}（可在 mobile_app_install_and_open 步骤中引用）",
                "文件",
            )
            self.reveal_in_explorer()
        elif path.lower().endswith((".log", ".json", ".jsonl", ".txt")):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(path)))
            self.console.log(f"已用系统默认程序打开：{os.path.basename(path)}", "文件")

    def _open_dataconfig(self, cfg, path: str) -> None:
        cfg.source_path = path
        self.dataconfig_editor.show_dataconfig(cfg)
        self.center.setCurrentWidget(self.dataconfig_editor)
        self._register_open(self.dataconfig_editor, cfg, "dataconfig", path,
                            self._doc_title(path, "数据配置"))
        self.console.log(f"已打开数据配置：{os.path.basename(path)}（共 {len(cfg.entries)} 项）", "文件")

    def _open_suite(self, ts, path: str, kind: str) -> None:
        ts.source_path = path
        self.suite_editor.show_suite(ts)
        self.center.setCurrentWidget(self.suite_editor)
        self._register_open(self.suite_editor, ts, "suite", path, self._doc_title(path, ts.name))
        self.console.log(f"已打开测试套（{kind}）：{ts.name}（{path}）", "文件")

    def _open_testplan(self, tp, path: str, kind: str) -> None:
        tp.source_path = path
        self.testplan_editor.show_testplan(tp)
        self.center.setCurrentWidget(self.testplan_editor)
        self._register_open(self.testplan_editor, tp, "testplan", path,
                            self._doc_title(path, tp.name))
        self.console.log(f"已打开测试计划（{kind}）：{tp.name}（共 {len(tp.members)} 个成员）", "文件")

    def _open_keyword(self, kd: "KeywordDef", path: str, _kind: str) -> None:
        kd.source_path = path
        self._sync_keyword_editor_platform()
        self.keyword_editor.show_keyworddef(kd)
        self.center.setCurrentWidget(self.keyword_editor)
        self._register_open(self.keyword_editor, kd, "keyword", path,
                            self._doc_title(path, kd.ks_id))
        self.console.log(f"已打开自定义关键字：{kd.ks_id}", "文件")

    def _open_case(self, tc: "TestCase", path: str, kind: str) -> None:
        tc.source_path = path     # 记来源，供平台标记同步/保存定位
        self.case_editor.show_case(tc)
        self.center.setCurrentWidget(self.case_editor)
        self._register_open(self.case_editor, tc, "case", path, self._doc_title(path, tc.name))
        self._sync_step_editor_context("case")
        # 右侧属性：先展示用例级追踪字段（选中步骤后切换为参数）
        show_meta = getattr(self.param_form, "show_case_meta", None)
        if callable(show_meta):
            show_meta(tc)
        self.console.log(f"已打开用例（{kind}）：{tc.name}（{path}）", "文件")

    def _open_map(self, mf: "MapFile", path: str, kind: str) -> None:
        mf.source_path = path
        self.map_editor.show_map(mf)
        self.center.setCurrentWidget(self.map_editor)
        self._register_open(self.map_editor, mf, "map", path, self._doc_title(path, mf.name))
        self.console.log(f"已打开对象库（{kind}）：{mf.name}（共 {len(mf.elements)} 个顶层元素）", "文件")

    def new_case(self) -> None:
        tc = TestCase(name="untitled")
        plat = settings.project_platform(self.project_dir) if (self.project_dir and os.path.isdir(self.project_dir)) else ""
        if not plat:
            choice, ok = QInputDialog.getItem(
                self, "快速草稿用例", "请选择用例平台",
                ["通用", "Android", "iOS", "Web", "HTTP / API"], 0, False)
            if ok:
                plat = {
                    "通用": "",
                    "Android": "android",
                    "iOS": "ios",
                    "Web": "web",
                    "HTTP / API": "http",
                }.get(choice, "")
                if plat and self.project_dir and os.path.isdir(self.project_dir):
                    settings.set_project_platform(self.project_dir, plat)
                    self._sync_keyword_editor_platform()
                    if hasattr(self, "_sync_ios_backend_controls"):
                        self._sync_ios_backend_controls()
        tc.platform = plat
        self.case_editor.show_case(tc)
        self.center.setCurrentWidget(self.case_editor)
        self._register_open(self.case_editor, tc, "case", None, "未命名用例")
        self._sync_step_editor_context("case")
        self.console.log("已打开快速草稿用例：从右侧「关键字库」双击添加步骤，完成后点「保存」落盘", "文件")

    def new_custom_keyword(self) -> None:
        kd = KeywordDef(ks_id="untitled_verb")
        self._sync_keyword_editor_platform()
        self.keyword_editor.show_keyworddef(kd)
        self.center.setCurrentWidget(self.keyword_editor)
        self._register_open(self.keyword_editor, kd, "keyword", None, "未命名关键字")
        self.console.log("已新建自定义关键字：从右侧「关键字库」双击添加步骤，完成后点「保存」", "文件")

    def close_current(self) -> None:
        """关闭当前标签页（多文件时切到相邻页，无页则回到空编辑区或欢迎页）。"""
        idx = self._tab_bar.currentIndex()
        if 0 <= idx < len(self._open_docs):
            self._on_tab_close(idx)
        else:
            self._show_idle_center()

    def _has_open_project(self) -> bool:
        return bool(self.project_dir) and os.path.isdir(self.project_dir)

    def _show_idle_center(self) -> None:
        """无打开文档时：有工程显示空编辑区，无工程显示欢迎页。"""
        self._doc_tab_row.hide()
        if self._has_open_project():
            self.center.setCurrentWidget(self.empty_workspace)
        else:
            self.center.setCurrentWidget(self.welcome)
        self._sync_step_editor_context()

    def close_project(self, *, discard_open: bool = False) -> None:
        """关闭当前工程：关全部标签，回到欢迎页（最近列表保留，下次启动不再自动恢复）。"""
        if not self._close_all_docs(confirm_unsaved=not discard_open):
            return
        if hasattr(self, "mirror"):
            # noinspection PyBroadException
            try:
                self.mirror.stop()
            except Exception:  # noqa: BLE001
                pass
        if hasattr(self, "_reset_inspect_session"):
            self._reset_inspect_session()
        self.project_dir = ""
        self.project_tree.set_root("")
        self.project_tree.clear_checks()
        if getattr(self, "project_panel", None) is not None:
            self.project_panel.set_actions_enabled(False)
            self.project_panel.filter.clear()
        self.param_form.set_project_dir("")
        if hasattr(self, "search_results"):
            self.search_results.set_project_dir("")
        self.param_form.clear_step()
        self._refresh_custom_keywords()
        self._sync_keyword_editor_platform()
        if hasattr(self, "_sync_ios_backend_controls"):
            self._sync_ios_backend_controls()
        settings.forget_last_project()
        self._sync_sidebar_project()
        self._sync_window_title()
        self._show_idle_center()
        self.console.log("已关闭工程", "工程")

    def save_current(self) -> bool:
        """保存当前中央编辑器内容（用例/对象库/自定义关键字）为新格式 YAML。"""
        cur = self.center.currentWidget()
        if cur in (self.welcome, getattr(self, "empty_workspace", None)):
            self.console.log("没有可保存的内容", "文件", "WARNING")
            return False
        try:
            if cur is self.map_editor:
                self._save_map()
            elif cur is self.keyword_editor:
                self._save_keyword()
            elif cur is self.dataconfig_editor:
                self._save_dataconfig()
            elif cur is self.suite_editor:
                self._save_suite()
            elif cur is self.testplan_editor:
                self._save_testplan()
            else:
                self.save_current_case()
        except (OSError, TypeError, ValueError) as exc:
            self.console.log(f"保存失败：{exc}", "文件", "ERROR")
            QMessageBox.warning(self, "保存失败", str(exc))
            return False
        self._resync_active_doc()   # 未命名→已保存：同步标签标题/路径
        return True

    def _save_suite(self) -> None:
        ts = self.suite_editor.suite
        if ts is None:
            self.console.log("没有可保存的测试套", "文件", "WARNING")
            return
        path = ts.source_path or ""
        if path.endswith((".ts.yaml", ".ts.yml")):
            out = path
        elif path.endswith(".ts"):
            out = path + ".yaml"
        else:
            out = os.path.join(
                self.project_dir or ".",
                validate_portable_name(ts.name or "untitled") + ".ts.yaml",
            )
        serializer.save_testsuite(ts, out)
        ts.source_path = out
        self.console.log(f"已保存测试套：{out}", "文件")

    def _save_testplan(self) -> None:
        tp = self.testplan_editor.testplan
        if tp is None:
            self.console.log("没有可保存的测试计划", "文件", "WARNING")
            return
        path = tp.source_path or ""
        if path.endswith((".tp.yaml", ".tp.yml")):
            out = path
        elif path.endswith(".tp"):
            out = path + ".yaml"
        else:
            out = os.path.join(
                self.project_dir or ".",
                validate_portable_name(tp.name or "untitled") + ".tp.yaml",
            )
        serializer.save_testplan(tp, out)
        tp.source_path = out
        self.console.log(f"已保存测试计划：{out}", "文件")

    def _save_dataconfig(self) -> None:
        cfg = self.dataconfig_editor.dataconfig
        if cfg is None:
            self.console.log("没有可保存的数据配置", "文件", "WARNING")
            return
        path = cfg.source_path or os.path.join(self.project_dir or ".", "DataConfig.properties")
        dataconfig_model.save(cfg, path)
        cfg.source_path = path
        self.console.log(f"已保存数据配置：{path}", "文件")

    def _save_keyword(self) -> None:
        kd = self.keyword_editor.keyworddef
        if kd is None:
            self.console.log("没有可保存的自定义关键字", "文件", "WARNING")
            return
        path = kd.source_path or ""
        if path.endswith((".ks.yaml", ".ks.yml")):
            out = path
        elif path.endswith(".ks"):
            out = path + ".yaml"
        else:
            base = (kd.ks_id or "untitled_verb")
            out = os.path.join(
                self.project_dir or ".",
                validate_portable_name(base) + ".ks.yaml",
            )
        serializer.save_keyword(kd, out)
        kd.source_path = out
        self.console.log(f"已保存自定义关键字：{out}", "文件")
        self._refresh_custom_keywords()

    def save_current_case(self) -> None:
        """保存当前用例为新格式 YAML。旧格式(.tc)另存为同名 .tc.yaml。"""
        tc = self.case_editor.case
        if tc is None:
            self.console.log("没有可保存的用例", "文件", "WARNING")
            return
        self._warn_case_platform_lint(tc)
        path = tc.source_path or ""
        if path.endswith(".tc.yaml") or path.endswith(".tc.yml"):
            out = path
        elif path.endswith(".tc"):
            out = path + ".yaml"  # login.tc → login.tc.yaml
        else:
            if path:
                out = path + ".tc.yaml"
            else:
                out = os.path.join(
                    self.project_dir or ".",
                    validate_portable_name(tc.name or "untitled") + ".tc.yaml",
                )
        serializer.save_testcase(tc, out)
        tc.source_path = out
        self.console.log(f"已保存用例：{out}", "文件")
        prompt = getattr(self, "mgmt_prompt_sync_after_save", None)
        if callable(prompt):
            prompt(tc)

    def _save_map(self) -> None:
        mf = self.map_editor.mapfile
        if mf is None:
            self.console.log("没有可保存的对象库", "文件", "WARNING")
            return
        path = mf.source_path or ""
        if path.endswith(".map.yaml") or path.endswith(".map.yml"):
            out = path
        elif path.endswith(".map"):
            out = path + ".yaml"
        else:
            if path:
                out = path + ".map.yaml"
            else:
                out = os.path.join(
                    self.project_dir or ".",
                    validate_portable_name(mf.name or "untitled") + ".map.yaml",
                )
        serializer.save_mapfile(mf, out)
        mf.source_path = out
        self.console.log(f"已保存对象库：{out}", "文件")

    # ---- 文件/工程操作 ----
    def new_project_dialog(self) -> None:
        """新建工程：一个对话框里填「位置(父目录)+工程名」(带路径预览) → 建目录并打开为工作区。"""
        from ..widgets.new_project_dialog import NewProjectDialog  # 延迟：仅新建工程
        base = self.project_dir or os.path.expanduser("~")
        dlg = NewProjectDialog(self, base)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        parent, name = dlg.parent_dir(), dlg.project_name()
        if not parent or not name:
            return
        try:
            name = validate_portable_name(name)
        except ValueError as e:
            self.console.log(f"新建工程失败：{e}", "工程", "ERROR")
            return
        path = os.path.join(parent, name)
        if os.path.isdir(path):
            self.console.log(f"目录已存在，直接打开：{path}", "工程", "WARNING")
            self.open_project(path)
            return
        try:
            path = self.create_project(parent, name)
        except (OSError, ValueError) as e:
            self.console.log(f"新建工程失败：{e}", "工程", "ERROR")
            return
        settings.set_project_platform(path, dlg.project_platform())
        self.console.log(f"已新建工程：{path}", "工程")
        self.open_project(path)

    @staticmethod
    def create_project(parent: str, name: str) -> str:
        """建工程目录 + 自动骨架，返回工程路径（纯逻辑，供对话框与测试复用）。

        自动建工程级共享的「数据配置」骨架 config/DataConfig.properties（空模板、内容不写死，
        对标参考工具的新建工程行为）；用例/套件/对象库等业务内容仍由用户按需手动新建。"""
        name = validate_portable_name(name)
        path = os.path.join(parent, name)
        os.makedirs(path, exist_ok=True)
        cfg_dir = os.path.join(path, "config")
        os.makedirs(cfg_dir, exist_ok=True)
        cfg = os.path.join(cfg_dir, "DataConfig.properties")
        if not os.path.exists(cfg):
            dataconfig_model.save(dataconfig_model.DataConfig(source_path=cfg), cfg)   # 空数据配置，等用户填
        return path

    def open_project_dialog(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "打开工程目录", self.project_dir or "")
        if d:
            self.open_project(d)

    def open_project(self, directory: str) -> None:
        directory = os.path.abspath(os.path.normpath(directory)) if directory else ""
        if directory and not os.path.isdir(directory):
            self.console.log(f"工程目录不存在：{directory}", "工程", "WARNING")
            return
        if not self._close_all_docs():
            return
        # 切工程：停镜像/检视会话，避免仍绑定旧设备
        if hasattr(self, "mirror"):
            # noinspection PyBroadException
            try:
                self.mirror.stop()
            except Exception:  # noqa: BLE001
                pass
        if hasattr(self, "_reset_inspect_session"):
            self._reset_inspect_session()
        self.project_tree.clear_checks()  # 批量运行勾选集属于旧工程，切换时不能带过去
        self.project_dir = directory
        self.project_tree.set_root(directory)
        if getattr(self, "project_panel", None) is not None:
            self.project_panel.set_actions_enabled(bool(directory) and os.path.isdir(directory))
            self.project_panel.filter.clear()
        self.param_form.set_project_dir(directory or "")
        if hasattr(self, "search_results"):
            self.search_results.set_project_dir(directory or "")
        self.param_form.clear_step()
        self._refresh_custom_keywords()
        self._sync_keyword_editor_platform()
        if hasattr(self, "_sync_ios_backend_controls"):
            self._sync_ios_backend_controls()
        settings.remember_project(directory)   # 记住为上次工程，下次启动自动恢复
        self._sync_sidebar_project()
        self._sync_window_title()
        self._show_idle_center()            # 打开工程不等于打开文件：停在空编辑区，不回欢迎页
        self.console.log(f"已打开工程：{directory}", "工程")

    def open_file_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "打开文件", self.project_dir or "",
            "工程文件 (*.tc *.ts *.map *.properties *.ks *.yaml *.yml);;所有文件 (*)")
        if path:
            self._on_file_activated(path)

    def _target_dir(self) -> str:
        """新建资源的目标目录：工程树选中目录优先，选中文件则其所在目录，否则工程根。
        无工程时返回空串（由 _require_project 拦截，绝不落到当前工作目录）。"""
        return self.project_tree.selected_dir() or self.project_dir or ""

    def _require_project(self) -> bool:
        """需要工程上下文的操作（直接落文件）前置校验：无工程则提示并拦截。"""
        if self.project_dir and os.path.isdir(self.project_dir):
            return True
        self.console.log("请先「新建工程」或「打开工程」，再在工程内新建资源", "工程", "WARNING")
        QMessageBox.information(self, "需要工程", "请先「新建工程」或「打开工程」。")
        return False

    _RES_LABELS = {"case": "用例", "suite": "测试套", "map": "对象库",
                   "dataconfig": "数据配置", "testplan": "测试计划",
                   "keyword": "自定义关键字"}

    def _new_resource(self, kind: str) -> None:
        if not self._require_project():
            return
        label = self._RES_LABELS.get(kind, kind)
        name, ok = QInputDialog.getText(self, f"新建{label}", "名称：")
        if not ok or not name.strip():
            return
        try:
            path = self.create_resource(kind, self._target_dir(), name)
        except (OSError, ValueError) as exc:
            self.console.log(f"新建{label}失败：{exc}", "文件", "ERROR")
            QMessageBox.warning(self, f"新建{label}失败", str(exc))
            return
        self.project_tree.refresh()
        self._on_file_activated(path)
        if kind in ("case", "map", "keyword"):
            self._refresh_custom_keywords()
        self.console.log(f"已新建{label}：{path}", "文件")

    def _new_folder_dialog(self) -> None:
        if not self._require_project():
            return
        name, ok = QInputDialog.getText(self, "新建文件夹", "名称：")
        if not ok:
            return
        try:
            path = self.create_folder(self._target_dir(), name)
        except (OSError, ValueError) as exc:
            self.console.log(f"新建文件夹失败：{exc}", "工程", "ERROR")
            QMessageBox.warning(self, "新建文件夹失败", str(exc))
            return
        self.project_tree.refresh()
        self.console.log(f"已新建文件夹：{path}", "工程")

    def save_as_dialog(self) -> bool:
        cur = self.center.currentWidget()
        specs = {
            self.case_editor: (".tc.yaml", (".tc.yaml", ".tc.yml")),
            self.suite_editor: (".ts.yaml", (".ts.yaml", ".ts.yml")),
            self.testplan_editor: (".tp.yaml", (".tp.yaml", ".tp.yml")),
            self.map_editor: (".map.yaml", (".map.yaml", ".map.yml")),
            self.keyword_editor: (".ks.yaml", (".ks.yaml", ".ks.yml")),
            self.dataconfig_editor: (".properties", (".properties",)),
        }
        spec = specs.get(cur)
        if spec is None:
            self.console.log("没有可另存的内容", "文件", "WARNING")
            return False
        suffix, allowed_suffixes = spec
        file_type = "Properties" if suffix == ".properties" else "YAML"
        path, _ = QFileDialog.getSaveFileName(
            self, "另存为", self.project_dir or "", f"{file_type} (*{suffix})")
        if not path:
            return False
        try:
            base = validate_portable_name(os.path.basename(path))
            path = os.path.join(os.path.dirname(path), base)
            if not path.lower().endswith(allowed_suffixes):
                path += suffix
                if os.path.lexists(path) and QMessageBox.question(
                    self, "覆盖文件", f"覆盖「{os.path.basename(path)}」？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                ) != QMessageBox.StandardButton.Yes:
                    return False
            if cur is self.map_editor and self.map_editor.mapfile is not None:
                serializer.save_mapfile(self.map_editor.mapfile, path)
                self.map_editor.mapfile.source_path = path
            elif cur is self.keyword_editor and self.keyword_editor.keyworddef is not None:
                serializer.save_keyword(self.keyword_editor.keyworddef, path)
                self.keyword_editor.keyworddef.source_path = path
                self._refresh_custom_keywords()
            elif cur is self.case_editor and self.case_editor.case is not None:
                serializer.save_testcase(self.case_editor.case, path)
                self.case_editor.case.source_path = path
            elif cur is self.suite_editor and self.suite_editor.suite is not None:
                serializer.save_testsuite(self.suite_editor.suite, path)
                self.suite_editor.suite.source_path = path
            elif cur is self.testplan_editor and self.testplan_editor.testplan is not None:
                serializer.save_testplan(self.testplan_editor.testplan, path)
                self.testplan_editor.testplan.source_path = path
            elif cur is self.dataconfig_editor and self.dataconfig_editor.dataconfig is not None:
                dataconfig_model.save(self.dataconfig_editor.dataconfig, path)
                self.dataconfig_editor.dataconfig.source_path = path
            else:
                self.console.log("没有可另存的内容", "文件", "WARNING")
                return False
        except (OSError, TypeError, ValueError) as exc:
            self.console.log(f"另存为失败：{exc}", "文件", "ERROR")
            QMessageBox.warning(self, "另存为失败", str(exc))
            return False
        self._resync_active_doc()   # 当前标签重定向到新路径（否则保存仍写旧文件）
        self.project_tree.refresh()
        if cur is self.keyword_editor:
            self._refresh_custom_keywords()
        self.console.log(f"已另存为：{path}", "文件")
        return True

    def rename_dialog(self) -> None:
        path = self.project_tree.selected_path()
        if not path or not os.path.lexists(path):
            self.console.log("请先在工程树选中要重命名的文件或文件夹", "工程", "WARNING")
            return
        old_norm = os.path.normcase(os.path.normpath(path))
        project_norm = os.path.normcase(os.path.normpath(self.project_dir or ""))
        renaming_project = bool(project_norm) and old_norm == project_norm
        old = os.path.basename(path)
        stem = display_name(old)                 # 去后缀显示名
        suffix = "" if os.path.isdir(path) else old[len(stem):]   # 原复合后缀(.tc.yaml/.properties…)
        new_name, ok = QInputDialog.getText(self, "重命名", "新名称：", text=stem)
        nn = (new_name or "").strip()
        if not ok or not nn:
            return
        if suffix and not nn.endswith(suffix):    # 用户没带后缀则自动补回，保留文件类型
            nn += suffix
        try:
            if renaming_project:
                # 若当前工作目录落在该工程内，先切到父目录以免阻塞重命名或留下失效 cwd
                try:
                    cwd_real = os.path.normcase(os.path.realpath(os.getcwd()))
                    old_real = os.path.normcase(os.path.realpath(path))
                    if cwd_real == old_real or cwd_real.startswith(old_real + os.sep):
                        parent_dir = os.path.dirname(path)
                        if parent_dir and os.path.isdir(parent_dir):
                            os.chdir(parent_dir)
                except OSError:
                    pass
                # 先卸载并销毁 QFileSystemModel 的旧根，释放 Windows/macOS/Linux 目录监视句柄。
                self.project_tree.set_root("")
                QApplication.processEvents()
                import errno as _errno
                import sys as _sys
                import time as _time

                newp = ""
                for attempt in range(6):
                    try:
                        newp = self.rename_path(path, nn)
                        break
                    except OSError as rename_exc:
                        busy_err = isinstance(rename_exc, PermissionError) or getattr(
                            rename_exc, "errno", None
                        ) in (_errno.EACCES, _errno.EPERM, _errno.EBUSY)
                        if not busy_err or attempt >= 5:
                            if busy_err:
                                fm_name = (
                                    "资源管理器"
                                    if _sys.platform == "win32"
                                    else ("访达（Finder）" if _sys.platform == "darwin" else "文件管理器")
                                )
                                detail_msg = f"{rename_exc.strerror or rename_exc}（请确认未在{fm_name}、终端或其他程序中占用该目录）"
                                if _sys.platform == "win32":
                                    raise type(rename_exc)(
                                        rename_exc.errno,
                                        detail_msg,
                                        rename_exc.filename,
                                        getattr(rename_exc, "winerror", None),
                                        rename_exc.filename2,
                                    ) from rename_exc
                                raise type(rename_exc)(
                                    rename_exc.errno,
                                    detail_msg,
                                    rename_exc.filename,
                                ) from rename_exc
                            raise
                        _time.sleep(0.05)
                        QApplication.processEvents()
            else:
                newp = self.rename_path(path, nn)
        except (OSError, ValueError) as exc:
            # 文件名冲突、非法名称或锁定文件必须留在 Qt 槽内处理，不能让异常终止 IDE。
            if renaming_project and os.path.isdir(path):
                self.project_tree.set_root(path)
            self.console.log(f"重命名失败：{exc}", "工程", "ERROR")
            QMessageBox.warning(self, "重命名失败", str(exc))
            return

        self._rename_open_paths(path, newp)   # 若正开着，同步标签/模型路径，别让保存写回旧名
        self.project_tree.rebase_paths(path, newp)
        failures: dict[str, str] = {}
        if renaming_project:
            # 工程根也是应用状态；成功改名后所有消费者都切换到新路径，
            # 否则下一次保存/刷新会继续访问已经不存在的旧目录。
            self.project_dir = newp
            self.project_tree.set_root(newp)
            if getattr(self, "project_panel", None) is not None:
                self.project_panel.set_actions_enabled(True)
            self.param_form.set_project_dir(newp)
            if hasattr(self, "search_results"):
                self.search_results.set_project_dir(newp)
            # Project defaults are keyed by normalized path in settings;
            # carry the value forward and remove any stale old key.
            updated = (
                settings.rename_project_platform(path, newp),
                settings.rename_mc_bound_project(path, newp),
                settings.remember_project(newp),
            )
            if not all(updated):
                failures[settings.config_dir()] = "工程设置未能保存"
            self._sync_sidebar_project()
            self._sync_window_title()
        else:
            self.project_tree.refresh()
        self._rewrite_project_references(path, newp, failures)
        self._rebase_file_references(path, newp, failures)
        self._rebase_testplan_refs(path, newp, failures)
        self._rebase_map_refs(path, newp, failures)
        self._refresh_open_case_platform_ui()
        current = self.center.currentWidget()
        if current is self.case_editor:
            self._sync_step_editor_context("case")
        elif current is self.suite_editor:
            self._sync_step_editor_context("suite")
        elif current is self.keyword_editor:
            self._sync_step_editor_context("keyword")
        self._refresh_custom_keywords()       # 改的是 .ks 或工程目录则按新路径重扫
        self._sync_keyword_editor_platform()
        if hasattr(self, "_sync_ios_backend_controls"):
            self._sync_ios_backend_controls()
        label = f"{stem} → {display_name(os.path.basename(newp))}"
        if failures:
            for file_path, reason in failures.items():
                self.console.log(f"引用同步失败：{file_path}（{reason}）", "工程", "ERROR")
            QMessageBox.warning(
                self, "重命名后引用同步未完成",
                f"{label}\n有 {len(failures)} 处未能同步。请在控制台查看文件路径和原因。",
            )
        else:
            self.console.log(f"已重命名：{label}", "工程")

    def delete_dialog(self) -> None:
        path = self.project_tree.selected_path()
        if not path or not os.path.lexists(path):
            self.console.log("请先在工程树选中要删除的文件或文件夹", "工程", "WARNING")
            return
        kind = "文件夹" if os.path.isdir(path) else "文件"
        disp = display_name(os.path.basename(path))     # 去后缀显示(与工程树一致)，不暴露全路径
        deleting_project = bool(self.project_dir) and (
            os.path.normcase(os.path.normpath(path))
            == os.path.normcase(os.path.normpath(self.project_dir))
        )
        prompt = f"确定删除{kind}「{disp}」？"
        if deleting_project and any(
            not doc["path"] or doc["model"] != doc.get("saved_model") for doc in self._open_docs
        ):
            prompt += "\n打开文档中的未保存修改也将丢弃。"
        if confirm(self, "确认删除", prompt, danger=True):
            try:
                self.delete_path(path)
            except OSError as exc:
                self.console.log(f"删除失败：{exc}", "工程", "ERROR")
                QMessageBox.warning(self, "删除失败", str(exc))
                return
            self.project_tree.drop_paths(path)
            self._close_open_under(path)     # 删掉的文件/目录若正开着，关掉其标签，别让编辑区残留
            if deleting_project:
                # 删除当前工程根后立即退出工程态，避免 project_dir、最近工程和
                # 面板继续指向已不存在的目录。
                self.close_project(discard_open=True)
                return
            self.project_tree.refresh()
            self._refresh_custom_keywords()  # 删的是 .ks 则从关键字库移除，避免残留失效条目
            self.console.log(f"已删除{kind}：{disp}", "工程")

    def _close_open_under(self, path: str) -> None:
        """关闭「正是该路径 / 位于该被删目录下」的所有已打开标签。

        删文件/目录后调用：否则编辑区仍显示已不存在文件的内容（保存会重新落盘，形同"复活"）。
        从后往前关，避免 _on_tab_close 弹出后索引错位。
        """
        norm = os.path.normcase(os.path.normpath(path))
        prefix = norm + os.sep
        for idx in range(len(getattr(self, "_open_docs", [])) - 1, -1, -1):
            dp = self._open_docs[idx].get("path") or ""
            if not dp:
                continue
            n = os.path.normcase(os.path.normpath(dp))
            if n == norm or n.startswith(prefix):
                self._remove_doc(idx)

    def _close_all_docs(self, *, confirm_unsaved: bool = True) -> bool:
        """关闭全部已打开标签（切换/打开工程时用，避免残留上一个工程的编辑内容）。"""
        indexes = range(len(self._open_docs))
        if confirm_unsaved and not self._confirm_close_docs(indexes):
            return False
        for idx in reversed(indexes):
            self._remove_doc(idx)
        return True

    def _rename_open_paths(self, old: str, new: str) -> None:
        """文件/目录被重命名后，同步「正是它 / 位于其下」的已打开标签：
        更新标签 path/标题、模型 source_path（否则保存会写回旧名，或重开出现重复标签）。
        _open_docs 与标签按同一索引对齐。"""
        o = os.path.normcase(os.path.normpath(old))
        oprefix = o + os.sep
        for idx, doc in enumerate(getattr(self, "_open_docs", [])):
            dp = doc.get("path") or ""
            if not dp:
                continue
            n = os.path.normcase(os.path.normpath(dp))
            if n == o:
                newp = new
            elif n.startswith(oprefix):
                newp = os.path.join(new, os.path.relpath(dp, old))
            else:
                continue
            doc["path"] = newp
            model = doc.get("model")
            if model is not None and hasattr(model, "source_path"):
                model.source_path = newp
            saved_model = doc.get("saved_model")
            if saved_model is not None and hasattr(saved_model, "source_path"):
                saved_model.source_path = newp
            doc["title"] = display_name(os.path.basename(newp))
            self._tab_bar.setTabText(idx, doc["title"])
            self._tab_bar.setTabToolTip(idx, newp)

    @staticmethod
    def _rebased_path(path: str, old: str, new: str) -> str:
        """Map a path that was observed after a rename back to its old name."""
        norm = os.path.normcase(os.path.normpath(path))
        new_norm = os.path.normcase(os.path.normpath(new))
        prefix = new_norm + os.sep
        if norm == new_norm:
            return old
        if norm.startswith(prefix):
            return os.path.join(old, os.path.relpath(path, new))
        return path

    @staticmethod
    def _rebase_relative_ref(ref: str, old_base: str, new_base: str,
                             old: str, new: str) -> tuple[str, bool]:
        """Rewrite a relative project reference when its target was renamed."""
        raw = str(ref or "").strip()
        if not raw:
            return ref, False
        native = to_native(raw)
        target = native if os.path.isabs(native) else os.path.join(old_base, native)
        norm = os.path.normcase(os.path.normpath(target))
        old_norm = os.path.normcase(os.path.normpath(old))
        prefix = old_norm + os.sep
        if norm != old_norm and not norm.startswith(prefix):
            return ref, False
        target_new = new if norm == old_norm else os.path.join(
            new, os.path.relpath(target, old)
        )
        if os.path.isabs(native):
            return target_new, True
        return os.path.relpath(target_new, new_base).replace(os.sep, "/"), True

    @classmethod
    def _rewrite_reference_nodes(cls, nodes, old_base: str, new_base: str,
                                 old: str, new: str) -> bool:
        changed = False
        for node in nodes or []:
            if isinstance(node, StepInnerCase):
                value, did_change = cls._rebase_relative_ref(
                    node.relative_path, old_base, new_base, old, new)
                if did_change:
                    node.relative_path = value
                    changed = True
            children = getattr(node, "children", None)
            if children:
                changed = cls._rewrite_reference_nodes(
                    children, old_base, new_base, old, new
                ) or changed
        return changed

    @staticmethod
    def _reference_files(root: str, suffixes: tuple[str, ...], failures: dict[str, str]):
        if not root:
            return
        def on_error(error):
            failures[str(error.filename or root)] = str(error)

        for dirpath, dirnames, filenames in os.walk(root, onerror=on_error):
            dirnames[:] = [name for name in dirnames if not name.startswith(".")]
            for filename in filenames:
                if filename.lower().endswith(suffixes):
                    yield os.path.join(dirpath, filename)

    @staticmethod
    def _save_rebased_model(model, path: str) -> None:
        writers = {
            TestCase: serializer.save_testcase, TestSuite: serializer.save_testsuite,
            TestPlan: serializer.save_testplan, KeywordDef: serializer.save_keyword,
        }
        staged = ""
        try:
            with tempfile.NamedTemporaryFile(
                dir=os.path.dirname(path), prefix=".autopilot-refs-", suffix=".yaml", delete=False,
            ) as handle:
                staged = handle.name
            writers[type(model)](model, staged)
            shutil.copymode(path, staged)
            os.replace(staged, path)
        finally:
            if staged and os.path.exists(staged):
                os.unlink(staged)

    def _persist_rebased_models(self, root, yaml_suffixes, kinds, rewrite, failures) -> None:
        # Rewrite the saved YAML and the editor buffer independently. The buffer can
        # contain unrelated edits that the user has not chosen to save.
        for path in self._reference_files(root, yaml_suffixes, failures):
            try:
                model = serializer.load(path)
                if rewrite(model, path):
                    self._save_rebased_model(model, path)
            except (OSError, AttributeError, TypeError, ValueError, serializer.yaml.YAMLError) as exc:
                failures[path] = str(exc)

        for doc in self._open_docs:
            if doc.get("kind") not in kinds:
                continue
            path = doc.get("path") or ""
            rewrite(doc["model"], path)
            baseline = doc.get("saved_model")
            if baseline is not None and path and path not in failures:
                rewrite(baseline, path)

    def _rewrite_project_references(
        self, old: str, new: str, failures: dict[str, str] | None = None,
    ) -> None:
        """持久化内嵌用例路径，同时保留旧工程的 XML 格式。"""
        failures = {} if failures is None else failures
        from ...runtime.legacy_references import rewrite_legacy_references

        root = self.project_dir
        if not root:
            return
        for path in self._reference_files(root, (".tc", ".ts", ".ks", ".tp"), failures):
            try:
                rewrite_legacy_references(path, root, old, new, self._rebase_relative_ref)
            except (OSError, ValueError, TypeError) as exc:
                failures[path] = str(exc)

        def rewrite(model, doc_path: str) -> bool:
            new_base = os.path.dirname(doc_path) if doc_path else root
            old_base = os.path.dirname(self._rebased_path(doc_path, old, new)) if doc_path else root
            shells = getattr(model, "shells", None)
            if shells is None:
                return self._rewrite_reference_nodes(
                    getattr(model, "steps", []), old_base, new_base, old, new,
                )
            changed = False
            for shell in shells:
                changed = self._rewrite_reference_nodes(
                    shell.steps, old_base, new_base, old, new,
                ) or changed
            return changed

        suffixes = (".tc.yaml", ".tc.yml", ".ts.yaml", ".ts.yml", ".ks.yaml", ".ks.yml")
        self._persist_rebased_models(root, suffixes, ("case", "suite", "keyword"), rewrite, failures)

    def _rebase_testplan_refs(
        self, old: str, new: str, failures: dict[str, str] | None = None,
    ) -> None:
        """更新工程内测试计划对重命名资源的引用。"""
        failures = {} if failures is None else failures
        root = self.project_dir
        if not root:
            return
        old_root = self._rebased_path(root, old, new)

        def rewrite_path(value: str, *, allow_config: bool = False) -> str:
            if not value:
                return value
            updated, matched = self._rebase_relative_ref(value, old_root, root, old, new)
            native = to_native(value)
            if not matched and allow_config and not os.path.isabs(native):
                candidate = os.path.join("config", native)
                updated, matched = self._rebase_relative_ref(candidate, old_root, root, old, new)
            return updated if matched else value

        def rewrite(plan, _path: str) -> bool:
            members = [rewrite_path(member) for member in plan.members]
            dataconfig = rewrite_path(plan.dataconfig, allow_config=True)
            changed = members != plan.members or dataconfig != plan.dataconfig
            if changed:
                plan.members = members
                plan.dataconfig = dataconfig
            return changed

        self._persist_rebased_models(root, (".tp.yaml", ".tp.yml"), ("testplan",), rewrite, failures)

    def _rebase_map_refs(
        self, old: str, new: str, failures: dict[str, str] | None = None,
    ) -> None:
        """更新用例/测试套/自定义关键字中的 ``map::文件::元素`` 引用。"""
        if os.path.isdir(new):
            return

        def stem(path: str) -> str:
            name = os.path.basename(path)
            map_name_lower = name.lower()
            for suffix in (".map.yaml", ".map.yml", ".map"):
                if map_name_lower.endswith(suffix):
                    return name[: -len(suffix)]
            return ""

        old_stem, new_stem = stem(old), stem(new)
        if not old_stem or not new_stem or old_stem == new_stem:
            return
        marker, replacement = f"map::{old_stem}::", f"map::{new_stem}::"

        def rewrite_nodes(nodes) -> bool:
            changed = False
            for node in nodes or []:
                for param in getattr(node, "params", []) or []:
                    value = str(getattr(param, "value", "") or "")
                    updated = value.replace(marker, replacement)
                    if updated != value:
                        param.value = updated
                        changed = True
                if rewrite_nodes(getattr(node, "children", []) or []):
                    changed = True
            return changed

        def rewrite_model(model) -> bool:
            if hasattr(model, "shells"):
                changed = False
                for shell in model.shells:
                    changed = rewrite_nodes(shell.steps) or changed
            else:
                changed = rewrite_nodes(getattr(model, "steps", []) or [])
            return changed

        suffixes = (".tc.yaml", ".tc.yml", ".ts.yaml", ".ts.yml", ".ks.yaml", ".ks.yml")
        self._persist_rebased_models(
            self.project_dir, suffixes, ("case", "suite", "keyword"),
            lambda model, _path: rewrite_model(model), {} if failures is None else failures,
        )

    def _rebase_file_references(
        self, old: str, new: str, failures: dict[str, str] | None = None,
    ) -> None:
        """更新工程内图片、应用包和数据池等实际文件路径引用。

        这些值既可能是工程相对路径，也可能是用户在文件选择器中留下的
        绝对路径；目录/文件重命名后两种形式都必须同步，否则运行时会在
        编辑器里看起来正常、执行时却找不到文件。
        """
        root = self.project_dir or ""
        if not root:
            return
        old_base, new_base = self._rebased_path(root, old, new), root

        def rewrite_path(raw: str) -> tuple[str, bool]:
            value = str(raw or "")
            if not value.strip() or "${" in value or "COLUMN(" in value:
                return raw, False
            updated, changed = self._rebase_relative_ref(
                value.strip(), old_base, new_base, old, new
            )
            if not changed:
                return raw, False
            left = value[:len(value) - len(value.lstrip())]
            right = value[len(value.rstrip()):]
            return left + updated + right, True

        def rewrite_datapool(spec: str) -> tuple[str, bool]:
            text = str(spec or "")
            match = re.match(r"^(\s*DATATABLE\s*\()(.*)(\)\s*)$", text, re.IGNORECASE | re.DOTALL)
            if match is None:
                return spec, False
            inner = match.group(2)
            source, sep, private = inner.rpartition(",")
            if not sep:
                source = inner
            if source.strip().upper() == "NONE":
                return spec, False
            source_new, changed = rewrite_path(source)
            if not changed:
                return spec, False
            return match.group(1) + source_new + (sep + private if sep else "") + match.group(3), True

        def rewrite_nodes(nodes) -> bool:
            changed = False
            for node in nodes or []:
                if hasattr(node, "datapool"):
                    value, did_change = rewrite_datapool(getattr(node, "datapool", ""))
                    if did_change:
                        node.datapool = value
                        changed = True
                for param in getattr(node, "params", []) or []:
                    pid = str(getattr(param, "param_id", "") or "")
                    value = str(getattr(param, "value", "") or "")
                    if "picture::" in value and value.strip().startswith("picture::"):
                        prefix, _, image = value.partition("picture::")
                        image_new, did_change = rewrite_path(image)
                        if did_change:
                            param.value = prefix + "picture::" + image_new
                            changed = True
                    elif pid in {"appFile", "datapool_source_path"}:
                        value_new, did_change = rewrite_path(value)
                        if did_change:
                            param.value = value_new
                            changed = True
                if rewrite_nodes(getattr(node, "children", []) or []):
                    changed = True
            return changed

        def rewrite_model(model) -> bool:
            if model is None:
                return False
            changed = False
            if hasattr(model, "datapool"):
                value, did_change = rewrite_datapool(getattr(model, "datapool", ""))
                if did_change:
                    model.datapool = value
                    changed = True
            shells = getattr(model, "shells", None)
            if shells is not None:
                for shell in shells:
                    changed = rewrite_nodes(shell.steps) or changed
            else:
                changed = rewrite_nodes(getattr(model, "steps", []) or []) or changed
            return changed

        suffixes = (".tc.yaml", ".tc.yml", ".ts.yaml", ".ts.yml", ".ks.yaml", ".ks.yml")
        self._persist_rebased_models(
            root, suffixes, ("case", "suite", "keyword"),
            lambda model, _path: rewrite_model(model), {} if failures is None else failures,
        )

    # ---- 纯逻辑助手（无对话框，便于测试与复用）----
    @staticmethod
    def create_resource(kind: str, directory: str, name: str) -> str:
        """在 directory 下新建一个资源文件，返回其路径。kind: case/suite/map/dataconfig。"""
        name = validate_portable_name(name)
        os.makedirs(directory, exist_ok=True)

        def allocate(filename: str) -> str:
            candidate_path = os.path.join(directory, filename)
            if os.path.lexists(candidate_path):
                raise FileExistsError(f"目标资源已存在：{os.path.basename(candidate_path)}")
            return candidate_path

        if kind == "case":
            path = allocate(name + ".tc.yaml")
            serializer.save_testcase(TestCase(name=name, source_path=path), path)
        elif kind == "suite":
            path = allocate(name + ".ts.yaml")
            serializer.save_testsuite(TestSuite(name=name, source_path=path), path)
        elif kind == "map":
            path = allocate(name + ".map.yaml")
            serializer.save_mapfile(MapFile(name=name, source_path=path), path)
        elif kind == "dataconfig":
            path = allocate(name + ".properties")
            dataconfig_model.save(dataconfig_model.DataConfig(source_path=path), path)
        elif kind == "testplan":
            path = allocate(name + ".tp.yaml")
            serializer.save_testplan(TestPlan(name=name, source_path=path), path)
        elif kind == "keyword":
            path = allocate(name + ".ks.yaml")
            serializer.save_keyword(KeywordDef(ks_id=name, source_path=path), path)
        else:
            raise ValueError(f"未知资源类型: {kind}")
        return path

    @staticmethod
    def create_folder(directory: str, name: str) -> str:
        name = validate_portable_name(name)
        path = os.path.join(directory, name)
        if os.path.lexists(path):
            raise FileExistsError(f"目标文件夹已存在：{name}")
        os.makedirs(path)
        return path

    @staticmethod
    def rename_path(path: str, new_name: str) -> str:
        if not path or not os.path.lexists(path):
            raise FileNotFoundError(path or "待重命名路径为空")
        # Keep names portable across all three desktop targets.  ``basename``
        # only knows the host separator, so validate both separators here.
        new_name = validate_portable_name(new_name)
        newp = os.path.join(os.path.dirname(path), new_name)
        old_exact = os.path.normpath(os.path.abspath(path))
        new_exact = os.path.normpath(os.path.abspath(newp))
        if old_exact == new_exact:
            return path
        # Windows and common macOS volumes can be case-insensitive. A
        # case-only rename therefore looks like a collision until the source
        # is moved through a temporary sibling.
        same_entry = False
        if os.path.lexists(newp):
            try:
                same_entry = os.path.samefile(path, newp)
            except (OSError, ValueError):
                same_entry = False
            if not same_entry:
                raise FileExistsError(f"目标名称已存在：{new_name}")
        if same_entry:
            parent = os.path.dirname(path)
            tmp = os.path.join(
                parent,
                f".{os.path.basename(path)}.autopilot-rename-{uuid.uuid4().hex}",
            )
            os.rename(path, tmp)
            # noinspection PyBroadException
            try:
                os.rename(tmp, newp)
            except Exception:
                try:
                    os.rename(tmp, path)
                except OSError:
                    pass
                raise
            return newp
        os.rename(path, newp)
        return newp

    @staticmethod
    def delete_path(path: str) -> None:
        if os.path.islink(path):
            os.unlink(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
