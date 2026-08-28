"""暗色主题 QSS 片段（与 qss_light 键名一一对应）。"""

MAIN_WINDOW_SHELL_QSS = """
QMainWindow {
    background-color: #1e1e1e;
    color: #e0e0e0;
}
QMainWindow::separator {
    background: #3c3c3c;
    width: 7px;
    height: 7px;
    border: 1px solid #2d2d2d;
}
QMainWindow::separator:hover {
    background: #505050;
}
QDockWidget {
    color: #e0e0e0;
    background-color: #252526;
    border: none;
}
QDockWidget#dock_left_sidebar,
QDockWidget#dock_right_aux,
QDockWidget#dock_console {
    background-color: #252526;
}
QDockWidget::title {
    background: #252526;
    padding: 0;
}
QDockWidget QWidget#qt_dockwidget_scrollarea {
    background-color: #252526;
    border: none;
}
QTreeWidget {
    background-color: #1e1e1e;
    color: #e0e0e0;
    border: none;
    alternate-background-color: #252526;
    outline: 0;
}
QTreeWidget::item {
    padding: 2px 0;
}
QTreeWidget::item:selected {
    background-color: #264f78;
    color: #ffffff;
}
QTreeWidget::item:hover:!selected {
    background-color: #2a2d2e;
}
QTreeView {
    background-color: #1e1e1e;
    color: #e0e0e0;
    border: none;
    alternate-background-color: #252526;
    outline: 0;
}
QTreeView::item {
    padding: 2px 0;
}
QTreeView::item:selected {
    background-color: #264f78;
    color: #ffffff;
}
QTreeView::item:hover:!selected {
    background-color: #2a2d2e;
}
QHeaderView::section {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: none;
    border-right: 1px solid #3c3c3c;
    border-bottom: 1px solid #3c3c3c;
    padding: 4px 6px;
}
QTabBar::tab {
    background: #2d2d2d;
    color: #9e9e9e;
    padding: 6px 12px;
    border: 1px solid #3c3c3c;
    border-bottom: none;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #1e1e1e;
    color: #e0e0e0;
}
QTabWidget::pane {
    border: 1px solid #3c3c3c;
    background: #1e1e1e;
}
QStatusBar {
    background: #252526;
    color: #e0e0e0;
    border-top: 1px solid #3c3c3c;
}
QStatusBar QLabel {
    color: #9e9e9e;
}
QStatusBar QWidget#status_bar_controls {
    background: transparent;
}
QStatusBar QWidget#status_bar_field {
    background: transparent;
}
QStatusBar QComboBox {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #3c3c3c;
    border-radius: 3px;
    padding: 1px 6px;
    min-height: 20px;
}
QStatusBar QProgressBar {
    background: #3c3c3c;
    border: 1px solid #505050;
    border-radius: 3px;
    text-align: center;
    color: #e0e0e0;
}
QStatusBar QProgressBar::chunk {
    background: #64b5f6;
    border-radius: 2px;
}
QLineEdit, QComboBox, QPushButton, QCheckBox {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #3c3c3c;
    border-radius: 3px;
    padding: 3px 6px;
}
/* QSpinBox 只给配色：一旦在 QSS 里给它 border/padding，Qt 就改由样式表绘制上下按钮，
   而我们没有箭头图片可用，微调箭头会整块消失（回归见 test_theme_spinbox_arrows.py）。*/
QSpinBox {
    background-color: #2d2d2d;
    color: #e0e0e0;
}
QLineEdit::placeholder {
    color: #9e9e9e;
}
QToolButton {
    color: #e0e0e0;
}
QComboBox QAbstractItemView {
    background-color: #2d2d2d;
    color: #e0e0e0;
    selection-background-color: #264f78;
}
QMenu {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #3c3c3c;
}
QMenu::item:disabled {
    color: #6e6e6e;
}
QMenu::item:selected {
    background-color: #264f78;
}
"""

