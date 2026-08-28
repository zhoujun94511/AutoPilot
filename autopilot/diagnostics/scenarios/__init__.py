"""内置诊断场景入口。

导入本包会注册随安装包提供的场景；扩展模块可调用
``register_scenario`` 增加自定义诊断。
"""

from .android_settings import ANDROID_SETTINGS_SCENARIO
from .registry import (
    DiagnosticScenario,
    get_scenario,
    list_scenarios,
    register_scenario,
)

register_scenario(ANDROID_SETTINGS_SCENARIO)

__all__ = [
    "DiagnosticScenario",
    "get_scenario",
    "list_scenarios",
    "register_scenario",
]
