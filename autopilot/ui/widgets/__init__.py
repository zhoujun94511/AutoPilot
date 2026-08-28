"""可复用界面组件：每个面板一个独立 widget 模块，组件间通过 Qt 信号解耦。"""

from .project_tree import ProjectTree
from .project_panel import ProjectPanel
from .keyword_panel import KeywordPanel
from .case_editor import CaseEditor
from .console import Console
from .param_form import ParamForm
from .map_editor import MapEditor
from .keyword_editor import CustomKeywordEditor
from .dataconfig_editor import DataConfigEditor
from .suite_editor import SuiteEditor
from .testplan_editor import TestPlanEditor
from .inspector_panel import InspectorPanel
from .mirror_panel import MirrorPanel
from .auxiliary_region import RightAuxiliaryRegion
from .search_results_panel import SearchResultsPanel
from .welcome_panel import WelcomePanel

__all__ = [
    "RightAuxiliaryRegion",
    "InspectorPanel",
    "MirrorPanel",
    "ProjectTree",
    "ProjectPanel",
    "KeywordPanel",
    "CaseEditor",
    "Console",
    "ParamForm",
    "MapEditor",
    "CustomKeywordEditor",
    "DataConfigEditor",
    "SuiteEditor",
    "TestPlanEditor",
    "SearchResultsPanel",
    "WelcomePanel",
]
