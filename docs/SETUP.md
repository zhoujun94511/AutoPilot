# AutoPilot 配置与依赖总览

本文是配置入口：先装**公共环境**，再按你要用的能力看对应的平台文档。

- [Web 配置](setup/web.md) — Selenium 4 + 浏览器驱动
- [Android 配置](setup/android.md) — adb + Appium + uiautomator2（+ scrcpy 实时镜像）
- [iOS 配置](setup/ios.md) — go-ios + pymobiledevice3 + WDA-direct（Win/Linux 主路径，**无需 Appium**）；macOS 可选 Appium xcuitest
- [管理台与客户端边界](managementconsole.md) — 指向 Autopilot-Platform；IDE 只经 HTTP 对接
- [企业部署 Platform 地址](CONFIGURATION.md#1-ide--platform-api-地址) — `platform.url` / `AUTOPILOT_PLATFORM_URL`（打包分发必读）
- [功能模块清单](feature-modules.md) — IDE 与 Web 管理台模块对照
- [macOS iOS 高帧镜像 helper](setup/ios_avf_capture.md) — `ios-avf-capture` 构建、协议、排障
- [iOS Monkey 稳定性测试](setup/ios_monkey.md) — `mobile_monkey` 参数、CLI、报告
- [控件检视器 / 实时镜像](inspector.md) — Inspector(Android/iOS/Web) + 交互镜像
- [移动端后端边界](mobile-backend-boundaries.md) — 设备层 / Appium / WDA-direct 职责划分
- [iOS WDA 能力矩阵](ios-wda-capability-matrix.md) — WDA-direct 相对 Appium iOS
- [WebDriverAgent 编译](wdadoc/IOS自动化测试之WebDriverAgent编译与构建.md) — iOS 真机 WDA 的 Mac/Xcode 侧准备

> **开跑前先体检**：`.venv/Scripts/python.exe tools/preflight.py` 会逐项检查 Python/依赖/资源/工具链/移动端外部运行时，并给出缺啥装啥的命令。详见 [§2.0](#20-环境预检-preflight)。

---

## 1. 能力 / 依赖矩阵

| 能力         | Python 可选依赖组                               | 外部工具或资源                                                                                               | 平台文档                                         |
|------------|--------------------------------------------|-------------------------------------------------------------------------------------------------------|----------------------------------------------|
| 基础 IDE     | （主依赖）`PyQt6` `lxml` `selenium`             | （无）                                                                                                   | （无）                                          |
| 图标美化（可选）   | `icons`（`qtawesome`）                       | （无）                                                                                                   | 缺失自动降级为文字徽章；`pip install qtawesome`          |
| WebUI      | （主依赖内含 selenium）                           | 浏览器 + driver（Selenium Manager 自动解析）                                                                   | [web.md](setup/web.md)                       |
| 图像识别       | （主依赖）`opencv` `numpy`                      | （无）                                                                                                   | [web.md](setup/web.md)                       |
| Http/接口    | （主依赖）`httpx` `jsonpath-ng`                 | （无）                                                                                                   | （无）                                          |
| Android    | （主依赖）`Appium-Python-Client` `pyaxmlparser` | JDK 17+、Node 18+、Appium + uiautomator2；adb（内置 `re_adb`）                                               | [android.md](setup/android.md)               |
| iOS        | （主依赖）mobile 相关                             | go-ios（`re_go_ios`）+ pymobiledevice3 + WDA；Win/Linux 默认 WDA-direct；macOS 可选 Appium xcuitest           | [ios.md](setup/ios.md)                       |
| 实时镜像/控制    | `mirror`（av/PyAV, adbutils）                | Android：scrcpy-server（`re_scrcpy`）+ adb；iOS Mac 优先 AVFoundation helper，回退 WDA MJPEG；Win/Linux 仅 MJPEG | [inspector.md](inspector.md)                 |
| 控件检视器      | Android/iOS/Web 主依赖已覆盖                     | 同各平台                                                                                                  | [inspector.md](inspector.md)                 |
| Excel / 报告 | （主依赖）`openpyxl` `Jinja2`                   | （无）                                                                                                   | （无）                                          |
| 数据/中间件     | `data`（redis, paramiko, SQLAlchemy 等）      | 对应服务端（Redis/SSH/FTP/Kafka/ES/HBase）                                                                   | （无）                                          |
| 管理台联调      | 兄弟仓 Autopilot-Platform                     | Node 18+（Vite）；另进程 TestRunner                                                                         | [managementconsole.md](managementconsole.md) |

> `data` / `mirror` / `secure` / `icons` 等仍为可选；缺失时对应能力优雅降级。`http`/`mobile`/`image`/`report` 已并入主依赖（兼容空 extra 名）。
> **Android 经 Appium 的外部运行时（JDK/Node/Appium/驱动）不是 Python 包**，需各自单独安装，见 [android.md](setup/android.md#3-appium-server--uiautomator2-driver) 与下方 §2.0 预检。

## 2. 公共环境

### 2.0 环境预检 (preflight)

任何时候都可一键体检环境是否就位（离线、不连真机/真服务）：

```bash
.venv/Scripts/python.exe tools/preflight.py
```

逐项检查并给出「缺啥装啥」的命令：
1. **Python**（≥3.10）+ 是否在 venv 内；
2. **依赖能力**：core 必需（含原 http/mobile/image/report），其余按 pyproject 可选组（data/mirror/secure）；
3. **内置资源**：`re_adb / re_aapt / re_scrcpy / re_uiautomator / re_go_ios`（按当前 OS）；
4. **派生工具链**：adb、go-ios；
5. **移动端外部运行时**：Java(JDK)、Node.js、Appium CLI + uiautomator2 驱动、`:4723` 服务（**Android 必需**；**iOS WDA-direct（Win/Linux）不依赖 Appium**，仅 macOS 走 Appium xcuitest 时需要）。

核心缺失才以非零码退出（可作 CI 闸门）；可选缺失只提示。可直接代装：

```bash
.venv/Scripts/python.exe tools/preflight.py --install data,mirror,secure,web_playwright   # 装可选 Python 能力
.venv/Scripts/python.exe tools/preflight.py --install-all             # 装全部可选 Python 能力
.venv/Scripts/python.exe tools/preflight.py --install-drivers         # 装宿主侧 Appium 驱动(uiautomator2)
```

> 真机 / 真服务的**连通性**验证（adb 设备、Redis/SSH/DB…）用另一脚本：`tools/verify_realenv.py`。preflight 管「装没装齐」，verify_realenv 管「连不连得上」。Platform 仓同类脚本见兄弟仓 `Autopilot-Platform/tools/preflight.py`（支持 `--role platform|runner`）。

### 2.1 Python 与虚拟环境

- Python **3.10+**（仓库 `.venv` 用 3.12）。
- 重建虚拟环境：

```bash
cd AutoPilot
python -m venv .venv
.venv/Scripts/python.exe -m pip install --upgrade pip
```

### 2.2 安装依赖（按需选可选组）

```bash
# 主依赖（IDE + Web/Http/Mobile/图像/报告/Excel 等已并入）
.venv/Scripts/python.exe -m pip install -e .

# 可选：数据中间件 / 实时镜像 / 钥匙串
.venv/Scripts/python.exe -m pip install -e ".[data,mirror,secure]"

# 兼容旧命令（http/mobile/image/report 现为空 extra，可照写）
.venv/Scripts/python.exe -m pip install -e ".[http,data,mobile,mirror,image,report]"
```

可选组一览：`data`（Redis/SSH/DB/Kafka/ES/HBase）、`mirror`（scrcpy/AVF）、`secure`（keyring）。`http`/`mobile`/`image`/`report` 已并入主依赖。

### 2.4 同平台多设备并行（可选）

首期支持 **同平台** round-robin 并行（Android 多台 / iOS 多台），关键字层无感知：

| 入口  | 用法                                                                                                               |
|-----|------------------------------------------------------------------------------------------------------------------|
| IDE | 运行测试套 / 运行选中用例：连接 ≥2 台同平台设备时弹窗勾选「并行执行」                                                                           |
| CLI | `python tools/run_suite.py --project <dir> --parallel --platform android --workers 3`（可选 `--kill-on-shard-fail`） |
| API | `from autopilot.engine import run_suite` → `mode="parallel_device"`                                              |

执行上下文注入（`DeviceSession.to_ctx_vars()`，并行时每 worker 独立）：

| 变量                        | 含义                                                                                                 |
|---------------------------|----------------------------------------------------------------------------------------------------|
| `__device_udid__`         | 本 worker 绑定的设备 UDID                                                                                |
| `__appium_server__`       | 本设备 Appium URL（slot0=`http://127.0.0.1:4723`，slot1=4724…）                                          |
| `__appium_caps__`         | Android：独立 `systemPort`/`chromedriverPort`/`mjpegServerPort`；iOS：按本机 WDA 端口/UDID                   |
| `__wda_local_port__`      | iOS WDA 本机转发端口（slot0=8100，slot1=8101…，按 UDID 粘滞）                                                   |
| `__tunnel_info_port__`    | go-ios 隧道信息端口（28100 + slot×10）                                                                     |
| `__mobile_backend_mode__` | iOS 后端决策：`auto` / `appium` / `wda`（见 [mobile-backend-boundaries.md](mobile-backend-boundaries.md)） |
| `__current_platform__`    | 当前用例有效平台（`android` / `ios`），由用例标记或步骤参数推断                                                           |
| `__worker_slot__`         | worker 槽位（报告/日志前缀）                                                                                 |

环境变量可覆盖端口基址：`AUTOPILOT_WDA_BASE_PORT`、`AUTOPILOT_TUNNEL_BASE_PORT`、`AUTOPILOT_MJPEG_BASE_PORT`。

> iOS 用例在 Win/Linux 上跑 WDA-direct 时，步骤里的 `appium_start` **会自动跳过**（不启动、也不要求安装 Appium）。Android 用例仍需 Appium。  
> **失败隔离**（默认开）：某设备分片失败不停止其它设备；IDE 弹窗可关，CLI 用 `--kill-on-shard-fail`。  
> **设备级隔离**：每台设备独立 Appium 进程 + UIA2/WDA 端口（按 UDID 粘滞）。`appium_stop` / suite 收尾只杀本设备端口。同一 Runner 上设备集合不相交的 Job 可并行（安卓任务与 iOS 任务可同机同时跑）。

### 2.3 启动与自检

```bash
.venv/Scripts/python.exe run.py                                   # 启动 IDE
.venv/Scripts/python.exe skills/autopilot-lint/autocheck.py   # 自检 + 全部测试套
```

## 3. 资源布局

资源按性质分两处放置，均由代码自动定位、**无需手工配置**：

**① 应用数据（随包发布，在 `autopilot/` 内）**

| 目录                                 | 用途                                                         | 谁来用                                       |
|------------------------------------|------------------------------------------------------------|-------------------------------------------|
| `autopilot/metadata/keyword_defs/` | 关键字定义 XML（webui/http/public/mobile）                        | `metadata.load_catalog()` 驱动 UI 参数表单      |
| `autopilot/mobile/`                | 移动端**设备层** + **iOS 组件**（adb、APK/IPA 解析、iOS 引导、`ios/`、设备信息） | UI 与关键字均 `from autopilot.mobile import …` |
| `autopilot/keywords/mobile/`       | 移动端**关键字 + 会话**（Appium / WDA、`session`/`driver`）           | 用例步骤注册与执行                                 |

**② 大体量二进制（仓库根 `resources/`，不打进 wheel）**

| 子目录               | 用途                                                                                     | 谁来用                                                                                                                                       |
|-------------------|----------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------|
| `re_adb/`         | 各平台 `platform-tools-*.zip`（adb 等）                                                      | [`autopilot/mobile/adb.py`](../autopilot/mobile/adb.py) 首用时自动解压到 `runpath/` 并入 PATH                                                       |
| `re_aapt/`        | 各平台 `aapt-*.zip`（APK 解析兜底）                                                             | [`autopilot/mobile/aapt.py`](../autopilot/mobile/aapt.py)（pyaxmlparser 不可用时回退）                                                            |
| `re_go_ios/`      | go-ios 二进制（`executable/<os>/`）、DeveloperDiskImage（`devimages/`）、`wintun`（Windows 隧道驱动） | [`autopilot/mobile/ios_bootstrap.py`](../autopilot/mobile/ios_bootstrap.py)                                                               |
| `re_scrcpy/`      | `scrcpy-server.jar`（Android H.264 实时镜像的设备侧 server）                                     | `inspector/stream/_scrcpy_core.py`（需 `mirror` 组）                                                                                          |
| `re_uiautomator/` | uiautomator2 **设备侧** server apk（`app-uiautomator*.apk`）                                | 备用资源；当前 Android 经 Appium 的 uiautomator2 驱动自带并安装它，**代码未直接引用**（见 [android.md](setup/android.md#3-appium-server--uiautomator2-driver) 的分层说明） |

> 体量：`keyword_defs` ~0.5M（随包）、`re_adb` ~33M、`re_go_ios` ~68M、`re_scrcpy` ~0.7M（根目录二进制，随源码部署、运行期定位）。
> 用 `tools/preflight.py` 的 [3] 段可一键确认这些资源是否按当前 OS 就位。

## 4. 常见问题

- **先跑 `tools/preflight.py`**：绝大多数「跑不起来/某能力不可用」都能在这里一眼看出缺什么、并附安装命令。
- **IDE 起不来**：先确认基础依赖装好（`pip install -e .`），再看是否缺少 PyQt6 运行库。
- **某类关键字报 `NotImplementedKeyword`**：对应可选依赖未安装，按矩阵补 `pip install -e ".[<组>]"`。
- **Android 用例连不上**：`mobile` 组只是 Python 客户端；真正跑还需 **JDK + Node + Appium + uiautomator2 驱动**（外部运行时，见 [android.md](setup/android.md)）。注意 `resources/re_uiautomator` 的 apk 是**设备侧** server，**替代不了宿主侧 Appium 驱动**。
- **iOS 用例报未检测到 Appium**：若宿主为 Win/Linux 且用例/上下文已识别为 iOS，应走 WDA-direct，`appium_start` 会自动跳过。若仍报错，检查 `__current_platform__` 是否为空（用例可设 `platform: ios` 或在步骤中指定 `type: ios` / `.ipa`）。
- **实时镜像黑屏/不可用**：Android 需 `mirror` 组（av+adbutils）且 `resources/re_scrcpy/scrcpy-server.jar` 在位；iOS MJPEG 断流时会回退截图轮询。
- **真机 / 服务相关**：见各平台文档的「常见问题」，连通性用 `tools/verify_realenv.py` 验。
