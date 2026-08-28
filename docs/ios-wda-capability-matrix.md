# iOS WDA-direct 能力矩阵（相对 Appium iOS）

| 能力                                                        | Appium iOS                 | WDA-direct           | 组件/备注                                                      |
|-----------------------------------------------------------|----------------------------|----------------------|------------------------------------------------------------|
| 启动 Appium 服务（`appium_start`）                              | ✅ 需要                       | ⏭️ 自动跳过              | Win/Linux WDA-direct 无需 4723                               |
| 元素点击/输入/属性                                                | ✅                          | ✅                    | `wda_client.WdaElement`                                    |
| 应用 launch/activate/terminate                              | ✅                          | ✅                    | `ios/app_lifecycle.py`                                     |
| **`mobile_app_reset`（重启应用）**                              | ✅ 可无 bundle（会话级 `reset()`） | ✅ terminate+activate | 优先 driver bundle → 变量 `app_package` → 会话；仍无则明确报错           |
| `mobile_presskey`                                         | ✅                          | ✅                    | `ios/keys.py`；XML 已标双端                                     |
| `mobile_element_text_clear`（密码）                           | ✅ keycode                  | ✅ `/wda/keys` 退格     | `ios/keys.press_delete_keys`                               |
| `mobile_get_device_ip`                                    | 部分                         | ✅                    | WDA `/status` → `device_info.ip`；Android 仍 adb             |
| 上下文 NATIVE/WEBVIEW                                        | ✅                          | ✅                    | `ios/context_switch.py`                                    |
| 按方向滑屏（`mobile_swipe_direction`）                           | ✅                          | ✅                    | `ios/swipe.py` 三层：ScrollView swipe → XCTest drag → W3C     |
| 物理键 home/volume                                           | ✅                          | ✅                    | `ios/keys.py`                                              |
| WebView URL                                               | ✅                          | ✅                    | `ios/webview.py`                                           |
| WebView JS 点击                                             | ✅                          | ✅（失败回退 click）        | `ios/webview.js_click_element`                             |
| Session 404 恢复                                            | 部分                         | ✅                    | `find_element` 前 `ensure_wda_session`                      |
| MJPEG 镜像                                                  | Appium/截屏                  | ✅ MJPEG + 断流截图回退     | `mjpeg_source` + `grab` fallback                           |
| WDA /status 健康检查                                          | —                          | ✅                    | `ios/health.py`                                            |
| execute_script（通用）                                        | ✅                          | ✅ WebView            | `WdaClient.execute_script`                                 |
| 滚动至控件 `mobile_slip_for_element`                           | ✅                          | ✅                    | `ios/scroll.scroll_until_element_found` + scroll_into_view |
| 控件属性/校验 `mobile_element_get_element_attribute` / `verify` | ✅                          | ✅                    | `ios/attributes.py` Android 别名→XCUI                        |
| 无 appFile 解析包名                                            | ✅ dumpsys                  | ✅ Bundle ID          | `app_lifecycle.current_bundle_id` + ctx                    |
| `mobile_get_deviceinfo`                                   | ✅ getprop                  | ✅ `/status` 归一       | `ios/device_info.py`；`AndroidVersion`→`version`            |
| `mobile_element_swipe` / `swipe_login`                    | ✅                          | ✅                    | `ios/gesture.py`；WDA `/element/swipe`                      |
| `mobile_tap` / `mobile_longclick`                         | ✅                          | ✅                    | `ios/gesture.tap_at` / `long_press_at`                     |
| `ios_alert_*`                                             | ✅                          | ✅                    | `platforms="ios"` + `IOS_ONLY_KEYWORD_IDS` lint            |
| Android Activity/adb                                      | ✅                          | ❌                    | 平台 lint 标记 android-only                                    |
| 独立 H5 浏览器会话（`mobile_browser_*`）                           | ✅ browserName              | ❌                    | **android-only**；iOS 用 `native_web_swith_context`          |
| 网络 bitmask（`mobile_set_network`）                          | ✅                          | ❌                    | **android-only**                                           |

Mac 上可用 Appium iOS 作行为参考；Win/Linux iOS 17+ 以 WDA-direct 为主路径。真机 parity 对照见 `tests/ios_parity_skeleton.py` + `tools/ios_parity_run.py`（`--backend-mode wda|appium`）。

### Mac 双真机 parity（基础设施）

两台 iPhone 已 USB 连接时：

