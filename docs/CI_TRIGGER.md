# CI 触发 Platform 批跑（Sonic Plan B1-C）

> 用 API Token / JWT 创建 TR Job，由已注册 Runner claim 执行。  
> 不替代 Web 控制台；面向 GitHub Actions / Jenkins / 运维脚本。

## 前置

1. Platform 可访问，且已有 **运维 API Token** 或可登录用户（需 `cap` 能创建 Job）。
2. 已上传工程制品（`artifact_id`），或目标 Runner 本机有 `project_dir`。
3. 至少一台 Runner 在线（`python -m autopilot.runner`），移动端任务需挂载对应设备。

环境变量（常用）：

| 变量 | 含义 |
|------|------|
| `MC_SERVER` | Platform base URL |
| `MC_API_TOKEN` | `X-API-Token` |
| `MC_JWT` | 可选 Bearer |
| `MC_ORG_ID` | 多租户 org |
| `MC_USERNAME` / `MC_PASSWORD` | 无 Token 时登录换 JWT |

## 本地 / 脚本

```bash
# 干跑：只看 JSON
python -m autopilot.mgmt create-job \
  --artifact-id art_xxx \
  --platform ios \
  --device-udids <UDID> \
  --dry-run

# 提交并等待终态（成功 exit 0，失败 exit 1）
python -m autopilot.mgmt create-job \
  --server "$MC_SERVER" \
  --token "$MC_API_TOKEN" \
  --artifact-id art_xxx \
  --platform android \
  --device-udids "$UDID" \
  --name "ci-$(date +%Y%m%d)" \
  --wait

# 等价入口（IDE 仓）
python tools/trigger_platform_job.py --artifact-id art_xxx --platform web --wait

# 仅装 Platform 仓时（无需 IDE）
ap-create-job --artifact-id art_xxx --platform ios --dry-run
# 或: python -m autopilot_platform.platform.cli_create_job ...
```

## GitHub Actions

模板：[`.github/workflows/platform-job.example.yml`](../.github/workflows/platform-job.example.yml)

1. 复制为可运行 workflow（或保留 example，用 `workflow_dispatch` 手工试）。
2. 配置 Secrets：`MC_SERVER`、`MC_API_TOKEN`，可选 `MC_ORG_ID`。
3. 在 Actions 界面填 `artifact_id` / `platform` / `device_udids`。

Runner **不要**跑在 GitHub-hosted runner 上指望插 USB；CI 只负责 **创建 Job**，真机在自建机房 Runner。

## Jenkins（最小）

```groovy
pipeline {
  agent any
  environment {
    MC_SERVER = credentials('mc-server-url')
    MC_API_TOKEN = credentials('mc-api-token')
  }
  stages {
    stage('Trigger TR Job') {
      steps {
        sh '''
          # CI 机只装客户端触发 Job；机房 Agent 用 Platform 仓 .[runner]
          pip install -e .
          python -m autopilot.mgmt create-job \
            --artifact-id "$ARTIFACT_ID" \
            --platform "$PLATFORM" \
            --device-udids "$DEVICE_UDIDS" \
            --wait
        '''
      }
    }
  }
}
```

## 相关

- Runner 无 GUI 部署（**主路径在 Platform**）：兄弟仓 `Autopilot-Platform` → `pip install -e ".[runner]"` → `python -m autopilot_platform.runner`；交叉说明见 [setup/runner_headless.md](./setup/runner_headless.md)
- 设备云冻结项：[ROADMAP.md](./ROADMAP.md)
- Platform 操作指南：`Autopilot-Platform/docs/setup/managementconsole.md`