CONSOLE_QSS = """
QWidget#autopilot_console {
    background-color: #1e1e1e;
    color: #e0e0e0;
}
QWidget#autopilot_console QLabel {
    color: #e0e0e0;
}
QWidget#autopilot_console QHeaderView::section {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: none;
    border-right: 1px solid #3c3c3c;
    border-bottom: 1px solid #3c3c3c;
    padding: 4px 6px;
}
QWidget#autopilot_console QTableCornerButton::section {
    background-color: #2d2d2d;
    border: none;
}
QWidget#autopilot_console QLineEdit,
QWidget#autopilot_console QComboBox,
QWidget#autopilot_console QPushButton,
QWidget#autopilot_console QCheckBox {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #3c3c3c;
}
QWidget#autopilot_console QTableWidget {
    background-color: #1e1e1e;
    color: #e0e0e0;
    gridline-color: #3c3c3c;
    border: none;
    alternate-background-color: #252526;
}
QWidget#autopilot_console QTableWidget::item:selected {
    background-color: #264f78;
    color: #ffffff;
}
"""

TOOLBAR_QSS = """
QToolBar#main_toolbar {
    spacing: 2px;
    padding: 2px 6px;
    border-bottom: 1px solid #3c3c3c;
    background: #2d2d2d;
}
QToolBar#main_toolbar QToolButton {
    padding: 3px;
    border-radius: 3px;
    min-width: 26px;
    min-height: 26px;
    color: #e0e0e0;
}
QToolBar#main_toolbar QToolButton:hover {
    background: #3c3c3c;
}
QToolBar#main_toolbar::separator {
    width: 1px;
    margin: 2px 4px;
    background: #3c3c3c;
}
QWidget#editor_run_toolbar QToolButton {
    padding: 3px;
    border-radius: 3px;
    min-width: 26px;
    min-height: 26px;
}
QWidget#editor_run_toolbar QToolButton:hover:enabled {
    background: #3c3c3c;
}
"""

PROJECT_PANEL_QSS = """
QWidget#project_panel {
    background: #1e1e1e;
}
QWidget#project_toolbar {
    background: #252526;
    border-bottom: 1px solid #3c3c3c;
}
QWidget#project_toolbar QToolButton {
    padding: 3px 6px;
    border-radius: 4px;
    min-width: 24px;
    min-height: 24px;
    color: #e0e0e0;
}
QWidget#project_toolbar QToolButton:hover:enabled {
    background: #3c3c3c;
}
QWidget#project_toolbar QToolButton:disabled {
    color: #6e6e6e;
}
QWidget#project_toolbar QToolButton#batch_run_btn {
    border-radius: 4px;
    border: 1px solid #5c6bc0;
    background: #3949ab;
    color: #e8eaf6;
}
QWidget#project_toolbar QToolButton#batch_run_btn:hover:enabled {
    background: #5c6bc0;
}
QWidget#project_toolbar QToolButton#batch_run_btn:disabled {
    color: #6e6e6e;
    background: #2d2d2d;
    border-color: #3c3c3c;
}
QLineEdit#project_filter {
    padding: 4px 8px;
    border: none;
    border-bottom: 1px solid #3c3c3c;
    background: #2d2d2d;
    color: #e0e0e0;
}
QLineEdit#project_filter::placeholder {
    color: #9e9e9e;
}
QLineEdit#project_filter:focus {
    border-bottom: 1px solid #64b5f6;
    background: #1e1e1e;
}
QTreeView#project_tree {
    background: #1e1e1e;
    color: #e0e0e0;
    alternate-background-color: #252526;
    border: none;
    outline: 0;
}
QTreeView#project_tree::item:selected {
    background: #264f78;
    color: #ffffff;
}
QTreeView#project_tree::item:hover:!selected {
    background: #2a2d2e;
}
"""

SIDEBAR_CONTEXT_QSS = """
QWidget#sidebar_context {
    background: #252526;
}
QLabel#sidebar_context_label {
    font-size: 12px;
    font-weight: 500;
    color: #9e9e9e;
}
"""

SIDEBAR_HEADER_QSS = SIDEBAR_CONTEXT_QSS

DEVICE_CHIP_QSS = """
QPushButton#device_status_chip {
    border-radius: 3px;
    padding: 1px 8px;
    font-size: 12px;
    min-height: 20px;
}
QPushButton#device_status_chip[state="idle"] {
    color: #9e9e9e;
    background: #2d2d2d;
    border: 1px solid #3c3c3c;
}
QPushButton#device_status_chip[state="detected"] {
    color: #90caf9;
    background: #2d2d2d;
    border: 1px solid #3949ab;
}
QPushButton#device_status_chip[state="connected"] {
    color: #a5d6a7;
    background: #2d2d2d;
    border: 1px solid #388e3c;
}
QPushButton#device_status_chip:hover {
    border-color: #64b5f6;
}
"""

