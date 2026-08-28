"""浅色主题 QSS 片段（单一事实源）。"""

MAIN_WINDOW_SHELL_QSS = """
QMainWindow {
    background-color: #f3f3f3;
    color: #212121;
}
QMainWindow::separator {
    background: #eceff1;
    width: 7px;
    height: 7px;
    border: 1px solid #cfd8dc;
}
QMainWindow::separator:hover {
    background: #bbdefb;
}
QDockWidget {
    color: #212121;
    background-color: #f3f3f3;
    border: none;
}
QDockWidget#dock_left_sidebar,
QDockWidget#dock_right_aux,
QDockWidget#dock_console {
    background-color: #f3f3f3;
}
QDockWidget::title {
    background: #f3f3f3;
    padding: 0;
}
QDockWidget QWidget#qt_dockwidget_scrollarea {
    background-color: #f3f3f3;
    border: none;
}
QTreeWidget {
    background-color: #ffffff;
    color: #212121;
    border: none;
    alternate-background-color: #f5f6f8;
    outline: 0;
}
QTreeWidget::item {
    padding: 2px 0;
}
QTreeWidget::item:selected {
    background-color: #e3f2fd;
    color: #000000;
}
QTreeWidget::item:hover:!selected {
    background-color: #f0f4f8;
}
QTreeView {
    background-color: #ffffff;
    color: #212121;
    border: none;
    alternate-background-color: #f5f6f8;
    outline: 0;
}
QTreeView::item {
    padding: 2px 0;
}
QTreeView::item:selected {
    background-color: #e3f2fd;
    color: #000000;
}
QTreeView::item:hover:!selected {
    background-color: #f0f4f8;
}
QHeaderView::section {
    background-color: #fafafa;
    color: #424242;
    border: none;
    border-right: 1px solid #e0e0e0;
    border-bottom: 1px solid #e0e0e0;
    padding: 4px 6px;
}
QTabBar::tab {
    background: #ececec;
    color: #616161;
    padding: 6px 12px;
    border: 1px solid #d0d0d0;
    border-bottom: none;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #212121;
}
QTabWidget::pane {
    border: 1px solid #d0d0d0;
    background: #ffffff;
}
QStatusBar {
    background: #f3f3f3;
    color: #212121;
    border-top: 1px solid #e0e0e0;
}
QStatusBar QLabel {
    color: #616161;
}
QStatusBar QWidget#status_bar_controls {
    background: transparent;
}
QStatusBar QWidget#status_bar_field {
    background: transparent;
}
QStatusBar QComboBox {
    background-color: #ffffff;
    color: #212121;
    border: 1px solid #d0d0d0;
    border-radius: 3px;
    padding: 1px 6px;
    min-height: 20px;
}
QStatusBar QProgressBar {
    background: #eceff1;
    border: 1px solid #cfd8dc;
    border-radius: 3px;
    text-align: center;
    color: #212121;
}
QStatusBar QProgressBar::chunk {
    background: #64b5f6;
    border-radius: 2px;
}
QLineEdit, QComboBox, QPushButton, QCheckBox {
    background-color: #ffffff;
    color: #212121;
    border: 1px solid #d0d0d0;
    border-radius: 3px;
    padding: 3px 6px;
}
/* QSpinBox 只给配色：一旦在 QSS 里给它 border/padding，Qt 就改由样式表绘制上下按钮，
   而我们没有箭头图片可用，微调箭头会整块消失（回归见 test_theme_spinbox_arrows.py）。*/
QSpinBox {
    background-color: #ffffff;
    color: #212121;
}
QLineEdit::placeholder {
    color: #616161;
}
QToolButton {
    color: #424242;
}
QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #212121;
    selection-background-color: #e3f2fd;
}
QMenu {
    background-color: #ffffff;
    color: #212121;
    border: 1px solid #d0d0d0;
}
QMenu::item:disabled {
    color: #9e9e9e;
}
QMenu::item:selected {
    background-color: #e3f2fd;
}
"""

