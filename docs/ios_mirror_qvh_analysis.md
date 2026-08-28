# iOS 高帧镜像：QVH 踩坑复盘与 AVFoundation 方案

> 目的：记录 iOS 真机高帧镜像从 **ws-qvh / libusb** 路线到 **AVFoundation 原生采集**
> 路线的完整分析，说明为什么 QVH 在现代 macOS 上不可行、代码已被移除，避免后续再次
> 踩同一个坑。

## TL;DR

- **QVH（ws-qvh + `quicktime_video_hack` + libusb）在现代 macOS 上不可用**：系统的
  CoreMediaIO DriverKit 扩展（`com.apple.cmio.videodriverkithostextension`）会在
  iPhone 进入"屏幕镜像/QuickTime"模式后 **独占** 那个 USB 接口，libusb 无法 claim，
  报 `LIBUSB_ERROR_OTHER (-99)` / `kIOReturnExclusiveAccess`。
- 这是 **操作系统架构层面的冲突**，不是可以靠重试/加 `SetAutoDetach`/patch fork 绕过
  的 bug。继续在 libusb 层"抢接口"只会和 coremediad 互抢，越修越脆。
- **正解：走 Apple 官方支持的 AVFoundation。** iPhone 的 QuickTime 屏幕流在 macOS 上会
  暴露成一个 CoreMediaIO 采集设备（和 QuickTime Player「新建影片录制」选 iPhone 时同源）。
  用 AVFoundation 消费它 **不抢 USB**，因此与 go-ios/WDA 控制通道天然共存。
- 现方案：Swift helper `tools/ios_avf_capture/`（`ios-avf-capture`）采集 → VideoToolbox
  硬件 H.264 编码 → Annex-B 裸流 → Python `AvfScreenSource`
  （`autopilot/inspector/stream/avf_source.py`）用 PyAV 解码 → QImage。详见「流畅度/性能」节。
- **使用与排障手册**：[setup/ios_avf_capture.md](setup/ios_avf_capture.md)（构建、CLI、环境变量、Python 调用链）。

## 背景：想要什么

对标 `ws-scrcpy` 的体验——在 Mac 上对 iOS 真机做 **高帧率画面镜像 + WDA/Appium 控制并存**。
最初选型是移植 `ws-qvh`（QuickTime Video Hack over WebSocket，H.264），Python 侧用
`websocket-client` + `PyAV` 解码。

## QVH 失败链路（按发现顺序）

1. **首帧能出、但控制起不来。** QVH 抓到首帧后再拉 WDA，`runwda` 却退出、RSD 隧道失效。
   —— QVH 用 libusb 切换/占用 QuickTime USB 配置，打断了 go-ios 的 usbmux/RSD 隧道。
   为此一度在 WDA 启动前强制回收并重建 RSD 隧道（`after_qvh_usb` 机制）。
2. **ws-qvh 进程 fatal 崩溃**：`fatal msg="Error closing usb context"`。claim 接口失败时
   泄漏了 device handle，`ctx.Close()` 报 "devices still open" 直接 `log.Fatalf` 拖垮进程。
   patch：泄漏路径补 `defer` 关闭 handle；`discovery.go` 里 `ctx.Close()` 失败降级为
   `log.Warn`，不再让整个进程崩。
3. **`SetAutoDetach(true)` 反而更糟**：macOS 的 Darwin libusb 后端不支持
   `detachKernelDriver`，加上后 `gousb.Config()` 直接失败 `Could not retrieve config`。
   patch：删掉这行。
4. **根因浮出水面**：即便修好上面所有稳定性问题，claim QuickTime 接口仍稳定失败——
   `LIBUSB_ERROR_OTHER (-99)`，底层是 IOKit 的 `kIOReturnExclusiveAccess`。加了 15 次
   重试也只是和 macOS 的 `coremediad` 互抢，赢不了：**该接口已被 CoreMediaIO DriverKit
   扩展独占持有**。

### 为什么这是"不可逾越"的瓶颈

现代 macOS（尤其 iOS 11+ 设备进入屏幕镜像模式后）把 iPhone 的 QuickTime H.264 流交给系统
的 CoreMediaIO DriverKit 扩展统一管理，对外只以 **采集设备（capture device）** 的形式暴露。
用户态 libusb 想直接 claim 那个 USB 接口，等于和内核扩展抢独占资源——设计上就不允许。
`ws-qvh` 诞生于更早的 macOS，那时还能用 libusb 直接抓；如今这条路被 OS 关死了。