AUXILIARY_TOOLBAR_QSS = """
QWidget#auxiliary_region_toolbar {
    background: #252526;
    border-bottom: 1px solid #3c3c3c;
}
QLabel#auxiliary_region_title {
    color: #9e9e9e;
    font-size: 11px;
}
"""

TEXT_MUTED_QSS = """
QLabel#text_muted {
    color: #bdbdbd;
}
"""

KEYWORD_PANEL_QSS = """
QTreeWidget#keyword_tree {
    outline: 0;
    background: #1e1e1e;
    color: #e0e0e0;
    alternate-background-color: #252526;
}
QTreeWidget#keyword_tree::item { padding: 4px 2px; }
QTreeWidget#keyword_tree::item:selected { background: #264f78; color: #ffffff; }
QLabel#keyword_platform_hint { color: #9e9e9e; font-size: 11px; padding: 0 2px; }
"""

CASE_EDITOR_QSS = """
QTableWidget#case_editor {
    background: #1e1e1e;
    color: #e0e0e0;
    gridline-color: #3c3c3c;
}
QTableWidget#case_editor QHeaderView::section {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: none;
    border-right: 1px solid #3c3c3c;
    border-bottom: 1px solid #3c3c3c;
    padding: 4px 6px;
}
QTableWidget#case_editor::item { padding: 3px 4px; }
QTableWidget#case_editor::item:selected { background: #264f78; color: #ffffff; }
"""

FORM_EDITOR_QSS = """
QTableWidget {
    background: #1e1e1e;
    color: #e0e0e0;
    gridline-color: #3c3c3c;
    alternate-background-color: #252526;
}
QTableWidget QHeaderView::section {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: none;
    border-right: 1px solid #3c3c3c;
    border-bottom: 1px solid #3c3c3c;
    padding: 4px 6px;
}
QTableWidget::item { padding: 3px 4px; }
QTableWidget::item:selected { background: #264f78; color: #ffffff; }
QListWidget {
    background: #1e1e1e;
    color: #e0e0e0;
    alternate-background-color: #252526;
    border: 1px solid #3c3c3c;
}
QListWidget::item:selected { background: #264f78; color: #ffffff; }
"""

EMPTY_STATE_QSS = """
QLabel#empty_state_title { font-size: 15px; color: #9e9e9e; }
QLabel#empty_state_hint { font-size: 12px; color: #9e9e9e; }
QLabel#empty_state_title_compact { font-size: 13px; color: #757575; }
QLabel#empty_state_hint_compact { font-size: 11px; color: #616161; }
"""

PARAM_FORM_QSS = """
QScrollArea#param_form {
    background: #1e1e1e;
    border: none;
}
QScrollArea#param_form QWidget#param_form_body {
    background: #1e1e1e;
    color: #e0e0e0;
}
QScrollArea#param_form QLabel#param_form_note {
    color: #9e9e9e;
    font-size: 12px;
}
QScrollArea#param_form QPlainTextEdit#param_form_multiline {
    background: #252526;
    color: #e0e0e0;
    border: 1px solid #3c3c3c;
    border-radius: 4px;
    padding: 6px;
    min-height: 120px;
    font-family: Consolas, "Courier New", monospace;
    font-size: 12px;
}
"""

MAP_EDITOR_QSS = """
QLabel#map_editor_hint { color: #9e9e9e; }
QTreeWidget {
    background: #1e1e1e;
    color: #e0e0e0;
    alternate-background-color: #252526;
    gridline-color: #3c3c3c;
}
"""

