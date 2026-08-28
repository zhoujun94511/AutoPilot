"""参数编辑表单组件：按 config XML 元数据为选中步骤动态生成参数表单。

数据来源：
  - 步骤模型 Step（携带当前 param 值）
  - 关键字元数据 KeywordMeta（ParamMeta：名称/必填/默认/下拉values/说明）
渲染规则：
  - 有下拉候选 → QComboBox（可编辑，允许变量引用）
  - 否则 → QLineEdit
  - 必填项标 *，说明作为 tooltip
编辑即写回 Step.params；发 stepChanged(step) 通知外部刷新展示。
找不到元数据（如内置关键字）时，退化为按现有 param 直接编辑。
"""

from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QComboBox,
    QLabel,
    QScrollArea,
    QToolButton,
    QMenu,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QPlainTextEdit,
)

from ...model.testcase import Step, StepVerbs, StepSet, StepInnerCase, ParamValue
from ...metadata import KeywordMeta
from ...model.keyworddef import KeywordDef
from .step_param_rules import (
    param_visible as _param_row_visible,
    strip_hidden_params,
)
from .param_file_rules import (
    file_param_spec,
    innercase_path_spec,
    resolve_dialog_filter,
    validate_literal_path,
    kind_label,
)
from .param_multiline_rules import is_multiline_param


