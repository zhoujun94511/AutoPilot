# RBAC 能力矩阵（UI / API 映射）

> **版本**：1.4（2026-08-20）  
> **适用**：AutoPilot IDE + Autopilot-Platform Web/API  
> **边界真源**（谁能看见什么）：Platform `docs/architecture/RBAC_BOUNDARY_CONTRACT.md`  
> **本文职责**：能力 ID、API、Web/IDE 控件映射。与边界契约冲突时改本文。

---

## 1. 角色（Role Catalog）

| role_id | 显示名 | 判定 |
|---------|--------|------|
| `platform_admin` | 平台管理员 | `User.role = admin` |
| `org_admin` | 组织管理员 | 当前 org 的 `owner` / `admin` |
| `project_member` | 项目成员 | 项目 `owner` / `member` |
| `project_viewer` | 项目只读 | 项目 `viewer` |
| `runner_agent` | Runner 进程 | `X-API-Token`（独立或全局） |

**层级**：平台 admin ⊃ 组织 admin（仅本 org）⊃ 项目成员 ⊃ 只读成员。  
**不混用**：组织 admin **不等于** 平台 admin（不可看全局 AI 预算、不可 purge/reclaim/发 Token）。

---

## 2. 能力 ID（Capability）

| ID | 说明 |
|----|------|
| `cap.jobs.create` | 创建/提交批跑 |
| `cap.jobs.cancel` | 取消任务 |
| `cap.jobs.retry` | 重试任务 |
| `cap.artifacts.upload` | 上传工程制品 |
| `cap.artifacts.purge` | 制品超期清理 |
| `cap.app_builds.upload` | 上传应用资源 |
| `cap.app_builds.purge` | 应用资源清理 |
| `cap.reports.view` | 查看 HTML/result |
| `cap.devices.view` | 查看 TR 设备看板（只读） |
| `cap.devices.release` | 强制释放设备占用 |
| `cap.runners.view` | 查看 Runner 列表/心跳（只读） |
| `cap.runners.issue_token` | 签发 Runner Token |
| `cap.runners.deregister` | 注销 Runner |
| `cap.runners.reclaim` | 回收僵死任务 |
| `cap.runners.managed` | 本机托管 Runner（Platform 同机） |
| `cap.share.read` | 查看共享 ACL |
| `cap.share.write` | 创建/撤销 ACL |
| `cap.ops.config` | 运维配置中心读写 |
| `cap.ops.view_budget` | 全局 AI Token 预算/用量 |
| `cap.ops.ai.codegen` | 链路 3 IDE 经平台 LLM 网关（持钥转发） |
| `cap.audit.view` | 审计日志（org 范围或全平台） |
| `cap.users.manage` | 用户账号管理 |
| `cap.design.edit` | 设计域写操作 |
| `cap.ide.runner.start_scoped` | IDE 自动签发 scoped Runner Token |

---

## 3. 能力矩阵

