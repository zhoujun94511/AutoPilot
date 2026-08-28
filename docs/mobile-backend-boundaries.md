# 移动端后端职责边界说明

这份说明用于统一 AutoPilot 当前移动端自动化链路的概念和边界，避免把执行链路、平台选择、UI 展示和 inspector 定位策略混为一谈。

## 1. 总体结论

当前项目不是“只有一条 Appium 链路”，而是按平台和宿主环境分成三种实际执行模式：

- Android + Appium/uiautomator2
- iOS + Appium/XCUITest
- iOS + WDA-direct

其中 `auto` 不是第三种后端，只是 iOS 的默认决策模式。

> **术语**：项目中**没有** `ios-direct` 模式；Win/Linux 默认的直连路径叫 **`WDA-direct`**（`backend=wda`）。
> **控制后端**（Appium / WDA-direct）与 **镜像画面源**（AVF / MJPEG 9100 / 截图轮询）是两条正交轴，勿混为一谈。

### 1.1 控制后端 vs 镜像画面源（正交）

| 维度              | 决策入口                                  | Android       | iOS @ Mac `auto`         | iOS @ Win/Linux `auto` |
|-----------------|---------------------------------------|---------------|--------------------------|------------------------|
| **控制/检视会话**     | `select_backend()`                    | Appium        | Appium + go-ios WDA      | WDA-direct             |
| **镜像画面（仅镜像面板）** | `resolve_mirror_source()` + `factory` | scrcpy → grab | AVF H.264 → MJPEG → grab | MJPEG → grab           |
| **镜像控制 Sink**   | `mirror_control_sink()`               | scrcpy        | AppiumControlSink        | WdaControlSink         |

环境变量：`IOS_BACKEND` / `IOS_BACKEND_MODE`（控制）；`IOS_MIRROR_SOURCE=auto|mjpeg`（画面，Mac `auto` 才尝试 AVF）。

## 2. 责任划分

### 2.1 `platform.py`

职责是决定后端模式。

- Android 默认返回 `appium`
- iOS 在 `auto/appium/wda` 之间选择
- 宿主为 Windows/Linux 时，iOS 默认走 `wda`
- 宿主为 Mac 时，iOS 默认可走 `appium`

这里不负责真正建会话，只负责选路。

### 2.2 `session.py`

职责是会话层和设备层动作。

- `appium_start` / `appium_stop`
- `mobile_app_start`
- `mobile_app_install_and_open`
- `mobile_app_adb_uninstall`（id 保留历史 adb 命名）
- 其它 Mobile 会话关键字

**`appium_start` 特殊规则（2026-07）**：当执行上下文已识别为 iOS 且 `select_backend` 结果为 `wda`（Win/Linux `auto`，或显式 `backendMode=wda`）时，**跳过**本机 Appium server 启动；仍同步 `__appium_server__` / `__appium_caps__`。Android 与 macOS+iOS+Appium 路径行为不变。

这里会把 iOS 的 `backendMode` 写入执行上下文，再交给 driver 层决定最终后端。

设备安装/卸载不依赖 Appium driver，本身属于设备层能力。

### 2.3 `driver.py`

职责是真正创建和管理移动端会话。

- Android 固定走 Appium/uiautomator2
- iOS 按 `backendMode` 和宿主环境选择 Appium 或 WDA-direct
- `backend` 会进入后续元素查找策略

这里是“执行分流”的核心位置。

### 2.4 `tree.py`

职责是根据 `platform/backend` 调整 inspector 里候选定位符的排序和推荐策略。

- 不决定会话怎么建
- 不决定平台怎么选
- 只做定位符生成结果的适配

### 2.5 `InspectorPanel`

职责是展示快照、属性、控件树和候选定位符。

- 显示 `平台：...`
- iOS 场景下显示 `Appium` 或 `WDA-direct`
- 使用 `platform/backend` 参与定位符生成

### 2.6 `CustomKeywordEditor`

职责是定义层关键字编辑。

- 只做静态参数可见性提示
- 使用 `visible_on_platforms` 这种定义期元数据
- 不读取运行时会话状态

## 3. 链路边界

### 3.1 Android

Android 的完整链路是：

`关键字` -> `session` -> `driver(Appium)` -> `uiautomator2`

特征：

- 只有 Appium 这一条执行链路
- inspector、执行、定位符推荐都按 Android/Appium 逻辑工作

### 3.2 iOS + Appium

iOS Appium 链路是：

`关键字` -> `session` -> `driver(Appium/XCUITest)` -> `WDA`

特征：

- 由 Appium 管理 WDA
- 更接近传统 Appium 生态
- 适合 Mac 宿主或强制 `backendMode=appium`

### 3.3 iOS + WDA-direct

iOS WDA-direct 链路是：