INSPECTOR_PANEL_QSS = """
QWidget#inspector_panel,
QWidget#inspector_tree_host,
QWidget#inspector_right_host {
    background: #1e1e1e;
    color: #e0e0e0;
}
QWidget#inspector_workspace_empty {
    background: #2d2d2d;
}
QWidget#inspector_panel QLabel {
    color: #e0e0e0;
}
QWidget#inspector_panel QLabel#inspector_section_label {
    color: #9e9e9e;
    font-size: 12px;
}
QWidget#inspector_panel QPushButton {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #3c3c3c;
    border-radius: 3px;
    padding: 3px 8px;
}
QWidget#inspector_panel QTreeWidget,
QWidget#inspector_panel QTableWidget,
QWidget#inspector_panel QListWidget {
    background: #1e1e1e;
    color: #e0e0e0;
    alternate-background-color: #252526;
    gridline-color: #3c3c3c;
    border: none;
}
QWidget#inspector_panel QTreeWidget::viewport,
QWidget#inspector_panel QTableWidget::viewport,
QWidget#inspector_panel QListWidget::viewport {
    background: #1e1e1e;
}
QWidget#inspector_panel QTableWidget::item {
    color: #e0e0e0;
}
QWidget#inspector_panel QHeaderView::section {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: none;
    border-right: 1px solid #3c3c3c;
    border-bottom: 1px solid #3c3c3c;
    padding: 4px 6px;
}
QWidget#inspector_panel QGraphicsView {
    background: #2d2d2d;
    border: none;
}
QLabel#inspector_loc_value {
    font-family: Consolas, 'Courier New', monospace;
    font-size: 12px;
    color: #e0e0e0;
}
"""

MIRROR_PANEL_QSS = """
QWidget#mirror_panel {
    background: #1e1e1e;
    color: #e0e0e0;
}
QWidget#mirror_panel QLabel {
    color: #e0e0e0;
}
QWidget#mirror_panel QPushButton,
QWidget#mirror_panel QToolButton {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #3c3c3c;
    border-radius: 3px;
    padding: 3px 8px;
}
QWidget#mirror_panel QLineEdit {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #3c3c3c;
    border-radius: 3px;
    padding: 3px 6px;
}
QWidget#mirror_panel QLineEdit::placeholder {
    color: #9e9e9e;
}
QWidget#mirror_panel QGraphicsView {
    background: #2d2d2d;
    border: 1px solid #3c3c3c;
}
"""

AUXILIARY_REGION_QSS = """
QWidget#right_auxiliary_region {
    background: #252526;
    color: #e0e0e0;
}
QWidget#right_auxiliary_region QTabBar,
QWidget#right_auxiliary_region QTabBar#aux_view_tab_bar {
    background: #252526;
    min-height: 28px;
}
QWidget#right_auxiliary_region QTabBar::tab {
    background: #2d2d2d;
    color: #9e9e9e;
    padding: 6px 12px;
    border: 1px solid #3c3c3c;
    border-bottom: none;
    margin-right: -1px;
}
QWidget#right_auxiliary_region QTabBar::tab:selected {
    background: #1e1e1e;
    color: #e0e0e0;
}
QWidget#right_auxiliary_region QTabWidget::pane {
    background: #1e1e1e;
    border: 1px solid #3c3c3c;
}
"""

LEFT_SIDEBAR_QSS = """
QWidget#left_sidebar {
    background: #252526;
    color: #e0e0e0;
}
QWidget#left_sidebar QWidget#project_panel {
    background: #1e1e1e;
}
"""

EDITOR_WORKSPACE_QSS = """
QWidget#editor_workspace {
    background: #1e1e1e;
    color: #e0e0e0;
}
QWidget#editor_workspace QStackedWidget#center_stack {
    background: #1e1e1e;
}
QWidget#doc_tab_row {
    background: #2d2d2d;
    border-bottom: 1px solid #3c3c3c;
}
"""

WELCOME_PANEL_QSS = """
QWidget#welcome_panel {
    background-color: #1e1e1e;
    color: #cccccc;
}
QWidget#welcome_panel QLabel#welcome_title {
    color: #ffffff;
    font-size: 26px;
    font-weight: bold;
}
QWidget#welcome_panel QLabel#welcome_subtitle {
    color: #858585;
    font-size: 13px;
}
QWidget#welcome_panel QLabel#section_title {
    color: #ffffff;
    font-size: 14px;
    font-weight: bold;
    padding-bottom: 6px;
    border-bottom: 1px solid #3c3c3c;
}
QWidget#welcome_panel QFrame#welcome_card {
    background-color: #252526;
    border: 1px solid #3c3c3c;
    border-radius: 6px;
}
QWidget#welcome_panel QPushButton#action_btn {
    background-color: transparent;
    border: none;
    text-align: left;
    padding: 10px 14px;
    font-size: 13px;
    color: #cccccc;
    border-radius: 4px;
}
QWidget#welcome_panel QPushButton#action_btn:hover {
    background-color: #37373d;
    color: #ffffff;
}
QWidget#welcome_panel QListWidget#recent_list {
    background-color: transparent;
    border: none;
    outline: none;
}
QWidget#welcome_panel QListWidget#recent_list::item {
    padding: 8px 12px;
    color: #cccccc;
    border-radius: 4px;
}
QWidget#welcome_panel QListWidget#recent_list::item:hover {
    background-color: #2a2d2e;
    color: #ffffff;
}
QWidget#welcome_panel QPushButton#clear_btn {
    background-color: transparent;
    border: none;
    color: #858585;
    font-size: 12px;
    padding: 6px 12px;
}
QWidget#welcome_panel QPushButton#clear_btn:hover {
    color: #ef5350;
    text-decoration: underline;
}
"""

