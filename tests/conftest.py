"""pytest 全局夹具。

离屏 CI 下，产品代码里的模态对话框（QInputDialog / QMessageBox / QFileDialog）
会 exec() 等待用户交互，无人点击时永久阻塞、拖垮整套用例。这里用 autouse 夹具
统一给它们的静态便捷方法打桩，返回“确定 + 首选项”的安全默认，保证流程可继续。

自检脚本的旧式 main 测试也通过 run_test_suite.py 复用同一组默认值。
手动 `python tests/xxx.py` 直跑不加载 conftest，仍保留脚本自己的交互行为。
"""

import os

import pytest

from tests.headless_dialogs import stub_modal_dialogs

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
def _stub_modal_dialogs():
    with stub_modal_dialogs():
        yield
