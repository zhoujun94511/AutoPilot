"""主窗口 chrome 组件：状态栏、工具栏、侧栏、右侧辅区等可复用 UI 块。

主窗口只负责装配与业务接线；样式与交互细节封装在各组件内，便于后期扩展。
"""

from .icon_tool_button import IconToolButton
from .action_builder import build_qactions, init_run_control_actions
from .run_progress_bar import RunProgressBar
from .pause_indicator import PauseIndicator
from .fault_strategy_selector import FaultStrategySelector
from .ios_backend_selector import IosBackendSelector
from .web_engine_selector import WebEngineSelector
from .http_env_selector import HttpEnvSelector
from .status_bar_chrome import StatusBarChrome
from .project_toolbar import ProjectExplorerToolbar
from .main_toolbar import MainToolbarChrome
from .editor_run_toolbar import EditorRunToolbar
from .auxiliary_toolbar import AuxiliaryRegionToolbar
from .view_tab_stack import ViewTabStack
from .menu_bar import MenuBarChrome, fill_menu_from_rows
from .run_control_tips import refresh_run_control_tips

__all__ = [
    "AuxiliaryRegionToolbar",
    "FaultStrategySelector",
    "IconToolButton",
    "HttpEnvSelector",
    "IosBackendSelector",
    "WebEngineSelector",
    "EditorRunToolbar",
    "MainToolbarChrome",
    "MenuBarChrome",
    "PauseIndicator",
    "ProjectExplorerToolbar",
    "RunProgressBar",
    "StatusBarChrome",
    "ViewTabStack",
    "build_qactions",
    "fill_menu_from_rows",
    "init_run_control_actions",
    "refresh_run_control_tips",
]