AI_AUTHORING_DIALOG_QSS = """
QDialog#ai_authoring_dialog {
    background: #252526;
    color: #e0e0e0;
}
QDialog#ai_authoring_dialog QLabel#dialog_hint {
    color: #b0bec5;
    font-size: 12px;
    padding: 0 0 4px 0;
}
QDialog#ai_authoring_dialog QLineEdit,
QDialog#ai_authoring_dialog QComboBox,
QDialog#ai_authoring_dialog QPlainTextEdit {
    background: #1e1e1e;
    color: #e0e0e0;
    border: 1px solid #4b4b4b;
    border-radius: 4px;
    padding: 4px 6px;
    selection-background-color: #264f78;
    selection-color: #ffffff;
}
QDialog#ai_authoring_dialog QLineEdit:focus,
QDialog#ai_authoring_dialog QComboBox:focus,
QDialog#ai_authoring_dialog QPlainTextEdit:focus {
    border-color: #64b5f6;
}
QDialog#ai_authoring_dialog QLineEdit[readOnly="true"] {
    background: #2d2d2d;
    color: #b0bec5;
}
QDialog#ai_authoring_dialog QCheckBox {
    color: #cfd8dc;
    spacing: 6px;
}
/* 保留 Fusion 原生上下箭头；不要为 QSpinBox 添加 border/padding。 */
QDialog#ai_authoring_dialog QSpinBox {
    background: #1e1e1e;
    color: #e0e0e0;
}
QDialog#ai_authoring_dialog QTableWidget#authoring_steps {
    background: #1e1e1e;
    alternate-background-color: #252526;
    color: #e0e0e0;
    gridline-color: #3c3c3c;
    border: 1px solid #4b4b4b;
    border-radius: 4px;
    selection-background-color: #264f78;
    selection-color: #ffffff;
}
QDialog#ai_authoring_dialog QHeaderView::section {
    background: #2d2d2d;
    color: #e0e0e0;
    border: none;
    border-right: 1px solid #3c3c3c;
    border-bottom: 1px solid #4b4b4b;
    padding: 5px 7px;
    font-weight: 600;
}
QDialog#ai_authoring_dialog QPushButton {
    background: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #505050;
    border-radius: 4px;
    padding: 5px 12px;
}
QDialog#ai_authoring_dialog QPushButton:hover {
    background: #37373d;
    border-color: #707070;
}
QDialog#ai_authoring_dialog QPushButton#primary_action {
    background: #1976d2;
    color: #ffffff;
    border-color: #1976d2;
    font-weight: 600;
}
QDialog#ai_authoring_dialog QPushButton#primary_action:hover {
    background: #1565c0;
}
QDialog#ai_authoring_dialog QPushButton:disabled {
    background: #2a2a2a;
    color: #6e6e6e;
    border-color: #3c3c3c;
}
QDialog#ai_authoring_dialog QLabel#authoring_status {
    color: #b0bec5;
    min-height: 18px;
}
"""

ABOUT_DIALOG_QSS = """
QDialog#about_dialog { background: #2d2d2d; color: #e0e0e0; }
QDialog#about_dialog QLabel#about_app_name { font-size: 18px; font-weight: 600; color: #ffffff; }
QDialog#about_dialog QLabel#about_version { color: #9e9e9e; font-size: 12px; }
QDialog#about_dialog QLabel#about_tagline { color: #bdbdbd; }
QDialog#about_dialog QFrame#about_separator { color: #3c3c3c; }
QDialog#about_dialog QLabel#about_fact_key { color: #9e9e9e; }
QDialog#about_dialog QLabel#about_fact_value { color: #e0e0e0; }
QDialog#about_dialog QLabel#about_copyright { color: #757575; font-size: 11px; }
"""

