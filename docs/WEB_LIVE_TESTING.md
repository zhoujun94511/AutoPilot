# Web 双引擎真浏览器白盒测试

> Selenium（默认）+ Playwright（可选）共用同一套 HTML 夹具与关键字 API。  
> 夹具：`tests/fixtures/web_pw_suite.html`（HTTP 提供，非 file://）。

## 前置

| 引擎         | 依赖                                                                        |
|------------|---------------------------------------------------------------------------|
| Selenium   | 本机 Chrome + Selenium Manager 自动解析 chromedriver                            |
| Playwright | `pip install 'autopilot[web_playwright]'` 且 `playwright install chromium` |

开发环境建议：

```bash
pip install -e ".[dev,web_playwright]"
playwright install chromium
```

## 运行

```bash
# 双引擎 parametrized live（每条用例 selenium + playwright 各跑一遍，可用引擎自动 skip）
python -m pytest -p no:xonsh tests/test_web_live.py -q

# 等价于旧版分拆文件（已合并，勿再维护）：
# tests/test_web_selenium_live.py / tests/test_web_playwright_live.py

# 单元 + 假件（无需浏览器）
python -m pytest -p no:xonsh tests/test_web_engine.py tests/test_web.py -q
```

不可用时会 **skip**（无 Chrome / 无 playwright），不会误报 fail。

## 覆盖范围

- **主路径**：导航、cookie、元素读写、校验、手势、iframe、窗口、alert/confirm/prompt、图像、定位策略
- **负向矩阵**：wait 超时、verify 校验失败、combo 多选/坏索引、upload 缺文件、JS 异常、坏 cookie domain 等
- **引擎差异**：未找到元素 / 非 iframe 切换 → 统一 `KeywordError`；confirm/prompt 处理顺序不同（PW 须先预置 dismiss/prompt 再触发点击）

共用辅助：`tests/web_live_support.py`。

## 双仓同步

Web 执行面 `autopilot/keywords/web/*.py` 与 Platform `ap/keywords/web/*.py` **须字节一致**。

```bash
python tools/check_dual_repo_contract.py
# 输出含：dual-repo web keywords sync: OK
```

改关键字后同步示例：

```powershell
Copy-Item -Force autopilot\keywords\web\*.py `
  ..\Autopilot-Platform\autopilot_platform\ap\keywords\web\
```

## CI 建议

- **PR 门禁**：`test_web_engine.py` + `test_dual_repo_contract.py`（无浏览器）
- **Nightly / 手动**：`.github/workflows/web-live.yml` 跑双引擎 live（需 Chrome + playwright）
