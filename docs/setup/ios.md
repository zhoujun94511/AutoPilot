# iOS 配置

iOS 自动化基于设备上的 **WebDriverAgent（WDA）** HTTP 服务。AutoPilot 按宿主系统选择会话后端（[`keywords/mobile/platform.py`](../../autopilot/keywords/mobile/platform.py)）：

| 宿主                  | 默认后端                       | 是否需要 Appium server                  |
|---------------------|----------------------------|-------------------------------------|
| **Windows / Linux** | **WDA-direct**             | **否**（`appium_start` 自动跳过）          |
| **macOS**           | Appium xcuitest（golden 参考） | 是（WDA 由 go-ios 准备，Appium 仅 HTTP 代理） |

Win/Linux 上 iOS 17+ 无法使用 Appium 的 RemoteXPC 隧道，因此主路径是 **go-ios + pymobiledevice3 准备 WDA → 直连 WDA HTTP**（[`wda_client.py`](../../autopilot/keywords/mobile/wda_client.py)）。Mac 上 **Appium golden 路径**同样是 go-ios `runwda` + **`webDriverAgentUrl` 直连**（见 [§5](#5-appium-xcuitestmacos-golden-参考路径)）；`build_ios_caps_managed` / RemoteXPC / xcodebuild 自建 WDA 在 iOS 26+ 真机上**不推荐**。

> 能力对照见 [ios-wda-capability-matrix.md](../ios-wda-capability-matrix.md)；架构边界见 [mobile-backend-boundaries.md](../mobile-backend-boundaries.md)。

## 1. 先决条件：编译 WDA（Mac/Xcode 侧，一次性）

把签好名的 WebDriverAgentRunner 安装到目标设备。完整步骤见：

- [WebDriverAgent 编译与构建（中文）](../wdadoc/IOS自动化测试之WebDriverAgent编译与构建.md)
- [Building WebDriverAgent for iOS Automation (EN)](../wdadoc/Building-WebDriverAgent-for-iOS-Automation.en.md)

要点：用 Apple 开发者账号在 Xcode 里为 WebDriverAgentRunner 配置签名 → 真机 build/test 安装一次 → 设备「设置 → 通用 → VPN与设备管理」信任该开发者证书。装好后设备上常驻可被 `runwda` 唤起的 WDA。

## 2. Python 依赖

```bash
.venv/Scripts/python.exe -m pip install -e ".[mobile]"   # Appium-Python-Client
.venv/Scripts/python.exe -m pip install pymobiledevice3   # 纯 Python：设备发现 / usbmux 端口转发 / 开发者镜像
```

## 3. go-ios（内置 `resources/re_go_ios`，零下载）

go-ios 负责 iOS 17+ 的**用户态 RSD 隧道**、**`runwda` 启动 WDA**、**DeveloperDiskImage 挂载**——这些都不需要管理员权限。

资源已随仓库内置（`resources/re_go_ios/`）：

| 子项                       | 说明                                                             |
|--------------------------|----------------------------------------------------------------|
| `executable/win/ios.exe` | go-ios Windows 二进制（mac/linux 同理放各自子目录）                         |
| `wintun/`                | Windows 上隧道所需的 wintun 驱动                                       |
| `devimages/`             | DeveloperDiskImage（含 iOS 16.6 与 iOS 17 个性化镜像 `ddi-*`），供挂载开发者镜像 |

关键点：
- **用户态隧道**：go-ios 以 `ENABLE_GO_IOS_AGENT=user` 跑隧道 agent，**Windows 免管理员**。隧道是 go-ios 进程内部的，pymobiledevice3 无法路由其中——所以**隧道 + runwda 由 go-ios 独占**。
- **端口要钉死**：隧道 agent 的 HTTP-API 端口要固定（`--tunnel-info-port`），否则崩溃后留下孤儿进程占端口、难以回收。隧道管理器应在启动时回收残留 agent。

典型命令（概念示意，实际由代码封装）：

```bash
# 启动用户态隧道（iOS 17+ 必需，常驻）
set ENABLE_GO_IOS_AGENT=user
resources\re_go_ios\executable\win\ios.exe tunnel start --tunnel-info-port 28100

# 挂载开发者镜像（首次/重启后，按系统版本选 devimages 下镜像）
ios.exe image auto --basedir resources\re_go_ios\devimages

# 在设备上拉起 WDA
ios.exe runwda --bundleid <WDA的bundleid> --testrunnerbundleid <...> --xctestconfig <...>.xctest
```

## 4. pymobiledevice3（设备发现 / 端口转发）

pymobiledevice3 走 usbmux，做不依赖隧道的活：列设备、把设备上 WDA 的 **8100** 端口转发到本机。

```bash
pymobiledevice3 usbmux list                                # 列出已连设备 + UDID
pymobiledevice3 usbmux forward 8100 8100 --serial <UDID>   # 本机:8100 → 设备 WDA:8100
```

转发后，本机 `http://127.0.0.1:8100/status` 能摸到 WDA 即就绪。

> **选设备的参数在 4.x 变了**：`usbmux forward` 只认 `--serial`，旧的 `--udid` 会直接
> 报 `No such option` 并退出，结果表现为「WDA `/status` 未就绪」。代码里由
> `ios_bootstrap.pmd3_forward_device_flag()` 读 `-h` 现场判定，新旧版本都能用。

> **`usbmux list` 返回空但设备确实插着**：先单独跑一次
> `python -m pymobiledevice3 usbmux list` 看报错。装坏的依赖（例如缺 `coloredlogs`）
> 会让枚举静默为空；`ios_devices.ios_tooling_error()` 会把这个原因带到设备列表与
> AI 编写的报错里。

排障脚本：`python tools/diag_ios_wda.py <UDID> 150` 会保留隧道 / runwda / 转发，
逐项打印「隧道就绪、WDA bundle、镜像挂载、runwda 存活、8100 是否监听、/status」，
用来区分「转发没起来」和「WDA 自己没起来」。

## 5. Appium xcuitest（macOS golden 参考路径）

以下适用于 **macOS + `backendMode=appium`**，且需 **`IOS_APPIUM_MANAGED=0`**（或 `prefer_appium_managed` 为 false）。Win/Linux 跑 iOS 可跳过本节。

```bash
npm install -g appium
appium driver install xcuitest
appium    # http://127.0.0.1:4723
```

WDA 由 **go-ios `runwda`** 以 XCTest 方式拉起，经 pymobiledevice3 转发到本机 8100；Appium **只当 HTTP 代理**，不 build/install/卸载 WDA：

| Cap                                      | 值                       | 说明                                               |
|------------------------------------------|-------------------------|--------------------------------------------------|
| `appium:webDriverAgentUrl`               | `http://127.0.0.1:8100` | 必填                                               |
| `appium:udid`                            | 设备 UDID                 | 必填                                               |
| `platformName` / `appium:automationName` | `iOS` / `XCUITest`      | 必填                                               |
| **`appium:usePreinstalledWDA`**          | **勿设**                  | 设了会触发 xcuitest 驱动 `cleanupApps`，**卸载自定义签名的 WDA** |

AutoPilot 的 [`build_ios_caps()`](../../autopilot/mobile/ios_bootstrap.py) 已只输出 `webDriverAgentUrl`（无 `usePreinstalledWDA`）。多步骤采集（parity / TEST002 / Monkey）前需 **常驻 WDA**（8100），否则子步骤间会 `ECONNREFUSED`。

> **代码化编排**：隧道 / 挂镜像 / runwda / 转发 / caps 封装在 [`ios_bootstrap.py`](../../autopilot/mobile/ios_bootstrap.py)（`IosDevicePrep.prepare()`）。`IOS_USE_GOIOS=1` 或非 managed 路径会自动合入 caps（端口 `IOS_WDA_LOCAL_PORT`，默认 8100）。

### 5.0 Mac iOS 17+/26：推荐与禁用路径

| 路径                                                     | 状态               | 说明                                                  |
|--------------------------------------------------------|------------------|-----------------------------------------------------|
| go-ios `--userspace` 隧道 + runwda + `webDriverAgentUrl` | ✅ **推荐（golden）** | Mac/Win 共用 WDA 准备；Appium 0.4s 建会话（2026-07 Mac 真机验证） |
| `usePreinstalledWDA` + RemoteXPC `tunnel-creation`     | ❌ 禁用             | iOS 26：WDA 8100 不监听，120s 超时                         |
| Appium xcodebuild 自建 WDA                               | ❌ 禁用（本机）         | 需 Xcode 登录 Team + 描述文件                              |
| WiFi 直连 `http://<device-ip>:8100`                      | ❌ 不可用            | runwda 的 WDA 仅 USB 转发可达                             |
| `build_ios_caps_managed` + pymobiledevice3 tunneld     | ⚠️ 不推荐 Mac 默认    | 与 go-ios 隧道争用；仅特殊场景                                 |

采集脚本：`tools/ios_golden_reference_run.py`（设 `IOS_APPIUM_MANAGED=0`）。

## 5.1 装卸与自动化分层

被测 **.ipa 的安装、卸载** 在 **设备层** 完成（[`autopilot/mobile/ios_bootstrap.py`](../../autopilot/mobile/ios_bootstrap.py) 的 `install_app` / `uninstall_app`；关键字编排见 [`session.py`](../../autopilot/keywords/mobile/session.py) 的 `ios_install_app` / `_ios_uninstall_app`），**不经过** Appium `install_app` / `remove_app`，且在 **Windows / macOS / Linux 上使用同一套实现**：

| 步骤    | 实现                                                          | 说明                   |
|-------|-------------------------------------------------------------|----------------------|
| 安装    | pymobiledevice3 `InstallationProxy` → 失败回退 go-ios `install` | IPA 预检（描述文件、授权 UDID） |
| 卸载    | pymobiledevice3 `uninstall` → 失败回退 go-ios `uninstall`       | 无需已建 WDA/Appium 会话   |
| 检测已安装 | pymobiledevice3 `get_apps`                                  | 用于装前是否先卸             |

关键字流程：

1. **`mobile_app_install_and_open`**：解析 Bundle ID → 若已安装则先卸 → 设备层装 IPA → 再 `AppiumManager.create()`（Win/Linux 为 WDA 直连，Mac 可选 Appium）。
2. **`mobile_app_adb_uninstall`**：按 `type=ios` 走设备层卸载（关键字 id 保留历史 `adb` 命名）。

为何不改为 Appium 装包：

- **Windows / Linux + iOS 17+**：自动化会话常为 **WDA HTTP 直连**，`WdaDriver` 无装/卸 API。
- **先装后测**：须在 `create(bundle_id)` 之前装好被测应用。
- **跨端用例一致**：在 Windows 上写的 iOS 用例，到 Mac 部署时装/卸路径不变。

Android 侧对称说明见 [Android 配置 §3.2](android.md#32-装卸与自动化分层)。

内置 go-ios 按宿主系统选用 `resources/re_go_ios/executable/{win,mac,linux}/`。

## 6. 启动顺序小结

### 6.0 Win/Linux — WDA-direct（推荐，无需 Appium）

1. （一次性）Mac/Xcode 编译签名安装 WDA → 设备信任证书。
2. 用例执行：`mobile_app_install_and_open`（设备层装 IPA）→ `AppiumManager.create()` 内部自动：
   - go-ios 用户态隧道（iOS 17+）
   - 挂载 DeveloperDiskImage
   - `runwda` 拉起 WDA
   - pymobiledevice3 转发 8100
   - 建 WDA HTTP session → `launch_app`
3. 步骤里的 `appium_start` **自动跳过**（识别 `__current_platform__=ios` 且后端为 WDA-direct）。
4. 后续元素/滑动/Alert 等关键字经 `WdaDriver` + `autopilot/mobile/ios/` 组件执行。

parity 骨架：`tests/ios_parity_skeleton.py`。

**离线 vs 真机（阶段 14）**

| 路径 | 命令 / 产物 | 是否需真机 |
|------|-------------|------------|
| 骨架自检 | `python tools/ios_parity_run.py --validate-only`；`python tools/ios_parity_diff.py --validate-only` | **否** |
| 相关单测 | `tests/test_*parity*`（若存在） | **否** |
| Win infra 采集 | 下文 `--host win --report logs/parity_win_wda.json` | **是**（已有样例：`logs/parity_win_wda.json`） |
| Mac↔Win / 双机 diff | `tools/ios_parity_diff.py` + 两侧 JSON | **是**（依赖已采集报告） |
| 定位符 / TEST002 用例层全量对齐 | 矩阵 ⚠️；非后端缺口 | **是**（依赖 App UI） |

无设备时只跑「离线」行即可验收工具链；勿把「未采 Win JSON」当成缺 runner。

**Mac 双真机 parity**（设备列表 → infra 单机签字 → 双机矩阵）：

```bash
python -m pymobiledevice3 usbmux list   # 列出 USB 连接的 iOS 真机与 UDID
python tools/ios_parity_run.py --udid <UDID> --infra-only --backend-mode wda
python tools/ios_parity_dual_run.py   # 默认 2 台 × wda+appium × 3 infra 用例
```

JSON 报告：`logs/parity_<udid>_<backend>_<ts>.json`（单机）、`logs/parity_dual_<ts>.json`（双机矩阵）。

**Win 侧 parity 采集**（供 Mac vs Win diff）：

```powershell
.venv\Scripts\python.exe tools\ios_parity_run.py --udid <UDID> --infra-only --backend-mode wda --host win --report logs\parity_win_wda.json
```

将 `parity_win_wda.json` 拷到 Mac 后与 Appium golden 或 Mac WDA 报告 diff。

**Mac vs Win diff**（Win 侧报告加 `--host win`）：

```bash
python tools/ios_parity_diff.py --preset mac-appium-vs-win-wda \\
  --left logs/parity_mac_appium.json --right logs/parity_win_wda.json
python tools/ios_parity_diff.py --dual logs/parity_dual_<ts>.json   # 双机 WDA 一致性
```

### 6.0.1 macOS — Appium golden（与 Win WDA-direct 对照）

1. （一次性）Xcode 编译签名安装 WDA → 设备信任证书。
2. go-ios 用户态隧道 → 挂镜像 → runwda → pymobiledevice3 转发 8100（与 Win 相同准备链）。
3. 启动 Appium（4723），caps **仅** `webDriverAgentUrl` + `udid`（**禁止** `usePreinstalledWDA`）。
4. 设 `IOS_APPIUM_MANAGED=0` 跑 golden / parity / TEST002 / Monkey。
5. `appium_start` **会**启动/检测本机 Appium。

反馈与逐步结果见 `logs/appium_golden_reference_feedback.yaml`。

### 6.0.2 原「逐步手动」序列（排障参考）

**已验证可行的精确序列**（手动逐条执行稳定通；`ENABLE_GO_IOS_AGENT=user`）：

```bash
set ENABLE_GO_IOS_AGENT=user
# 1) 用户态隧道(--userspace 是关键开关，iOS17+ 免管理员)
ios tunnel start --userspace --tunnel-info-port 28100
# 2) 轮询就绪：ios tunnel ls --tunnel-info-port 28100  （出现 userspaceTun:true 即可）
# 3) 挂开发者镜像（go-ios 会按系统版本在线解析个性化镜像；内置 ddi-15F31d 适配 iOS 26.x）
ios image auto --basedir=resources/re_go_ios/devimages --udid <udid>
# 4) 拉起 WDA（保活进程；=-形参 + 传 USE_PORT）
ios runwda --bundleid=<WDA> --testrunnerbundleid=<WDA> --xctestconfig=WebDriverAgentRunner.xctest --udid <udid> --env USE_PORT=8100
# 5) 等 WDA 暖机 ~15s，再用 pymobiledevice3 转发（go-ios forward 在 17+ 给 error code3，不可用）
python -m pymobiledevice3 usbmux forward 8100 8100 --udid <udid>
# 6) curl http://127.0.0.1:8100/status  → 返回 WDA build 即就绪
```

要点（避坑）：
- **查 WDA bundle id**：`ios apps --list`（找 `WebDriverAgentRunner`，形如 `com.facebook.WebDriverAgentRunner.<team>.test.xctrunner`）。
- **转发必须用 pymobiledevice3**（`usbmux forward`），go-ios 自带 forward 在 iOS17+ 连不到 WDA:8100。
- **镜像不是版本不匹配问题**：`ddi-15F31d` 即 iOS 26.x 个性化镜像，`image auto` 会自动解析/复用；runwda 前务必先成功挂载，否则 WDA 起不来。
- **A18 / ApChipId 0x8140（iPhone 16 系）**：旧 `ddi-15F31d` 的 BuildManifest **不含**该芯片身份。`IosDevicePrep.ensure_image` 只挂载**芯片匹配**的本地镜像；若无匹配项则走 `go-ios image auto` / `pymobiledevice3 mounter auto-mount` **联网下载**到 `devimages/`（大体积 DDI 通常不进 Git）。需可访问 Apple 镜像源；离线环境请自行放入已含该芯片身份的个性化镜像。
- **Appium 必须能找到 xcuitest 驱动**：若 `appium driver list --installed` 有 xcuitest 但会话报 “Could not find a driver for XCUITest”，说明**正在跑的 server 实例启动早于驱动安装**，**重启 Appium server** 即加载。
- **稳定性（已解决）**：`ios_bootstrap.IosDevicePrep` 已内置健壮编排——开跑前回收 28100/60105 端口残留 agent、隧道存在则复用、每步就绪门控（隧道 `tunnel ls`、镜像挂载确认、runwda 存活、转发监听、轮询 `/status`）。实测可稳定把设备准备到 **WDA `/status` 200**。

### 后端分支（已实现）

装/卸与会话 **分层**：见上文 [§5.1](#51-装卸与自动化分层)。会话后端由 [`platform.py`](../../autopilot/keywords/mobile/platform.py) 决策：

| 目标      | Windows        | macOS     | Linux          |
|---------|----------------|-----------|----------------|
| Android | Appium         | 同         | 同              |
| iOS     | **WDA-direct** | Appium 默认 | **WDA-direct** |

- **WDA-direct**：[`wda_client.py`](../../autopilot/keywords/mobile/wda_client.py) + [`mobile/ios`](../../autopilot/mobile/ios/__init__.py) 组件层；`IosDevicePrep` 编排隧道/镜像/runwda/转发；session 404 recover；系统 Alert `/alert/accept`。
- **强制**：`backendMode=auto|appium|wda` 或 `IOS_BACKEND` / `IOS_BACKEND_MODE`。
- **WDA 证书**：设备上测试运行器须有效；过期会 runwda 失败，AutoPilot 预检 `ios apps --list` 并提示。

### Appium 在 Win/Linux + iOS 17+ 的限制

- WDA 设备准备（隧道→镜像→runwda→转发）在 Windows **可行**。
- Appium xcuitest 依赖 **appium-ios-remotexpc**（TUN/TAP），**未支持 Windows** → `RemoteXPC is not available`。
- **AutoPilot 已实现 WDA-direct 作为 Win/Linux 默认路径**；遗留用例中的 `appium_start` 会自动跳过。

> 参考：[appium-ios-remotexpc](https://github.com/appium/appium-ios-remotexpc)、[pymobiledevice3 iOS17 隧道](https://github.com/doronz88/pymobiledevice3/blob/master/docs/guides/ios17-tunnels.md)。

## 6.2 多设备并行（同平台）

AutoPilot 支持将用例 **round-robin** 分到多台同平台设备并行执行（IDE 弹窗或 `tools/run_suite.py --parallel`）。

要点：

- **每台 iOS 设备独立端口族**：WDA `8100+slot`、隧道 `28100+slot×10`、MJPEG `9100+slot`（见 [SETUP.md §2.4](../SETUP.md#24-同平台多设备并行可选)）；并行时每 slot 独立生成 `__appium_caps__`（`webDriverAgentUrl` 指向本机端口），避免首台 caps 串台。
- **Android** 通常共用单个 Appium Server（4723），靠不同 `appium:udid` 区分 session；IDE 弹窗会提示该约束。
- **失败隔离**（默认开）：某分片失败不停止其它设备；IDE 可取消勾选，CLI 用 `--kill-on-shard-fail`。
- **每台设备独立 go-ios 隧道**（`--tunnel-info-port` 按 slot 错开）；并行前确认无残留进程占用端口。
- 并行执行与 **控件检视器 / F6 单步调试** 互斥（避免抢设备）。
- 真机建议先用 2 台验证稳定性，再扩大并行数。

## 7. 常见问题

- **iOS 17+ 开发者服务连不上**：隧道没起或挂了——确认 `ENABLE_GO_IOS_AGENT=user` 且隧道 agent 在跑、端口已钉死。
- **`/status` 摸不到 WDA**：WDA 没 `runwda` 起来，或 8100 没转发；先 `runwda` 再 `forward`。
- **镜像未挂载**：按设备系统版本在 `resources/re_go_ios/devimages` 选对镜像后 `image auto`。
- **证书过期/不信任**：重新在「VPN与设备管理」里信任，或重编 WDA（免费账号 7 天过期）。
- **mobile 关键字报未实现**：未装 `mobile` 组，`pip install -e ".[mobile]"`。
- **`appium_start` 报未检测到 Appium**：Win/Linux 跑 iOS 时应自动跳过；若仍报错，确认用例平台（`platform: ios` 或步骤 `type: ios` / `.ipa`）已让执行器写入 `__current_platform__=ios`。
- **Appium 每次跑都卸载 WDA**：caps 里误设了 `usePreinstalledWDA`。Mac golden 路径只用 `webDriverAgentUrl`（见 [`build_ios_caps`](../../autopilot/mobile/ios_bootstrap.py)）。