| capability | platform_admin | org_admin | project_member (operator) | project_viewer | 主要 API |
|------------|:--------------:|:---------:|:-------------------------:|:--------------:|----------|
| cap.jobs.* | ✅ | ✅ | ✅ | ❌ | `/jobs*` |
| cap.artifacts.upload | ✅ | ✅ | ✅ | ❌ | POST `/artifacts` |
| cap.artifacts.purge | ✅ | ❌ | ❌ | ❌ | POST purge |
| cap.app_builds.upload | ✅ | ✅ | ✅ | ❌ | POST `/app-builds` |
| cap.app_builds.purge | ✅ | ❌ | ❌ | ❌ | POST purge |
| cap.reports.view | ✅ | ✅ | ✅ | ✅ | `/reports*`, `/jobs/{id}/report` |
| cap.devices.view | ✅ | ✅ | ✅ | ✅ | GET `/devices`, `/devices/board` |
| cap.devices.release | ✅ | ❌ | ❌ | ❌ | release 类 |
| cap.runners.view | ✅ | ✅ | ✅ | ✅ | GET `/runners` |
| cap.runners.issue_token | ✅ | ❌ | ❌ | ❌ | POST token |
| cap.runners.deregister | ✅ | ❌ | ❌ | ❌ | DELETE runner |
| cap.runners.reclaim | ✅ | ❌ | ❌ | ❌ | POST reclaim |
| cap.runners.managed | ✅ | ❌ | ❌ | ❌ | `/runners/managed` |
| cap.share.read | ✅ | ✅ | ✅ | ✅ | GET `/acl` |
| cap.share.write | ✅ | ✅ | ✅† | ❌ | POST/DELETE `/acl` |
| cap.ops.config | ✅ | ❌ | ❌ | ❌ | `/ops/config*` |
| cap.ops.view_budget | ✅ | ❌ | ❌ | ❌ | tokens in stats/agentops |
| cap.ops.ai.codegen | ✅ | ✅ | ✅ | ✅ | POST `/ops/ai/codegen`（已登录；Key 仅服务端） |
| cap.audit.view | ✅ | ✅‡ | ❌ | ❌ | GET `/audit` |
| cap.users.manage | ✅ | ✅‡ | ❌ | ❌ | `/auth/users*` |
| cap.design.edit | ✅ | ✅ | ✅ | ❌ | `/design/*` 写 |
| cap.ide.runner.start_scoped | ✅ | ❌ | ❌ | — | POST scoped-token |

† 需项目写权限（member+）。  
‡ org 范围内，非全平台。

---

## 4. UI 映射（Web）

| capability | 导航/组件 | operator | org_admin | platform_admin |
|------------|-----------|----------|-----------|----------------|
| cap.devices.view | 设备与执行 | ✅ 只读 | ✅ | ✅ |
| cap.runners.view | 执行节点列表 | ✅ 只读 | ✅ | ✅ + 管理 |
| cap.runners.issue_token | 授权令牌按钮 | 隐藏 | 隐藏 | 显示 |
| cap.ops.view_budget | Dashboard/设计域 Token 卡 | 隐藏 | 隐藏 | 显示 |
| cap.ops.config | 运维侧栏 | 隐藏 | 隐藏 | 显示 |
| cap.share.read | 共享侧栏 + ACL 列表 | ✅ | ✅ | ✅ |
| cap.share.write | 建立/撤销 ACL | ❌‡ | ✅† | ✅ |
| 批跑服务态 | Dashboard 概览 | 「可用/不可用」 | 在线数+离线详情 | 同左 |

‡ 项目 viewer 仅可查看列表（`SharePanel` 只读提示）。

### 4.1 前端 `useCapabilities` 映射（Web 真源）

> 实现：`Autopilot-Platform/.../composables/useCapabilities.ts`  
> **禁止**在组件内直接使用 `store.isPlatformAdmin` / 已移除的 `store.canEditProject` 等；一律走下表 composable。