CONSOLE_QSS = """
QWidget#autopilot_console {
    background-color: #ffffff;
    color: #212121;
}
QWidget#autopilot_console QLabel {
    color: #212121;
}
QWidget#autopilot_console QHeaderView::section {
    background-color: #fafafa;
    color: #424242;
    border: none;
    border-right: 1px solid #e0e0e0;
    border-bottom: 1px solid #e0e0e0;
    padding: 4px 6px;
}
QWidget#autopilot_console QTableCornerButton::section {
    background-color: #fafafa;
    border: none;
}
QWidget#autopilot_console QLineEdit,
QWidget#autopilot_console QComboBox,
QWidget#autopilot_console QPushButton,
QWidget#autopilot_console QCheckBox {
    background-color: #ffffff;
    color: #212121;
}
QWidget#autopilot_console QTableWidget {
    background-color: #ffffff;
    color: #212121;
    gridline-color: #e0e0e0;
    border: none;
    alternate-background-color: #f5f6f8;
}
QWidget#autopilot_console QTableWidget::item:selected {
    background-color: #e3f2fd;
    color: #000000;
}
"""

TOOLBAR_QSS = """
QToolBar#main_toolbar {
    spacing: 2px;
    padding: 2px 6px;
    border-bottom: 1px solid #e0e0e0;
    background: #fafafa;
}
QToolBar#main_toolbar QToolButton {
    padding: 3px;
    border-radius: 3px;
    min-width: 26px;
    min-height: 26px;
}
QToolBar#main_toolbar QToolButton:hover {
    background: #eeeeee;
}
QToolBar#main_toolbar::separator {
    width: 1px;
    margin: 2px 4px;
    background: #e0e0e0;
}
QWidget#editor_run_toolbar QToolButton {
    padding: 3px;
    border-radius: 3px;
    min-width: 26px;
    min-height: 26px;
}
QWidget#editor_run_toolbar QToolButton:hover:enabled {
    background: #eeeeee;
}
"""

PROJECT_PANEL_QSS = """
QWidget#project_panel {
    background: #ffffff;
}
QWidget#project_toolbar {
    background: #f3f3f3;
    border-bottom: 1px solid #e0e0e0;
}
QWidget#project_toolbar QToolButton {
    padding: 3px 6px;
    border-radius: 4px;
    min-width: 24px;
    min-height: 24px;
    color: #424242;
}
QWidget#project_toolbar QToolButton:hover:enabled {
    background: #e8e8e8;
}
QWidget#project_toolbar QToolButton:disabled {
    color: #9e9e9e;
}
QWidget#project_toolbar QToolButton#batch_run_btn {
    border-radius: 4px;
    border: 1px solid #7986cb;
    background: #e8eaf6;
    color: #283593;
}
QWidget#project_toolbar QToolButton#batch_run_btn:hover:enabled {
    background: #c5cae9;
    border-color: #5c6bc0;
}
QWidget#project_toolbar QToolButton#batch_run_btn:disabled {
    color: #9e9e9e;
    background: #f3f3f3;
    border-color: #e0e0e0;
}
QLineEdit#project_filter {
    padding: 4px 8px;
    border: none;
    border-bottom: 1px solid #e0e0e0;
    background: #ffffff;
    color: #212121;
}
QLineEdit#project_filter::placeholder {
    color: #616161;
}
QLineEdit#project_filter:focus {
    border-bottom: 1px solid #64b5f6;
    background: #ffffff;
}
QTreeView#project_tree {
    background: #ffffff;
    color: #212121;
    alternate-background-color: #f5f6f8;
    border: none;
    outline: 0;
}
QTreeView#project_tree::item:selected {
    background: #e3f2fd;
    color: #000000;
}
QTreeView#project_tree::item:hover:!selected {
    background: #f0f4f8;
}
"""

