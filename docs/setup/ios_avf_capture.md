# macOS iOS 高帧镜像：`ios-avf-capture` 使用说明

> **适用范围**：仅在 **macOS** 上对 **iOS 真机** 做实时镜像的高帧画面采集。  
> **不负责触控**：点击/滑动等控制仍走 WDA（Appium 或 WDA-direct），与画面链路正交。  
> **背景复盘**：为何不用 QVH/libusb、为何与 WDA 能共存，见 [ios_mirror_qvh_analysis.md](../ios_mirror_qvh_analysis.md)。

---

## 1. 它是什么

`tools/ios_avf_capture/` 提供的是一个 **Swift 原生可执行文件** `ios-avf-capture`，不是 Python 包，也不是 IDE 内嵌模块。

| 组件        | 路径                                         | 职责                                             |
|-----------|--------------------------------------------|------------------------------------------------|
| 源码        | `tools/ios_avf_capture/capture.swift`      | AVFoundation 采集 + VideoToolbox H.264 硬编        |
| 构建脚本      | `tools/ios_avf_capture/build.sh`           | `swiftc` 编译为 `ios-avf-capture`                 |
| Python 封装 | `autopilot/inspector/stream/avf_source.py` | `subprocess` 拉起 helper，PyAV 解码 → `QImage`      |
| 策略/路径     | `autopilot/mobile/ios_mirror.py`           | 何时走 AVF、`build_avf_opts()`、`avf_helper_path()` |
| 镜像编排      | `autopilot/ui/main_window/device.py`       | 首帧后建 WDA、断流重启、回退 MJPEG                         |

**调用关系（运行时）**：

```
AutoPilot IDE / 镜像面板
  → factory.make_source("ios", opts)     # opts 含 avf_capture / avf_helper / avf_unique_id …
    → AvfScreenSource（QThread）
      → subprocess.Popen(["ios-avf-capture", ...])   # 子进程，非 import Swift
      → 读 stdout：magic "AVFH" + Annex-B H.264
      → PyAV 解码 + 可选下采样（avf_max_width）
      → frame 信号 → MirrorPanel 显示
```

Python **不会**解释执行 `capture.swift`；必须先 `./build.sh` 生成二进制，再由 Python 以子进程方式调用。

---

## 2. 前置条件

### 2.1 系统与环境

