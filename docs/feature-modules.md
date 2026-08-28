# AutoPilot 功能模块清单

本文档列出 **桌面 IDE** 与 **AutoPilot Platform 管理台（Web）** 的用户可见功能，便于对照职责与入口。  
依据源码整理；**未落地的能力不写入**。产品总览见双仓 README。

相关文档：

- IDE ↔ Platform 边界：[managementconsole.md](managementconsole.md)
- 双仓契约：[architecture/DUAL_REPO_CONTRACT.md](architecture/DUAL_REPO_CONTRACT.md)
- IDE 界面约定：[ui-design.md](ui-design.md)
- 配置入口：[SETUP.md](SETUP.md)
- Platform 导航真源：`Autopilot-Platform/autopilot_platform/frontend/src/router/tabs.ts`

---

## 1. 产品边界（先读）

| 形态 | 名称 | 角色 |
|------|------|------|
| 桌面 | AutoPilot IDE（本仓 `autopilot/`） | 用例编辑、Inspector/本机镜像、Binding 真源、本地执行；向 Platform **投递**制品与远程批跑 |
| Web | AutoPilot 管理台（`Autopilot-Platform` / `frontend/`） | 设计域、权限、TR 池、批跑、报告、计划、轻量远控；**不是** Web IDE |
| 平台 | Platform（`autopilot_platform/platform`） | 唯一 HTTP API / JWT / 数据存储 |
| 执行节点 | TestRunner（Platform `runner/` 或 IDE `autopilot.runner`） | 注册、心跳、claim、调用执行核 |

```
IDE (本机编辑/本地池)  --JWT-->  Platform  <--JWT--  Web 管理台
                                 ^
                                 | Runner Token
                              TestRunner (TR 池)
```

三链路：① 传统自动化（IDE 编排 + Platform Job）默认可交付；② 设计 AI 在 Platform（APPROVED ≠ 可云端跑）；③ AI 辅助编写在 IDE（厂商 Key 只在 Platform）。

| 能力 | IDE | Web 管理台 |
|------|-----|------------|
| 打开/编辑用例、对象库、套件 | 是 | 否 |
| 本机设备运行（本地池） | 是 | 否 |
| 控件检视 / 本机实时镜像 | 是 | 否 |
| 需求/意图用例/知识库 | 导入已审核（高级） | 是（设计域主责） |
| 上传工程制品 / 应用资源 | 是 | 是 |
| 提交远程批跑 | 是 | 是 |
| TR 设备池观察 / 强制释放 / 远控 | 否（仅可启停本机 Runner） | 是 |
| 任务日志 / 报告对比 / 计划 / ACL / 运维 | 否（打开浏览器） | 是 |
| 用户 / 审计 | 否 | 是（按人设） |

---

## 2. 桌面 IDE 功能模块

动作与菜单单一事实源：`autopilot/ui/actions.py`；主窗口：`autopilot/ui/main_window/`。

### 2.1 壳层分区

| 区域 | 模块内容 | 主要路径 |
|------|----------|----------|
| 左侧栏 | 工程树、筛选、工程工具条 | `widgets/left_sidebar.py`、`project_panel.py` |
| 中央 | 欢迎页、多文档编辑器、标签栏运行按钮 | `main_window/window.py`、`chrome/editor_run_toolbar.py` |
| 右侧辅区 | 关键字库、参数；控件检视器、实时镜像 | `widgets/auxiliary_region.py` |
| 底栏 Dock | 执行控制台；查找引用结果 | `widgets/console.py`、`search_results_panel.py` |
| 状态栏 | 失败策略、iOS 后端、设备 Chip、Platform 会话、本机 Runner | `chrome/status_bar_chrome.py` |

### 2.2 菜单模块

| 菜单 | 模块职责 | 典型入口 |
|------|----------|----------|
| 文件 | 工程与资源生命周期 | 菜单；工程工具条 |
| 编辑 | 步骤编辑、控制流、查找引用 | 菜单；编辑器右键 |
| 运行 | 本机执行、暂停停止、本机计划调度 | 菜单；标签栏 F5/F6 |
| 设备 | 本地设备池、安装包信息；检视/镜像在枢纽内 | 菜单；状态栏 Chip |
| 管理台 | 连接、启停本机 Runner、上传制品/应用、提交远程批跑、打开 Web；高级：意图入队/导入/审阅 | 菜单；启动登录门禁 |
| AI | 采页辅助编写传统关键字步骤 | 菜单 |
| 视图 | Dock、主题、布局 | 菜单 |
| 帮助 | 日志目录、Monkey 报告、关于 | 菜单 |

无独立「工具」顶栏菜单。日常使用需登录 Platform（测试：`AUTOPILOT_SKIP_LOGIN=1`）。

### 2.3 按用户心智划分的功能模块