class ParamForm(QScrollArea):
    stepChanged = pyqtSignal(object)
    caseMetaChanged = pyqtSignal(object)  # TestCase 追踪字段变更

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("param_form")
        self.setWidgetResizable(True)
        self._step: Optional[Step] = None
        self._node: Optional[object] = None   # Step / StepVerbs / StepSet / StepInnerCase
        self._keyword_def: Optional[KeywordDef] = None
        self._case_platform: str = ""
        self._testcase: Optional[object] = None  # TestCase，用例级元数据
        self._columns: list[str] = []     # 当前步骤受约束数据池的列名（COLUMN 选择器用）
        self._inner = QWidget()
        self._inner.setObjectName("param_form_body")
        self._layout = QFormLayout(self._inner)
        self.setWidget(self._inner)
        self._first_editor = None     # 首个参数输入框，供 focus_first 聚焦
        self._param_rows: dict[str, QWidget] = {}
        self._meta: Optional[KeywordMeta] = None
        self._project_dir: str = ""
        self._placeholder()

        from ..theme import init_panel_style

        self._ui_theme = init_panel_style(self, "param_form")

    def focus_first(self) -> None:
        """聚焦第一个参数输入框（双击表格「参数」列跳转到此编辑）。"""
        if self._first_editor is not None:
            self._first_editor.setFocus()
            sel = getattr(self._first_editor, "selectAll", None)
            if callable(sel):
                sel()

    def set_project_dir(self, project_dir: str) -> None:
        """工程根目录：图像定位「选择图片」默认打开 images/，并写相对 picture:: 路径。"""
        self._project_dir = (project_dir or "").strip()

    # ---- 公开 ----
    def show_step(self, step: Step, meta: Optional[KeywordMeta],
                  columns: Optional[list[str]] = None,
                  case_platform: str = "") -> None:
        """展示某步骤的参数表单。meta 为 None 时退化为按现有 param 编辑。
        columns 为该步骤受约束数据池的列名——非空时每个参数给「插列」下拉，选列写入 COLUMN(列,)。"""
        self._node = step
        self._step = step
        self._testcase = None
        self._keyword_def = None
        self._meta = meta
        self._columns = list(columns or [])
        self._case_platform = (case_platform or "").strip().lower()
        self._rebuild_form()

    def show_stepverbs(self, node: StepVerbs, kd: Optional[KeywordDef] = None,
                       columns: Optional[list[str]] = None,
                       case_platform: str = "") -> None:
        """展示自定义关键字调用(StepVerbs)的实参表单。"""
        self._node = node
        self._step = None
        self._testcase = None
        self._keyword_def = kd
        self._meta = None
        self._columns = list(columns or [])
        self._case_platform = (case_platform or "").strip().lower()
        self._rebuild_form_stepverbs()

    def show_stepset(self, node: StepSet) -> None:
        """展示步骤组属性：名称、数据池、说明、备注。"""
        self._node = node
        self._step = None
        self._testcase = None
        self._keyword_def = None
        self._meta = None
        self._columns = []
        self._case_platform = ""
        self._rebuild_form_stepset()

    def show_innercase(self, node: StepInnerCase) -> None:
        """展示内嵌用例引用属性。"""
        self._node = node
        self._step = None
        self._testcase = None
        self._keyword_def = None
        self._meta = None
        self._columns = []
        self._case_platform = ""
        self._rebuild_form_innercase()

    def show_case_meta(self, tc: object) -> None:
        """展示用例级 schema 2.0 追踪字段（无步骤选中或打开用例时）。"""
        self._node = None
        self._step = None
        self._keyword_def = None
        self._meta = None
        self._columns = []
        self._case_platform = ""
        self._testcase = tc
        self._rebuild_form_case_meta()

    def clear_step(self) -> None:
        self._step = None
        self._node = None
        self._keyword_def = None
        self._meta = None
        self._case_platform = ""
        self._testcase = None
        self._clear()
        self._placeholder()

    def _rebuild_form(self) -> None:
        """按当前步骤与元数据重建参数表单（含条件显隐）。"""
        step = self._step
        meta = self._meta
        if step is None:
            return
        self._clear()

        title = step.keyword_id
        if meta is not None and meta.name:
            title = f"{meta.name} ({step.keyword_id})"
        header = QLabel(f"<b>{title}</b>")
        header.setWordWrap(True)
        self._layout.addRow(header)

        if meta is not None and meta.params:
            if any(pm.required for pm in meta.params):
                note = QLabel("带 * 为必填项")
                note.setObjectName("param_form_note")
                self._layout.addRow(note)
            for pm in meta.params:
                self._add_param_row(
                    param_id=pm.param_id,
                    label=pm.name or pm.param_id,
                    required=pm.required,
                    default=pm.default,
                    values=pm.values,
                    comment=pm.comment,
                    keyword_id=step.keyword_id,
                    is_output=pm.is_output,
                )
            self._sync_default_params(meta.params)
            strip_hidden_params(step, self._case_platform)
            self._update_param_visibility()
        else:
            # 退化：按步骤现有参数逐个给 QLineEdit
            for p in step.params:
                self._add_param_row(p.param_id, p.param_id, False, "", [], "")
            if not step.params:
                self._layout.addRow(QLabel("（该关键字无参数元数据）"))

    def _rebuild_form_stepverbs(self) -> None:
        node = self._node
        if not isinstance(node, StepVerbs):
            return
        self._clear()
        kd = self._keyword_def
        title = f"自定义关键字调用：{node.ks_id}"
        if kd is not None and kd.ks_id and kd.ks_id != node.ks_id:
            title += f"（定义 id：{kd.ks_id}）"
        header = QLabel(f"<b>{title}</b>")
        header.setWordWrap(True)
        self._layout.addRow(header)
        if kd is not None and kd.params:
            for pm in kd.params:
                if node.param(pm.param_id) is None and pm.default:
                    node.params.append(ParamValue(pm.param_id, pm.default))
                self._add_param_row(
                    param_id=pm.param_id,
                    label=pm.name or pm.param_id,
                    required=pm.required,
                    default=pm.default,
                    values=pm.values,
                    comment=pm.comment,
                    keyword_id=node.ks_id,
                )
        else:
            for p in node.params:
                self._add_param_row(p.param_id, p.param_id, False, "", [], "")
            if not node.params:
                hint = "（未找到 .ks 定义，可直接编辑下方参数行）" if kd is None else "（该自定义关键字未声明形参）"
                self._layout.addRow(QLabel(hint))

    def _rebuild_form_stepset(self) -> None:
        node = self._node
        if not isinstance(node, StepSet):
            return
        self._clear()
        header = QLabel(f"<b>步骤组：{node.name or '（未命名）'}</b>")
        header.setWordWrap(True)
        self._layout.addRow(header)
        self._layout.addRow(QLabel(f"子步骤数：{len(node.children)}"))
        for label, attr, tip in (
            ("组名", "name", "步骤组显示名称"),
            ("数据池", "datapool", "如 DATATABLE(表名,false)；留空则继承上级"),
            ("说明", "comment", "步骤组用途说明"),
            ("备注", "remark", "维护备注"),
        ):
            editor = QLineEdit(getattr(node, attr, "") or "")
            editor.setToolTip(tip)
            # noinspection PyUnresolvedReferences
            editor.textChanged.connect(
                lambda text, a=attr, n=node: self._write_stepset_field(n, a, text)
            )
            if self._first_editor is None:
                self._first_editor = editor
            self._layout.addRow(label, editor)

    def _rebuild_form_innercase(self) -> None:
        node = self._node
        if not isinstance(node, StepInnerCase):
            return
        self._clear()
        header = QLabel("<b>内嵌用例引用</b>")
        self._layout.addRow(header)
        for label, attr, tip in (
            ("相对路径", "relative_path", "相对当前用例文件的路径，如 cases/login.tc.yaml"),
            ("说明", "comment", ""),
            ("备注", "remark", ""),
        ):
            editor = QLineEdit(getattr(node, attr, "") or "")
            if tip:
                editor.setToolTip(tip)
            # noinspection PyUnresolvedReferences
            editor.textChanged.connect(
                lambda text, a=attr, n=node: self._write_innercase_field(n, a, text)
            )
            if attr == "relative_path":
                spec = innercase_path_spec()
                # noinspection PyUnresolvedReferences
                editor.editingFinished.connect(
                    lambda e=editor: self._warn_if_invalid_path(e, spec)
                )
            if self._first_editor is None:
                self._first_editor = editor
            if attr == "relative_path":
                row_w = QWidget()
                row = QHBoxLayout(row_w)
                row.setContentsMargins(0, 0, 0, 0)
                row.setSpacing(8)
                row.addWidget(QLabel(label))
                row.addWidget(editor, 1)
                browse = QPushButton("浏览…")
                browse.setToolTip(f"从本机选择用例文件（{kind_label(spec)}）")
                # noinspection PyUnresolvedReferences
                browse.clicked.connect(
                    lambda _=False, e=editor, sp=spec: self._browse_file_into(e, sp)
                )
                row.addWidget(browse)
                self._layout.addRow(row_w)
            else:
                self._layout.addRow(label, editor)

    def _write_stepset_field(self, node: StepSet, attr: str, value: str) -> None:
        if getattr(node, attr, None) == value:
            return
        setattr(node, attr, value)
        # noinspection PyUnresolvedReferences
        self.stepChanged.emit(node)

    def _write_innercase_field(self, node: StepInnerCase, attr: str, value: str) -> None:
        if getattr(node, attr, None) == value:
            return
        setattr(node, attr, value)
        # noinspection PyUnresolvedReferences
        self.stepChanged.emit(node)

    def _sync_default_params(self, params_meta) -> None:
        """元数据默认值写入步骤模型，不触发条件显隐中间态。"""
        assert self._step is not None
        for pm in params_meta:
            if self._step.param(pm.param_id) is not None:
                continue
            default = pm.default
            if not default:
                continue
            self._step.params.append(ParamValue(param_id=pm.param_id, value=default))

    # ---- 内部 ----
    def _rebuild_form_case_meta(self) -> None:
        tc = self._testcase
        if tc is None:
            return
        self._clear()
        header = QLabel("<b>用例追踪（schema 2.0）</b>")
        header.setWordWrap(True)
        self._layout.addRow(header)
        note = QLabel("与 Platform 逻辑用例对齐；空表示纯本地用例。保存用例时一并写入。")
        note.setObjectName("param_form_note")
        note.setWordWrap(True)
        self._layout.addRow(note)

        fields = (
            ("schema_version", "Schema"),
            ("project_id", "项目 ID"),
            ("logical_case_id", "逻辑用例 ID"),
            ("automation_case_id", "自动化用例 ID"),
            ("revision_id", "修订 ID"),
            ("case_key", "用例 Key"),
        )

        def _bind(field: str, line: QLineEdit) -> None:
            def _on_edit(_text: str = "") -> None:
                setattr(tc, field, line.text().strip())
                # noinspection PyUnresolvedReferences
                self.caseMetaChanged.emit(tc)

            # noinspection PyUnresolvedReferences
            line.editingFinished.connect(_on_edit)

        for attr, label in fields:
            edit = QLineEdit(str(getattr(tc, attr, "") or ""))
            edit.setPlaceholderText("可选")
            _bind(attr, edit)
            self._layout.addRow(label, edit)

        # 前置条件（Desc）
        pre = QPlainTextEdit()
        pre.setPlainText(str(getattr(getattr(tc, "desc", None), "precondition", "") or ""))
        pre.setPlaceholderText("前置条件（可选）")
        pre.setMaximumHeight(80)

        def _on_pre() -> None:
            desc = getattr(tc, "desc", None)
            if desc is not None:
                desc.precondition = pre.toPlainText().strip()
                # noinspection PyUnresolvedReferences
                self.caseMetaChanged.emit(tc)

        # noinspection PyUnresolvedReferences
        pre.textChanged.connect(_on_pre)
        self._layout.addRow("前置条件", pre)

    def _placeholder(self) -> None:
        self._layout.addRow(QLabel("选中一个步骤以编辑参数；或打开用例查看追踪字段"))

    def _clear(self) -> None:
        self._first_editor = None
        self._param_rows.clear()
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _current_value(self, param_id: str, default: str) -> str:
        target = self._params_target()
        if target is None:
            return default
        existing = target.param(param_id) if hasattr(target, "param") else None
        if existing is not None:
            return existing
        for p in getattr(target, "params", []):
            if p.param_id == param_id:
                return p.value
        return default

    def _params_target(self) -> Step | StepVerbs | None:
        if isinstance(self._step, Step):
            return self._step
        if isinstance(self._node, StepVerbs):
            return self._node
        return None

    def _add_param_row(
        self,
        param_id: str,
        label: str,
        required: bool,
        default: str,
        values: list[str],
        comment: str,
        keyword_id: str = "",
        is_output: bool = False,
    ) -> None:
        cur = self._current_value(param_id, default)
        file_spec = file_param_spec(keyword_id, param_id) if keyword_id else None
        multiline = (
            not values
            and is_multiline_param(param_id, is_output=is_output, label=label)
        )
        if values:
            editor = QComboBox()
            editor.setEditable(True)
            editor.addItems(values)
            editor.blockSignals(True)
            editor.setCurrentText(cur)
            editor.blockSignals(False)
            # noinspection PyUnresolvedReferences
            editor.currentTextChanged.connect(
                lambda text, pid=param_id: self._write_back(pid, text)
            )
            # noinspection PyUnresolvedReferences
            editor.activated.connect(
                lambda _idx, pid=param_id, e=editor: self._write_back(pid, e.currentText())
            )
        elif multiline:
            editor = QPlainTextEdit()
            editor.setObjectName("param_form_multiline")
            editor.setPlainText(cur)
            editor.setMinimumHeight(120)
            editor.setTabChangesFocus(True)
            # noinspection PyUnresolvedReferences
            editor.textChanged.connect(
                lambda pid=param_id, e=editor: self._write_back(pid, e.toPlainText())
            )
        else:
            editor = QLineEdit(cur)
            # noinspection PyUnresolvedReferences
            editor.textChanged.connect(
                lambda text, pid=param_id: self._write_back(pid, text)
            )
            if file_spec is not None:
                type_hint = kind_label(file_spec, self._step, self._case_platform)
                file_tip = f"支持手填路径或「浏览…」选择；允许类型：{type_hint}"
                if comment:
                    editor.setToolTip(f"{comment}\n\n{file_tip}")
                else:
                    editor.setToolTip(file_tip)
                # noinspection PyUnresolvedReferences
                editor.editingFinished.connect(
                    lambda e=editor, sp=file_spec: self._warn_if_invalid_path(e, sp)
                )
        if comment and (file_spec is None or values or multiline):
            editor.setToolTip(comment)
        if self._first_editor is None:
            self._first_editor = editor
        label_text = f"{label} *" if required else label
        label_widget = QLabel(label_text)
        row_w = QWidget()
        row = QHBoxLayout(row_w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(label_widget, 0)
        field = QWidget()
        inner = QHBoxLayout(field)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(4)
        inner.addWidget(editor, 1)
        if self._columns:
            btn = QToolButton()
            btn.setText("列▾")
            btn.setToolTip("插入数据列引用 COLUMN(列,默认)")
            btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu = QMenu(btn)
            for col in self._columns:
                menu.addAction(col, lambda _=False, c=col, e=editor: self._insert_column(e, c))
            btn.setMenu(menu)
            inner.addWidget(btn)
        if file_spec is not None and not values and not multiline:
            browse = QPushButton("浏览…")
            browse.setToolTip(resolve_dialog_filter(file_spec, self._step, self._case_platform))
            # noinspection PyUnresolvedReferences
            browse.clicked.connect(
                lambda _=False, e=editor, sp=file_spec, pid=param_id: self._browse_param_file(
                    e, sp, pid
                )
            )
            inner.addWidget(browse)
        # picture:: 白名单关键字：locator 旁提供「选择图片」入口
        from ...keywords.mobile.picture_locator import supports_picture_locator
        if (
            param_id == "locator"
            and keyword_id
            and supports_picture_locator(keyword_id)
            and not values
            and not multiline
        ):
            pic_btn = QPushButton("选择图片…")
            pic_btn.setToolTip(
                "选择 PNG 模板图，写入 picture:: 相对工程路径（供图像点击/存在校验）")
            # noinspection PyUnresolvedReferences
            pic_btn.clicked.connect(
                lambda _=False, e=editor: self._browse_picture_locator(e)
            )
            inner.addWidget(pic_btn)
            tip = editor.toolTip() or comment or ""
            extra = "本关键字支持 picture:: 图像定位；可用「选择图片…」或检视器「框选图片定位」。"
            editor.setToolTip(f"{tip}\n\n{extra}".strip() if tip else extra)
        row.addWidget(field, 1)
        self._layout.addRow(row_w)
        self._param_rows[param_id] = row_w

    @staticmethod
    def _insert_column(editor, col: str) -> None:
        """把编辑器内容设为 COLUMN(列,默认)——默认值留空待用户补。触发 textChanged 写回。"""
        text = f"COLUMN({col},)"
        if isinstance(editor, QComboBox):
            editor.setCurrentText(text)
        elif isinstance(editor, QPlainTextEdit):
            editor.setPlainText(text)
        else:
            editor.setText(text)

    def _warn_if_invalid_path(self, editor: QLineEdit, spec) -> None:
        err = validate_literal_path(
            editor.text(), spec, self._step, self._case_platform
        )
        if err:
            QMessageBox.warning(self, "文件类型", err)

    def _browse_file_into(self, editor: QLineEdit, spec, *, start_dir: str = "") -> None:
        from ...runtime.paths import project_relative_or_abs

        filt = resolve_dialog_filter(spec, self._step, self._case_platform)
        proj = self._project_dir
        if not start_dir and proj and os.path.isdir(proj):
            for sub in ("apps", "app", "packages", "apk", "ipa"):
                cand = os.path.join(proj, sub)
                if os.path.isdir(cand):
                    start_dir = cand
                    break
            else:
                start_dir = proj
        initial = start_dir or editor.text().strip() or os.path.expanduser("~")
        if spec.save_dialog:
            path, _ = QFileDialog.getSaveFileName(self, spec.dialog_title, initial, filt)
        else:
            path, _ = QFileDialog.getOpenFileName(self, spec.dialog_title, initial, filt)
        if not path:
            return
        err = validate_literal_path(path, spec, self._step, self._case_platform)
        if err:
            QMessageBox.warning(self, "文件类型", err)
            return
        # 安装包：工程内写入相对路径，保证工程制品远程批跑可解析
        kind = getattr(spec, "kind", "") or ""
        if kind.startswith("mobile_app") and proj and os.path.isdir(proj):
            stored = project_relative_or_abs(proj, path)
            if stored == path and os.path.isabs(path):
                QMessageBox.warning(
                    self,
                    "安装包不在工程内",
                    "所选 apk/ipa 不在当前工程目录内。\n\n"
                    "本地调试仍可使用绝对路径；上传管理台后远程 Runner "
                    "通常无法找到该文件。\n"
                    "请将安装包放到工程目录（例如 apps/）后重新选择。",
                )
            path = stored
        editor.setText(path)

    def _browse_param_file(self, editor: QLineEdit, spec, param_id: str) -> None:
        self._browse_file_into(editor, spec)
        if param_id in ("type", "platform"):
            return
        # 浏览后刷新 appFile 等依赖平台的 tooltip（终端类型刚改过时）
        if isinstance(self._step, Step) and param_id == "appFile":
            type_hint = kind_label(spec, self._step, self._case_platform)
            base = editor.toolTip().split("\n\n")[0] if editor.toolTip() else ""
            editor.setToolTip(f"{base}\n\n支持手填路径或「浏览…」选择；允许类型：{type_hint}".strip())

    def _browse_picture_locator(self, editor) -> None:
        """白名单关键字：选 PNG → 写入 picture:: 工程相对路径。"""
        from ...keywords.mobile.picture_locator import picture_locator_for_path

        proj = self._project_dir
        img_dir = os.path.join(proj, "images") if proj and os.path.isdir(proj) else ""
        if img_dir:
            # noinspection PyBroadException
            try:
                os.makedirs(img_dir, exist_ok=True)
            except OSError:
                pass
        initial = img_dir or (proj if proj and os.path.isdir(proj) else os.path.expanduser("~"))
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图像定位模板", initial, "PNG 图片 (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            QMessageBox.warning(self, "文件类型", "图像定位仅支持 PNG 图片。")
            return
        if not (proj and os.path.isdir(proj)):
            QMessageBox.warning(self, "工程", "请先打开工程，再选择图片定位模板。")
            return
        locator = picture_locator_for_path(proj, path)
        if isinstance(editor, QComboBox):
            editor.setCurrentText(locator)
        else:
            editor.setText(locator)

    def _write_back(self, param_id: str, value: str) -> None:
        target = self._params_target()
        if target is None:
            return
        for p in target.params:
            if p.param_id == param_id:
                p.value = value
                break
        else:
            target.params.append(ParamValue(param_id=param_id, value=value))
        if isinstance(self._step, Step) and param_id in ("type", "platform") and self._step.keyword_id in (
            "mobile_app_install_and_open", "mobile_app_start", "mobile_app_adb_uninstall"
        ):
            strip_hidden_params(self._step, self._case_platform)
            self._update_param_visibility()
            self._inner.updateGeometry()
            self._refresh_file_param_hints()
        # noinspection PyUnresolvedReferences
        self.stepChanged.emit(self._node or self._step)

    def _update_param_visibility(self) -> None:
        if self._step is None:
            return
        kid = self._step.keyword_id
        for param_id, row_w in self._param_rows.items():
            row_w.setVisible(_param_row_visible(kid, param_id, self._step, self._case_platform))

    def _refresh_file_param_hints(self) -> None:
        """终端类型变化后，刷新 appFile 等文件参数的浏览过滤器提示。"""
        if self._step is None:
            return
        kid = self._step.keyword_id
        for param_id, row_w in self._param_rows.items():
            spec = file_param_spec(kid, param_id)
            if spec is None:
                continue
            for btn in row_w.findChildren(QPushButton):
                if btn.text() == "浏览…":
                    btn.setToolTip(resolve_dialog_filter(spec, self._step, self._case_platform))
            for ed in row_w.findChildren(QLineEdit):
                type_hint = kind_label(spec, self._step, self._case_platform)
                base = (ed.toolTip() or "").split("\n\n")[0]
                ed.setToolTip(
                    f"{base}\n\n支持手填路径或「浏览…」选择；允许类型：{type_hint}".strip()
                )

    def apply_theme(self, theme: str) -> None:
        from ..theme import apply_panel_theme

        self._ui_theme = apply_panel_theme(self, "param_form", theme)