- **macOS**（CoreMediaIO / AVFoundation 屏幕采集设备仅存在于 Mac）
- **Xcode Command Line Tools**（提供 `swiftc`）：`xcode-select --install`
- **iPhone 真机**：USB 连接、已解锁、已信任此电脑
- **相机权限（TCC）**：首次运行会弹系统「相机」权限；未授权则列不出 iPhone 屏幕设备（见 [§7 故障排查](#7-故障排查)）

### 2.2 Python 可选依赖

```bash
pip install av    # PyAV，用于 H.264 解码；通常随 pip install -e ".[mirror]" 安装
```

### 2.3 与 WDA 的关系

- AVF 消费的是系统 **CoreMediaIO 采集设备**（与 QuickTime「新建影片录制」同源），**不抢占** QuickTime USB 接口。
- 因此可与 **go-ios 隧道 + runwda** 并存：镜像默认 **先出画面，首帧后再建 WDA 控制会话**。
- 采集激活后 iPhone USB 配置会变化，AutoPilot 会通过 `capture_active()` **强制重建 RSD 隧道** 再 `runwda`。

---

## 3. 构建 helper

```bash
cd tools/ios_avf_capture
chmod +x build.sh    # 首次
./build.sh           # 默认输出：./ios-avf-capture
```

自定义输出路径：

```bash
./build.sh /usr/local/bin/ios-avf-capture
```

验证二进制：

```bash
ls -l tools/ios_avf_capture/ios-avf-capture
file tools/ios_avf_capture/ios-avf-capture   # 应显示 Mach-O arm64/x86_64
```

### 3.1 helper 路径解析（AutoPilot 自动）

`ios_mirror.avf_helper_path()` 按优先级：

1. 环境变量 **`IOS_AVF_BIN`**（绝对路径，可执行）
2. 仓库内 **`tools/ios_avf_capture/ios-avf-capture`**
3. **`PATH`** 中的 `ios-avf-capture`

---

## 4. 命令行接口（独立调试）

在 IDE 外也可直接运行 helper，便于排查权限与设备枚举问题。

### 4.1 列出采集设备

```bash
tools/ios_avf_capture/ios-avf-capture --list
```

输出为 JSON 数组，每项含 `name`、`uniqueID`、`modelID`。  
**iPhone 屏幕**设备的 `uniqueID` 通常等于设备 **UDID**；应使用 `--unique-id` 选中它，避免误选 **Continuity Camera**（连续互通相机 → 黑屏或摄像头画面）。

### 4.2 采集并写 H.264 到 stdout

```bash
tools/ios_avf_capture/ios-avf-capture \
  --unique-id <UDID> \
  --bitrate 12000000 \
  --fps 60 \
  > /tmp/test.h264
```

| 参数               | 默认         | 说明                           |
|------------------|------------|------------------------------|
| `--list`         | —          | 枚举设备后退出；stdout 为 JSON        |
| `--unique-id ID` | 空          | 按 UDID 精确选中屏幕设备（**推荐**）      |
| `--index N`      | 0          | 无 unique-id 时按 muxed 设备列表下标选 |
| `--bitrate BPS`  | `12000000` | VideoToolbox 目标码率            |
| `--fps N`        | `60`       | 编码帧率上限                       |

- **stdout**：先写 4 字节 magic **`AVFH`**，随后为 **Annex-B H.264** 裸流（`00 00 00 01` 起始码）。
- **stderr**：诊断日志（设备名、分辨率、错误）；AutoPilot 运行时追加到 `~/.autopilot/logs/avf-capture.log`。

用 `ffplay` 粗测（需去掉 magic 或从 IDR 起播，仅作参考）：

```bash
# 仅验证 helper 是否在写数据
tools/ios_avf_capture/ios-avf-capture --unique-id <UDID> 2>/dev/null | head -c 100000 > /tmp/snip.bin
```

---

## 5. 在 AutoPilot 中启用

### 5.1 IDE 镜像面板

1. 工具栏 **连接检视设备** → 平台选 **iOS**，填 UDID。
2. 打开 **实时镜像** 面板并开始镜像。
3. 默认 **`IOS_MIRROR_SOURCE=auto`**（或设置项等价）：Mac 且 helper 存在 → 走 AVF；否则 MJPEG 9100 或截图轮询。

成功时控制台/日志可见类似：

- `镜像走 AVFoundation 原生采集（CoreMediaIO，与 WDA 控制共存）`
- `AVFoundation 首帧 WxH`
- 首帧后：`正在建立 iOS WDA 控制会话…`

### 5.2 画面源 vs 控制后端（勿混）

| 维度     | 配置                                    | Mac 默认                         |
|--------|---------------------------------------|--------------------------------|
| **画面** | `IOS_MIRROR_SOURCE` / 设置项             | `auto` → AVF（helper 就绪时）       |
| **控制** | iOS backend `auto` / `appium` / `wda` | `appium` → `AppiumControlSink` |

Win/Linux **无 AVF**；`auto` 在画面侧等价 `mjpeg`。

### 5.3 环境变量（画面侧）

| 变量                     | 含义                                    |
|------------------------|---------------------------------------|
| `IOS_MIRROR_SOURCE`    | `auto`（Mac 尝试 AVF）\| `mjpeg`（强制 9100） |
| `IOS_AVF_BIN`          | 覆盖 helper 可执行文件路径                     |
| `IOS_MIRROR_MAX_WIDTH` | PyAV 解码后下采样宽度；默认 `1080`；`0`=原生分辨率     |
| `IOS_MIRROR_BITRATE`   | 传给 helper 的 `--bitrate`（bps）          |
| `IOS_MIRROR_FPS`       | 传给 helper 的 `--fps`（15–60）            |
| `IOS_MIRROR_STRICT=1`  | 调试：禁用 AVF 失败/断流后自动回退 MJPEG            |

编排逻辑见 `ios_mirror.build_avf_opts()` 与 `device._mirror_session()`。

---

## 6. 数据协议（Python ↔ helper）

```
┌─────────────────────────────────────────────────────────┐
│  ios-avf-capture (Swift 子进程)                          │
│  CoreMediaIO → AVCaptureSession → VTCompressionSession    │
└───────────────────────────┬─────────────────────────────┘
                            │ stdout (pipe)
                            ▼
              [ 'A','V','F','H' ]  ← 仅首次 4 字节
              Annex-B H.264 NAL 流（持续）
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│  AvfScreenSource (Python)                                │
│  select 读超时 5s → av.CodecContext("h264") → QImage    │
└─────────────────────────────────────────────────────────┘
```

- 编码端：**单帧在途背压**（`StreamWriter.canAccept()`），过载丢帧而非堆积延迟。
- 解码端：默认 `max_width=1080` 降低 GUI 上传成本；**点击坐标按帧尺寸比例映射**，下采样不影响触控精度。

---

## 7. 故障排查

| 现象                                  | 可能原因               | 处理                                                                   |
|-------------------------------------|--------------------|----------------------------------------------------------------------|
| `未找到 ios-avf-capture helper`        | 未构建                | `cd tools/ios_avf_capture && ./build.sh`                             |
| `缺少 PyAV`                           | 未装 `av`            | `pip install av` 或 `pip install -e ".[mirror]"`                      |
| `--list` 只有 Continuity Camera       | 屏幕 muxed 设备未注册     | 拔插 USB、解锁手机、信任电脑；或 QuickTime 新建影片录制选一次 iPhone                        |
| 黑屏 / 1920×1080 横条占位                 | 误选相机或未等到真屏         | 必须 `--unique-id <UDID>`；看 stderr / `avf-capture.log`                 |
| `camera permission denied`          | TCC 未授权            | 系统设置 → 隐私 → 相机 → 允许终端/Python/AutoPilot                               |
| 有画面无控制 / `could not connect to RSD` | 采集后隧道过期            | 正常应由 `capture_active()` 触发重建；仍失败时重连检视设备或 `IOS_MIRROR_STRICT=1` 单独查采集 |
| 长时间无操作画面冻结                          | 管道静默阻塞             | 已实现 5s 读超时 + 12s UI 看门狗 → 重启 AVF 或回退 MJPEG                           |
| 控制 `session terminated`             | Appium 空闲杀 session | 镜像控制路径已设 `newCommandTimeout=0`（仅镜像，检视仍 60s）                          |

**日志位置**：

- Helper stderr：`~/.autopilot/logs/avf-capture.log`
- IDE 总日志：`~/.autopilot/logs/autopilot_YYYYMMDD.log`

**手动二分**：

```bash
# 1) 设备能否被枚举
tools/ios_avf_capture/ios-avf-capture --list

# 2) helper 能否持续出流（另开终端，观察 stderr）
tools/ios_avf_capture/ios-avf-capture --unique-id <UDID> 2>&1 | head -20

# 3) 强制不走 AVF，验证 WDA 画面链路
export IOS_MIRROR_SOURCE=mjpeg
```

---

## 8. 断流恢复（AutoPilot 内置）

1. AVF 断流 → 最多 **3 次**重启 helper（`build_avf_opts` 含完整 UDID/码率参数）。
2. 仍失败且未设 `IOS_MIRROR_STRICT=1` → 回退 **WDA MJPEG 9100**（`_handoff_to_mjpeg`）。
3. 镜像面板 **12s 无新帧** 触发 `video_fallback` 回调上述逻辑。

---

## 9. 相关文档

| 文档                                                              | 内容                               |
|-----------------------------------------------------------------|----------------------------------|
| [inspector.md](../inspector.md)                                 | 检视器 vs 镜像、画面源矩阵、ControlSink      |
| [ios_mirror_qvh_analysis.md](../ios_mirror_qvh_analysis.md)     | QVH 废弃原因、AVF 方案设计复盘              |
| [mobile-backend-boundaries.md](../mobile-backend-boundaries.md) | 控制后端 vs 画面源正交表                   |
| [ios.md](ios.md)                                                | go-ios / WDA / Appium 全平台 iOS 配置 |
| [SETUP.md](../SETUP.md)                                         | 依赖矩阵与 `mirror` 可选组               |

---

## 10. 维护者备忘

- 修改 `capture.swift` 后需重新 `./build.sh`；CI/发布流程若打包 Mac 镜像能力，应把二进制构建或预编译产物纳入检查（`preflight` 可扩展检测 `ios-avf-capture` 是否存在）。
- 勿在 helper stdout 打印非协议数据（会破坏 H.264 解析）；诊断一律走 **stderr**。
- 历史 magic `AVFJ`（逐帧 JPEG）已废弃；当前为 **`AVFH` + H.264**。
