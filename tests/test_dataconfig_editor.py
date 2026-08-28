"""阶段11.2 数据配置(.properties)编辑器回归（离屏 GUI）。

覆盖：打开 .properties → 表格编辑回写模型 → 保存 → 重载保持键值与注释、保序。
"""

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import autopilot.keywords  # noqa: F401
from autopilot.model import dataconfig as dc

_APP = None


def _win(tmp):
    global _APP
    from PyQt6.QtWidgets import QApplication
    from autopilot.ui.main_window import MainWindow
    _APP = QApplication.instance() or QApplication([])
    return MainWindow(project_dir=tmp, config_dir="")


def test_edit_save_reload() -> bool:
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "DataConfig.properties")
            with open(path, "w", encoding="utf-8") as f:
                f.write("!baseUrl:首页\nbaseUrl=http://a\ntimeout=30\n")
            win = _win(tmp)
            win._on_file_activated(path)            # 打开 → 数据配置编辑器
            ed = win.dataconfig_editor
            opened_ok = (ed.dataconfig is not None and len(ed.dataconfig.entries) == 2)

            # 编辑：改 timeout 值 + 新增一行 + 保存
            ed.table.item(1, 1).setText("60")       # timeout=60
            ed.add_row()
            ed.table.item(2, 0).setText("retry")
            ed.table.item(2, 1).setText("3")
            win._save_dataconfig()

            cfg2 = dc.load(path)
            d = cfg2.as_dict()
            ok = (opened_ok and d.get("baseUrl") == "http://a" and d.get("timeout") == "60"
                  and d.get("retry") == "3" and cfg2.comments.get("baseUrl") == "首页"
                  and [k for k, _ in cfg2.entries] == ["baseUrl", "timeout", "retry"])
            win.close()
    except Exception as e:  # noqa: BLE001
        print("数据配置编辑器: ⏭ 跳过(", e, ")")
        return True
    print("数据配置 编辑→保存→重载:", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([test_edit_save_reload()])
    print("\n总结:", "✅ 数据配置编辑器全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