SIDEBAR_CONTEXT_QSS = """
QWidget#sidebar_context {
    background: #f3f3f3;
}
QLabel#sidebar_context_label {
    font-size: 12px;
    font-weight: 500;
    color: #616161;
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
    color: #616161;
    background: #ffffff;
    border: 1px solid #d0d0d0;
}
QPushButton#device_status_chip[state="detected"] {
    color: #1565c0;
    background: #ffffff;
    border: 1px solid #90caf9;
}
QPushButton#device_status_chip[state="connected"] {
    color: #2e7d32;
    background: #ffffff;
    border: 1px solid #a5d6a7;
}
QPushButton#device_status_chip:hover {
    border-color: #64b5f6;
}
"""

AUXILIARY_TOOLBAR_QSS = """
QWidget#auxiliary_region_toolbar {
    background: #f3f3f3;
    border-bottom: 1px solid #e0e0e0;
}
QLabel#auxiliary_region_title {
    color: #757575;
    font-size: 11px;
}
"""

TEXT_MUTED_QSS = """
QLabel#text_muted {
    color: #757575;
}
"""

KEYWORD_PANEL_QSS = """
QTreeWidget#keyword_tree {
    outline: 0;
    background: #ffffff;
    color: #212121;
    alternate-background-color: #f5f6f8;
}
QTreeWidget#keyword_tree::item { padding: 4px 2px; }
QTreeWidget#keyword_tree::item:selected { background: #e3f2fd; color: #000; }
QLabel#keyword_platform_hint { color: #78909c; font-size: 11px; padding: 0 2px; }
"""

CASE_EDITOR_QSS = """
QTableWidget#case_editor {
    background: #ffffff;
    color: #212121;
    gridline-color: #e0e0e0;
    alternate-background-color: #f5f6f8;
}
QTableWidget#case_editor QHeaderView::section {
    background-color: #fafafa;
    color: #424242;
    border: none;
    border-right: 1px solid #e0e0e0;
    border-bottom: 1px solid #e0e0e0;
    padding: 4px 6px;
}
QTableWidget#case_editor::item { padding: 3px 4px; }
QTableWidget#case_editor::item:selected { background: #e3f2fd; color: #000; }
"""

FORM_EDITOR_QSS = """
QTableWidget {
    background: #ffffff;
    color: #212121;
    gridline-color: #e0e0e0;
    alternate-background-color: #fafafa;
}
QTableWidget QHeaderView::section {
    background-color: #fafafa;
    color: #424242;
    border: none;
    border-right: 1px solid #e0e0e0;
    border-bottom: 1px solid #e0e0e0;
    padding: 4px 6px;
}
QTableWidget::item { padding: 3px 4px; }
QTableWidget::item:selected { background: #e3f2fd; color: #000; }
QListWidget {
    background: #ffffff;
    color: #212121;
    alternate-background-color: #fafafa;
    border: 1px solid #e0e0e0;
}
QListWidget::item:selected { background: #e3f2fd; color: #000; }
"""

EMPTY_STATE_QSS = """
QLabel#empty_state_title { font-size: 15px; color: #757575; }
QLabel#empty_state_hint { font-size: 12px; color: #757575; }
QLabel#empty_state_title_compact { font-size: 13px; color: #9e9e9e; }
QLabel#empty_state_hint_compact { font-size: 11px; color: #bdbdbd; }
"""

PARAM_FORM_QSS = """
QScrollArea#param_form {
    background: #ffffff;
    border: none;
}
QScrollArea#param_form QWidget#param_form_body {
    background: #ffffff;
    color: #212121;
}
QScrollArea#param_form QLabel#param_form_note {
    color: #757575;
    font-size: 12px;
}
QScrollArea#param_form QPlainTextEdit#param_form_multiline {
    background: #ffffff;
    color: #212121;
    border: 1px solid #e0e0e0;
    border-radius: 4px;
    padding: 6px;
    min-height: 120px;
    font-family: Consolas, "Courier New", monospace;
    font-size: 12px;
}
"""

MAP_EDITOR_QSS = """
QLabel#map_editor_hint { color: #757575; }
QTreeWidget {
    background: #ffffff;
    color: #212121;
    alternate-background-color: #f5f6f8;
    gridline-color: #e0e0e0;
}
"""

