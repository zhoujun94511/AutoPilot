"""HTTP / API 环境 profile 选择器（http 工程时显示）。"""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QComboBox


class HttpEnvSelector(QWidget):
    profileChanged = pyqtSignal(str)

    def __init__(self, initial_profile: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("status_bar_field")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self._label = QLabel("API 环境")
        lay.addWidget(self._label)
        self.combo = QComboBox()
        self.combo.setObjectName("http_env_combo")
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._reload_items([str(initial_profile or "").strip()] if initial_profile else [])
        self.combo.setToolTip(
            "批跑注入的 api_env.yaml profile。留空则由用例步骤「切换API环境」决定。"
        )
        lay.addWidget(self.combo)
        # noinspection PyUnresolvedReferences
        self.combo.currentTextChanged.connect(
            # noinspection PyUnresolvedReferences
            lambda text: self.profileChanged.emit(str(text or "").strip())
        )

    def _reload_items(self, extra: list[str] | None = None) -> None:
        current = str(self.combo.currentText() or "").strip() if self.combo.count() else ""
        names: list[str] = []
        seen: set[str] = set()
        for name in ["", *(extra or [])]:
            key = str(name or "").strip()
            if key in seen:
                continue
            seen.add(key)
            names.append(key)
        self.combo.blockSignals(True)
        self.combo.clear()
        for name in names:
            self.combo.addItem("用例内切换" if not name else name, name)
        pick = current or (extra[0] if extra else "")
        idx = self.combo.findData(pick)
        if idx < 0 and pick:
            self.combo.addItem(pick, pick)
            idx = self.combo.findData(pick)
        self.combo.setCurrentIndex(max(0, idx))
        self.combo.blockSignals(False)

    def set_project_dir(self, project_dir: str) -> None:
        from autopilot.keywords.http.env import list_api_env_profiles

        profiles = list_api_env_profiles(project_dir or "")
        current = str(self.combo.currentText() or "").strip()
        if current.lower() == "用例内切换":
            current = ""
        extra = list(profiles)
        if current and current not in extra:
            extra.insert(0, current)
        self._reload_items(extra)

    def set_visible_for_platform(self, platform: str) -> None:
        visible = (platform or "").strip().lower() == "http"
        self._label.setVisible(visible)
        self.combo.setVisible(visible)

    def current_profile(self) -> str:
        raw = str(self.combo.currentData() or self.combo.currentText() or "").strip()
        if raw.lower() in ("用例内切换", "auto"):
            return ""
        return raw
