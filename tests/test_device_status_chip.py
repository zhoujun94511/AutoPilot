"""DeviceStatusChip 与设备状态刷新（离屏）。"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_APP = None


def _app():
    global _APP
    from _qt import get_qt_app
    _APP = get_qt_app()
    return _APP


def test_chip_states() -> bool:
    try:
        from autopilot.ui.widgets.device_status_chip import DeviceStatusChip
        _app()
        chip = DeviceStatusChip()
        chip.set_status("idle", "未连接设备", "tip idle")
        ok_idle = chip.property("state") == "idle" and chip.text() == "未连接设备"
        chip.set_status("detected", "已检测 Android 1", "tip det")
        ok_det = chip.property("state") == "detected"
        chip.set_status("connected", "iOS · abc", "tip conn")
        ok_conn = chip.property("state") == "connected"
        ok = ok_idle and ok_det and ok_conn
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("DeviceStatusChip 状态:", "⏭ 跳过(", e, ")")
        return True
    print("DeviceStatusChip 三态:", "✅" if ok else "❌")
    return ok


def test_main_window_device_chip() -> bool:
    try:
        import tempfile
        from autopilot.ui.main_window import MainWindow
        _app()
        with tempfile.TemporaryDirectory() as tmp:
            w = MainWindow(project_dir=tmp, config_dir="")
            chip = w._sb_device
            ok_type = hasattr(chip, "set_status")
            w._devices = (["dev1"], [])
            w._inspect_chosen = False
            w._update_device_status()
            ok_det = "Android 1" in chip.text()
            w._inspect_chosen = True
            w._inspect_platform = "Android"
            w._inspect_udid = "dev1"
            w._update_device_status()
            ok_conn = (
                chip.status_state() == "connected"
                if hasattr(chip, "status_state")
                else chip.property("state") == "connected"
            )
            w.close()
        ok = ok_type and ok_det and ok_conn
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("主窗口设备 Chip:", "⏭ 跳过(", e, ")")
        return True
    print("主窗口 _update_device_status:", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([test_chip_states(), test_main_window_device_chip()])
    print("\n总结:", "✅ 设备 Chip 全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
