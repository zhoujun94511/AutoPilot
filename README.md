<div align="center">

![AutoPilot logo](resources/branding/autopilot-96.png)

# AutoPilot

**面向测试团队的全栈自动化测试 IDE**

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![PyQt6](https://img.shields.io/badge/GUI-PyQt6-41cd52.svg)](https://www.riverbankcomputing.com/software/pyqt/)
[![Selenium](https://img.shields.io/badge/Web-Selenium%204-43b02a.svg)](https://www.selenium.dev/)
[![Appium](https://img.shields.io/badge/Mobile-Appium-662d91.svg)](https://appium.io/)

[中文](README.md) · [English](README_en.md)

**[配置指南](docs/SETUP.md)** · **[Platform 联调](#与-platform-配合)** · **[检视器](docs/inspector.md)** · **[工程模型](docs/project-model.md)**

</div>

AutoPilot 是面向测试工程团队的专业桌面 IDE，以关键字驱动方式统一编排 Web、移动端、接口、数据与中间件自动化。与 [AutoPilot Platform](../Autopilot-Platform/README.md) 协同，覆盖从用例设计、本机验证到远程批跑与报告归档的完整测试交付链路。

![IDE 主界面](docs/pic/ide-main-CN.png)

---

## 产品亮点

* **关键字驱动，降低自动化门槛** — 提供可视化步骤编排、对象库与参数化配置，测试人员无需编写底层框架代码即可覆盖常规测试场景；复杂逻辑可通过扩展关键字灵活承接。
* **全栈能力，统一工程管理** — 在同一项目内贯通 Web（Selenium / Playwright）、REST/HTTP、Android（UiAutomator2）与 iOS（WDA）等多端能力，避免工具链割裂与测试资产分散。
* **智能检视，加速元素定位** — 内置控件检视器，支持 Web / Android / iOS 控件树采集与定位符回填；配合本机镜像能力，显著缩短定位与调试周期。
* **接口资产快速复用** — 支持 OpenAPI 3.x 与 Postman Collection 导入，生成标准化、可回归的 HTTP 用例，助力接口测试体系化建设。
* **设计—执行一体化协同** — 与 Platform 联动，承接意图用例评审、Binding 绑定、工程制品发布与远程批跑调度；本机设备可纳入统一设备池参与执行。
* **工程化调试与并行执行** — 提供步骤级调试、结构化测试报告与执行证据留存；支持同平台多设备并行，满足规模化回归与持续集成需求。

---

## 快速开始

### 1. 验证执行内核

无需浏览器或真机，约 30 秒确认环境可用：

```powershell
# Windows
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe tests\smoke.py
```

```bash
# Linux / macOS
python3.12 -m venv .venv
./.venv/bin/python -m pip install -U pip
./.venv/bin/python -m pip install -e .
./.venv/bin/python tests/smoke.py
```

期望输出：**PASS**、恰好 **1** 个 NOIMPL（`sap_login`）、无 FAIL，退出码 **0**。

### 2. 启动桌面 IDE

```powershell
# Windows
.\.venv\Scripts\python.exe -m pip install -e ".[data,mirror,icons]"
.\.venv\Scripts\python.exe tools\preflight.py
.\.venv\Scripts\python.exe run.py
```

```bash
# Linux / macOS
./.venv/bin/python -m pip install -e ".[data,mirror,icons]"
./.venv/bin/python tools/preflight.py
./.venv/bin/python run.py
```

在 IDE 中：**新建工程 → 添加 Web/HTTP 关键字 → 执行 → 打开 `reports/` 下 HTML 报告**。

无头批量：

```bash
python tools/run_suite.py --project <工程目录>
python tools/run_suite.py --project <工程目录> --parallel --platform android
```

完整依赖矩阵见 [配置总览](docs/SETUP.md)。

---

## 自动化覆盖范围

| 层级       | 技术栈                        | 说明                           |
|:---------|:---------------------------|:-----------------------------|
| Web      | Selenium 4 · 可选 Playwright | 浏览器 UI 自动化                   |
| HTTP     | 内置 REST 客户端                | 鉴权、断言、JsonPath/XPath 提取      |
| Android  | UiAutomator2 · adb         | USB / 无线调试真机                 |
| iOS      | WDA 直连                     | Windows/Linux 可连已备 WDA 的设备   |
| 数据 / 中间件 | `.[data]` 可选               | Redis、SSH、SQLAlchemy、Kafka 等 |
| 导入       | OpenAPI · Postman          | 生成确定性 `.tc.yaml` 用例          |

---

## 与 Platform 配合

AutoPilot IDE 专注用例编排与本机验证；[AutoPilot Platform](../Autopilot-Platform/README.md) 提供测试设计评审、远程调度、设备池治理与报告归档。两者协同，形成从设计评审、Binding 绑定、制品发布到远程批跑与结果回传的完整闭环。

先启动 Platform，在 IDE 连接设置中登录对应实例。若需将本机设备纳入统一设备池：

```powershell
$env:MC_RUNNER_TOKEN = "<your-runner-token>"
python -m autopilot.runner --server http://127.0.0.1:8000 --token-env MC_RUNNER_TOKEN
```

对接清单：[IDE 集成说明](../Autopilot-Platform/docs/architecture/IDE_INTEGRATION.md)。

---

## 核心能力

**可视化编排** — 工程树、步骤编辑器、关键字库与执行控制台一体化呈现，支持浅色/暗色主题，满足日常编排与批量执行需求。

**控件检视与本机镜像** — 覆盖 Android、iOS、Web 控件树采集与定位符维护；Android 采用 scrcpy 低延迟镜像，iOS 在 macOS 环境支持高帧率采集。详见 [检视器说明](docs/inspector.md)。

![控件检视器](docs/pic/ide-inspector-CN.png)

**意图用例落地** — 支持导入 Platform 评审通过的意图步骤，结合工程 Binding 解析为可执行关键字；AI 辅助内容作为候选方案，模型与密钥由 Platform 统一管控。

**稳定性验证** — 提供移动端 Monkey 压测能力，适用于专用测试设备与实验环境。详见 [iOS Monkey](docs/setup/ios_monkey.md)。

---

## 可选组件

| Extra      | 安装                  | 用途                     |
|:-----------|:--------------------|:-----------------------|
| 数据与中间件     | `.[data]`           | Redis、SSH、SQLAlchemy 等 |
| 实时镜像       | `.[mirror]`         | scrcpy / AVFoundation  |
| 图标         | `.[icons]`          | 矢量图标                   |
| Playwright | `.[web_playwright]` | 可选浏览器引擎                |
| 开发         | `.[dev]`            | 测试与静态检查                |

内置 `resources/` 按操作系统分发 adb、go-ios、scrcpy 等工具链；首次运行请执行 `tools/preflight.py`。

---

## 目录结构

```
autopilot/
  ui/           桌面界面
  keywords/     关键字实现
  engine/       执行与套件编排
  mobile/       设备层（adb、安装包、iOS 工具链）
  inspector/    控件检视与本机镜像
  mgmt/         Platform 客户端
  runner/       IDE Runner
docs/           配置、架构与平台说明
tools/          预检、批量执行与契约校验
```

---

<details>
<summary><strong>架构、兼容性与职责边界</strong></summary>

### 适用与非适用

**适用：** 关键字编排与本机调试；落地已评审意图；上传工程制品与应用资源；本机 USB 设备作为 IDE Runner 接入。

**非适用：** 不替代 Platform 多租户权限、远程调度与报告归档；不承诺在 Windows/Linux 从零完成 iOS WDA 签名；`mobile_monkey` 不用于个人设备或生产账号。

### 与 Platform 的职责边界

| 能力           | AutoPilot IDE | AutoPilot Platform |
|--------------|---------------|--------------------|
| 关键字用例编排      | 主责            | 浏览 / 治理            |
| Binding 与定位器 | 主责            | 随制品保存              |
| 本机调试         | 主责            | 不承担                |
| 意图设计与评审      | 导入、绑定、落地      | 主责                 |
| 远程批跑         | 提交与查看         | 调度、治理              |
| 设备接入         | IDE Runner    | 设备池 + 独立 Runner    |
| AI 密钥        | 使用            | 统一托管               |

### 版本兼容

请按 IDE 与 Platform 发布说明配对使用；工程格式为 `.tc.yaml` / `.map.yaml`（兼容旧版 `.tc` / `.map`）。对接细节见 [`RUNTIME_PIN`](../Autopilot-Platform/contracts/RUNTIME_PIN) 与 [IDE 对接](../Autopilot-Platform/docs/architecture/IDE_INTEGRATION.md)。

| IDE 版本 | Platform 版本 | 工程格式                     | 状态    |
|--------|-------------|--------------------------|-------|
| 0.1.x  | 0.2.x       | `.tc.yaml` / `.map.yaml` | 当前开发线 |

### 支持矩阵

| 项目            | 最低     | 推荐      |
|---------------|--------|---------|
| Python        | 3.10   | 3.12    |
| Node.js       | 18     | 20 或 22 |
| JDK（Android）  | 17+    | 17+     |
| Chrome / Edge | Stable | Stable  |

iOS：macOS + Xcode 用于签名与初次部署；Windows/Linux 需设备侧 WDA 已就绪。详见 [Android](docs/setup/android.md) · [iOS](docs/setup/ios.md)。

### 术语

| 术语          | 定义                     |
|-------------|------------------------|
| 执行节点 Runner | 领取任务并执行的节点统称           |
| 独立 Runner   | Platform 仓提供的 CLI 执行进程 |
| IDE Runner  | 由本 IDE 启动的本机执行节点       |
| 设备池         | Platform 管理的设备资源集合     |

</details>

---

## 文档

| 文档                                                                                     | 说明                 |
|----------------------------------------------------------------------------------------|--------------------|
| [配置总览](docs/SETUP.md)                                                                  | 依赖矩阵与环境预检          |
| [Web](docs/setup/web.md) · [Android](docs/setup/android.md) · [iOS](docs/setup/ios.md) | 各平台工具链             |
| [检视器](docs/inspector.md)                                                               | 控件树与本机镜像           |
| [工程模型](docs/project-model.md)                                                          | 工程文件格式             |
| [与 Platform 的边界](docs/managementconsole.md)                                            | 客户端集成说明            |
| [打包](docs/packaging.md)                                                                | 发行与 `platform.url` |

开发检查：

```bash
python tests/smoke.py
python skills/autopilot-lint/autocheck.py --no-test
```

---

## 常见问题

**关键字不可用** — 运行 `tools/preflight.py`；中间件需 `.[data]`，镜像需 `.[mirror]`。

**未列出设备** — 检查 `adb devices` 或 iOS 信任；参见 [iOS 配置](docs/setup/ios.md)。

**无法连接 Platform** — 确认 Platform 已启动且账号/项目空间匹配；开发凭据仅允许 `127.0.0.1`。

**远程任务未安装应用** — 在应用资源库选择版本；工程制品不包含安装包。

---

## 许可证

详见 [LICENSE.txt](LICENSE.txt)。
