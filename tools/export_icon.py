"""把程序化绘制的品牌图标 app_icon() 导出成真实图片文件。

产物（resources/branding/）：
  autopilot.png  —— 256×256 主图（窗口/关于/README/Linux 用）
  autopilot.ico  —— 多尺寸(16/32/48/64/128/256)，Windows 打包 .exe / 快捷方式 / 任务栏
  autopilot.icns —— macOS 打包 .app（py2app/PyInstaller --icon）用

同步到 Web 管理台（兄弟仓 Autopilot-Platform，默认 `../Autopilot-Platform/autopilot_platform/frontend/public/brand/`；
可用 `AUTOPILOT_PLATFORM_ROOT`，兼容旧名 `AUTOPILOT_CONSOLE_ROOT`）：
  autopilot.png / favicon.ico / apple-touch-icon.png
  —— 与 IDE 同源，禁止前端另画一套。

源是 draw_icon()(矢量级，渲染 1024 高分辨率基图再降采样，各尺寸清晰)。
要换 logo：改 branding.draw_icon() 后重跑本脚本；勿在前端手写第二套标识。

用法：.venv/Scripts/python.exe tools/export_icon.py
"""

from __future__ import annotations

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT_DIR = os.path.join("resources", "branding")
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PLATFORM_ROOT = os.environ.get("AUTOPILOT_PLATFORM_ROOT") or os.environ.get(
    "AUTOPILOT_CONSOLE_ROOT",
    os.path.normpath(os.path.join(_REPO_ROOT, "..", "Autopilot-Platform")),
)
WEB_BRAND_DIR = os.path.join(
    _PLATFORM_ROOT, "autopilot_platform", "frontend", "public", "brand"
)
SIZES = [16, 32, 48, 64, 128, 256]


def _sync_web(png_path: str, ico_path: str, base) -> None:
    """把同一套导出图同步到 Vite public，供 favicon / BrandMark 使用。"""
    # noinspection PyPackageRequirements
    from PIL import Image

    public_root = os.path.dirname(WEB_BRAND_DIR)
    if not os.path.isdir(public_root):
        print(f"跳过 Web 同步（未找到 Console frontend/public：{public_root}）")
        return

    os.makedirs(WEB_BRAND_DIR, exist_ok=True)
    web_png = os.path.join(WEB_BRAND_DIR, "autopilot.png")
    web_ico = os.path.join(WEB_BRAND_DIR, "favicon.ico")
    web_touch = os.path.join(WEB_BRAND_DIR, "apple-touch-icon.png")
    shutil.copy2(png_path, web_png)
    shutil.copy2(ico_path, web_ico)
    base.resize((180, 180), Image.Resampling.LANCZOS).save(web_touch, "PNG")
    # 兼容浏览器默认请求 /favicon.ico
    shutil.copy2(ico_path, os.path.join(public_root, "favicon.ico"))
    print(f"已同步 Web：{WEB_BRAND_DIR}")


def main() -> int:
    import io
    # noinspection PyPackageRequirements
    from PIL import Image
    from PyQt6.QtCore import QBuffer
    from PyQt6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])   # 须保留引用，否则被 GC 后渲染崩溃
    from autopilot.ui.branding import draw_icon          # 从绘制源出图，保证大尺寸清晰

    os.makedirs(OUT_DIR, exist_ok=True)
    png_path = os.path.join(OUT_DIR, "autopilot.png")
    ico_path = os.path.join(OUT_DIR, "autopilot.ico")
    icns_path = os.path.join(OUT_DIR, "autopilot.icns")

    # 渲染 1024 高分辨率基图 → PIL，按需降采样
    qb = QBuffer()
    qb.open(QBuffer.OpenModeFlag.WriteOnly)
    draw_icon(1024).pixmap(1024, 1024).save(qb, "PNG")
    base = Image.open(io.BytesIO(bytes(qb.data()))).convert("RGBA")

    base.resize((256, 256)).save(png_path, "PNG")               # 256 主图
    base.save(ico_path, format="ICO", sizes=[(s, s) for s in SIZES])   # Windows 多尺寸
    # noinspection PyBroadException
    try:
        base.save(icns_path, format="ICNS")                     # macOS .app 图标
        icns_done = True
    except Exception as e:  # noqa: BLE001
        icns_done = False
        print(f"ICNS 跳过（{e}）")
    print(f"已导出：{png_path}")
    print(f"已导出：{ico_path}  (尺寸 {SIZES})")
    if icns_done:
        print(f"已导出：{icns_path}  (macOS)")

    _sync_web(png_path, ico_path, base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
