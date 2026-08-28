"""IDE 远程批跑对话框：切到 HTTP 时清掉移动/浏览器残留 backend。"""

from __future__ import annotations


def test_submit_dialog_http_resets_uia2_and_retitles(tmp_path, monkeypatch):
    from tests._qt import get_qt_app
    from autopilot.ui.widgets.mgmt_submit_job_dialog import MgmtSubmitJobDialog

    get_qt_app()
    dlg = MgmtSubmitJobDialog(None)
    dlg.platform.setCurrentText("android")
    idx = dlg.backend_mode.findText("uia2")
    assert idx >= 0
    dlg.backend_mode.setCurrentIndex(idx)
    dlg.platform.setCurrentText("http")
    assert dlg.backend_mode.currentText() == "auto"
    assert "执行节点" in dlg._dev_box.title()
    dlg.backend_mode.setEditText("staging")
    dlg.platform.setCurrentText("web")
    assert dlg.backend_mode.currentText() == "auto"
    dlg.platform.setCurrentText("http")
    assert dlg.backend_mode.currentText() == "auto"
