# AutoPilot IDE — 配置说明

> Platform 服务端见 [Autopilot-Platform/docs/CONFIGURATION.md](../Autopilot-Platform/docs/CONFIGURATION.md)

## 0. 三链路与配置关系

| 链路 | 需要什么 |
|------|----------|
| 1 传统本地跑 | 工程 + 设备/浏览器；**可不登录 Platform、可不绑项目** |
| 1 远程批跑 | 登录 + 项目空间 + 上传制品 |
| 2 设计 AI | 仅在 Platform Web；IDE 导入意图 / Webhook 为**高级可选** |
| 3 AI 辅助编写 | **企业**：登录 Platform，Key 只在服务端；**单机开发**：可选本机 `AP_AI_*` 逃生口。会话驱动 NL→固化传统 `.tc` |

---

## 1. IDE ↔ Platform API 地址

### 企业部署（打包分发给用户）

`platform.url.example` **只是模板**，不会被程序读取。打包或装机时把它复制为 **`platform.url`**，写入用户电脑能访问的 Platform **根 URL**（含协议和端口），不要只写 IP。

IT / 安装包 **任选其一**（推荐文件，用户无感）：

| 方式 | 位置 | 说明 |
|------|------|------|
| 文件（推荐） | 与 `AutoPilot.exe` 同目录的 `platform.url` | Windows 安装包最常用 |
| 文件 | `%ProgramData%\AutoPilot\platform.url` | 全机一份，升级 exe 也不丢 |
| 文件 | macOS：`/Library/Application Support/AutoPilot/platform.url`；Linux：`/etc/autopilot/platform.url` | 系统级 |
| 环境变量 | `AUTOPILOT_PLATFORM_URL` | 组策略 / 启动脚本 |
| 自定义路径 | `AUTOPILOT_PLATFORM_URL_FILE` | 指向任意 `platform.url` |

`platform.url` 示例（`#` 行会被忽略，有效内容须是**一行完整 URL**）：

```text
# 生产 Platform
https://autopilot.company.com
```

内网 HTTP 示例：`http://192.168.1.10:8000`（必须带 `http://` 和端口）。

配上之后：

- IDE **锁定**该地址，登录页不能改（除非设 `AUTOPILOT_ALLOW_PLATFORM_URL_OVERRIDE=1`，仅联调）。
- 用户仍须输入 **用户名和密码**，并选择项目空间。地址锁定 ≠ 免登录、≠ 自动连上就能干活。
- 厂商 AI Key **不要**打进 IDE：在 Platform 运维配置 `AP_AI_API_KEY`。锁定 URL 后链路 3 默认走 `POST /ops/ai/codegen`。

