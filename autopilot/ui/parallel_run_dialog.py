"""并行执行选项对话框（同平台、多设备时）。

并行含义：勾选的用例在每台参与设备上各完整跑一遍（N 条 × M 台），同时执行。
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)


def ask_parallel_run(
    parent, platform: str, device_count: int, *, case_count: int = 0,
) -> tuple[bool, int, bool] | None:
    """返回 (parallel, workers, fault_isolation) 或 None（取消）。

    device_count<2 时直接 (False, 0, True)。
    fault_isolation=True 表示某台失败不杀其它设备（默认）。
    """
    if device_count < 2:
        return False, 0, True

    plat = (platform or "").strip().lower()
    plat_label = {"android": "Android", "ios": "iOS"}.get(plat, platform or "移动")
    n_cases = max(int(case_count or 0), 0)

    dlg = QDialog(parent)
    dlg.setWindowTitle("运行选项")
    layout = QVBoxLayout(dlg)
    if n_cases > 0:
        tip_text = (
            f"检测到 {device_count} 台 {plat_label} 设备，本次勾选 {n_cases} 条用例。\n"
            f"勾选并行后，每台设备都会完整跑这 {n_cases} 条"
            f"（{device_count} 台同时执行，合计 {n_cases * device_count} 次）。")
    else:
        tip_text = (
            f"检测到 {device_count} 台 {plat_label} 设备。\n"
            "勾选并行后，每台设备都会完整跑本次勾选的全部用例（多台同时执行）。")
    tip = QLabel(tip_text)
    tip.setWordWrap(True)
    layout.addWidget(tip)

    maps_hint = QLabel("提示：并行时对象库只读共享，请勿在关键字内就地修改对象库元素。")
    maps_hint.setWordWrap(True)
    maps_hint.setStyleSheet("color: #666;")
    layout.addWidget(maps_hint)

    if plat == "android":
        hint = QLabel(
            "Android 并行：每台设备独立 Appium 端口与 UIA2 systemPort"
            "（slot0=4723/8200，slot1=4724/8201…），互不停服。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666;")
        layout.addWidget(hint)

    chk = QCheckBox("并行执行（每台设备都跑完全部勾选用例）")
    chk.setChecked(True)
    layout.addWidget(chk)

    form = QFormLayout()
    spin = QSpinBox()
    spin.setRange(2, device_count)
    spin.setValue(device_count)
    form.addRow("并行设备数：", spin)
    layout.addLayout(form)

    chk_isolate = QCheckBox("失败隔离（某设备失败不停止其它设备）")
    chk_isolate.setChecked(True)
    chk_isolate.setToolTip(
        "开启：各设备独立收尾；关闭：任一台失败即请求停止其它设备。")
    layout.addWidget(chk_isolate)

    def on_toggle(checked: bool) -> None:
        spin.setEnabled(checked)
        chk_isolate.setEnabled(checked)

    # noinspection PyUnresolvedReferences
    chk.toggled.connect(on_toggle)
    on_toggle(chk.isChecked())

    btn_row = QHBoxLayout()
    btn_row.addStretch()
    ok_btn = QPushButton("确定")
    cancel_btn = QPushButton("取消")
    # noinspection PyUnresolvedReferences
    ok_btn.clicked.connect(dlg.accept)
    # noinspection PyUnresolvedReferences
    cancel_btn.clicked.connect(dlg.reject)
    btn_row.addWidget(ok_btn)
    btn_row.addWidget(cancel_btn)
    layout.addLayout(btn_row)

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    if not chk.isChecked():
        return False, 0, True
    return True, spin.value(), chk_isolate.isChecked()