`关键字` -> `session` -> `driver(WDA-direct)` -> `WDA HTTP`

特征：

- 不依赖完整 Appium iOS 会话
- 更依赖 go-ios / pymobiledevice3 / WDA 转发
- 适合 Windows/Linux 宿主或强制 `backendMode=wda`

## 4. UI 规则

### 4.1 工程默认平台

工程默认平台应在新建工程时显式设置，并在新建用例时自动继承。

优先级：

1. 用例自身平台
2. 工程默认平台
3. 首次新建时弹窗确认

### 4.2 iOS backend 仅在 iOS 工程显示

`backendMode=auto|appium|wda` 只应该在 iOS 工程中出现。

Android 不显示这套后端切换入口，因为它不会进入 iOS backend 分流。

### 4.3 inspector 和 keyword editor 统一口径

两者都应该表达同一件事：

- 当前平台是什么
- 如果是 iOS，当前后端是 Appium 还是 WDA-direct

不要在一个地方写“Appium”，另一个地方只写“WDA”，第三个地方又写“backendMode”。

## 5. 当前已完成

- iOS backend `auto/appium/wda` 已进入执行链路
- Win/Linux iOS：`appium_start` 在 WDA-direct 模式下自动跳过
- inspector 和 keyword editor 已按平台统一展示
- 新建工程支持默认平台；新建用例可继承工程默认平台
- **关键字平台 Phase 1–3**：XML `platforms`、库灰显、用例/定位符/`map::` lint（保存/运行 WARNING）
- WebUI 关键字已标记 `platforms="web"`；Mobile android-only 约 19 个已标记

## 6. 后续增强项

- 更丰富的定义期条件表达式
- 更强的 inspector 文案统一
- 如需要，可把“平台规则”进一步抽成可复用的 UI 配置层

## 7. iOS 组件层（WDA-direct / Appium iOS 共用）

关键字层（`session.py` / `element.py`）只做薄封装；**生命周期、手势、物理键、上下文、WebView、Alert、Monkey** 等逻辑在 `autopilot/mobile/ios/`，按 `is_wda_backend()` / `driver_backend()` 分支，避免在关键字里散落 `if wda`。

### 7.1 WDA-direct 与 Appium iOS 对齐原则（2026-07）

| 策略                 | 说明                                                                       |
|--------------------|--------------------------------------------------------------------------|
| **组件层单入口**         | 新 iOS 能力优先加在 `mobile/ios/*`，WDA/Appium 双路径一起实现                           |
| **元数据与实现一致**       | 已实现双端的关键字不得标 `platforms="android"`（如 `mobile_presskey`）                  |
| **bundle 解析链**     | `app_package` / 会话 caps / `current_package` → `reset_app` / Monkey 共用    |
| **仍 android-only** | adb、Toast、`start_activity`、网络 bitmask、`mobile_browser_*` 独立会话等保持 lint 拦截 |
| **明确不支持**          | `WdaDriver.__getattr__` → `KeywordError`，执行记 FAIL 而非 NOIMPL              |

近期对齐项：`mobile_presskey`、`mobile_get_device_ip`（WDA `/status`）、密码框 `text_clear`（`/wda/keys` 退格）、`mobile_app_reset`（ctx 变量补 bundle）、`mobile_element_combo_select`（iOS 原生点击点选）、`mobile_browser_*` / `mobile_set_network`（android-only 元数据 + 运行时守卫）、**属性映射/滚动至控件/无 appFile Bundle 解析**（`attributes.py` / `scroll_until_element_found`）、`ios_alert_*`（`platforms="ios"`）。

真机对照：`tests/ios_parity_skeleton.py` + `tools/ios_parity_run.py --backend-mode wda|appium`。Mac 双机矩阵：`tools/ios_parity_dual_run.py`；Mac vs Win diff：`tools/ios_parity_diff.py`。CI/离线：`python tools/ios_parity_run.py --validate-only` 或 `tests/test_mobile_p2_boundaries.py`。

`autopilot/mobile/ios/` 提供与后端无关的 iOS 操作组件，关键字层（`session.py`）只调用组件，不在关键字内散落 backend 分支：