| 模块 | 职责摘要 | 关键入口 | 代码锚点 |
|------|----------|----------|----------|
| 工程与资源管理 | 工作区、用例/套件/计划/对象库/数据/自定义关键字 | 文件菜单；工程树 | `main_window/files.py` |
| 用例与步骤编辑 | 步骤表、控制流、参数、数据驱动 | 中央编辑器 | `case_editor.py`、`param_form.py` |
| 关键字库 | 分类浏览、平台灰显、自定义关键字 | 右侧「关键字库」 | `keyword_panel.py`、`metadata/keyword_defs/` |
| Intent / Binding | `intent_act`；工程 `bindings/*.json` | 步骤；管理台高级导入 | `intent/`、`mgmt/` |
| AI 辅助编写 | 采页 → Platform 网关 → `.tc` | AI 菜单 | `authoring/`、`ai_authoring_dialog.py` |
| 查找引用 | 关键字/对象/步骤检索 | Shift+F12 | `search_results_panel.py` |
| 本地执行 | 本机跑批、失败策略、多机并行、HTML 报告 | 运行菜单 | `main_window/run.py`、`engine/` |
| 设备检视与镜像 | 控件树、定位符、本机 scrcpy/AVF/MJPEG | 设备菜单；右侧面板 | `inspector_panel.py`、`mirror_panel.py` |
| 管理台集成 | JWT、项目空间、制品/应用资源、远程 Job、本机 Runner | 管理台菜单 | `main_window/mgmt*.py`、`autopilot/mgmt/` |
| 主题与布局 | 浅色/暗色；Dock 持久化 | 视图菜单 | `ui/theme/` |

### 2.4 本地设备池 vs 远程批跑

| 对照项 | 本地设备池（IDE） | TR 池（远程批跑） |
|--------|-------------------|-------------------|
| 设备来源 | IDE 本机枚举（adb / iOS） | Runner 心跳上报到 Platform |
| 用户所见 | 「已连接设备」、状态栏 Chip | Web「设备」；提交批跑时勾选 TR 设备 |
| 进池条件 | 插线授权即可 | CLI 或 IDE「启动本机 Runner」 |
| 执行入口 | 运行菜单 / F5·F6 / 批量运行 | 「提交远程批跑…」或 Web「批跑」 |
| 任务观察 | IDE 控制台与本机报告 | **仅 Web**（队列、日志、报告） |
| 安装包 | 本机路径或工程内文件 | **应用资源库**钉死版本；工程 zip **不含** apk/ipa |

### 2.5 关键字库顶层分类（IDE 可见）

| 分类 | 定义 | 说明 |
|------|------|------|
| WebUI | `webui.xml` | 浏览器与页面；可选 Playwright |
| Http | `http.xml` | HTTP/JSON/XML 等 |
| Public | `public.xml` | 公用、数据与执行控制 |
| Mobile | `mobile.xml` | 移动端设备与控件 |
| Intent | `intent.xml` | `intent_act` |
| 自定义 | 工程内 `.ks` | 工程自定义关键字 |

---

## 3. AutoPilot 管理台（Web）功能模块

前端壳：`Autopilot-Platform/autopilot_platform/frontend/src/App.vue`；路由：`router/tabs.ts`。

### 3.1 侧栏信息架构

| 分区 | 导航项 | 说明 |
|------|--------|------|
| 概览 | 概览、项目、共享 | 项目=空间成员；共享=同组织资源 ACL |
| 测试设计 | 设计总览、需求文档、意图用例、知识库 | 链路 2；APPROVED ≠ 可执行制品 |
| 测试与执行 | 工程制品、应用资源、批跑、计划、报告 | 制品与安装包分离 |
| 设备与执行 | 设备 | 同页含 Runner、资源池、远控入口 |
| 系统管理 | 运维配置中心、审计、用户 | 按人设显示 |

### 3.2 三域拆分（勿混用）

| 域 | UI 名称 | 职责 | 主 API | 存储 |
|----|---------|------|--------|------|
| artifacts | 工程制品 | 用例/配置 zip（**不含** apk/ipa） | `/api/v1/artifacts*` | `MC_ARTIFACTS_DIR` |
| app-builds | 应用资源 | apk / xapk / ipa 版本库（sha256 去重） | `/api/v1/app-builds*` | `MC_APP_BUILDS_DIR` |
| jobs | 批跑 | 制品 + 可选应用版本 + 设备 → 报告 | `/api/v1/jobs*`、`/reports*` | DB + Runner 工作目录 |

编排：选工程制品 → 选应用资源版本（可选）→ 勾选 TR 设备 → 提交。Web/Http Job 无移动设备。

### 3.3 Web 功能模块一览

