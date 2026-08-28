# ADR：无 GUI Runner 归属（更正 B1-A）

- 状态：Superseded / Clarified
- 日期：2026-08-11
- 关联：[ROADMAP.md](../ROADMAP.md)、[DUAL_REPO_CONTRACT.md](./DUAL_REPO_CONTRACT.md)

## 更正

Sonic Plan 原文把 B1-A（`ap/` 切片 + 无 PyQt 机房 Agent）写成待办，**归属错误**。

该能力已在 **Autopilot-Platform** 交付：

| 能力 | 位置 |
|------|------|
| 执行核切片（无 IDE UI） | `autopilot_platform/ap/` |
| Agent 入口 | `python -m autopilot_platform.runner` / `ap-runner` |
| 无 PyQt 安装 | `pip install -e ".[runner]"`（Platform `pyproject.toml`，dependencies 不含 PyQt6） |
| 操作文档 | Platform `docs/setup/managementconsole.md` §0 / §1 |

双仓契约亦写明：`ap/` 供 Runner 与无 Qt 主机使用（[DUAL_REPO_CONTRACT.md](./DUAL_REPO_CONTRACT.md) §1.3）。

## IDE 仓侧

- `python -m autopilot.runner` 是**协议对齐的镜像客户端**，方便同机装了 IDE 的开发者；主依赖仍含 PyQt，**不等于**机房 Agent 主路径。
- 不在 IDE 仓再立项「去掉 PyQt 瘦包」来重复 Platform 已做完的事。
- `docs/setup/runner_headless.md` 仅作交叉引用，指向 Platform 为权威部署说明。

## 决策

**B1-A 关闭。** 机房节点请装 Platform 仓并走 `autopilot_platform.runner`。