| composable | 能力 ID / 语义 | 判定摘要 |
|------------|----------------|----------|
| `canOps` | `cap.ops.*`（config/budget/purge/reclaim/token） | `User.role === admin` |
| `canManageOrg` | `cap.users.manage` / `cap.audit.view`（本 org） | 当前 org `owner`/`admin` 或平台 admin |
| `canCreateOrg` | 创建组织（Platform POST `/orgs`） | 仅平台 admin |
| `canManageAnyOrg` | 组织设置入口（至少管一个 org） | 平台 admin 或任一 org `owner`/`admin` |
| `canManageCurrentOrg` | 当前顶栏 org 改策略 / 加任意角色成员 | 平台 admin，或当前选中组织的 `owner`/`admin` |
| `canCreateProject` | 当前组织下新建项目 | 平台 admin / 当前 org owner·admin / 组织策略 `members_can_create_projects` 打开的 member |
| `canInviteOrgMember` | 邀请同事进当前组织 | `canManageCurrentOrg`，或组织策略 `members_can_invite` 打开的 member（只能邀 member） |
| `canViewCluster` | `cap.devices.view` + `cap.runners.view` | 已登录 |
| `canManageInfra` | 离线 Runner 详情 / 托管入口 | 平台 admin 或 org admin |
| `canManageRunners` | `cap.runners.issue_token` 等写操作 | 仅平台 admin |
| `canViewOpsBudget` | `cap.ops.view_budget` | 仅平台 admin |
| `canShareRead` | `cap.share.read` | 已登录 |
| `canShareWrite` | `cap.share.write` | 平台 admin 或 `canEditProject` |
| `canViewProject` | 设计域/任务读 | 项目 `owner`/`member`/`viewer`、本组织 owner/admin、或平台 admin |
| `canEditProject` | `cap.design.edit` + 任务提交等 | 项目 `owner`/`member`、本组织 owner/admin、或平台 admin |
| `canManageProject` | 项目成员/邀请 | 项目 `owner`、本组织 owner/admin、或平台 admin |
| `isProjectViewer` | 只读横幅 / 禁用写控件 | 项目 `viewer`（非平台 admin、非本组织 owner/admin） |
| `currentProjectRole` | — | API `ProjectOut.my_role`；平台 admin 与本组织 owner/admin 视同 `owner` |
| `currentOrgRole` | — | API `OrganizationOut.my_role` |

**组件覆盖**（阶段 M–N）：`ProjectsPanel`、`OrgSettingsSection`、`ProjectList`、`Design*Panel`、`JobCreatePanel`、`SharePanel`、`ProjectReadonlyBanner` 等均已迁入。

---

## 5. IDE 映射

| capability | 菜单/对话框 | platform_admin | operator |
|------------|-------------|:--------------:|:--------:|
| cap.ide.runner.start_scoped | 启动本机 Runner | 自动签发 **组织** scope Token（`project_ids` 可空） | **禁用自签**；使用连接设置中预配 Token（管理员签发） |
| Runner Token 字段 | 连接设置 | 可编辑（可选；可自签） | 可填预配 Token；对话框引导 + 无 Token 保存确认 |
| 管理台菜单 | `ActionSpec.min_role` | 全部可见（预留 admin 项） | 全部可见；登录后 `_mgmt_apply_action_roles` |
| 连接设置默认项目 | 连接对话框 | **可选**；空项目仍可保存/登录 | 同左；上传/回写仍 `require_cached_project_id` |
| 上传/批跑/导入 | 管理台菜单 | ✅ 须已绑项目；首次/变更时确认并记住「本地工程 → Platform 项目」 | 同左 |
| cap.ops.ai.codegen / 闲聊 | AI 辅助编写、Web 闲聊 | ✅ 已登录即可（无项目走合成计费桶） | 同左；RAG/落库/审核仍要项目写 |

---

## 6. API 响应契约

| 端点 | platform_admin | 其他已登录用户 |
|------|----------------|----------------|
| `GET /design/stats` | 含 `tokens`（含 budget） | **无 `tokens` 字段** |
| `GET /ops/agentops` | 含 `tokens` | **无 `tokens` 字段**（保留 `trace`） |
| `GET /ops/summary` | 403 以外用户 | 403 |
| `POST /runners/{id}/scoped-token` | 200（平台 admin） | **403** |

---

## 7. 验收账号（手工矩阵）

| 账号 | 角色 | 必测 |
|------|------|------|
| A | platform_admin | 运维/Token/purge/预算可见 |
| B | org_admin | 审计/用户（本 org）；无全局预算 |
| C | operator | 批跑+设备/Runner 只读；403 token；Dashboard 无预算 |

---

## 8. 变更流程

1. 改能力矩阵 → 更新本文件版本号  
2. 同步 `feature-modules.md` §3.5 摘要  
3. 后端 API + 前端 `useCapabilities` + IDE 菜单  
4. 跑 `tests/test_rbac_caps.py` + `tests/test_rbac_whitebox_chain.py` + `tools/rbac_web_e2e.py` + `tests/test_frontend_persona_capabilities.py`