| 模块                    | 职责                                                                                       |
|-----------------------|------------------------------------------------------------------------------------------|
| `runtime.py`          | 识别 wda / appium iOS                                                                      |
| `app_lifecycle.py`    | terminate / activate / launch / reset / is_installed                                     |
| `context_switch.py`   | NATIVE / WEBVIEW 上下文切换                                                                   |
| `scroll.py`           | 滚动至元素（WDA scroll / Appium ActionChains）                                                  |
| `swipe.py`            | 按方向滑屏三层策略：ScrollView swipe → XCTest drag → W3C（`mobile_swipe_direction` 的 `strategy` 参数） |
| `keys.py`             | 物理键（WDA pressButton / Appium mobile: pressButton）                                        |
| `picker.py`           | 原生下拉点选（勿对 WdaElement 用 Selenium Select）                                                  |
| `attributes.py`       | 控件属性读取（Android 别名 ↔ XCUI label/name/value）                                               |
| `device_info.py`      | WDA `/status` → mobile_get_deviceinfo 字段映射                                               |
| `gesture.py`          | 坐标 tap/长按、元素滑动、滑块水平滑                                                                     |
| `webview.py`          | WebView URL、JS 点击（失败回退 click）                                                            |
| `health.py`           | WDA `/status` 探活、`ensure_wda_session`                                                    |
| `session_recovery.py` | WDA session 失效检测与 recover 重试                                                             |
| `alert/`              | 系统权限 Alert 统一处理（WDA `/alert/*` + Appium `switch_to.alert`）                               |
| `monkey/`             | iOS 随机稳定性测试引擎（`mobile_monkey` iOS 分支）                                                    |

`wda_client.py` 扩展：terminate_app、contexts、scroll_into_view、session recover 钩子。

Phase 3 已接入：
- `find_element` / `screen_locate` 前调用 `ensure_wda_session`（WDA-direct）
- 镜像画面：Mac AVF H.264（`avf_source`）与 WDA 控制正交；MJPEG 断流自动回退 `grab`（`MjpegScreenSource.fallback_grab`）；AVF 断流先重启 helper（`build_avf_opts`），仍失败回退 MJPEG（`IOS_MIRROR_STRICT=1` 可禁用回退）
- `mirror_control_sink`：WDA-direct → `WdaControlSink`；Mac Appium → `AppiumControlSink`
- `tests/ios_parity_skeleton.py`：Mac Appium / Win WDA 对照用例骨架

## 8. iOS 系统弹框（2026-07）

系统权限类 Alert（WLAN、通知、相机等）与 App 内 onboarding 按钮（Allow/Next）是两类 UI：

- **系统 Alert**：走 `autopilot/mobile/ios/alert/`，WDA 主路径为 `/alert/text` + `/alert/accept`；Appium 走 `switch_to.alert`。
- **App 内按钮**：仍走普通元素查找（predicate/class-chain），**不要**误走 Alert API。

### 8.1 接入点

1. **装包/启动后**：`mobile_app_install_and_open` / `mobile_app_start` 建会话后 opportunistic 处理一次。
2. **步骤 FAIL 后**：`executor._run_step` 处理弹框并重试当前步骤 1 次（`ios_alert_retry_on_handled` 控制）。
3. **显式关键字**：`ios_alert_handle` / `ios_alert_exists` / `ios_alert_set_policy`。

### 8.2 配置（`~/.autopilot/settings.json`）

- `ios_alert_enabled`（默认 `true`）
- `ios_alert_policy`：`auto|accept|dismiss|ignore|strict`（默认 `auto`）
- `ios_alert_retry_on_handled`（默认 `true`）
- `ios_alert_record_unknown`（默认 `true`）

运行期可通过 ctx 变量 `__ios_alert_policy__` / `__ios_alert_enabled__` 覆盖。

### 8.3 约束

- WDA session **不得绑 bundleId**，否则系统 Alert 不在 page_source（真机实测）。
- 后端命名使用 `wda` / `appium` + `__mobile_backend_mode__`。
- 未知弹框采集目录：`logs/ios_alerts/<timestamp>/`（screenshot + xml + json）。

## 9. iOS Monkey（2026-07）

`mobile_monkey` 关键字双平台：`platforms="android ios"`。

| 平台      | 行为                                    |
|---------|---------------------------------------|
| Android | `adb shell monkey -p {pkg} {steps}`   |
| iOS     | `mobile/ios/monkey/` 随机稳定性引擎（WDA 主路径） |

### 9.1 架构

- 一套 `IOSMonkeyEngine` + `WdaMonkeyDriver` / `AppiumMonkeyDriver`
- 复用 `wda_swipe_by_ratio`、`IOSAlertHandler`、`app_state` Recovery
- **watchdog**：`ensure_monkey_stack`（WDA 探活 + Appium 会话重建）
- **Appium 长跑**：`session_prep.prepare_monkey_appium_session` 合入 `newCommandTimeout=0`
- **Bundle ID 从 ctx/会话解析**（`app_package` / `WdaDriver._bundle_id`），步骤 XML 不要求填 bundleId
- **WDA session caps 仍不绑 bundleId**（与 Alert/检视器一致）

### 9.2 参数

与 Android 共用 `monkeySteps`（20–200）。**iOS 始终解析步骤数为事件上限**；若 `durationSec>0` 则按时长跑，**时长与步骤数先到先停**（步骤数作安全帽，非忽略）。