INSPECTOR_PANEL_QSS = """
QWidget#inspector_panel,
QWidget#inspector_tree_host,
QWidget#inspector_right_host {
    background: #ffffff;
    color: #212121;
}
QWidget#inspector_workspace_empty {
    background: #f3f3f3;
}
QWidget#inspector_panel QLabel {
    color: #212121;
}
QWidget#inspector_panel QLabel#inspector_section_label {
    color: #757575;
    font-size: 12px;
}
QWidget#inspector_panel QPushButton {
    background-color: #ffffff;
    color: #212121;
    border: 1px solid #d0d0d0;
    border-radius: 3px;
    padding: 3px 8px;
}
QWidget#inspector_panel QTreeWidget,
QWidget#inspector_panel QTableWidget,
QWidget#inspector_panel QListWidget {
    background: #ffffff;
    color: #212121;
    alternate-background-color: #f5f6f8;
    gridline-color: #e0e0e0;
    border: none;
}
QWidget#inspector_panel QTreeWidget::viewport,
QWidget#inspector_panel QTableWidget::viewport,
QWidget#inspector_panel QListWidget::viewport {
    background: #ffffff;
}
QWidget#inspector_panel QTableWidget::item {
    color: #212121;
}
QWidget#inspector_panel QHeaderView::section {
    background-color: #fafafa;
    color: #424242;
    border: none;
    border-right: 1px solid #e0e0e0;
    border-bottom: 1px solid #e0e0e0;
    padding: 4px 6px;
}
QWidget#inspector_panel QGraphicsView {
    background: #f3f3f3;
    border: none;
}
QLabel#inspector_loc_value {
    font-family: Consolas, 'Courier New', monospace;
    font-size: 12px;
    color: #212121;
}
"""

MIRROR_PANEL_QSS = """
QWidget#mirror_panel {
    background: #ffffff;
    color: #212121;
}
QWidget#mirror_panel QLabel {
    color: #212121;
}
QWidget#mirror_panel QPushButton,
QWidget#mirror_panel QToolButton {
    background-color: #ffffff;
    color: #212121;
    border: 1px solid #d0d0d0;
    border-radius: 3px;
    padding: 3px 8px;
}
QWidget#mirror_panel QLineEdit {
    background-color: #ffffff;
    color: #212121;
    border: 1px solid #d0d0d0;
    border-radius: 3px;
    padding: 3px 6px;
}
QWidget#mirror_panel QLineEdit::placeholder {
    color: #616161;
}
QWidget#mirror_panel QGraphicsView {
    background: #f3f3f3;
    border: 1px solid #e0e0e0;
}
"""

AUXILIARY_REGION_QSS = """
QWidget#right_auxiliary_region {
    background: #f3f3f3;
    color: #212121;
}
QWidget#right_auxiliary_region QTabBar,
QWidget#right_auxiliary_region QTabBar#aux_view_tab_bar {
    background: #f3f3f3;
    min-height: 28px;
}
QWidget#right_auxiliary_region QTabBar::tab {
    background: #ececec;
    color: #616161;
    padding: 6px 12px;
    border: 1px solid #d0d0d0;
    border-bottom: none;
    margin-right: -1px;
}
QWidget#right_auxiliary_region QTabBar::tab:selected {
    background: #ffffff;
    color: #212121;
}
QWidget#right_auxiliary_region QTabWidget::pane {
    background: #ffffff;
    border: 1px solid #e0e0e0;
}
"""

LEFT_SIDEBAR_QSS = """
QWidget#left_sidebar {
    background: #f3f3f3;
    color: #212121;
}
QWidget#left_sidebar QWidget#project_panel {
    background: #ffffff;
}
"""

EDITOR_WORKSPACE_QSS = """
QWidget#editor_workspace {
    background: #ffffff;
    color: #212121;
}
QWidget#editor_workspace QStackedWidget#center_stack {
    background: #ffffff;
}
QWidget#doc_tab_row {
    background: #fafafa;
    border-bottom: 1px solid #e0e0e0;
}
"""