| 模块（UI） | 职责摘要 | 前端组件 | 主 API | 权限要点 |
|------------|----------|----------|--------|----------|
| 登录 | JWT / 可选 OIDC·SAML | `LoginView.vue` | `/auth/login`、`/auth/me` | 未登录仅登录页 |
| 概览 | 指标、近期批跑、失败趋势 | `DashboardPanel.vue` | `/ops/summary` 等 | 全体 |
| 项目 | 组织下项目空间与成员 | `ProjectsPanel.vue` | `/projects*`、`/orgs*` | 全体 |
| 共享（ACL） | 制品/应用/任务/计划分享 | `SharePanel.vue` | `/acl` | 同组织 |
| 设计域 | 文档、意图用例、知识、入队 | `design/*` | `/design/*`、enqueue-job | 全体（写看项目角色） |
| 工程制品 | 上传列表删除；超期清理 | `ArtifactsPanel.vue` | `/artifacts*` | purge：admin |
| 应用资源 | 安装包版本；去重；清理 | `AppBuildsPanel.vue` | `/app-builds*` | purge：admin |
| 批跑 | 编排 + 队列取消重试日志 | `JobCreatePanel.vue`、`JobsPanel.vue` | `/jobs*` | 全体 |
| 计划 | delay/interval | `SchedulesPanel.vue` | `/schedules*` | 全体 |
| 报告 | 归档筛选、双报告对比 | `ReportsPanel.vue` | `/reports*` | 全体 |
| 设备 | TR 占用看板、释放、远控 | `DevicesHub` / remote/* | `/devices*`、远控会话 | 释放：admin |
| 执行节点 | Runner、Token、僵死回收 | `RunnersPanel.vue` | `/runners*`；`/jobs/reclaim` | Token/reclaim：admin |
| 运维 | 运行时配置、告警、AI 网关 | `OpsPanel.vue` | `/ops/*` | 平台 admin |
| 审计 / 用户 | 操作审计、账号 | `AuditPanel.vue`、`UsersPanel.vue` | `/audit`、`/auth/users*` | 平台或组织管理员 |

远控：Android scrcpy→WebRTC；iOS WDA MJPEG。**不是** IDE 本机镜像，也不是 QVH/QuickTime。

### 3.4 TestRunner（非 Web 页）

| 模块 | 职责 | 入口 |
|------|------|------|
| TestRunner Agent | 注册；心跳上报 TR 池；claim/执行/回传 | `python -m autopilot_platform.runner` 或 IDE「启动本机 Runner」 |

| 项 | 说明 |
|----|------|
| 设备元数据 | name/model/os_version、健康态 `ready\|unauthorized\|error\|offline` |
| 后端矩阵 | `android-appium` / `ios-appium` / `ios-wda` |
| 调度门禁 | claim 要求 ready、未占用，且 `backend_mode` 与 backends 有交集 |
| 联调 | `python -m autopilot_platform.runner --dry-probe` |

无 Runner 时 Web「设备」无 TR 数据。步骤见 Platform `docs/setup/managementconsole.md`。

### 3.5 人设摘要

真源：Platform `docs/architecture/RBAC_BOUNDARY_CONTRACT.md`；能力 ID：[rbac-capability-matrix.md](rbac-capability-matrix.md)。

| 角色 | 可见/可做 |
|------|-----------|
| operator | 概览、项目/共享、设计、制品、应用、批跑、计划、报告、设备只读；无平台运维/Token 签发 |
| org admin | operator + 本组织成员/审计/共享；仍无平台运维与全局预算 |
| platform admin | 上述 + 运维/审计/用户；purge；设备释放；Runner Token；reclaim |

---

## 4. 跨端能力对照速查

| 业务场景 | IDE | Web |
|----------|-----|-----|
| 写用例 / 调关键字 | 主战场 | 无 |
| 本机插线调试 | 本地池 + 运行菜单 | 无 |
| 设计意图用例 / 人审 | 高级导入已审核 | 设计域主责 |
| 把工程交给集群跑 | 上传制品 + 提交远程批跑 | 批跑页编排 |
| 版本化安装包 | 上传应用资源 | 应用资源页 |
| 看设备是否进池 | 启停本机 Runner | 设备页 |
| 远控真机 | 无（仅本机镜像） | 设备远控 |
| 看批跑进度与报告 | 打开管理台 | 批跑 / 报告 |
| 定时回归 | 仅本机「计划执行」 | 平台 schedules |
| 用户权限与审计 | 无 | 用户 / 审计 |

---

## 5. 修订说明

- 审计范围：本仓 `autopilot/ui`、`autopilot/mgmt`；Platform `frontend`、`platform`、`runner`。
- 菜单以 `actions.py` 为准；Web 侧栏以 `tabs.ts` 为准。
- 旧路径 `AutoPilot_Console` / `managementconsole.*` 已废弃。
