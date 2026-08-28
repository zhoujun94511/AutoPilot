# Chrome 组件

主窗口外围可复用 UI 块，与业务逻辑解耦。主窗口（`MainWindow`）只负责装配与信号接线。

| 组件                         | 文件                           | 职责                                 |
|----------------------------|------------------------------|------------------------------------|
| `IconToolButton`           | `icon_tool_button.py`        | 统一图标按钮（含 qtawesome 降级）             |
| `ProjectExplorerToolbar`   | `project_toolbar.py`         | 工程树头部工具条                           |
| `SidebarHeader`            | `../sidebar_header.py`       | 侧栏顶栏标题（工程名/搜索）                     |
| `StatusBarChrome`          | `status_bar_chrome.py`       | 状态栏装配器                             |
| `FaultStrategySelector`    | `fault_strategy_selector.py` | 失败策略下拉                             |
| `IosBackendSelector`       | `ios_backend_selector.py`    | iOS 后端下拉                           |
| `RunProgressBar`           | `run_progress_bar.py`        | 运行进度（`begin`/`advance_case`/`end`） |
| `PauseIndicator`           | `pause_indicator.py`         | 暂停状态指示                             |
| `MainToolbarChrome`        | `main_toolbar.py`            | 全局工具栏（`TOOLBAR_GROUPS`）            |
| `AuxiliaryRegionToolbar`   | `auxiliary_toolbar.py`       | 右侧辅区顶栏                             |
| `ViewTabStack`             | `view_tab_stack.py`          | 带 view_id 的 Tab 堆叠                 |
| `build_qactions`           | `action_builder.py`          | `ACTIONS` → `QAction` 字典           |
| `refresh_run_control_tips` | `run_control_tips.py`        | 暂停/停止 tooltip                      |
| `MenuBarChrome`            | `menu_bar.py`                | 菜单栏（MENUS + 视图/帮助）                 |
| `fill_menu_from_rows`      | `menu_bar.py`                | 按 MENUS 行填充 QMenu                  |
| `DeviceStatusField`        | `../device_status_chip.py`   | 状态栏「设备」标签 + 可点击状态按钮（与失败策略同构）       |

样式集中在 `autopilot/ui/theme/`（`apply_main_window`、`panel_stylesheet`、`THEME_DARK`）；`styles.py` 保留向后兼容导出。

## 主题

- `qss_light.py` / `qss_dark.py` — 浅色/暗色 QSS 片段（键名一一对应）。
- `panel_stylesheet(name, theme=...)` — 按面板名取样式；**未知 `name` 会抛 `ValueError`**（禁止静默空串）。
- `registered_panel_names()` — 已注册名称集合；新增面板先在两边 `*_QSS` 与映射表登记，再调用。
- 视图菜单 **主题 → 浅色/暗色** 切换，持久化到 `~/.autopilot/settings.json` 的 `ui_theme`。
- 已接入主题的面板：`welcome_panel`、`keyword_panel`、`case_editor`、`param_form`、`map_editor`、`inspector_panel`、`empty_state` 等（各组件实现 `apply_theme`）。
- 对话框：`ai_authoring_dialog`、`about_dialog`、`dialog_form`（新建工程/数据源/列表选择）、`login_gate` 通过 `apply_dialog_theme()` 取主窗口当前主题。
- 离屏测试请用 `tests/_qt.py` 的 `get_qt_app()`，避免 macOS 上 `Sans Serif` 字体警告。

## 扩展方式

- **侧栏**：`LeftSidebar` 直挂 `ProjectPanel`；文件名筛选见 `ProjectPanel.filter`。
- **新增工程工具**：在 `ProjectExplorerToolbar` 加按钮并声明 `pyqtSignal`，`ProjectPanel` 转发或处理。
- **新增状态栏块**：实现小组件后在 `StatusBarChrome.__init__` 挂载，并在 `MainWindow._build_statusbar` 暴露别名（若 mixin 需要）。
- **新增右侧辅区视图**：在 `RightAuxiliaryRegion` 的 `ViewTabStack` 元组中加 `(view_id, label, widget)`。
- **新增工具栏按钮**：在 `actions.TOOLBAR_GROUPS` 加 action id（无需改 `MainToolbarChrome`）。