DIALOG_FORM_QSS = """
QDialog#form_dialog { background: #2d2d2d; color: #e0e0e0; }
QDialog#form_dialog QLabel#dialog_hint {
    color: #9e9e9e;
    font-size: 12px;
    padding: 0 0 2px 0;
}
QDialog#form_dialog QLineEdit, QDialog#form_dialog QComboBox {
    background: #1e1e1e;
    color: #e0e0e0;
    border: 1px solid #3c3c3c;
    padding: 4px 6px;
}
QDialog#form_dialog QFrame#list_pick_frame {
    background: #252525;
    border: 1px solid #3c3c3c;
    border-radius: 6px;
}
QDialog#form_dialog QListWidget#list_pick_list {
    background: transparent;
    border: none;
    outline: none;
    padding: 4px;
}
QDialog#form_dialog QListWidget#list_pick_list::item {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    margin: 1px 2px;
    padding: 0;
}
QDialog#form_dialog QListWidget#list_pick_list::item:selected {
    background: #264f78;
    border: 1px solid #64b5f6;
}
QDialog#form_dialog QListWidget#list_pick_list::item:hover:!selected {
    background: #333333;
}
QDialog#form_dialog QWidget#list_pick_row {
    background: transparent;
    border-radius: 4px;
}
QDialog#form_dialog QLabel#list_pick_title {
    color: #e8e8e8;
    font-size: 13px;
    font-weight: 600;
}
QDialog#form_dialog QLabel#list_pick_sub {
    color: #9e9e9e;
    font-size: 11px;
    font-family: Consolas, "Courier New", monospace;
}
QDialog#form_dialog QWidget#list_pick_row[selected="true"] QLabel#list_pick_title {
    color: #ffffff;
}
QDialog#form_dialog QWidget#list_pick_row[selected="true"] QLabel#list_pick_sub {
    color: #cfd8dc;
}
"""