WELCOME_PANEL_QSS = """
QWidget#welcome_panel {
    background-color: #f3f3f3;
    color: #333333;
}
QWidget#welcome_panel QLabel#welcome_title {
    color: #2c2c2c;
    font-size: 26px;
    font-weight: bold;
}
QWidget#welcome_panel QLabel#welcome_subtitle {
    color: #777777;
    font-size: 13px;
}
QWidget#welcome_panel QLabel#section_title {
    color: #2c2c2c;
    font-size: 14px;
    font-weight: bold;
    padding-bottom: 6px;
    border-bottom: 1px solid #d0d0d0;
}
QWidget#welcome_panel QFrame#welcome_card {
    background-color: #ffffff;
    border: 1px solid #d0d0d0;
    border-radius: 6px;
}
QWidget#welcome_panel QPushButton#action_btn {
    background-color: transparent;
    border: none;
    text-align: left;
    padding: 10px 14px;
    font-size: 13px;
    color: #333333;
    border-radius: 4px;
}
QWidget#welcome_panel QPushButton#action_btn:hover {
    background-color: #e1e1e1;
    color: #2c2c2c;
}
QWidget#welcome_panel QListWidget#recent_list {
    background-color: transparent;
    border: none;
    outline: none;
}
QWidget#welcome_panel QListWidget#recent_list::item {
    padding: 8px 12px;
    color: #333333;
    border-radius: 4px;
}
QWidget#welcome_panel QListWidget#recent_list::item:hover {
    background-color: #eaeaea;
    color: #2c2c2c;
}
QWidget#welcome_panel QPushButton#clear_btn {
    background-color: transparent;
    border: none;
    color: #777777;
    font-size: 12px;
    padding: 6px 12px;
}
QWidget#welcome_panel QPushButton#clear_btn:hover {
    color: #c62828;
    text-decoration: underline;
}
"""

AI_AUTHORING_DIALOG_QSS = """
QDialog#ai_authoring_dialog {
    background: #f7f8fa;
    color: #212121;
}
QDialog#ai_authoring_dialog QLabel#dialog_hint {
    color: #566573;
    font-size: 12px;
    padding: 0 0 4px 0;
}
QDialog#ai_authoring_dialog QLineEdit,
QDialog#ai_authoring_dialog QComboBox,
QDialog#ai_authoring_dialog QPlainTextEdit {
    background: #ffffff;
    color: #212121;
    border: 1px solid #cfd6dd;
    border-radius: 4px;
    padding: 4px 6px;
    selection-background-color: #e3f2fd;
    selection-color: #000000;
}
QDialog#ai_authoring_dialog QLineEdit:focus,
QDialog#ai_authoring_dialog QComboBox:focus,
QDialog#ai_authoring_dialog QPlainTextEdit:focus {
    border-color: #1976d2;
}
QDialog#ai_authoring_dialog QLineEdit[readOnly="true"] {
    background: #f1f3f5;
    color: #566573;
}
QDialog#ai_authoring_dialog QCheckBox {
    color: #37474f;
    spacing: 6px;
}
/* 保留 Fusion 原生上下箭头；不要为 QSpinBox 添加 border/padding。 */
QDialog#ai_authoring_dialog QSpinBox {
    background: #ffffff;
    color: #212121;
}
QDialog#ai_authoring_dialog QTableWidget#authoring_steps {
    background: #ffffff;
    alternate-background-color: #f7f9fb;
    color: #212121;
    gridline-color: #e0e5ea;
    border: 1px solid #cfd6dd;
    border-radius: 4px;
    selection-background-color: #e3f2fd;
    selection-color: #000000;
}
QDialog#ai_authoring_dialog QHeaderView::section {
    background: #f1f3f5;
    color: #37474f;
    border: none;
    border-right: 1px solid #e0e5ea;
    border-bottom: 1px solid #d5dbe1;
    padding: 5px 7px;
    font-weight: 600;
}
QDialog#ai_authoring_dialog QPushButton {
    background: #ffffff;
    color: #263238;
    border: 1px solid #c5ccd3;
    border-radius: 4px;
    padding: 5px 12px;
}
QDialog#ai_authoring_dialog QPushButton:hover {
    background: #eef4fa;
    border-color: #90a4ae;
}
QDialog#ai_authoring_dialog QPushButton#primary_action {
    background: #1565c0;
    color: #ffffff;
    border-color: #1565c0;
    font-weight: 600;
}
QDialog#ai_authoring_dialog QPushButton#primary_action:hover {
    background: #0d47a1;
}
QDialog#ai_authoring_dialog QPushButton:disabled {
    background: #eceff1;
    color: #9e9e9e;
    border-color: #d9dee2;
}
QDialog#ai_authoring_dialog QLabel#authoring_status {
    color: #566573;
    min-height: 18px;
}
"""

