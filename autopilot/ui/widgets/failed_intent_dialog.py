"""失败意图人审对话框：展示失败步，并可手写定位符固化 Binding。"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...intent.manual_bind import apply_manual_binding, default_keyword_id
from ...intent.review import collect_failed_intents


class _BindEditDialog(QDialog):
    def __init__(self, row: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("写入 Binding")
        self._row = row
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.ed_locator = QLineEdit()
        prev = ""
        # 取候选首条 locator 作默认
        summary = str(row.get("candidates_summary") or "")
        if summary:
            prev = summary.split(";")[0].split("(")[0].strip()
        if row.get("keyword_id") and not prev:
            prev = ""
        self.ed_locator.setText(prev)
        self.ed_locator.setPlaceholderText("例如 xpath:://*[@text='登录'] 或 id=xxx")
        form.addRow("定位符", self.ed_locator)

        self.cmb_platform = QComboBox()
        self.cmb_platform.addItems(["web", "android", "ios"])
        plat0 = str(row.get("platform") or "").strip().lower()
        if plat0 in ("web", "android", "ios"):
            self.cmb_platform.setCurrentText(plat0)
        form.addRow("平台", self.cmb_platform)

        self.cmb_action = QComboBox()
        self.cmb_action.addItems(["click", "type", "assert", "open", "swipe", "wait", "custom"])
        act0 = str(row.get("action") or "").strip().lower()
        if act0 in ("click", "type", "assert", "open", "swipe", "wait", "custom"):
            self.cmb_action.setCurrentText(act0)
        form.addRow("动作", self.cmb_action)

        self.ed_keyword = QLineEdit()
        prev_kw = str(row.get("keyword_id") or "").strip()
        if prev_kw:
            self.ed_keyword.setText(prev_kw)
        self.ed_keyword.setPlaceholderText("留空则按平台+动作推断")
        form.addRow("关键字", self.ed_keyword)

        self.ed_value = QLineEdit()
        prev_val = str(row.get("value") or "").strip()
        if prev_val:
            self.ed_value.setText(prev_val)
        self.ed_value.setPlaceholderText("type 时的输入值（可选）")
        form.addRow("value", self.ed_value)
        lay.addLayout(form)

        buttons = QDialogButtonBox(self)
        buttons.addButton("确定", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        # noinspection PyUnresolvedReferences
        buttons.accepted.connect(self.accept)
        # noinspection PyUnresolvedReferences
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def payload(self) -> dict:
        plat = self.cmb_platform.currentText()
        action = self.cmb_action.currentText()
        kid = self.ed_keyword.text().strip() or default_keyword_id(plat, action)
        return {
            "locator": self.ed_locator.text().strip(),
            "platform": plat,
            "action": action,
            "keyword_id": kid,
            "value": self.ed_value.text().strip(),
        }


class FailedIntentReviewDialog(QDialog):
    def __init__(self, project_dir: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("失败意图（人审）")
        self.resize(900, 460)
        self._project_dir = project_dir
        self._rows: list[dict] = []

        lay = QVBoxLayout(self)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["用例", "intent_id", "步骤", "binding", "归因", "heal", "候选", "错误"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        # noinspection PyUnresolvedReferences
        self.table.doubleClicked.connect(lambda *_: self._edit_selected())
        lay.addWidget(self.table)

        row = QHBoxLayout()
        self.btn_reload = QPushButton("刷新")
        # noinspection PyUnresolvedReferences
        self.btn_reload.clicked.connect(self.reload)
        self.btn_bind = QPushButton("写入定位符…")
        # noinspection PyUnresolvedReferences
        self.btn_bind.clicked.connect(self._edit_selected)
        self.btn_pick_cand = QPushButton("采用首个候选")
        # noinspection PyUnresolvedReferences
        self.btn_pick_cand.clicked.connect(self._apply_first_candidate)
        row.addWidget(self.btn_reload)
        row.addWidget(self.btn_bind)
        row.addWidget(self.btn_pick_cand)
        row.addStretch(1)
        lay.addLayout(row)

        buttons = QDialogButtonBox(self)
        close_btn = buttons.addButton("关闭", QDialogButtonBox.ButtonRole.AcceptRole)
        # noinspection PyUnresolvedReferences
        buttons.accepted.connect(self.accept)
        # noinspection PyUnresolvedReferences
        buttons.rejected.connect(self.reject)
        if close_btn is not None:
            # noinspection PyUnresolvedReferences
            close_btn.clicked.connect(self.accept)
        lay.addWidget(buttons)

        self.reload()

    def _selected_row(self) -> dict | None:
        idxs = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not idxs:
            r = self.table.currentRow()
            if r < 0:
                return None
            item = self.table.item(r, 0)
        else:
            item = self.table.item(idxs[0].row(), 0)
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        return data if isinstance(data, dict) else None

    def _edit_selected(self) -> None:
        row = self._selected_row()
        if not row:
            QMessageBox.information(self, "人审", "请先选择一条失败意图。")
            return
        lid = str(row.get("logical_case_id") or "").strip()
        iid = str(row.get("intent_id") or "").strip()
        if not lid or not iid:
            QMessageBox.warning(
                self,
                "人审",
                "该行缺少 logical_case_id / intent_id，无法写 Binding。",
            )
            return
        dlg = _BindEditDialog(row, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        payload = dlg.payload()
        if not payload["locator"]:
            QMessageBox.warning(self, "人审", "定位符不能为空。")
            return
        try:
            apply_manual_binding(
                self._project_dir,
                lid,
                iid,
                locator=payload["locator"],
                keyword_id=payload["keyword_id"],
                platform=payload["platform"],
                action=payload["action"],
                value=payload["value"],
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "写入失败", str(exc))
            return
        QMessageBox.information(
            self,
            "已写入",
            f"已固化 Binding：{lid}/{iid}\n重新运行该用例即可验证。",
        )
        self.reload()

    def _apply_first_candidate(self) -> None:
        row = self._selected_row()
        if not row:
            QMessageBox.information(self, "人审", "请先选择一条失败意图。")
            return
        summary = str(row.get("candidates_summary") or "").strip()
        if not summary:
            # 允许手填
            text, ok = QInputDialog.getText(self, "采用候选", "无缓存候选，请输入定位符：")
            if not ok or not text.strip():
                return
            locator = text.strip()
        else:
            locator = summary.split(";")[0].split("(")[0].strip()
        lid = str(row.get("logical_case_id") or "").strip()
        iid = str(row.get("intent_id") or "").strip()
        if not lid or not iid:
            QMessageBox.warning(self, "人审", "缺少 logical_case_id / intent_id。")
            return
        plat = str(row.get("platform") or "").strip().lower() or "web"
        if plat not in ("web", "android", "ios"):
            plat = "web"
        action = str(row.get("action") or "").strip().lower() or "click"
        kid = str(row.get("keyword_id") or "").strip() or default_keyword_id(plat, action)
        try:
            apply_manual_binding(
                self._project_dir,
                lid,
                iid,
                locator=locator,
                keyword_id=kid,
                platform=plat,
                action=action,
                value=str(row.get("value") or ""),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "写入失败", str(exc))
            return
        QMessageBox.information(self, "已写入", f"已采用候选写入 {lid}/{iid}")
        self.reload()

    def reload(self) -> None:
        path, rows = collect_failed_intents(self._project_dir)
        self._rows = rows
        if path is None:
            self.hint.setText(
                "未找到最近一次运行结果。\n"
                "请先本地运行含意图步骤的用例，再回来审阅失败项。\n"
                "可选：双击行或点「写入定位符」固化绑定。"
            )
        else:
            self.hint.setText(
                f"来源：{path}\n"
                f"共 {len(rows)} 条失败意图。"
                " 双击或「写入定位符」可人工固化绑定；自动恢复失败的步骤请在此处理。"
            )
        self.table.setRowCount(0)
        for item in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            vals = [
                str(item.get("case_name") or item.get("logical_case_id") or ""),
                str(item.get("intent_id") or ""),
                str(item.get("name") or ""),
                str(item.get("binding_hit") or ""),
                str(
                    item.get("fail_reason_label")
                    or item.get("fail_reason")
                    or ""
                ),
                str(item.get("heal_count", "")),
                str(item.get("candidates_summary") or ""),
                str(item.get("error_message") or ""),
            ]
            for c, text in enumerate(vals):
                cell = QTableWidgetItem(text)
                cell.setData(Qt.ItemDataRole.UserRole, item)
                self.table.setItem(r, c, cell)


def show_failed_intent_review(project_dir: str | Path, parent: QWidget | None = None) -> None:
    dlg = FailedIntentReviewDialog(str(project_dir), parent)
    dlg.exec()