```bash
python -m pymobiledevice3 usbmux list          # 列出 USB 连接的 iOS 真机与 UDID
# 单机 infra（无 UI 控件依赖，推荐先跑通）
python tools/ios_parity_run.py --udid <UDID> --infra-only --backend-mode wda
python tools/ios_parity_run.py --udid <UDID> --infra-only --backend-mode appium
# 双机 × 双后端矩阵，报告 logs/parity_dual_<ts>.json
python tools/ios_parity_dual_run.py
```

`--infra-only` 用例（3 个）：`ios-alert-policy`、`ios-device-meta`、`ios-session-infra`。全量 7 用例含 UI 依赖步骤，需当前界面有对应控件。

预检：设备解锁、信任此 Mac、开发者模式；失败时可 `kill_goios_tunnel_agents` 后重试或加 `--skip-preflight`。

**Mac vs Win diff**：`tools/ios_parity_diff.py`（`--preset mac-appium-vs-win-wda` 或 `--dual` 对比双机 WDA）。

## Parity 结论（Mac Appium golden，2026-07-06）

来源：`logs/appium_golden_reference_feedback.yaml`、`logs/golden_reference_20260706.json`。

| 类别      | 项                                                                   | 结论                         |
|---------|---------------------------------------------------------------------|----------------------------|
| 基础设施 OK | go-ios runwda → webDriverAgentUrl；Appium 0.4s 建会话；Monkey 双端 passed  | ✅                          |
| 后端能力差异  | `mobile_app_reset` 无 bundle：Appium 会话级 reset vs WDA 从 ctx 解析 bundle | ⚠️ 仍建议用例显式维护 `app_package` |
| 用例/界面   | parity `OK` 按钮；TEST002 英文控件未命中                                      | ❌ 非后端问题                    |
| 代码修复    | `build_ios_caps` 去掉 `usePreinstalledWDA`                            | ✅ Mac 已修                   |

## 已签字（Win WDA-direct 真机 / 离线）

| 关键字/能力                              | 状态 | 备注                              |
|-------------------------------------|----|---------------------------------|
| `appium_start` 跳过                   | ✅  | iOS + WDA-direct                |
| `elementClick` + Alert 弱/强 hint     | ✅  | 离线 + TEST002 场景                 |
| `class-chain::` 解析                  | ✅  | context + driver + 检视器推荐        |
| `predicate::` 首选定位                  | ✅  | 检视器 WDA 顺序                      |
| `mobile_swipe_direction` onboarding | ✅  | xctest/scrollview 策略，TEST002 真机 |
| TEST002 全流程                         | ✅  | Win WDA-direct 1/1 通过           |
| 应用装/卸/启动                            | ✅  | TEST002 真机                      |

## 已签字（Mac Appium golden + 双端 Monkey，2026-07-06）

| 关键字/能力                               | 状态     | 备注                          |
|--------------------------------------|--------|-----------------------------|
| Appium smoke（webDriverAgentUrl only） | ✅      | 截图 ~2.6MB，WDA 不被卸载          |
| Monkey 60s safe Appium               | ✅      | 33 事件 / 0 错 / 0 crash / 61s |
| Monkey 60s safe WDA-direct           | ✅      | 28 事件 / 0 错 / 0 crash / 67s |
| TEST002 Appium                       | ⚠️ 0/1 | 前半 PASS；定位符与当前 App 界面不匹配    |
| parity 最小集                           | ⚠️ 0/3 | 会话 OK；UI 依赖步骤未命中            |

## 已签字（Mac 双真机 WDA infra + 同机 WDA/Appium，2026-07-07）

| 项                            | 状态              | 备注                                                   |
|------------------------------|-----------------|------------------------------------------------------|
| 双机 WDA infra（18.6.2 + 26.5）  | ✅ 3/3 × 2       | `logs/parity_dual_20260707_102718.json`              |
| 双机 WDA 逐步 diff               | ✅ 11/11         | `ios_parity_diff.py --dual`                          |
| 同机 WDA vs Appium infra（26.5） | ✅ 3/3 + diff OK | `driver_device_info` 经 WDA `/status`                 |
| parity infra 集（无 UI）         | ✅               | `ios-alert-policy` / `device-meta` / `session-infra` |
| parity 全量 7 用例               | ⚠️              | 含 `OK` 按钮等 UI 依赖步骤，待用例层对齐                            |