ABOUT_DIALOG_QSS = """
QDialog#about_dialog {
    background: #ffffff;
    color: #212121;
}
QDialog#about_dialog QLabel#about_app_name { font-size: 18px; font-weight: 600; }
QDialog#about_dialog QLabel#about_version { color: #888888; font-size: 12px; }
QDialog#about_dialog QLabel#about_tagline { color: #666666; }
QDialog#about_dialog QFrame#about_separator { color: #e0e0e0; }
QDialog#about_dialog QLabel#about_fact_key { color: #999999; }
QDialog#about_dialog QLabel#about_fact_value { color: #212121; }
QDialog#about_dialog QLabel#about_copyright { color: #aaaaaa; font-size: 11px; }
"""

DIALOG_FORM_QSS = """
QDialog#form_dialog {
    background: #ffffff;
    color: #212121;
}
QDialog#form_dialog QLabel#dialog_hint {
    color: #616161;
    font-size: 12px;
    padding: 0 0 2px 0;
}
QDialog#form_dialog QLineEdit, QDialog#form_dialog QComboBox {
    background: #ffffff;
    color: #212121;
    border: 1px solid #d0d0d0;
    padding: 4px 6px;
}
QDialog#form_dialog QFrame#list_pick_frame {
    background: #fafafa;
    border: 1px solid #e0e0e0;
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
    background: #e8f1fb;
    border: 1px solid #1565c0;
}
QDialog#form_dialog QListWidget#list_pick_list::item:hover:!selected {
    background: #f0f0f0;
}
QDialog#form_dialog QWidget#list_pick_row {
    background: transparent;
    border-radius: 4px;
}
QDialog#form_dialog QWidget#list_pick_row[selected="true"] {
    background: transparent;
}
QDialog#form_dialog QLabel#list_pick_title {
    color: #212121;
    font-size: 13px;
    font-weight: 600;
}
QDialog#form_dialog QLabel#list_pick_sub {
    color: #757575;
    font-size: 11px;
    font-family: Consolas, "Courier New", monospace;
}
QDialog#form_dialog QWidget#list_pick_row[selected="true"] QLabel#list_pick_title {
    color: #0d47a1;
}
QDialog#form_dialog QWidget#list_pick_row[selected="true"] QLabel#list_pick_sub {
    color: #546e7a;
}
"""

