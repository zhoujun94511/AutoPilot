"""内置诊断场景注册表。"""

from __future__ import annotations

from typing import Protocol

from ...mgmt.target_app import TargetAppParams


class DiagnosticScenario(Protocol):
    """诊断场景插件契约。"""

    name: str
    description: str

    def requirement(self) -> str:
        """返回用于联调生成的需求文本。"""

    def acquire_target_app(self, *, udid: str = "") -> TargetAppParams:
        """获取场景目标 App。"""

    def resolve_assert_target(self, *, udid: str = "") -> str:
        """解析场景专属断言目标。"""


_SCENARIOS: dict[str, DiagnosticScenario] = {}


def register_scenario(scenario: DiagnosticScenario) -> None:
    """注册内置或扩展场景；同名重复注册直接报错。"""
    name = (scenario.name or "").strip().lower()
    if not name:
        raise ValueError("诊断场景 name 不能为空")
    if name in _SCENARIOS:
        raise ValueError(f"诊断场景重复注册: {name}")
    _SCENARIOS[name] = scenario


def get_scenario(name: str) -> DiagnosticScenario:
    """按名称返回诊断场景。"""
    key = (name or "").strip().lower()
    scenario = _SCENARIOS.get(key)
    if scenario is None:
        raise KeyError(f"unknown diagnostic scenario: {name!r}; known={list_scenarios()}")
    return scenario


def list_scenarios() -> list[str]:
    """列出已注册场景。"""
    return sorted(_SCENARIOS)
