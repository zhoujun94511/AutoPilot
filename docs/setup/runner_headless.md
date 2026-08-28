# 无 GUI TestRunner 部署（交叉引用）

> **权威路径在 Platform 仓，不在本 IDE 仓。**

机房 / 无桌面节点请使用：

- 仓库：兄弟仓 `Autopilot-Platform`（或对应 clone）
- 安装：`pip install -e ".[runner]"`（**无 PyQt**）
- 启动：`python -m autopilot_platform.runner` 或 `ap-runner`
- 文档：兄弟仓 Autopilot-Platform 的 `docs/setup/managementconsole.md`（§0 最短路径、§ Runner）

执行核为仓内 `autopilot_platform/ap/` 切片（与 IDE `autopilot/` 契约同步，见 [DUAL_REPO_CONTRACT.md](../architecture/DUAL_REPO_CONTRACT.md)）。

机房多台设备机：每台只起 Runner 进程、`--server` 指向同一 Platform。同仓不是「每台都要起管理台」。安装面削瘦 / 独立 Runner 包是 Platform **预留工作项**（暂不改代码），见兄弟仓 `docs/managementconsole-split.md`。

## 本仓 `autopilot.runner` 何时用

仅当本机已装 AutoPilot **IDE 客户端**、想顺手起一个协议相同的 Runner 时：

```bash
python -m autopilot.runner --server http://127.0.0.1:8000 --token <token>
# 或 IDE「启动本机 Runner」
```

这不替代 Platform 的无 GUI Agent 交付；归属更正见 [ADR_runner_headless_install.md](../architecture/ADR_runner_headless_install.md)。

## CI 触发 Job

见 [CI_TRIGGER.md](../CI_TRIGGER.md)（B1-C）：CI 只创建任务，真机仍由上述 Runner claim。
