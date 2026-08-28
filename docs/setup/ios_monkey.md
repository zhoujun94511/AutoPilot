# iOS Monkey 稳定性测试

> 关键字 **`mobile_monkey`**（`platforms="android ios"`）在 iOS 上走 `autopilot/mobile/ios/monkey/` 自建引擎，**不是** adb monkey。  
> Android 仍为 `adb shell monkey`。边界总览见 [mobile-backend-boundaries.md §9](../mobile-backend-boundaries.md#9-ios-monkey2026-07)。

---

## 1. 快速开始

### 用例步骤（IDE）

1. `mobile_app_install_and_open` 或 `mobile_app_start`（建立 iOS 会话并启动被测 App）
2. `mobile_monkey` — 填 `monkeySteps`（必填），可选 iOS 专用参数（见下表）
3. 结束后：**帮助 → 打开 Monkey 报告**（优先 HTML）

### 独立 CLI

```bash
python tools/ios_monkey_run.py --udid <UDID> --bundle-id com.example.app \
  --ipa path/to/app.ipa --monkey-steps 80 --monkey-policy safe --backend-mode wda

# 按时长跑（最多 6h），50 步为安全上限
python tools/ios_monkey_run.py --udid <UDID> --bundle-id com.example.app \
  --duration-sec 3600 --monkey-steps 200
```

---

## 2. 架构

```
mobile_monkey (misc.py)
  → run_ios_monkey (engine.py)
    → prepare_monkey_appium_session  # Mac Appium：newCommandTimeout=0
    → create_monkey_driver           # WdaMonkeyDriver | AppiumMonkeyDriver
    → IOSMonkeyEngine.run()
    → DeviceLogCollector + report.html
```

| 组件            | 路径                                      |
|---------------|-----------------------------------------|
| 引擎            | `autopilot/mobile/ios/monkey/engine.py` |
| 策略/权重         | `policy.py`                             |
| WDA/Appium 适配 | `wda_driver.py` / `appium_driver.py`    |
| Watchdog      | `watchdog.py`（`ensure_monkey_stack`）    |
| Appium 会话加固   | `session_prep.py`                       |
| 设备日志          | `device_logs/`                          |
| CLI           | `tools/ios_monkey_run.py`               |

**双后端**：Win/Linux 默认 **WDA-direct**；Mac 默认 **Appium**。共用同一套 `IOSMonkeyEngine`。

---

## 3. 关键字参数（IDE 与 XML 同步）

Android 仅显示 `monkeySteps`（`step_param_rules.py` 按平台灰显 iOS 专用项）。

| 参数 id               | 平台  | 说明                                          |
|---------------------|-----|---------------------------------------------|
| `monkeySteps`       | 全平台 | 20–200；iOS 纯步数=上限；有 `durationSec` 时为**安全帽** |
| `durationSec`       | iOS | >0 按时长跑（最长 6h），与步数**先到先停**                  |
| `throttleMs`        | iOS | 事件间隔 + 随机抖动                                 |
| `monkeyPolicy`      | iOS | safe / balanced / aggressive                |
| `seed`              | iOS | 复现随机路径                                      |
| `collectDeviceLogs` | iOS | 是否采集 syslog/crash                           |
| `deviceLogsBackend` | iOS | auto / go-ios / pmd3 / off                  |
| `syslogMode`        | iOS | full / ostrace（长跑推荐 ostrace）                |
| `reportHtml`        | iOS | 是否生成 `report.html`                          |

定义来源：`autopilot/metadata/keyword_defs/mobile.xml` → `mobile_monkey`。

---

## 4. 停止条件

- **仅步数**：执行 `monkeySteps` 次事件后结束
- **时长 + 步数**：`durationSec` 到期 **或** 达到 `monkeySteps`（先到先停）
- **失败**：连续 3 次动作异常 → 关键字 FAIL

Crash 增量采集**默认不**把结果判为 FAIL（可作附加信号查看报告）。

---

## 5. 产出物

目录：`logs/ios_monkey/<timestamp>[_udid]/`

| 文件                   | 说明                   |
|----------------------|----------------------|
| `events.jsonl`       | 逐步事件 JSON            |
| `summary.json`       | 汇总（seed、backend、计数）  |
| `report.html`        | 自包含 HTML 时间线         |
| `errors/event_XXXX/` | 异常现场（截图、page_source） |
| `device/`            | syslog、crash 增量等     |

指针：`logs/ios_monkey/latest.json`（IDE 帮助菜单读取）。

---

## 6. 全局设置（`~/.autopilot/settings.json`）

未在步骤填写的项回退到 settings，例如：

- `ios_monkey_throttle_ms` / `ios_monkey_throttle_jitter_ms`
- `ios_monkey_source_interval`（降频 page_source）
- `ios_monkey_policy`
- `ios_monkey_device_logs_*` / `ios_monkey_report_html`

---

## 7. 资源与互斥

- Monkey 结束**不关闭** WDA 隧道 / mobile driver，后续步骤可复用会话
- 仅停止本模块拉起的 syslog 子进程
- 长跑占设备；与同平台多机并行、检视器争用设备时注意互斥（见 SETUP §2.4）

---

## 8. 故障排查

| 现象                                  | 处理                                                   |
|-------------------------------------|------------------------------------------------------|
| 无法解析 Bundle ID                      | 先 `mobile_app_install_and_open` / `mobile_app_start` |
| Appium `session terminated`（Mac 长跑） | 已自动 `newCommandTimeout=0` + 启动时刷新会话；仍失败看 watchdog 日志 |
| WDA 端口不可达                           | watchdog 会 `prep.prepare()` 重建；检查 go-ios 隧道          |
| 报告目录空                               | 确认 `__project_path__` 已设（打开工程）                       |
| 设备日志过大                              | `syslogMode=ostrace` 或 `collectDeviceLogs=false`     |

---

## 9. 相关文档

- [mobile-backend-boundaries.md §9](../mobile-backend-boundaries.md#9-ios-monkey2026-07)
- [ios.md](ios.md) — WDA / Appium 配置
- [SETUP.md](../SETUP.md) — 依赖矩阵