LOGIN_GATE_QSS = """
QDialog#login_gate_dialog {
    background: #1e1e1e;
    color: #e0e0e0;
}
QDialog#login_gate_dialog QFrame#login_card {
    background: #2d2d2d;
    border: 1px solid #3c3c3c;
    border-radius: 12px;
}
QDialog#login_gate_dialog QLabel#login_title {
    font-size: 20px;
    font-weight: 700;
    color: #ffffff;
}
QDialog#login_gate_dialog QLabel#login_tagline {
    font-size: 12px;
    color: #9e9e9e;
}
QDialog#login_gate_dialog QLabel#field_label {
    font-size: 12px;
    font-weight: 600;
    color: #bdbdbd;
    padding-top: 4px;
}
QDialog#login_gate_dialog QLineEdit {
    background: #252525;
    color: #e0e0e0;
    border: 1px solid #454545;
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 13px;
    min-height: 20px;
}
QDialog#login_gate_dialog QLineEdit:focus {
    border: 1px solid #42a5f5;
    background: #1e1e1e;
}
QDialog#login_gate_dialog QFrame#platform_chip {
    background: #252525;
    border: 1px solid #3c3c3c;
    border-radius: 8px;
}
QDialog#login_gate_dialog QLabel#platform_chip_label {
    font-size: 11px;
    font-weight: 600;
    color: #9e9e9e;
}
QDialog#login_gate_dialog QLabel#platform_chip_url {
    font-size: 12px;
    color: #cfd8dc;
    font-family: Consolas, "Segoe UI", monospace;
}
QDialog#login_gate_dialog QPushButton#link_btn {
    color: #64b5f6;
    border: none;
    background: transparent;
    font-size: 12px;
    padding: 2px 6px;
}
QDialog#login_gate_dialog QPushButton#link_btn:hover {
    color: #90caf9;
}
QDialog#login_gate_dialog QPushButton#login_primary_btn {
    background: #1565c0;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 600;
    padding: 11px 16px;
    min-height: 22px;
}
QDialog#login_gate_dialog QPushButton#login_primary_btn:hover {
    background: #1976d2;
}
QDialog#login_gate_dialog QPushButton#login_primary_btn:pressed {
    background: #0d47a1;
}
QDialog#login_gate_dialog QPushButton#login_primary_btn:disabled {
    background: #37474f;
    color: #78909c;
}
QDialog#login_gate_dialog QPushButton#login_exit_btn {
    color: #9e9e9e;
    border: none;
    background: transparent;
    font-size: 12px;
    padding: 6px;
}
QDialog#login_gate_dialog QPushButton#login_exit_btn:hover {
    color: #e0e0e0;
}
QDialog#login_gate_dialog QLabel#login_error {
    color: #ef5350;
    font-size: 12px;
    padding: 4px 2px;
}
QDialog#login_gate_dialog QLabel#step_hint {
    font-size: 13px;
    color: #9e9e9e;
    padding-bottom: 4px;
}
QDialog#login_gate_dialog QLabel#step_crumb {
    font-size: 12px;
    color: #757575;
    padding: 2px 0;
}
QDialog#login_gate_dialog QLabel#step_crumb[active="true"] {
    color: #64b5f6;
    font-weight: 600;
}
QDialog#login_gate_dialog QLabel#step_sep {
    color: #616161;
    font-size: 12px;
}
QDialog#login_gate_dialog QFrame#session_strip {
    background: #1a2836;
    border: 1px solid #37474f;
    border-radius: 8px;
}
QDialog#login_gate_dialog QLabel#session_user {
    font-size: 12px;
    font-weight: 600;
    color: #64b5f6;
}
QDialog#login_gate_dialog QLabel#session_platform {
    font-size: 11px;
    color: #90a4ae;
    font-family: Consolas, "Segoe UI", monospace;
}
QDialog#login_gate_dialog QLineEdit#project_search {
    min-height: 18px;
    padding: 8px 10px;
}
QDialog#login_gate_dialog QFrame#list_pick_frame {
    background: #252525;
    border: 1px solid #3c3c3c;
    border-radius: 8px;
}
QDialog#login_gate_dialog QListWidget#list_pick_list {
    background: transparent;
    border: none;
    outline: none;
    padding: 4px;
}
QDialog#login_gate_dialog QListWidget#list_pick_list::item {
    border-radius: 6px;
    padding: 0;
    margin: 2px 0;
}
QDialog#login_gate_dialog QListWidget#list_pick_list::item:selected {
    background: transparent;
}
QDialog#login_gate_dialog QListWidget#list_pick_list::item:hover:!selected {
    background: #2f2f2f;
}
QDialog#login_gate_dialog QWidget#list_pick_row {
    background: transparent;
    border: 1px solid transparent;
    border-left: 3px solid transparent;
    border-radius: 6px;
}
QDialog#login_gate_dialog QWidget#list_pick_row[selected="true"] {
    background: #37474f;
    border: 1px solid #64b5f6;
    border-left: 3px solid #64b5f6;
    border-radius: 6px;
}
QDialog#login_gate_dialog QLabel#list_pick_title {
    font-size: 13px;
    font-weight: 600;
}
QDialog#login_gate_dialog QWidget#list_pick_row[selected="true"] QLabel#list_pick_title {
    color: #ffffff;
}
QDialog#login_gate_dialog QLabel#list_pick_sub {
    color: #9e9e9e;
    font-size: 11px;
    font-family: Consolas, "Segoe UI", monospace;
}
QDialog#login_gate_dialog QWidget#list_pick_row[selected="true"] QLabel#list_pick_sub {
    color: #cfd8dc;
}
QDialog#login_gate_dialog QLabel#project_count {
    font-size: 11px;
    color: #9e9e9e;
    padding: 2px 2px 0 2px;
}
QDialog#login_gate_dialog QListWidget#list_pick_list QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px 0;
}
QDialog#login_gate_dialog QListWidget#list_pick_list QScrollBar::handle:vertical {
    background: #4a4a4a;
    border-radius: 5px;
    min-height: 24px;
}
QDialog#login_gate_dialog QListWidget#list_pick_list QScrollBar::handle:vertical:hover {
    background: #616161;
}
QDialog#login_gate_dialog QListWidget#list_pick_list QScrollBar::add-line:vertical,
QDialog#login_gate_dialog QListWidget#list_pick_list QScrollBar::sub-line:vertical {
    height: 0;
}
QDialog#login_gate_dialog QListWidget#list_pick_list QScrollBar::add-page:vertical,
QDialog#login_gate_dialog QListWidget#list_pick_list QScrollBar::sub-page:vertical {
    background: transparent;
}
"""