结论：**不要再试图用 libusb / `quicktime_video_hack` 在 macOS 抓 iOS 屏幕。** 想改都改不动，
方向就是错的。

## 正解：AVFoundation 原生采集

既然系统把流封装成了 CoreMediaIO 采集设备，就用 Apple 官方的 AVFoundation 去消费它。

- **不抢 USB**：消费的是系统采集设备，不 claim USB 接口 → 与 go-ios/WDA 控制并存，
  不再需要 `after_qvh_usb` 那套隧道重建。
- **要点**：
  - 先启用隐藏的 iOS 屏幕采集 DAL/CoreMediaIO 设备（设置
    `kCMIOHardwarePropertyAllowScreenCaptureDevices = 1`），iPhone 才会出现在设备列表里。
  - **TCC 相机权限**：AVFoundation 采集需要相机权限；首次运行会弹权限申请，未授权则
    设备枚举为空/阻塞。见"排障"一节。
- **数据通路**：Swift helper 采帧 → CMSampleBuffer(CVPixelBuffer) → VideoToolbox 硬件 H.264
  编码 → Annex-B 裸流写 stdout；Python 侧用 **PyAV** 解码成 QImage（不再走 websocket-client）。

### 帧流协议（helper → Python）

```
[magic "AVFH" 4 字节，仅首次]  then  连续 Annex-B H.264 裸流
（00 00 00 01 起始码分隔的 NAL；SPS/PPS 在每个 IDR 前重发）
```

### 相关文件

| 角色                         | 路径                                               |
|----------------------------|--------------------------------------------------|
| Swift 采集 helper（源码 + 构建脚本） | `tools/ios_avf_capture/capture.swift`、`build.sh` |
| 构建产物                       | `tools/ios_avf_capture/ios-avf-capture`          |
| Python 帧源                  | `autopilot/inspector/stream/avf_source.py`       |
| 帧源工厂（选源优先级）                | `autopilot/inspector/stream/factory.py`          |
| 源策略 / 可用性 / 严格开关           | `autopilot/mobile/ios_mirror.py`                 |
| 镜像编排（生命周期/重试/回退）           | `autopilot/ui/main_window/device.py`             |
| 镜像面板（首帧→控制、UI 提示）          | `autopilot/ui/widgets/mirror_panel.py`           |

## 当前镜像编排（Mac iOS）

1. `auto`（默认）且 Mac + helper 就绪 → 走 AVFoundation 高帧；否则 → MJPEG 9100。
2. 高帧先出画面，**首帧到达后**再起 WDA/Appium 控制（`videoFirstFrame` → `_on_mirror_first_frame`，
   对齐 ws-scrcpy 顺序）。
3. 采集断流：先重启 helper（默认最多 3 次）；仍失败且允许回退 → **WDA + MJPEG 9100**。
4. 调试时设 `IOS_MIRROR_STRICT=1` **关闭 →MJPEG 自动回退**，便于暴露采集根因（生产默认回退）。

### 环境变量

| 变量                                     | 作用                          |
|----------------------------------------|-----------------------------|
| `IOS_MIRROR_SOURCE=auto\|mjpeg`        | 画面源意图（历史值 `qvh` 兼容为 `auto`） |
| `IOS_MIRROR_STRICT=1`                  | 调试：禁用高帧→MJPEG 自动回退          |
| `IOS_AVF_BIN=/path/to/ios-avf-capture` | 覆盖 helper 路径                |

## AVFoundation 选设备踩坑：muxed（屏幕） vs video（相机）

现代 macOS（尤其 Sequoia + Apple Silicon）上，一台 iPhone 通过 USB 会以**两种不同的
AVFoundation 设备**出现：

| 设备                             | mediaType    | deviceType          | 内容            | 现象                                                                                             |
|--------------------------------|--------------|---------------------|---------------|------------------------------------------------------------------------------------------------|
| **屏幕采集**（QuickTime 同源）         | **`.muxed`** | `.external`         | iPhone **屏幕** | 我们要的                                                                                           |
| Continuity Camera（iPhone 当摄像头） | `.video`     | `.continuityCamera` | 后置**摄像头**     | 手机显示"Connected to Mac camera list / Disconnect / Pause"，画面是摄像头（对着桌面就全黑），常见 1920×1080/1920×1440 |

