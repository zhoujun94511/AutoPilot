# Web（WebUI）配置

WebUI 关键字基于 **Selenium 4**。先完成 [公共环境](../SETUP.md#2-公共环境)。

## 1. 依赖

WebUI 的 `selenium` 已在**基础依赖**里（`pip install -e .` 即含）。图像识别类关键字（`picture::` 模板匹配、截图比对）需额外装 `image` 组：

```bash
.venv/Scripts/python.exe -m pip install -e ".[image]"   # opencv-python-headless + numpy
```

## 2. 浏览器与驱动

Selenium 4 自带 **Selenium Manager**：首次启动会按本机浏览器版本**自动下载匹配的 driver**（chromedriver / geckodriver / msedgedriver），通常无需手动管理。

要求：
- 本机已安装对应浏览器（Chrome / Edge / Firefox）。
- 能联网让 Selenium Manager 拉取 driver（离线环境见下）。

### 离线 / 手动指定 driver

无外网时，手动下载与浏览器同版本的 driver，并让其可被发现：

- 把 driver 放进系统 `PATH`；或
- 设环境变量指向 driver（如 `chromedriver`），或在用例/配置里指定 driver 路径。

> 版本匹配原则：driver 主版本号需与浏览器一致。

## 3. 验证

```bash
# headless Chrome 真实跑一遍 Web 测试套
.venv/Scripts/python.exe tests/test_web.py
```

该套件用真实 headless Chrome 验证浏览器/元素/断言/等待等关键字。通过即说明 Selenium + driver 链路就绪。

## 4. Web 控件检视

「🔍 控件检视器」选 **Web**（填 URL + 浏览器）即可抓页面控件、取候选定位符并填入步骤/写入对象库。取源复用同一套 Selenium（独立检视会话），定位符（id/css/xpath）在**浏览器内**校验唯一性后产出——无额外依赖。详见 [控件检视器](../inspector.md#web-检视)。

## 5. 常见问题

- **找不到 driver / 版本不匹配**：升级浏览器或让 Selenium Manager 重新解析；离线则手动放置同版本 driver。
- **headless 与有头行为不一致**：部分站点对 headless 有差异，可在浏览器选项里关掉 headless 调试。
- **图像类关键字报未实现**：未装 `image` 组，执行 `pip install -e ".[image]"`。
