"""pytest 全局夹具。

离屏 CI 下，产品代码里的模态对话框（QInputDialog / QMessageBox / QFileDialog）
会 exec() 等待用户交互，无人点击时永久阻塞、拖垮整套用例。这里用 autouse 夹具
统一给它们的静态便捷方法打桩，返回“确定 + 首选项”的安全默认，保证流程可继续。

注意：夹具仅在 pytest 收集运行时生效；手动 `python tests/xxx.py` 直跑不加载
conftest，仍会真实弹窗（符合人工交互场景）。
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# 用例不得继承开发机 .env：intent CLI 等入口会 load_project_dotenv，
# 一旦加载，本机的 AUTOPILOT_INTENT_VISION / 厂商 Key 会残留到后续所有用例。
os.environ["AUTOPILOT_NO_DOTENV"] = "1"


@pytest.fixture(autouse=True)
def _reset_device_isolation_state():
    from autopilot.keywords.mobile.appium_server import reset_appium_server_pool_for_tests
    from autopilot.runtime.device_runtime import reset_device_runtimes_for_tests

    reset_device_runtimes_for_tests()
    reset_appium_server_pool_for_tests()
    yield
    reset_device_runtimes_for_tests()
    reset_appium_server_pool_for_tests()


pytest_plugins = [
    "tests.web_live_support",
    "tests.web_live_fixtures",
]


@pytest.fixture(autouse=True)
def _stub_modal_dialogs(monkeypatch):
    try:
        from PyQt6.QtWidgets import QFileDialog, QInputDialog, QMessageBox
    except (ImportError, ModuleNotFoundError):
        return  # 无 PyQt6 的纯逻辑测试无需打桩

    # 输入类：返回 (值, ok=True)，让 new_case 等流程选中首项后继续
    monkeypatch.setattr(QInputDialog, "getItem",
                        staticmethod(lambda *a, **k: ("通用", True)), raising=False)
    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("", True)), raising=False)
    monkeypatch.setattr(QInputDialog, "getInt",
                        staticmethod(lambda *a, **k: (0, True)), raising=False)
    monkeypatch.setattr(QInputDialog, "getDouble",
                        staticmethod(lambda *a, **k: (0.0, True)), raising=False)

    # 消息框：默认“是/确定”，避免二次确认阻塞
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes), raising=False)
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok), raising=False)
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok), raising=False)
    monkeypatch.setattr(QMessageBox, "critical",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok), raising=False)

    # 文件框：默认“取消”（空路径），测试若需真实路径会自行打桩覆盖
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: ("", "")), raising=False)
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: ("", "")), raising=False)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: ""), raising=False)
