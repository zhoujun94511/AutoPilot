# 控件检视器（Inspector）使用说明

写用例时用它**抓界面控件 → 拿定位符 → 一键填进步骤参数或写入对象库**。体验类似 Appium Inspector：
设备截图（可点选）+ 控件树 + 属性表 + 候选定位符（按稳定性排序）。基于**静态快照**（每次刷新更新，非实时视频）。

## 用法

1. 工具栏 **🔌 连接检视设备** → 选平台（Android / iOS / Web）、填 UDID（iOS 另填 WDA bundle id）。
   - Android：需 Appium server 在跑 + uiautomator2 驱动。
   - iOS：走内置直连 WDA（go-ios 隧道/runwda + pymobiledevice3 转发，见 [iOS 配置](setup/ios.md)）。
2. 右侧「🔍 控件检视器」面板点 **🔄 刷新快照** → 显示设备截图 + 控件树。
3. **点截图上的控件** 或 **点控件树节点** → 两侧联动高亮，右侧出属性表 + 候选定位符。
4. 选一条候选定位符 → **复制 / 填入步骤 / 写入对象库**：
   - 填入步骤：把定位符填进当前选中步骤的 `locator`/`element` 参数；
   - 写入对象库：在当前打开的 `.map` 里新建命名控件（返回 `map::文件::名` 引用）。

### Web 检视

「🔌 连接检视设备」选 **Web** → 填页面 URL + 浏览器（chrome/edge/firefox/headless）→ 刷新快照。
- **取源**：复用 Selenium WebDriver（独立检视会话），注入 JS 遍历**可见 DOM**，对每个元素读 `getBoundingClientRect()` 产出带边界的节点树（`inspector/web_snapshot.py`），+ `get_screenshot_as_png`。HTML 无坐标的问题由此解决。
- **坐标**：DOM 边界是 CSS 像素（视口坐标系），截图是设备像素，比例=`devicePixelRatio`，由面板按「截图宽 / 根节点宽(=`innerWidth`)」自动换算（与 iOS 点↔像素同理）。
- 复用同一面板/命中/双向高亮/落地动作，零改 UI。

## 候选定位符策略（按稳定性排序）

- **Android**：`resource-id`(唯一→`id::`) → `content-desc`/`text` 的 xpath → 绝对 xpath 兜底。
- **iOS（按会话后端分叉）**：
  - **WDA-direct**（Win/Linux 默认、检视器 `backend=wda`）：`predicate(label)` 首选 → `xpath(label)` → `predicate(name)` → `class-chain`（有 XCUI 类型时）→ 绝对 xpath。
  - **Appium iOS**（Mac 默认、检视器 `backend=appium`）：唯一 `name` → `predicate(name)` 首选 → `predicate(label)` → `class-chain` → 绝对 xpath。
  - 执行层 `find_element` 与检视器共用 `ios_strategies.py`；**link text 回退**在候选列表末尾以 `[运行时]` 标注（可填入用例，但不作首选）。
  - iOS WDA 可选 `strategy`：`auto|scrollview|xctest|w3c`（分页 carousel 用 auto）
- **Web**：`id`(唯一→`id::`/`css::#id`) → `data-testid`/`name`(唯一→`css::[..]`) → 唯一单 class(`css::.cls`) → `aria-label`/可点击元素文本 的 xpath → 绝对 xpath 兜底。
- 产出的都是执行引擎可直接用的前缀串（`id:: / name:: / predicate:: / class-chain:: / xpath:: / css::`）。

### iOS 定位前缀支持矩阵（执行层）

| 前缀              | WDA-direct | Appium iOS | 说明                                                                      |
|-----------------|------------|------------|-------------------------------------------------------------------------|
| `name::`        | ✅          | ✅          | accessibility id                                                        |
| `predicate::`   | ✅ 首选       | ✅ 首选       | NSPredicate                                                             |
| `class-chain::` | ✅          | ✅          | XCUI class chain                                                        |
| `xpath::`       | ✅ 兜底       | ✅          | 绝对/属性 xpath                                                             |
| `css::`         | —          | —          | 原生 Mobile 不适用                                                           |
| `picture::`     | ✅          | ✅          | 图像匹配；仅 **点击 / 存在校验 / 判断并点击** 消费。参数表「选择图片…」或检视器框选填入；`accuracy` 控制精确/模糊阈值 |

## 说明

- **只读快照**：仅读取 `page_source`/DOM + 截图，不注入、不代理、不录制 → 稳定、对被测无侵入。
## 实时交互镜像（📱 实时镜像面板）

**与控件检视器是两个独立面板，职责隔离**：控件检视器点屏幕=选控件取定位符（静态快照）；实时镜像点屏幕=操作真机。二者「点击语义」相反，故拆成两个面板互不干扰。

操作映射：单击→tap；**按住→长按(long_press)**；**双击→double_tap**；按住拖动→swipe；滚轮→scroll；键盘可见字符→文本输入；回车/退格/Esc→enter/delete/back。视图坐标→帧像素→**设备坐标**按 `control.resolution()`（Android=scrcpy 流尺寸；iOS=WDA window 点尺寸）÷帧像素自动换算，**越界点击（letterbox 黑边）钳到边界内**。控制调用走后台顺序队列，不阻塞 GUI（WDA 串行 ~0.8s 也不卡界面）。

