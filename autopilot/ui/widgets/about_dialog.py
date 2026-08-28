"""「关于」对话框：参照成熟桌面应用（JetBrains/VS Code 风格）。

左侧产品图标，右侧：名称+版本 → 一句定位 → 分隔线 → 键值对齐的事实区
（平台/关键字库/运行环境）→ 版权；底部「复制信息 / 确定」。
「复制信息」把版本+运行环境拷成纯文本，便于反馈问题时贴出。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame,
    QPushButton, QApplication,
)

from ..theme import apply_dialog_theme


class AboutDialog(QDialog):
    def __init__(self, *, app_name: str, version: str, tagline: str,
                 facts: list[tuple[str, str]], copyright_text: str,
                 icon: QIcon, parent=None, theme: str | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("about_dialog")
        self.setWindowTitle(f"关于 {app_name}")
        self.setMinimumWidth(420)
        self._plain = self._build_plain(app_name, version, facts, copyright_text)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 14)
        outer.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(16)
        logo = QLabel()
        logo.setPixmap(icon.pixmap(72, 72))
        logo.setFixedSize(72, 72)
        top.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(6)
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        name_lbl = QLabel(app_name)
        name_lbl.setObjectName("about_app_name")
        ver_lbl = QLabel(f"v{version}")
        ver_lbl.setObjectName("about_version")
        title_row.addWidget(name_lbl)
        title_row.addWidget(ver_lbl)
        title_row.addStretch(1)
        col.addLayout(title_row)
        sub = QLabel(tagline)
        sub.setObjectName("about_tagline")
        col.addWidget(sub)

        line = QFrame()
        line.setObjectName("about_separator")
        line.setFrameShape(QFrame.Shape.HLine)
        col.addWidget(line)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(5)
        grid.setColumnStretch(1, 1)
        for r, (k, v) in enumerate(facts):
            kl = QLabel(k)
            kl.setObjectName("about_fact_key")
            kl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            vl = QLabel(v)
            vl.setObjectName("about_fact_value")
            vl.setWordWrap(True)
            vl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(kl, r, 0)
            grid.addWidget(vl, r, 1)
        col.addLayout(grid)

        cp = QLabel(copyright_text)
        cp.setObjectName("about_copyright")
        col.addWidget(cp)
        top.addLayout(col, 1)
        outer.addLayout(top)

        bar = QHBoxLayout()
        bar.addStretch(1)
        btn_copy = QPushButton("复制信息")
        # noinspection PyUnresolvedReferences
        btn_copy.clicked.connect(self._copy)
        btn_ok = QPushButton("确定")
        btn_ok.setDefault(True)
        # noinspection PyUnresolvedReferences
        btn_ok.clicked.connect(self.accept)
        bar.addWidget(btn_copy)
        bar.addWidget(btn_ok)
        outer.addLayout(bar)

        self.apply_theme(theme)

    def apply_theme(self, theme: str | None = None) -> None:
        apply_dialog_theme(self, "about_dialog", theme)

    @staticmethod
    def _build_plain(app_name: str, version: str,
                     facts: list[tuple[str, str]], copyright_text: str) -> str:
        lines = [f"{app_name} v{version}"]
        lines += [f"{k}: {v}" for k, v in facts]
        lines.append(copyright_text)
        return "\n".join(lines)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._plain)