| 参数                  | 说明                                      |
|---------------------|-----------------------------------------|
| `monkeySteps`       | 事件上限 20–200（纯步数模式或时长模式安全帽）              |
| `durationSec`       | iOS：>0 按时长跑（最长 6h），与 `monkeySteps` 取先到者 |
| `throttleMs`        | 基础间隔（默认 500ms）+ 随机 jitter               |
| `monkeyPolicy`      | safe / balanced / aggressive            |
| `seed`              | 随机种子，留空自动生成                             |
| `collectDeviceLogs` | 是否采集 syslog/crash（默认 true）              |
| `deviceLogsBackend` | auto / go-ios / pmd3 / off              |
| `syslogMode`        | full / ostrace（长跑推荐 ostrace）            |
| `reportHtml`        | 是否生成 `report.html`（默认 true）             |

前置步骤：`mobile_app_install_and_open` 或 `mobile_app_start`。Mac Appium 路径在 Monkey 启动时会合入 `appium:newCommandTimeout=0` 并刷新会话（与镜像控制策略一致）。

全局默认见 `~/.autopilot/settings.json`：`ios_monkey_throttle_ms`、`ios_monkey_source_interval` 等。

### 9.3 长跑优化（借鉴 Fastmonkey / Fastbot）

- **降频 page_source**：默认每 5 步或控件点击前才 dump（`source_interval`）
- **WDA watchdog**：每 10 步探活端口 + session 恢复（`watchdog.py`）
- **throttle jitter**：避免固定节拍

### 9.4 输出

`logs/ios_monkey/<timestamp>/events.jsonl`、`summary.json`；异常现场在 `errors/event_XXXX/`。

独立 CLI：`python tools/ios_monkey_run.py [--udid <UDID>] ...`。

**多进程并行自适应**：未指定 `--udid` 时，按已连接设备列表自动认领空闲真机（`.leases/` 文件锁 + PID 探活）；并自动分配 WDA/隧道/MJPEG 端口，两台终端同时启动即可各跑一台设备。

### 9.5 设备日志与 HTML 报告（Phase 3）

Monkey 结束后在报告目录追加：

| 路径                           | 说明                                 |
|------------------------------|------------------------------------|
| `device/syslog.raw.txt`      | 设备 syslog（go-ios 主路径，pmd3 回退）      |
| `device/syslog.filtered.txt` | 按 bundleId 过滤的子集                   |
| `device/crashes/new/`        | 跑后增量 crash（.ips）                   |
| `device/collection.json`     | 采集元数据                              |
| `report.html`                | 自包含 HTML（事件时间线 + 异常现场 + syslog 预览） |

**资源释放**：仅终止本模块启动的 syslog 子进程；**不**关闭 WDA 会话、go-ios 隧道/runwda 或 mobile driver，后续用例步骤可继续使用同一会话。

**配置**（`~/.autopilot/settings.json`）：

- `ios_monkey_device_logs_enabled`（默认 `true`）
- `ios_monkey_device_logs_backend`：`auto|go-ios|pmd3|off`
- `ios_monkey_report_html`（默认 `true`）

CLI：`--no-device-logs`、`--device-logs-backend`、`--no-report-html`、`--pre-case`、`--pre-steps`、`--pre-skip`、`--syslog-mode full|ostrace`。

UI：**帮助 → 打开 Monkey 报告**（读取 `logs/ios_monkey/latest.json`，优先打开 HTML，否则打开报告目录）。

`ostrace` 模式（go-ios）：设备侧按进程过滤，适合长跑；进程名默认取 bundleId 末段，可通过 `ios_monkey_ostrace_process` 覆盖。

Crash 增量仅作附加信号，**不**自动将 Monkey 结果判为 FAIL。

### 9.6 Mac Appium vs WDA-direct Monkey 对照（2026-07-06 真机）

同一设备（iOS 26.5）、同一被测 App（`imobile.broadcast.app`）、`safe` 策略、60s：

| 指标                | Appium (golden) | WDA-direct |
|-------------------|-----------------|------------|
| 结果                | passed          | passed     |
| 事件数               | 33              | 28         |
| errorCount        | 0               | 0          |
| crashNewCount     | 0               | 0          |
| stuckRecoverCount | 15              | 6          |
| durationSec       | 61              | 67         |
| seed              | 426878          | 54611      |

事件数差异来自**随机种子不同**，属正常波动；stuck 自恢复 Appium 略多，暂不视为后端缺陷。报告目录见 `logs/ios_monkey/20260705_235717_F2801C`（appium）、`logs/ios_monkey/20260706_000319_F2801C`（wda）。

Golden 采集摘要：`logs/appium_golden_reference_feedback.yaml`。