LOGIN_GATE_QSS = """
QDialog#login_gate_dialog {
    background: #f5f7fa;
    color: #212121;
}
QDialog#login_gate_dialog QFrame#login_card {
    background: #ffffff;
    border: 1px solid #e0e4ea;
    border-radius: 12px;
}
QDialog#login_gate_dialog QLabel#login_title {
    font-size: 20px;
    font-weight: 700;
    color: #1a1a1a;
}
QDialog#login_gate_dialog QLabel#login_tagline {
    font-size: 12px;
    color: #757575;
}
QDialog#login_gate_dialog QLabel#field_label {
    font-size: 12px;
    font-weight: 600;
    color: #424242;
    padding-top: 4px;
}
QDialog#login_gate_dialog QLineEdit {
    background: #fafbfc;
    color: #212121;
    border: 1px solid #d0d7de;
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 13px;
    min-height: 20px;
}
QDialog#login_gate_dialog QLineEdit:focus {
    border: 1px solid #1565c0;
    background: #ffffff;
}
QDialog#login_gate_dialog QFrame#platform_chip {
    background: #f0f4f8;
    border: 1px solid #e3e8ef;
    border-radius: 8px;
}
QDialog#login_gate_dialog QLabel#platform_chip_label {
    font-size: 11px;
    font-weight: 600;
    color: #546e7a;
}
QDialog#login_gate_dialog QLabel#platform_chip_url {
    font-size: 12px;
    color: #37474f;
    font-family: Consolas, "Segoe UI", monospace;
}
QDialog#login_gate_dialog QPushButton#link_btn {
    color: #1565c0;
    border: none;
    background: transparent;
    font-size: 12px;
    padding: 2px 6px;
}
QDialog#login_gate_dialog QPushButton#link_btn:hover {
    color: #0d47a1;
    text-decoration: underline;
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
    background: #90caf9;
    color: #e3f2fd;
}
QDialog#login_gate_dialog QPushButton#login_exit_btn {
    color: #757575;
    border: none;
    background: transparent;
    font-size: 12px;
    padding: 6px;
}
QDialog#login_gate_dialog QPushButton#login_exit_btn:hover {
    color: #424242;
}
QDialog#login_gate_dialog QLabel#login_error {
    color: #c62828;
    font-size: 12px;
    padding: 4px 2px;
}
QDialog#login_gate_dialog QLabel#step_hint {
    font-size: 13px;
    color: #616161;
    padding-bottom: 4px;
}
QDialog#login_gate_dialog QLabel#step_crumb {
    font-size: 12px;
    color: #9e9e9e;
    padding: 2px 0;
}
QDialog#login_gate_dialog QLabel#step_crumb[active="true"] {
    color: #1565c0;
    font-weight: 600;
}
QDialog#login_gate_dialog QLabel#step_sep {
    color: #bdbdbd;
    font-size: 12px;
}
QDialog#login_gate_dialog QFrame#session_strip {
    background: #e8f4fd;
    border: 1px solid #bbdefb;
    border-radius: 8px;
}
QDialog#login_gate_dialog QLabel#session_user {
    font-size: 12px;
    font-weight: 600;
    color: #1565c0;
}
QDialog#login_gate_dialog QLabel#session_platform {
    font-size: 11px;
    color: #546e7a;
    font-family: Consolas, "Segoe UI", monospace;
}
QDialog#login_gate_dialog QLineEdit#project_search {
    min-height: 18px;
    padding: 8px 10px;
}
QDialog#login_gate_dialog QFrame#list_pick_frame {
    background: #fafafa;
    border: 1px solid #e0e0e0;
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
    background: #eef2f7;
}
QDialog#login_gate_dialog QWidget#list_pick_row {
    background: transparent;
    border: 1px solid transparent;
    border-left: 3px solid transparent;
    border-radius: 6px;
}
QDialog#login_gate_dialog QWidget#list_pick_row[selected="true"] {
    background: #e3f2fd;
    border: 1px solid #1565c0;
    border-left: 3px solid #1565c0;
    border-radius: 6px;
}
QDialog#login_gate_dialog QLabel#list_pick_title {
    font-size: 13px;
    font-weight: 600;
}
QDialog#login_gate_dialog QWidget#list_pick_row[selected="true"] QLabel#list_pick_title {
    color: #0d47a1;
}
QDialog#login_gate_dialog QLabel#list_pick_sub {
    color: #757575;
    font-size: 11px;
    font-family: Consolas, "Courier New", monospace;
}
QDialog#login_gate_dialog QWidget#list_pick_row[selected="true"] QLabel#list_pick_sub {
    color: #37474f;
}
QDialog#login_gate_dialog QLabel#project_count {
    font-size: 11px;
    color: #757575;
    padding: 2px 2px 0 2px;
}
QDialog#login_gate_dialog QListWidget#list_pick_list QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px 0;
}
QDialog#login_gate_dialog QListWidget#list_pick_list QScrollBar::handle:vertical {
    background: #c5cdd6;
    border-radius: 5px;
    min-height: 24px;
}
QDialog#login_gate_dialog QListWidget#list_pick_list QScrollBar::handle:vertical:hover {
    background: #9aa7b4;
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