**按钮组件化、按平台能力数据驱动**：面板按 `control.capabilities()` 只显示该平台能做的按钮——

| 能力键                    | Android(scrcpy)         | iOS(WDA)                          |
|------------------------|-------------------------|-----------------------------------|
| 返回/最近/通知栏/快捷设置/收起面板/旋转 | ✅                       | —                                 |
| 主屏                     | ✅(keycode)              | ✅(/wda/homescreen)                |
| 音量±/电源                 | ✅                       | ✅音量(/wda/pressButton)·电源→锁屏       |
| 锁屏/设备截图                | —                       | ✅(/wda/lock·pressButton snapshot) |
| 长按/双击/滑动/滚动/文本         | ✅                       | ✅                                 |
| 剪贴板写入(发送/粘贴)           | ✅(scrcpy SET_CLIPBOARD) | ✅(/wda/setPasteboard)             |
| 剪贴板读取                  | —                       | ✅(/wda/getPasteboard)             |

剪贴板行：把文本一键发送到设备剪贴板（Android 同时触发粘贴）/ 读取设备剪贴板（iOS）——写测试时往输入框灌数据很顺手。

控制通道（现成能力，载体由 Web 换成 PyQt）：
- **Android**：scrcpy 控制 socket（touch/text/keycode/scroll/back），无 socket 时回退 `adb shell input`。见 `_scrcpy_core` + `ScrcpyControlSink`。
- **iOS**：按会话后端选控制汇（`mirror_control_sink`）：
  - **WDA-direct**（Win/Linux 默认、Mac 强制 `wda`）→ `WdaControlSink`（WDA HTTP：tap→W3C `/actions`、swipe、文本→`/wda/keys` 等）。
  - **Appium**（Mac 默认 `auto`/`appium`）→ `AppiumControlSink`（复用 Appium driver 的 W3C actions）。
- 抽象 `ControlSink`（`inspector/stream/control.py`）与帧源 `ScreenSource` 对称解耦，面板只依赖抽象。
- **画面与控制正交**：Mac 上 AVFoundation 高帧画面可与 Appium 或 WDA-direct 控制并存；首帧到达后再建 WDA 控制会话。

## 实时画面源（帧）

帧源组件化、可插拔，工厂按平台+可用性自动选（`inspector/stream/factory.py`）：

| 平台      | 宿主 / 模式                        | 首选                                                   | 次选                    | 兜底           |
|---------|--------------------------------|------------------------------------------------------|-----------------------|--------------|
| iOS     | **macOS** + `auto` + helper 就绪 | **AVFoundation H.264**（`ios-avf-capture`，与 WDA 共存）   | WDA **MJPEG 9100**    | 截图轮询（`grab`） |
| iOS     | Win/Linux `auto`，或显式 `mjpeg`   | WDA **MJPEG 9100**（runwda 带 `MJPEG_SERVER_PORT` 并转发） | —                     | 截图轮询         |
| Android | 全平台                            | **scrcpy**（H.264）                                    | Appium MJPEG（若提供 URL） | 截图轮询         |
| Web     | —                              | 截图轮询（v2 计划 CDP screencast）                           | —                     | —            |

- 组件：`autopilot/inspector/stream/`（`base.ScreenSource` + `avf_source`/`mjpeg_source`/`polling_source`/`scrcpy_source` + `factory`）。
- **iOS Win/Linux 零 AVF**：无 Mac CoreMediaIO 路径，`IOS_MIRROR_SOURCE=auto` 等价 `mjpeg`。
- **Mac AVF 高帧**：需构建 `tools/ios_avf_capture/ios-avf-capture`（见 [setup/ios_avf_capture.md](setup/ios_avf_capture.md)）+ 可选 `pip install av`（PyAV 解码）；失败/断流默认回退 MJPEG 9100（`IOS_MIRROR_STRICT=1` 关闭回退）。
- **零额外依赖兜底**：MJPEG 9100 / 截图轮询全平台开箱即用。
- **scrcpy 高帧（Android）**：装 `pip install av adbutils` 且放好 `re_scrcpy/scrcpy-server.jar` 后，工厂自动启用；缺任一自动回退，不影响使用。
- 实现：采集+解码核心见 `autopilot/inspector/stream/_scrcpy_core.py`（精简：视频解码 + 控制下发，不含音频/WebRTC）——adb 推 server + reverse 隧道 → 读视频 socket → 解析 scrcpy 视频包（会话包随旋转更新分辨率,媒体包抽 H.264 访问单元）→ PyAV 解码 → 直接由帧平面字节构 `QImage`（不引入 cv2/PIL）。`scrcpy_source.ScrcpyScreenSource` 把它包成一个 `ScreenSource`。
- 视频包解析为纯静态函数 `ScrcpyCore.consume_packets`,已脱机单测（`tests/test_stream.py`）。
- 实现：`autopilot/inspector/tree.py`（解析+命中+定位符，纯逻辑）+ `ui/widgets/inspector_panel.py`（面板）。
