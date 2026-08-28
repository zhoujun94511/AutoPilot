# AutoPilot 当前状态与冻结项

阶段 0–13、15 已完成（IDE 编排、关键字、报告、WDA-direct 文档面）。下文只保留**仍开放**或**明确冻结**的项。详细产品边界见 [feature-modules.md](feature-modules.md)、[architecture/DUAL_REPO_CONTRACT.md](architecture/DUAL_REPO_CONTRACT.md)。

## 仍开放

| 项 | 说明 |
|----|------|
| 阶段 14 残留 | 中间件真服务连通性；iOS parity 用例层/定位符全量对齐（依赖 App UI） |
| HTTP 导入桥 | OpenAPI / Postman → `.tc.yaml` 脚本引擎与双向同步仍缓做，见 [architecture/API_TESTING_PLAN.md](architecture/API_TESTING_PLAN.md) |

## 设备云（B1 已收口，B2/B3 冻结）

**已交付：** CI 触发 Job、独立 Runner、claim 长轮询、设备租约/purge、Android/iOS 录屏关键字与报告播放、`AUTOPILOT_RUNNER_KEEP_APPIUM`。CI 用法见 [CI_TRIGGER.md](CI_TRIGGER.md)；无 GUI Runner 见 [setup/runner_headless.md](setup/runner_headless.md) 与 [architecture/ADR_runner_headless_install.md](architecture/ADR_runner_headless_install.md)。

**未书面解冻前不立项：** WebSocket claim、Runner 进程池/预热、`cloudDeviceId` 双 ID、浏览器远控产品化、Job 全程自动录像。

**明确不做：** 在 IDE 仓再做一套 Platform Agent；用日志 SSE 冒充 claim；整仓引入 Sonic/AGPL；Web 做成云真机控制台。

## 运营面（已交付，主仓在 Platform）

Runner 离线告警、Job 失败趋势、ACL 一键/审计前缀、设计域减壳。IDE 不重复实现 Ops / Dashboard。

## 不实现

SAP GUI / IBM MQ / WindQ 等无中性 Python 路径的占位已从关键字目录移除。图像识别与部分中间件按 extras 按需安装，缺失时降级。