服务端须按同一地址对外提供 API（监听、防火墙、反向代理、证书）。非 loopback 部署须按 Platform [生产安全基线](../Autopilot-Platform/docs/setup/managementconsole.md#10-生产部署安全基线) 轮换默认 Token / JWT。

模板见 [`platform.url.example`](../platform.url.example)。打包步骤见 [packaging.md](packaging.md#分发时写入-platform-地址)。

### 本地开发

不配置 → 默认 `http://127.0.0.1:8000`；登录页可「更改地址」。  
链路 3 默认 `local`：可在仓库根 `.env` 放 `AP_AI_*`（**禁止提交**；已在 `.gitignore`）。

### 优先级

```
AUTOPILOT_PLATFORM_URL / platform.url（部署，默认锁定）
  → settings.json mc_server_url
  → MC_SERVER
  → http://127.0.0.1:8000
```

代码：`platform_deploy.py` + `platform_url.py`  
校验：`python tools/config_doctor.py`

### HTTPS / TLS（IDE 客户端）

**边界**：Platform **服务端**持证书（`MC_SSL_CERTFILE` / `MC_SSL_KEYFILE`，见 [Platform https.md](../Autopilot-Platform/docs/setup/https.md)）。IDE 安装包**不包含**服务端私钥；客户端只需 URL（`platform.url`）与可选的信任配置。

| 场景 | IDE 要配什么 |
|------|----------------|
| 公网 CA（Let's Encrypt 等） | 仅 `platform.url` 为 `https://…` |
| 企业内网私有 CA | `platform.url` + 机器环境变量 `AUTOPILOT_SSL_CA_FILE` 指向 **IT 下发到用户机** 的 CA 证书（如 `%ProgramData%\AutoPilot\corp-ca.crt`） |
| 双仓开发者本机自签 | 见 Platform 仓 [https.md §2.3](../Autopilot-Platform/docs/setup/https.md#23-双仓本地联调开发)（`start_dev_https` / 证书目录旁 `dev-local-ide.env`） |

| 变量 | 默认 | 说明 |
|------|------|------|
| `AUTOPILOT_SSL_VERIFY` | `1` | 设为 `0` 关闭校验（**仅开发联调**，勿用于生产/分发） |
| `AUTOPILOT_SSL_CA_FILE` | — | 企业 CA 或联调自签 **PEM** 路径；企业场景由 IT 下发，**勿**写 Platform 开发仓路径 |

实现：`autopilot/runtime/http_ssl.py`。

---

## 2. 链路 3 LLM 模式与密钥边界

**AUD-2026-15（安全边界）：** 链路 3 Authoring **不得**扩展到 Data/SSH 域。catalog / LLM 解析 / 执行层均拦截 `linux_ssh_*`、`redis_*`、jdbc/mongo/kafka 等前缀及 `intent_act`；高危卸载/monkey 另由 `irreversible` 闸门覆盖。勿为「NL 写库/SSH」放开白名单。

| 模式 | 何时 | IDE 持有 | Key 在哪 |
|------|------|----------|----------|
| **platform**（企业默认） | 已登录管理台、部署锁定了 Platform URL，或显式 `AUTOPILOT_AUTHORING_LLM_MODE=platform` | 仅登录 JWT | Platform Ops / 服务端 env |
| **local**（开发逃生口） | 未登录且未锁定 URL 的默认，或显式 `=local` | 本机 env / `.env` | 开发者本机；**不得入库** |

显式 `AUTOPILOT_AUTHORING_LLM_MODE` 始终优先于锁定推断。
`settings.json` **不存**厂商 Key。

**Intent Vision 密钥边界（与链路 3 对齐）**：锁定 Platform URL 的企业分发下，默认**忽略**本机 Vision Key（避免「编写走 Platform、Vision 却散落用户 `.env`」）。企业默认保持 `AUTOPILOT_INTENT_VISION=0`；若受管 Runner 需 Vision，由 IT 注入 Key 并设 `AUTOPILOT_VISION_ALLOW_LOCAL_KEY=1`。未锁定 URL 的本机开发不受影响。

### Token 消耗护栏（IDE 侧）

| 机制 | 说明 |
|------|------|
| 调用前预检 | 已登录时自动走平台持钥网关；读取 `/ops/ai/capabilities` 确认模型可用，该请求不调用厂商、不耗 token |
| 图片能力 | DeepSeek 等文本模型自动标记 `text_only_ui_tree`；链路 3 只发送压缩 UI 树，不上传截图。Intent Vision 的 `auto` 模式也会跳过图片 |
| 并发互斥 | AI 编写对话框同一时刻只跑一轮，重复点击无效 |
| prompt 上限 | 单次 60000 字符（与 Platform 一致），超限本地拦截 |
| 上下文预算 | 关键字目录去掉展示字段；每回合只带最近 6 步历史，页面摘要截断到 12000 字符 |
| 单用例预算 | `AUTOPILOT_AUTHORING_MAX_LLM_CALLS_PER_CASE` 默认 = 回合上限 + 4（默认 8 回合即 12 次，硬顶 48）；`AUTOPILOT_AUTHORING_MAX_PROMPT_CHARS_PER_CASE` 默认累计 1200000 字符。护栏只防跑飞，调大回合/步数预算时调用上限自动跟随 |
| 每回合步数 | 一回合最多落 4 步（`MAX_STEPS_PER_TURN`），模型被要求把确定的连续动作一次给全，长用例不必一步一次调用 |
| Vision 硬顶 | `AUTOPILOT_VISION_MAX_CALLS_PER_CASE`（默认 30），每用例开始重置 |
| .env 隔离 | `AUTOPILOT_NO_DOTENV=1` 时不自动加载 `.env`（测试/CI 默认置位），本机 Key 不会漏进用例进程 |
| 连续失败熔断 | 会话驱动连续 3 步执行失败即收手，不在同一卡点反复重规划 |

### 会话与门禁（IDE 侧）

| 机制 | 说明 |
|------|------|
| 会话复用 | 已连检视器/镜像且平台与设备一致时直接复用其会话，不再重建 driver、不抢 WDA 端口 |
| 自动前置 | 自动选设备、解析 Bundle/包名、Android 补启动 Activity、iOS 按后端模式预置 Appium caps |
| 多设备 | 多台在线时弹窗选一台（取消即中止）；无 UI 回调的 CLI 场景取第一台 ready |
| 首轮采页 | 启动 App 后等页面稳定再采（默认最少 4.5s、最多 15s），避免把启动页喂给模型白烧一轮 |
| NL 前置线索 | 对话框槽位优先 → 一次 LLM 结构化抽取（仅 platform/app/package/url/inputs）→ 正则兜底。`AUTOPILOT_AUTHORING_NL_LLM=0` 可强制只用正则。不把整条操作路径做成关键字匹配。平台支持 **Android / iOS / Web**（有 URL 且未点明移动端时倾向 web） |
| 页面摘要语义 | 跨平台统一 ``ck``（可点）/ ``ed``（可输入）；摘要带屏幕尺寸（优先 driver 窗口）与 ``p=x,y,宽,高``。控件名不可轻信，结合方位与文案语义选型 |
| 观察-执行 | 借鉴 Midscene：点击/启动/打开等可能改页动作执行后立即重采页再规划；摘要外定位符默认拒绝 |
| 定位两阶段 | 可用 `params.target` / comment 先解析页摘要 ``l``；`AUTOPILOT_AUTHORING_DEEP_THINK=1` 时启发式失败再打一次定位 LLM |
| Vision 兜底 | 默认关。采页为空且 `AUTOPILOT_AUTHORING_VISION_FALLBACK=1`、同时 Intent Vision 已开时，把 Vision 候选压成摘要再规划（仍落传统关键字；受 `AUTOPILOT_VISION_MAX_CALLS_PER_CASE` 约束） |
| 分模型 | 本机 / Platform：`AP_AI_PLANNING_MODEL`（规划/编写/NL）、`AP_AI_LOCATE_MODEL`（深度定位）；未配则回落 `AP_AI_MODEL`。Platform codegen 按 `purpose` 选模 |
| 试跑当前页 | 对话框「试跑当前页」：复用检视器会话、最多 1 回合，仅预览不落盘 |
| 决策轨迹 | 保存草稿时写入 `authored/_authoring_trace.json`（页签名、计划/执行/缓存命中） |
| 正式落盘 | 链路 3 草稿经 `TestCase` + `save_testcase` 写出（顶层 `name`、标准字段、按关键字元数据补默认参数），与链路 1 正式 `.tc.yaml` 对齐 |
| 采页取证 | `python tools/diag_authoring_capture.py [自然语言] [max_elements]` 打印模型实际看到的控件树。真机 smoke/e2e 默认用系统设置作通用锚点，不绑定商业 App；可用参数覆盖任意场景 |
| 试跑门禁 | 会话驱动逐步执行成功**且 AI 宣告已达成需求**才记为已验证；回合耗尽/中途卡住时即便每步都跑通也不放行（步骤能跑通不等于符合需求），需人工核对并本地 F5 |
| 步骤净化 | 同一包名/URL 的入口关键字只落一次（跨 App 允许再次入口）；截图步骤仅当用户明确要求留证时写入；摘要外定位符默认拒绝 |
| 门禁落盘 | 结论写 `authored/_authoring.json`；上传工程时未验证草稿必须人工确认——AI 生成的用例是否符合预期只有人能判定，故不做机器硬拦截 |
| 应用目录 | 分层解析（企业自定义优先，对齐 Midscene `appNameMapping`）：`AUTOPILOT_AUTHORING_APP_ALIASES_FILE` → 系统多语言目录 → 热门第三方候选 → 设备显示名模糊匹配。目录命中后按候选包校验已装列表；第三方禁止臆测已安装；仅稳定系统 Bundle 可回落 |
| 应用名探测 | `AUTOPILOT_AUTHORING_LABEL_PROBES`（默认 12）：Android 未命中目录时最多探测多少个应用显示名；探测顺序为「目录候选包 → LAUNCHER → 已装列表」。Android 设置优先 `SETTINGS` intent |
| 显示名缓存 | Android 显示名双级缓存：内存 + `~/.autopilot/android_app_labels.json`（可用 `AUTOPILOT_AUTHORING_LABEL_CACHE` 指定路径，或 `0` 关闭）；减少重复 dumpsys/APK pull |
| 资源回收 | 对话框关闭/重写时：自建会话关移动 driver + 浏览器；复用检视器会话只清临时包名、不关 driver。共享 Appium 服务由主窗口管理，编写结束不杀 |

企业应用目录 JSON 示例（第三方条目只参与已安装应用匹配）：

```json
{
  "ios": [
    {
      "id": "company_portal",
      "packages": ["com.example.portal"],
      "aliases": ["企业门户", "Company Portal"]
    }
  ]
}
```

---

## 3. 其它配置

| 项 | 说明 |
|----|------|
| 用户名/密码 | 登录 |
| 项目空间 | 登录后选择；无可见项目仍可进 IDE（本地可用），上传/投递需绑定项目 |
| API Token | Runner / Operator |
| Platform `.env` / Ops | 服务端 DB、**AI Key**、`MC_PLATFORM_URL`（与 IDE 部署地址一致） |
| Webhook | Platform `MC_DESIGN_WEBHOOK_URL` ↔ IDE `:8765`（设计域，可选） |

---

## 4. 相关文件

- `%USERPROFILE%\.autopilot\settings.json` — 登录态、项目（无 AI Key）
- IDE `.env` — 仅本地开发：Intent/Vision / 链路 3 local 逃生口（`AUTOPILOT_*` / `AP_AI_*`）

---

## 5. 默认关闭的可选能力

日常保持关闭，避免成本与误操作。主链路（设计评审 → 导入/绑定 → 本机或批跑）**不依赖**下面两项。

### 设计 Chat 实验动作（Platform）

| 项 | 说明 |
|----|------|
| 开关 | `AP_ENABLE_EXPERIMENTAL_ACTIONS=1` |
| 默认 | 关 |
| 作用 | Chat 面板可触发实验性工具动作（非稳定 API） |
| 建议 | 仅在受控环境、平台管理员知情时开启 |

未开启时 Chat 仍可用于生成草稿、检索知识库与人审。

### Intent Vision（IDE）

| 项 | 说明 |
|----|------|
| 开关 | `AUTOPILOT_INTENT_VISION=1` + 对应厂商 API Key |
| 默认 | `AUTOPILOT_INTENT_VISION=0` |
| 作用 | 启发式/heal 失败后，用 LLM + DOM（可选截图）猜定位 |
| 成本 | 按 Vision 厂商计费；建议 `AUTOPILOT_VISION_WHEN=fallback` |

企业锁定 Platform URL 时的 Key 边界见上文 §2。体检：

```powershell
python -m autopilot.intent vision-doctor
python -m autopilot.intent vision-doctor --ping
```

样例见仓库根 `.env.example`「Intent Vision」章节。
