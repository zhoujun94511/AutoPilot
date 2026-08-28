# Android 配置

Android 关键字基于 **Appium**（uiautomator2 driver）。先完成 [公共环境](../SETUP.md#2-公共环境)。

## 1. Python 依赖

```bash
.venv/Scripts/python.exe -m pip install -e ".[mobile]"   # Appium-Python-Client + pyaxmlparser
# 图像点击（picture::）/截图比对额外需要：
.venv/Scripts/python.exe -m pip install -e ".[image]"
```

- `pyaxmlparser` 用于解析 APK（取 package/activity/版本），**替代 aapt**，无需 Android SDK build-tools。实现见 [`autopilot/mobile/apk.py`](../../autopilot/mobile/apk.py)。

## 2. adb（内置自举，通常零配置）

AutoPilot 自带 adb，无需单独安装：

- 解析顺序（见 [`autopilot/mobile/adb.py`](../../autopilot/mobile/adb.py)）：
  1. 环境变量 `ADB_PATH` / `ADBUTILS_ADB_PATH`；
  2. 系统 `PATH` 上已有的 `adb`（尊重你的工具链）；
  3. 都没有 → 从 `resources/re_adb/platform-tools-latest-<os>.zip` 解压到 `resources/runpath/` 并前插 PATH。
- 解析到的目录会注入 PATH，供 Appium 子进程继承。

验证设备连通：

```bash
adb devices            # 已在 PATH；或用解压后的 resources/runpath/.../adb
```

## 3. Appium Server + uiautomator2 driver

Appium 需要 **Node.js**。

```bash
# 1) 安装 Appium（Node ≥ 18）
npm install -g appium

# 2) 安装 Android 驱动
appium driver install uiautomator2

# 3) 启动 server（默认 http://127.0.0.1:4723）
#    Mac：Appium **服务进程**需 ANDROID_HOME（UiAutomator2 驱动读 SDK）
export ANDROID_HOME="$HOME/Library/Android/sdk"   # macOS Android Studio 默认
export ANDROID_SDK_ROOT="$ANDROID_HOME"
appium

# 4) 环境体检（可选）
npm install -g @appium/doctor && appium driver doctor uiautomator2
```

> Appium 还需要 **JDK 17+**（设 `JAVA_HOME`）。一键确认 JDK/Node/Appium/驱动/服务是否齐：
> `.venv/Scripts/python.exe tools/preflight.py`（[5] 段），缺驱动可 `tools/preflight.py --install-drivers`。

### 3.1 「设备侧 apk」≠「宿主侧驱动」（别混淆）

uiautomator2 在两层各有一份东西，**不能互相替代**：

| 层       | 是什么                                                 | 在哪                            |
|---------|-----------------------------------------------------|-------------------------------|
| **宿主侧** | `appium driver uiautomator2`（Node 驱动，跑在电脑上）         | `npm`/`appium driver install` |
| **设备侧** | `io.appium.uiautomator2.server(.test)` 等 apk（跑在手机上） | 建会话时由上面那个驱动自动推到设备             |

仓库里的 `resources/re_uiautomator/app-uiautomator*.apk` 是**设备侧** server 的副本（来自参考工程），**当前代码并不直接引用**——Android 走 Appium 时，宿主侧 uiautomator2 驱动会携带并安装它自己那份。所以即使 `resources/re_uiautomator` 在位，仍必须安装**宿主侧** `appium driver install uiautomator2`。

AutoPilot 侧通过执行上下文传入 Appium server 与 caps（见 [`mobile/session.py`](../../autopilot/keywords/mobile/session.py)、[`mobile/driver.py`](../../autopilot/keywords/mobile/driver.py)）：
- `__appium_server__`：server 地址（默认 `http://127.0.0.1:4723`）；
- `__appium_caps__` / `__device_udid__`：附加 capabilities 与设备序列号；
- **`appium_start`**：Android 用例会启动/检测本机 Appium（4723）；iOS 在 Win/Linux WDA-direct 模式下自动跳过（见 [iOS 配置](ios.md)）；
- `app_start(type, packageName, activityName, udid)`：`packageName` 为空时附着到前台应用。

## 3.2 装卸与自动化分层

（Windows / macOS / Linux 行为一致。）

被测应用的 **安装、卸载** 刻意 **不经过 Appium** `install_app` / `remove_app`，而在 **设备层** 用 adb 完成（[`autopilot/mobile/adb.py`](../../autopilot/mobile/adb.py)；关键字编排见 [`session.py`](../../autopilot/keywords/mobile/session.py)）：

| 关键字                           | 设备层实现                               | 之后                                         |
|-------------------------------|-------------------------------------|--------------------------------------------|
| `mobile_app_install_and_open` | `adb install`（支持 `-r` 保留数据 / 先卸载再装） | `AppiumManager.create()` 建 UiAutomator2 会话 |
| `mobile_app_adb_uninstall`    | `adb uninstall`（`-k` 可选保留缓存）        | 无需会话                                       |

原因简述：

1. **三端同一语义**：用例在 Windows 上编写，到 Mac/Linux 跑 Android 时行为一致（均 adb）。
2. **先装后测**：须在 `create()` 之前装好 APK，并支持 `keepData` 等细粒度策略。
3. **独立卸载**：可在未启动 Appium 时卸载被测包。

元素点击、截屏等 **会话内** 操作仍走 Appium；与装/卸分层。iOS 对应说明见 [iOS 配置 §5.1](ios.md#51-装卸与自动化分层)。

## 4. 真机注意事项

- **开启开发者选项 + USB 调试**；首次连接在手机上「允许 USB 调试」。
- **允许通过 USB 安装应用**：Appium 会安装 `io.appium.uiautomator2.server` 等辅助 apk。部分 ROM（MIUI/HyperOS）需在开发者选项里打开「USB 安装」「USB 调试(安全设置)」。
- **UIA2 初始化失败**（`instrumentation cannot be initialized`）：通常是旧版辅助 apk 残留，先卸载再重连：

```bash
adb uninstall io.appium.uiautomator2.server
adb uninstall io.appium.uiautomator2.server.test
adb uninstall io.appium.settings
```

> 实测：小米 HyperOS 设备已通过框架关键字端到端跑通；关键是打开上述 USB 安装安全设置。

## 5. 实时镜像 + 设备控制（scrcpy，可选）

「📱 实时镜像」面板可实时看屏并直接操作真机（点/拖/输入/返回·主屏·最近）。Android 走 scrcpy（H.264，低延迟），与 Appium 无关，单独依赖：

```bash
.venv/Scripts/python.exe -m pip install -e ".[mirror]"   # av(PyAV) + adbutils
```

- 设备侧 server 已内置：`resources/re_scrcpy/scrcpy-server.jar`，无需手装 scrcpy。
- 运行期：adb 推 server → reverse 隧道 → 读视频 socket → PyAV 解 H.264 → 帧；控制走 scrcpy 控制通道（无控制 socket 时回退 `adb shell input`）。
- 依赖/资源缺任一会**自动回退**到 MJPEG / 截图轮询，不影响使用。
- 实现见 `autopilot/inspector/stream/_scrcpy_core.py`，用法见 [控件检视器 / 实时镜像](../inspector.md)。

## 6. 真机 parity / 冒烟（Mac 已验证）

```bash
adb devices                                   # 列出在线 Android 设备与 serial
python tools/android_parity_run.py --serial <serial> --infra-only
```

报告：`logs/parity_android_<serial>_<ts>.json`。infra 用例 3 个：`android-device-meta`、`android-session-infra`、`android-package-meta`。

> 若报 `Neither ANDROID_HOME nor ANDROID_SDK_ROOT`：在**启动 appium 的终端**里 export SDK 路径后重启 appium；框架 `appium_start` 自启时也会注入 SDK（见 `android_env.py`）。

## 7. 验证

```bash
.venv/Scripts/python.exe tests/test_mobile.py    # 无真机时用 Fake 验证派发；有真机+Appium 可跑真实流程
.venv/Scripts/python.exe tests/test_apk_sdk.py   # pyaxmlparser 解析 APK
.venv/Scripts/python.exe tests/test_mirror.py    # scrcpy 控制报文编码 + 坐标映射（离线）
```

## 8. 常见问题

- **`adb devices` 空**：换数据线/口、确认已授权调试、`adb kill-server && adb start-server`。
- **Appium 连不上**：确认 `appium` 在跑、端口 4723、`__appium_server__` 一致。
- **mobile 关键字报未实现**：未装 `mobile` 组，执行 `pip install -e ".[mobile]"`。