**坑**：用 `AVCaptureDevice.DiscoverySession(deviceTypes:[.external], mediaType: nil, ...)`
会优先枚举到 **Continuity Camera**，于是抓到的是摄像头而不是屏幕（黑屏/桌面画面）。

**正解**：发现设备时必须按 **`mediaType: .muxed`** 过滤——这才是 iPhone 屏幕流，QuickTime
和所有可用的 USB 录屏工具都是这么区分的。屏幕 muxed 设备的 `uniqueID` 未必等于 go-ios 的
UDID，所以 helper 里先按 UDID 匹配、匹配不到则取第一个 muxed 设备，**绝不回退到相机**。

**其它注意**（来自 [CodeJam 2025](https://www.codejam.info/2025/06/usb-iphone-screen-recording-swift.html)
及 Apple 开发者论坛）：
- 设置 `kCMIOHardwarePropertyAllowScreenCaptureDevices` 后设备**不会立刻出现**，需要几秒；
  且必须先跑一次 `DiscoverySession`（哪怕返回 0 个）来"预热"，否则连接通知永不触发。
- 该属性**有速率限制**，频繁开关可能导致设备最长 60s 才可见——不要反复 toggle。
- 少数机器需要先在 QuickTime「新建影片录制」里选一次 iPhone，屏幕 muxed 设备才会冒出来。
- 不要强设 `sessionPreset` 或 `activeFormat`：会把竖屏塞进黑色 1920×1080 横屏占位帧。

### ⚠️ 最大的坑：主线程必须跑 run loop（否则 muxed 设备永远 0 个）

muxed 屏幕设备是**异步注册**的：设完 `AllowScreenCaptureDevices` + 预热 `DiscoverySession`
后，CoreMediaIO 要通过 `AVCaptureDeviceWasConnected` 通知把设备投递上来，而**通知/Timer
都依赖主线程 run loop 在跑**。

早期 helper 用 `Thread.sleep` 死循环轮询、之后才 `dispatchMain()`——轮询期间 run loop 根本
没跑，CoreMediaIO 无法注册/投递设备，于是 `mediaType: .muxed` 永远返回空，只剩 Continuity
Camera（表现为「no iOS screen (muxed) capture device found / 只暴露相机」）。而且
**`dispatchMain()` 只跑 libdispatch 主队列，不跑 CFRunLoop**，`Timer` 也不会触发。

正确姿势（见 `tools/ios_avf_capture/capture.swift`）：
1. `enableScreenCaptureDevices()`；
2. 跑一次预热 `screenDevices()`（期望返回 0）；
3. 注册 `AVCaptureDeviceWasConnected` 观察者（`queue: .main`），设备出现即开采集；
4. 再挂一个 `Timer`（`RunLoop.main`）兜底轮询 + 超时（~25s 没设备就报错退出）；
5. 用 **`RunLoop.main.run()`**（不是 `dispatchMain()`）把主 run loop 跑起来；采集开始后
   Timer 不 invalidate，留作心跳，避免 run loop 提前返回拆掉会话。
   帧投递在独立的 `avf.samples` dispatch 队列上，不受影响。

## 流畅度/性能：为什么走 H.264 硬件视频流（而不是逐帧 JPEG）

**结论先行**：逐帧 JPEG 传输本质等同 WDA 的 9100 MJPEG——只是 fps/分辨率高一点的「同类物」，
形式上没有质变，白绕一圈。AVFoundation 唯一值得的理由是拿到**真·视频流**。所以采集 helper
最终改为 **VideoToolbox 硬件 H.264 编码 + PyAV 解码**（见 `capture.swift` / `avf_source.py`）。

管线：`AVCaptureVideoDataOutput`（BGRA CVPixelBuffer）→ `VTCompressionSession` 硬件 H.264
（低延迟：`RealTime=true`、`AllowFrameReordering=false` 无 B 帧、`MaxKeyFrameInterval` 有界）→
转 Annex-B（`00 00 00 01` 起始码，SPS/PPS 在每个 IDR 前重发）→ stdout 管道 → Python `PyAV`
解码 → 按 `avf_max_width` swscale 下采样 → QImage → 现有 QGraphicsView / 点击控制不变。

为什么这样才丝滑：
1. **硬件时域压缩**：H.264 轻松跑满 60fps；JPEG 是逐帧全量编码，3.6MP 逼近 16ms 预算撑不满。
2. **管道带宽骤降**：每帧从数百 KB（JPEG）→ ~10-50KB（H.264 P 帧），管道几乎不会积压。
3. **单帧在途背压**：`StreamWriter.canAccept()` 只在上一 access unit 写完后才接受新输入帧；
   消费端卡顿时**丢输入帧**（H.264 流仍合法，只是降 fps），延迟钉死在 ~1 帧。
4. **解码后下采样**：Swift 按原生分辨率编码（编码便宜），下采样放到 Python 端 swscale，
   控制解码 + GUI 上传成本。点击坐标按帧尺寸比例映射，下采样不影响精度。

协议 magic：`AVFH`（区别于旧 JPEG 的 `AVFJ`）。可调 env：`IOS_MIRROR_MAX_WIDTH`
（0=原生最清晰但解码/上传最重）、`IOS_MIRROR_BITRATE`（bps）、`IOS_MIRROR_FPS`（15~60）。

坑：
- **VideoToolbox 输出是 AVCC**（4 字节大端长度前缀的 NAL），必须转 Annex-B 起始码 PyAV 才认。
- **分辨率会变**：iPhone 屏幕设备可能先给占位尺寸再切原生，`VTCompressionSession` 尺寸固定，
  须在帧尺寸变化时重建 session（`H264Encoder.recreate`）。
- **PyAV 与 OpenCV(cv2) 各自打包 ffmpeg dylib**，同进程加载会打印 `AVFFrameReceiver ... implemented
  in both` 警告。只影响 `avdevice`（设备输入），我们只用 `avcodec` 解码裸流，无实际影响。

> 若还要再进一步（真正零拷贝、零解码，几乎零 CPU）：Swift 侧直接 `AVSampleBufferDisplayLayer`
> 显示，或把 CVPixelBuffer 经 IOSurface 共享给 UI 用 GPU 直显。需 pyobjc + 原生视图嵌入 Qt +
> 点击透明浮层，改造更大，暂留作后续选项。

## 排障

- **AVFoundation 列不出 iPhone / 卡住**：多半是 **TCC 相机权限** 没给。首次运行会弹系统权限
  申请；授权后（系统设置 → 隐私与安全性 → 相机）再重试。
- **设备列表为空**：确认已启用屏幕采集设备（`AllowScreenCaptureDevices`），并且 iPhone 已解锁、
  已"信任此电脑"。
- **采集日志**：`~/.autopilot/logs/avf-capture.log`。
- **画面出了但控制没起**：看是否卡在首帧（`_wait_first_frame`）；确认 WDA/go-ios 隧道正常。
- **`runwda` 退出、日志 `could not connect to RSD … connection refused`**：go-ios 用户态 RSD
  隧道没起来。常见根因是**上一次运行退出没清干净**，遗留的隧道/agent/转发进程霸占端口
  （`ios` 进程占 28100/60105、`python` 占 8100/9100），新会话复用了「进程在、RSD 代理已死」
  的陈旧隧道。`tunnel_running()` 只看 `tunnel ls`、看不出这点。
  - 排查：`lsof -nP -iTCP -sTCP:LISTEN | grep -E "28100|60105|8100|9100"`，有残留就 `kill -9`。
  - 已加固：`prepare()` 在无可复用 WDA 时**一律硬回收残留 + `ensure_tunnel(force=True)` 干净
    重建**；`reclaim(hard=True)` 现也清 `wda_port`/`9100` 的陈旧转发。
- **交互式镜像控制 `A session is either terminated or not started`**：Appium 默认 60s 空闲杀
  session。镜像控制会话已单独设 `appium:newCommandTimeout=0`（**仅镜像**，检视快照沿用默认）。

## 教训

1. **先判断是不是 OS 层面的架构冲突，再决定修不修。** QVH 的问题不是稳定性 bug，而是
   "libusb 抢一个被内核扩展独占的接口"这一方向本身错了。花在 patch fork 上的时间，本可更早
   转向 AVFoundation。
2. **优先用平台官方支持的能力**（AVFoundation / CoreMediaIO），而不是逆向/抢占底层资源——
   前者与系统协作，后者与系统对抗。
3. 已移除的 QVH 相关代码：`autopilot/mobile/qvh_runner.py`、
   `autopilot/inspector/stream/qvh_source.py`，以及 `ios_bootstrap` 里的 `after_qvh_usb`
   隧道重建机制、`ios_mirror` 里的一众 `qvh_*` 函数/常量。历史 fork 补丁位于仓库外
   `~/src/ws-qvh-renovation/`（仅存档，不再使用）。
