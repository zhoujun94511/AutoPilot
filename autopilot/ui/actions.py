"""UI 动作注册表：所有命令的单一事实源。

每个动作声明一次（id / 文案 / 槽方法名 / 作用域 / 快捷键 / 图标 / 附加参数），
菜单栏、工具栏、编辑器右键菜单都从这里构建，避免动作散落各处、各写各的。

作用域 scope：
  - "global"：文件/运行/设备等，进主菜单 + 主工具栏；
  - "editor"：步骤增删改/控制流插入/剪贴板，只进编辑器右键 + 编辑菜单，
              不污染全局工具栏（转发给当前用例/套件编辑器）。

槽绑定：主窗口 build_actions(self) 时按 slot 名 getattr(self, slot)，附 args 调用。
结构（菜单层级、工具栏分组）也在本文件声明，引用 action id。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ActionSpec:
    id: str
    text: str
    slot: str                       # 主窗口方法名
    scope: str = "global"           # global | editor
    shortcut: str = ""
    icon: str = ""                  # qtawesome 图标名（统一用 Material Design Icons：mdi6.*）
    checkable: bool = False         # 可勾选动作（如暂停/继续）
    args: tuple = field(default_factory=tuple)
    tip: str = ""
    min_role: str = "operator"      # operator | admin（平台 User.role=admin）


# ---- 动作清单（单一事实源）----
ACTIONS: tuple[ActionSpec, ...] = (
    # 文件
    ActionSpec("file.new_project", "新建工程…", "new_project_dialog", icon="mdi6.folder-plus"),
    ActionSpec("file.open_project", "打开工程…", "open_project_dialog", icon="mdi6.folder-open"),
    ActionSpec("file.open_file", "打开文件…", "open_file_dialog", icon="mdi6.file-outline"),
    ActionSpec("file.new_case", "快速草稿用例", "new_case", icon="mdi6.file-plus",
               tip="无需工程即可编辑；保存时再选择落盘位置"),
    ActionSpec("file.new_suite", "新建测试套", "_new_resource", args=("suite",), icon="mdi6.folder-multiple-outline"),
    ActionSpec("file.new_map", "新建对象库", "_new_resource", args=("map",), icon="mdi6.map-marker"),
    ActionSpec("file.new_dataconfig", "新建数据配置", "_new_resource", args=("dataconfig",), icon="mdi6.cog-outline"),
    ActionSpec("file.new_testplan", "新建测试计划", "_new_resource", args=("testplan",), icon="mdi6.clipboard-text-outline"),
    ActionSpec("file.new_keyword", "新建自定义关键字", "new_custom_keyword", icon="mdi6.puzzle-outline"),
    ActionSpec("file.new_folder", "新建文件夹", "_new_folder_dialog", icon="mdi6.folder-plus-outline"),
    ActionSpec("file.save", "保存", "save_current", shortcut="Ctrl+S", icon="mdi6.content-save"),
    ActionSpec("file.save_as", "另存为…", "save_as_dialog", icon="mdi6.content-save-edit-outline"),
    ActionSpec("file.close", "关闭当前", "close_current", shortcut="Ctrl+W", icon="mdi6.close"),
    ActionSpec("file.rename", "重命名…", "rename_dialog", icon="mdi6.rename-box"),
    ActionSpec("file.delete", "删除", "delete_dialog", icon="mdi6.delete-outline"),

    # 运行
    ActionSpec("run.case", "运行用例", "run_current_case", shortcut="F5", icon="mdi6.play",
               tip="运行当前编辑器中的完整用例（F5）"),
    ActionSpec("run.selected", "运行当前步骤", "run_selected_step",
               shortcut="F6", icon="mdi6.play-box-outline",
               tip="只执行编辑器中选中的一步（含其子步骤/循环体），不跑整用例（F6）"),
    ActionSpec("run.suite", "运行测试套", "run_suite", icon="mdi6.playlist-play",
               tip="运行工程内全部用例（忽略勾选）"),
    ActionSpec("run.checked", "批量运行已勾选", "run_checked_from_menu",
               icon="mdi6.play-circle-outline",
               tip="只运行工程树中已勾选的用例"),
    ActionSpec("run.testplan", "运行测试计划", "run_current_testplan",
               icon="mdi6.clipboard-play-outline",
               tip="运行当前打开或工程树选中的测试计划（含失败重试次数）"),
    ActionSpec("run.pause", "暂停", "toggle_pause_run", icon="mdi6.pause",
               checkable=True, tip="暂停/继续用例执行（需先运行用例；当前步骤完成后挂起）"),
    ActionSpec("run.stop", "停止", "stop_run", icon="mdi6.stop",
               tip="停止正在运行的用例（需先运行用例）"),
    ActionSpec("run.schedule", "计划执行", "schedule_dialog", icon="mdi6.clock-outline"),

    # 设备（菜单只挂「枢纽 + 安装包」；连接检视/看信息/装 IPA 收进已连接设备弹出菜单，避免顶层重复）
    ActionSpec("device.list", "已连接设备…", "show_connected_devices",
               icon="mdi6.cellphone-link", scope="global",
               tip="已连接真机列表：设为检视目标、查看信息、开始实时镜像"),
    ActionSpec("device.pkg_info", "查看安装包信息…", "show_package_info",
               icon="mdi6.information-outline",
               tip="解析本地 .apk / .ipa 元信息（不依赖已连接设备）"),
    # 以下动作仍注册（枢纽菜单 / Chip / 测试调用），不进顶层「设备」菜单
    ActionSpec("device.connect", "连接检视设备…", "connect_inspector",
               icon="mdi6.connection", scope="global",
               tip="连接真机或浏览器，用于控件检视与镜像"),
    ActionSpec("device.info", "查看设备信息…", "show_device_info",
               icon="mdi6.cellphone-information"),
    ActionSpec("device.ios_install", "安装 iOS 应用(IPA)…", "install_ios_app",
               icon="mdi6.cellphone-arrow-down", scope="global"),

    # 视图（global：仅菜单快捷键，不进工具栏）
    ActionSpec("view.focus_project", "聚焦工程", "_focus_project_view",
               shortcut="Ctrl+Shift+E", icon="mdi6.folder-outline", scope="global",
               tip="切换到工程视图"),
    ActionSpec("search.find_references", "查找引用", "find_references_action",
               shortcut="Shift+F12", icon="mdi6.file-find-outline", scope="global",
               tip="查找当前选中关键字/对象/步骤的引用（Shift+F12）"),

    # 编辑（editor 作用域：转发给当前用例/套件编辑器）
    ActionSpec("edit.undo", "撤销", "_edit_op", scope="editor", shortcut="Ctrl+Z", args=("undo",), icon="mdi6.undo"),
    ActionSpec("edit.redo", "重做", "_edit_op", scope="editor", shortcut="Ctrl+Y", args=("redo",), icon="mdi6.redo"),
    ActionSpec("edit.copy", "复制步骤", "_edit_op", scope="editor", shortcut="Ctrl+C", args=("copy_selected",), icon="mdi6.content-copy"),
    ActionSpec("edit.cut", "剪切步骤", "_edit_op", scope="editor", shortcut="Ctrl+X", args=("cut_selected",), icon="mdi6.content-cut"),
    ActionSpec("edit.paste", "粘贴步骤", "_edit_op", scope="editor", shortcut="Ctrl+V", args=("paste",), icon="mdi6.content-paste"),
    ActionSpec("edit.remove", "删除步骤", "_step_editor_op", scope="editor", args=("remove_selected",), icon="mdi6.trash-can-outline"),
    ActionSpec("edit.up", "上移", "_step_editor_op", scope="editor", args=("move_selected", -1), icon="mdi6.arrow-up-bold"),
    ActionSpec("edit.down", "下移", "_step_editor_op", scope="editor", args=("move_selected", 1), icon="mdi6.arrow-down-bold"),
    ActionSpec("edit.ins_if", "插入 if", "insert_control", scope="editor", args=("exec_control_if_end",), icon="mdi6.code-braces"),
    ActionSpec("edit.ins_ifelse", "插入 if-else", "insert_control", scope="editor", args=("exec_control_if_else_end",), icon="mdi6.source-branch"),
    ActionSpec("edit.ins_loop", "插入循环", "insert_loop", scope="editor", args=("keyword",), icon="mdi6.sync"),
    ActionSpec("edit.ins_mloop", "插入移动循环", "insert_loop", scope="editor", args=("mobile",), icon="mdi6.cellphone-cog"),

    # 管理台：会话 + 投递 + 打开 Web（运维观察不在 IDE）
    ActionSpec("mgmt.connect", "连接设置…", "mgmt_connect_settings",
               icon="mdi6.cloud-cog-outline",
               tip="服务器、账号、默认项目空间"),
    ActionSpec("mgmt.logout", "退出登录", "mgmt_logout",
               icon="mdi6.logout",
               tip="退出后须重新登录才能继续使用 IDE"),
    ActionSpec("mgmt.runner_start", "启动本机 Runner", "mgmt_start_local_runner",
               icon="mdi6.play-network-outline",
               tip="把本机 USB 设备心跳上报到管理台 TR 池（需已配置服务器与 API Token）"),
    ActionSpec("mgmt.runner_stop", "停止本机 Runner", "mgmt_stop_local_runner",
               icon="mdi6.stop-circle-outline",
               tip="停止 IDE 拉起的本机 TestRunner Agent"),
    ActionSpec("mgmt.upload", "上传工程制品", "mgmt_upload_project",
               icon="mdi6.cloud-upload-outline",
               tip="打包当前工程上传（自动确保项目空间）"),
    ActionSpec("mgmt.upload_app", "上传应用资源…", "mgmt_upload_app_build",
               icon="mdi6.cellphone-arrow-down",
               tip="上传 apk/ipa 到管理台应用资源库（与工程制品分离）"),
    ActionSpec("mgmt.submit", "提交远程批跑…", "mgmt_submit_remote_job",
               icon="mdi6.cloud-sync-outline",
               tip="创建管理台批跑任务"),
    ActionSpec("mgmt.enqueue_approved", "（高级）已通过逻辑用例一键入队…",
               "mgmt_enqueue_approved_cases",
               icon="mdi6.playlist-check",
               tip="高级：打包工程并为已审核通过的设计用例创建批跑任务"),
    ActionSpec("mgmt.import_logical", "（高级）导入意图用例…", "mgmt_import_logical_cases",
               icon="mdi6.file-download-outline",
               tip="高级：从管理台拉取已审核通过的意图用例草稿"),
    ActionSpec("mgmt.review_failed_intents", "（高级）审阅失败意图…", "mgmt_review_failed_intents",
               icon="mdi6.alert-circle-outline",
               tip="查看最近一次运行中定位失败的意图步骤"),
    ActionSpec("mgmt.solidify_stable", "（高级）固化稳定意图步…", "mgmt_solidify_stable_intents",
               icon="mdi6.hammer-screwdriver",
               tip="把多次稳定成功的意图步骤固化成普通关键字"),
    ActionSpec("authoring.ai_assist", "AI 辅助编写…", "authoring_ai_assist",
               icon="mdi6.robot-outline",
               tip="用一句话描述操作，自动在设备上试出可运行的用例"),
    ActionSpec("mgmt.open", "打开管理台", "mgmt_open_web",
               icon="mdi6.open-in-new",
               tip="浏览器打开管理台（已登录可免二次登录）"),
)

ACTIONS_BY_ID = {a.id: a for a in ACTIONS}


def action_allowed_for_role(spec: ActionSpec, user_role: str | None) -> bool:
    from .mgmt_role import action_allowed_for_role as _allow

    return _allow(spec, user_role)

# ---- 菜单栏结构：(菜单标题, [行]); 行 = action id | None(分隔) | ("submenu", 标题, [ids]) ----
_SEP = None
MENUS: tuple = (
    ("文件(&F)", [
        "file.new_project", "file.open_project", "file.open_file", _SEP,
        ("submenu", "新建", ["file.new_case", "file.new_suite", "file.new_map",
                            "file.new_dataconfig", "file.new_testplan",
                            "file.new_keyword", "file.new_folder"]),
        _SEP, "file.save", "file.save_as", "file.close",
        _SEP, "file.rename", "file.delete",
    ]),
    ("编辑(&E)", [
        "edit.undo", "edit.redo", _SEP,
        "edit.copy", "edit.cut", "edit.paste", _SEP,
        "edit.remove", "edit.up", "edit.down", _SEP,
        "search.find_references", _SEP,
        ("submenu", "插入控制流", ["edit.ins_if", "edit.ins_ifelse",
                                "edit.ins_loop", "edit.ins_mloop"]),
    ]),
    ("运行(&R)", [
        "run.case", "run.selected", _SEP,
        "run.checked", "run.suite", "run.testplan", _SEP,
        "run.pause", "run.stop", _SEP, "run.schedule",
        # 失败策略子菜单在主窗口里特殊处理（可勾选项）
    ]),
    ("设备(&D)", [
        "device.list", _SEP, "device.pkg_info",
    ]),
    ("管理台(&M)", [
        "mgmt.connect", "mgmt.logout", _SEP,
        "mgmt.runner_start", "mgmt.runner_stop", _SEP,
        "mgmt.upload", "mgmt.upload_app", "mgmt.submit", _SEP,
        ("submenu", "高级（意图兼容）", [
            "mgmt.enqueue_approved", "mgmt.import_logical",
            "mgmt.review_failed_intents", "mgmt.solidify_stable",
        ]),
        _SEP, "mgmt.open",
    ]),
    ("AI(&A)", [
        "authoring.ai_assist",
    ]),
    # 视图(&V) 菜单在主窗口动态生成（dock 显隐 + 重置布局）
    # 帮助(&H) 菜单在主窗口生成（关于/文档）
)

# ---- 全局工具栏：已收敛到工程区（保存/批量运行）与编辑器标签栏（F5/暂停/停止）----
TOOLBAR_GROUPS: tuple = ()

# ---- 编辑器右键菜单：分组（组间分隔）----
EDITOR_CONTEXT_GROUPS: tuple = (
    ["edit.remove", "edit.up", "edit.down"],
    ["edit.ins_if", "edit.ins_ifelse", "edit.ins_loop", "edit.ins_mloop"],
    ["edit.copy", "edit.cut", "edit.paste"],
)


def label(spec: ActionSpec) -> str:
    """动作显示文案（图标走 QIcon，不再混入 emoji 前缀）。"""
    return spec.text


# qtawesome 缺失时优雅降级：无图标但功能不受影响（可选依赖组 icons，见 pyproject.toml；pip install qtawesome）
try:
    # noinspection PyPackageRequirements
    import qtawesome as _qta  # type: ignore[import-untyped]
except ImportError:
    _qta = None


def qicon(name: str, color: str = ""):
    """按 qtawesome 名取 QIcon（统一 Material Design Icons）；color 可指定颜色；不可用返回 None。"""
    if not name or _qta is None:
        return None
    # noinspection PyBroadException
    try:
        return _qta.icon(name, color=color) if color else _qta.icon(name)
    except Exception:
        return None
