# 管理台与客户端边界

运行时 **只通过 HTTP `/api/v1`**。Platform 不 import IDE；两边 Runner 各维护一份、协议对齐。

| 角色 | 仓库 | 说明 |
|------|------|------|
| **服务端** | [Autopilot-Platform](../../Autopilot-Platform/README.md) | FastAPI Platform + Vue 管理台 + `autopilot_platform.runner` |
| **客户端** | 本仓 AutoPilot | IDE + 默认 `python -m autopilot.runner` |

旧仓名 `AutoPilot_Console` 仅为迁移来源，不再作为部署真源。

| 文档 | 位置 |
|------|------|
| 架构 / API | Platform `docs/managementconsole.md` |
| 联调操作 | Platform `docs/setup/managementconsole.md` |
| 仓边界 | Platform `docs/managementconsole-split.md` |
| IDE HTTP 对接 | Platform `docs/architecture/IDE_INTEGRATION.md` |
| 双仓契约 | [architecture/DUAL_REPO_CONTRACT.md](architecture/DUAL_REPO_CONTRACT.md) |

本仓：

- HTTP 投递：`autopilot/mgmt/`（制品、应用资源、Job、设计域导入）
- 本机 TestRunner：`autopilot/runner/`（IDE「启动本机 Runner」默认入口）
- 覆盖模块：环境变量 `MC_RUNNER_MODULE`（例如 `autopilot_platform.runner`，须已安装 Platform `[runner]`）
- 打包 zip **故意不含** apk/ipa；安装包走 Platform 应用资源库

登录门禁、设备池隔离、远程批跑步骤以 Platform 联调文档为准。测试/离屏可用 `AUTOPILOT_SKIP_LOGIN=1`。
