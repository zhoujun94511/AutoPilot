# 打包与图标（Windows / macOS / Linux）

品牌图标单一来源：`branding.draw_icon()`（程序化绘制）。运行期 `app_icon()` 优先用导出的
图片文件、无文件则回退绘制。导出三平台文件：

```bash
.venv/Scripts/python.exe tools/export_icon.py
```

产物（`resources/branding/`）：

| 文件               | 用途                                                 |
|------------------|----------------------------------------------------|
| `autopilot.png`  | 256×256 通用主图；Linux 启动器图标、README                    |
| `autopilot.ico`  | Windows 多尺寸(16/32/48/64/128/256)：.exe / 快捷方式 / 任务栏 |
| `autopilot.icns` | macOS `.app` 图标                                    |

同步（默认 `../Autopilot-Platform/autopilot_platform/frontend/public/brand/`；
可用 `AUTOPILOT_PLATFORM_ROOT`，兼容旧名 `AUTOPILOT_CONSOLE_ROOT`）：
Web 管理台 favicon / `BrandMark` 与 IDE **同一套图**，禁止前端另画「AP」字母标。

> 换 logo：改 `branding.draw_icon()` 后重跑导出脚本。代码调用点无需改动。

## 运行期图标已内建

`autopilot/app/application.py` 启动时已：

- `app.setWindowIcon(app_icon())` —— 窗口/Alt-Tab 图标（三平台）。
- `set_windows_app_id()` —— Windows 设 AppUserModelID，任务栏用本程序图标而非 python.exe。
- `app.setDesktopFileName("autopilot")` —— Linux 关联 `.desktop` 启动器。

## Windows（PyInstaller）

```bash
pyinstaller --noconfirm --windowed --name AutoPilot ^
  --icon resources/branding/autopilot.ico ^
  --add-data "autopilot/metadata/keyword_defs;autopilot/metadata/keyword_defs" ^
  --add-data "resources/branding;resources/branding" ^
  run.py
```

- `--windowed` 不弹控制台；`--icon` 设 .exe 图标；任务栏图标由运行期 AppUserModelID + windowIcon 保证。

## 分发时写入 Platform 地址

打包 **不会**自动读仓库里的 `platform.url.example`。把该模板复制为 **`platform.url`**，放进安装目录（与 `AutoPilot.exe` 同级），或放到 `%ProgramData%\AutoPilot\platform.url`。

文件内写用户能访问的 Platform 根 URL，例如 `https://autopilot.company.com` 或 `http://192.168.1.10:8000`。只写 IP、不写协议/端口无效。

写入后 IDE 启动即锁定该地址，用户只需登录账号，不必再填服务器。详细规则与优先级见 [CONFIGURATION.md §1](CONFIGURATION.md#1-ide--platform-api-地址)。

**与服务端对齐**：同一根 URL 须在 Platform 侧配置（`MC_PLATFORM_URL` 或 `deploy/platform.env.example` → `%ProgramData%\AutoPilot\platform.env`）。双端检查清单见兄弟仓 [Autopilot-Platform/docs/CONFIGURATION.md §7](../Autopilot-Platform/docs/CONFIGURATION.md#7-向用户分发-ideplatform-地址)。

PyInstaller 若要把 `platform.url` 打进包内，在 `--add-data` 中加入该文件，并保证运行时落在 `install_dir()`（exe 所在目录）。更稳妥的做法是安装程序/组策略单独下发 `platform.url`，避免每次升级 exe 覆盖运维改过的地址。

## macOS（PyInstaller，生成 .app）

```bash
pyinstaller --noconfirm --windowed --name AutoPilot \
  --icon resources/branding/autopilot.icns \
  --add-data "autopilot/metadata/keyword_defs:autopilot/metadata/keyword_defs" \
  --add-data "resources/branding:resources/branding" \
  run.py
```

- macOS Dock 图标只能由 `.app` 包的 `.icns` 决定——**开发期 `python run.py` 跑，Dock 显示的是
  Python 解释器图标，属正常**（非缺陷）；要自定义 Dock 图标必须打成 `.app`。

## Linux

1. 安装 `.desktop`：把 `resources/branding/autopilot.desktop` 拷到 `~/.local/share/applications/`
   （或系统级 `/usr/share/applications/`），按注释改好 `Exec=` 和 `Icon=`。
2. 图标：把 `autopilot.png` 装进图标主题
   `~/.local/share/icons/hicolor/256x256/apps/autopilot.png`（这样 `Icon=autopilot` 即可生效），
   或直接把 `Icon=` 写成 png 的绝对路径。
3. `StartupWMClass=autopilot` 须与运行窗口 WM_CLASS 一致（代码已 `setDesktopFileName("autopilot")`），
   任务栏/Dock 才会把运行窗口归到该启动器图标、不再显示通用 python 图标。

> 多数 EWMH 兼容 WM（GNOME/KDE）下，即便不装 `.desktop`，运行窗口的标题栏/Alt-Tab 也会显示
> `setWindowIcon` 的图标；`.desktop` 主要用于固定到启动器/Dock 的关联与分组。

## 打包前双仓契约检查

IDE 与 Platform 相邻检出（默认 `../Autopilot-Platform`）时，打包或发布前执行：

```powershell
python tools/check_dual_repo_contract.py
```

非相邻目录可显式传入：

```powershell
python tools/check_dual_repo_contract.py --ide-root <ide-root> `
  --platform-root <platform-root>
```

脚本校验 `contracts/runtime_contract.json` 的 schema、runtime major.minor 和 capabilities；
并检查 Http / **Web** / Intent / 执行编排核字节一致、mobile/settings 语义探针、Platform `ap` Intent 依赖可达。
退出码非零时不得发布。CI 可直接将同一命令作为打包步骤的前置检查。

Web 双引擎 live 白盒见 [WEB_LIVE_TESTING.md](./WEB_LIVE_TESTING.md)；GitHub Actions 可选 workflow：`.github/workflows/web-live.yml`。

双仓同构/分叉边界、扩展清单与责任划分见：

- IDE：[architecture/DUAL_REPO_CONTRACT.md](architecture/DUAL_REPO_CONTRACT.md)
- Platform：`docs/architecture/DUAL_REPO_CONTRACT.md`（与上同文，链接表按仓本地调整）
