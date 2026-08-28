"""状态栏 chrome 装配：将各子组件挂到 QStatusBar 并统一暴露引用。"""

from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QStatusBar, QWidget

from ..device_status_chip import DeviceStatusField
from .fault_strategy_selector import FaultStrategySelector
from .http_env_selector import HttpEnvSelector
from .ios_backend_selector import IosBackendSelector
from .pause_indicator import PauseIndicator
from .run_progress_bar import RunProgressBar
from .web_engine_selector import WebEngineSelector


class StatusBarChrome:
    """装配状态栏子组件；MainWindow 通过属性别名访问，Run/Device mixin 无需大改。"""

    def __init__(
        self,
        status_bar: QStatusBar,
        *,
        ios_backend_mode: str = "auto",
        web_engine: str = "selenium",
        http_env_profile: str = "",
    ) -> None:
        self._bar = status_bar
        # 左侧：失败策略 / iOS 后端 / Web 引擎 / 设备 —— 同一条控件带
        self._controls = QWidget(status_bar)
        self._controls.setObjectName("status_bar_controls")
        lay = QHBoxLayout(self._controls)
        lay.setContentsMargins(2, 0, 8, 0)
        lay.setSpacing(12)
        self.fault = FaultStrategySelector(self._controls)
        lay.addWidget(self.fault)
        self.ios_backend = IosBackendSelector(ios_backend_mode, self._controls)
        lay.addWidget(self.ios_backend)
        self.web_engine = WebEngineSelector(web_engine, self._controls)
        lay.addWidget(self.web_engine)
        self.http_env = HttpEnvSelector(http_env_profile, self._controls)
        lay.addWidget(self.http_env)
        self.device = DeviceStatusField(self._controls)
        lay.addWidget(self.device)
        status_bar.addWidget(self._controls)

        self.mc_session = QLabel("未登录", status_bar)
        self.mc_session.setObjectName("status_bar_field")
        self.mc_session.setToolTip("必须登录后才能使用 IDE")
        status_bar.addPermanentWidget(self.mc_session)

        self.mc_runner = QLabel("Runner 未启动", status_bar)
        self.mc_runner.setObjectName("status_bar_field")
        self.mc_runner.setToolTip("管理台 → 启动本机 Runner，可将本机 USB 设备注册到 TR 池")
        status_bar.addPermanentWidget(self.mc_runner)

        self.progress = RunProgressBar(status_bar)
        status_bar.addPermanentWidget(self.progress)
        self.pause = PauseIndicator(status_bar)
        status_bar.addPermanentWidget(self.pause)

    def wire_device_connect(self, slot) -> None:
        # noinspection PyUnresolvedReferences
        self.device.connectRequested.connect(slot)

    def apply_theme(self, theme: str) -> None:
        self.device.apply_theme(theme)
        self.pause.apply_theme(theme)
