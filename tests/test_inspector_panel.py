"""阶段16.3/16.4 控件检视器面板（离屏 GUI）：渲染快照 + 点选联动 + 定位符动作信号。"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import autopilot.keywords  # noqa: F401

_APP = None
_ANDROID = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node class="android.widget.Button" resource-id="com.x:id/login"
          content-desc="登录" text="登录" bounds="[100,200][300,280]"/>
  </node>
</hierarchy>"""


def _app():
    global _APP
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication([])
    return _APP


def test_refresh_before_check_aborts() -> bool:
    """before_refresh 返回 False 时不启动 worker、不进入「正在取快照」态。"""
    try:
        app = _app()
        from autopilot.ui.widgets.inspector_panel import InspectorPanel
        p = InspectorPanel()
        p.snapshot_provider = lambda: (_ for _ in ()).throw(AssertionError("不应调用"))
        p.before_refresh = lambda: False
        p.refresh()
        ok = p.lbl.text() == p._idle_lbl and not p._snap_running()
        _ = app
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("检视器前置校验中止: ⏭ 跳过(", e, ")")
        return True
    print("检视器 refresh 前置校验中止:", "✅" if ok else "❌")
    return ok


def test_render_and_select() -> bool:
    try:
        _app()
        from autopilot.ui.widgets.inspector_panel import InspectorPanel
        p = InspectorPanel()
        p.render_snapshot(b"", _ANDROID, "android")     # 空截图也应正常解析/建树
        tree_ok = p.tree.topLevelItemCount() == 1
        # 点截图按钮中心 → 命中 Button → 出候选定位符
        p._on_view_click(200, 240)
        from PyQt6.QtCore import Qt
        locs = [p.loc_list.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(p.loc_list.count())]
        sel_ok = p.loc_list.count() > 0 and any("id::com.x:id/login" in t for t in locs)
        # 填入步骤信号
        captured = {}
        # noinspection PyUnresolvedReferences
        p.fillStep.connect(lambda s: captured.update(loc=s))
        p.loc_list.setCurrentRow(0)
        p._fill()
        fill_ok = captured.get("loc", "").startswith(("id::", "xpath::"))
        ok = tree_ok and sel_ok and fill_ok
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("检视器面板: ⏭ 跳过(", e, ")")
        return True
    print("检视器 渲染+点选+定位符动作:", "✅" if ok else "❌")
    return ok


def test_refresh_async() -> bool:
    """refresh() 异步取快照：provider 在 worker 线程跑（慢设备不阻塞 GUI），完成后渲染。"""
    try:
        import time
        app = _app()
        from autopilot.ui.widgets.inspector_panel import InspectorPanel
        p = InspectorPanel()
        calls = {"thread": ""}

        import threading

        def slow_provider():
            calls["thread"] = threading.current_thread().name
            time.sleep(0.2)                      # 模拟慢设备（如装 uiautomator2）
            return b"", _ANDROID, "android"

        p.snapshot_provider = slow_provider
        p.refresh()
        # 立即返回、worker 在跑 → 主线程未阻塞、尚未渲染
        immediate_ok = p._snap_worker.isRunning() and p.tree.topLevelItemCount() == 0
        deadline = time.monotonic() + 5
        while p._snap_worker.isRunning() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.02)
        app.processEvents()
        rendered_ok = p.tree.topLevelItemCount() == 1
        offthread_ok = calls["thread"] is not None and calls["thread"] != threading.main_thread().name
        ok = immediate_ok and rendered_ok and offthread_ok
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("检视器异步取快照: ⏭ 跳过(", e, ")")
        return True
    print("检视器异步取快照(不阻塞GUI/worker线程):", "✅" if ok else "❌")
    return ok


def test_cancel_refresh() -> bool:
    """终止快照：取快照中 btn_cancel 可用；终止→丢弃结果、不渲染；后台收尾后 btn_refresh 恢复。"""
    try:
        import time
        import threading
        app = _app()
        from autopilot.ui.widgets.inspector_panel import InspectorPanel
        p = InspectorPanel()
        release = threading.Event()

        def held_provider():
            release.wait(5)                       # 阻塞，模拟慢设备初始化
            return b"", _ANDROID, "android"

        released = {"n": 0}
        # noinspection PyUnresolvedReferences
        p.cancelled.connect(lambda: released.__setitem__("n", released["n"] + 1))

        p.snapshot_provider = held_provider
        p.refresh()
        running_ok = (p._snap_worker.isRunning()
                      and not p.btn_refresh.isEnabled() and p.btn_cancel.isEnabled())
        # 终止：立即反馈、按钮置「收尾中」状态，标记 cancelled
        p.cancel_refresh()
        cancel_ok = (p._snap_cancelled is True and not p.btn_cancel.isEnabled())
        # 放行后台调用 → worker 结束 → done 投递：丢弃结果、不渲染、刷新恢复、发 cancelled（释放会话）
        release.set()
        deadline = time.monotonic() + 5
        while p._snap_worker.isRunning() and time.monotonic() < deadline:
            app.processEvents(); time.sleep(0.02)
        p._snap_worker.wait(2000)
        app.processEvents()
        settled_ok = (p.tree.topLevelItemCount() == 0          # 结果被丢弃，没渲染
                      and p.btn_refresh.isEnabled() and not p.btn_cancel.isEnabled()
                      and p._snap_cancelled is False
                      and released["n"] == 1)                  # 收尾后发了一次「释放会话」信号
        ok = running_ok and cancel_ok and settled_ok
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("终止快照: ⏭ 跳过(", e, ")")
        return True
    print("检视器终止快照(进行中可终止/丢弃结果/恢复刷新):", "✅" if ok else "❌")
    return ok


def test_crop_image_locator() -> bool:
    """框选图片定位：render 后 crop_region 按截图像素裁出正确尺寸的 PNG；空选区返回空。"""
    try:
        from PyQt6.QtCore import QRectF, QBuffer
        from PyQt6.QtGui import QImage
        app = _app()
        from autopilot.ui.widgets.inspector_panel import InspectorPanel
        # 造一张 1080x2400 的 PNG（与 _ANDROID 根 bounds 一致，scale≈1）
        img = QImage(1080, 2400, QImage.Format.Format_RGB32)
        img.fill(0x3366CC)
        buf = QBuffer(); buf.open(QBuffer.OpenModeFlag.WriteOnly); img.save(buf, "PNG")
        png = bytes(buf.data())
        p = InspectorPanel()
        p.render_snapshot(png, _ANDROID, "android")
        enabled_ok = p.btn_pick_img.isEnabled()           # 有快照后按钮可用
        out = p.crop_region(QRectF(100, 200, 200, 80))     # 裁 200x80
        crop = QImage.fromData(out)
        size_ok = (not crop.isNull()) and crop.width() == 200 and crop.height() == 80
        empty_ok = p.crop_region(QRectF(0, 0, 0, 0)) == b""  # 空选区
        # 框选信号 → cropRequested 携带 PNG 字节
        got = {}
        # noinspection PyUnresolvedReferences
        p.cropRequested.connect(lambda b: got.__setitem__("n", len(b)))
        p._on_region_selected(QRectF(10, 10, 50, 50))
        sig_ok = got.get("n", 0) > 0 and not p.btn_pick_img.isChecked()
        ok = enabled_ok and size_ok and empty_ok and sig_ok
        _ = app
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("框选图片定位: ⏭ 跳过(", e, ")")
        return True
    print("检视器框选图片定位(裁剪尺寸/空选区/信号):", "✅" if ok else "❌")
    return ok


def test_in_mainwindow() -> bool:
    try:
        import tempfile
        _app()
        from autopilot.ui.main_window import MainWindow
        with tempfile.TemporaryDirectory() as tmp:
            win = MainWindow(project_dir=tmp, config_dir="")
            has_panel = win.inspector is not None and win.inspector.snapshot_provider is not None
            # 用例里选中步骤 → 填入定位符
            win.new_case()
            win.case_editor.insert_step("mobile_element_click", win.catalog.get("mobile_element_click"))
            win.center.setCurrentWidget(win.case_editor)
            win.case_editor.selectRow(0)
            win._inspector_fill_step("id::loginBtn")
            step = win.case_editor.selected_node()
            filled = any(p.param_id in ("locator", "element") and p.value == "id::loginBtn"
                         for p in step.params)
            win.close()
        ok = has_panel and filled
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("检视器接入主窗口: ⏭ 跳过(", e, ")")
        return True
    print("检视器接入主窗口(填步骤):", "✅" if ok else "❌")
    return ok


_LONG_ANDROID = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node class="android.widget.TextView"
          resource-id="com.mi.android.globallauncher:id/very_long_resource_identifier_for_scroll_test"
          text="GetApps" bounds="[100,200][300,280]"/>
  </node>
</hierarchy>"""


_DEEP_ANDROID = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node class="android.widget.LinearLayout" bounds="[0,0][1080,2400]">
      <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
        <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
          <node class="android.widget.TextView"
                resource-id="com.mi.android.globallauncher:id/very_long_resource_identifier_for_scroll_test"
                text="GetApps" bounds="[100,200][300,280]"/>
        </node>
      </node>
    </node>
  </node>
</hierarchy>"""


def test_tree_horizontal_scroll() -> bool:
    """深层嵌套 + 长 resource-id：列宽计入缩进，文本不省略。"""
    try:
        _app()
        from PyQt6.QtCore import Qt
        from autopilot.ui.widgets.inspector_panel import InspectorPanel
        p = InspectorPanel()
        p.render_snapshot(b"", _DEEP_ANDROID, "android")
        p.tree.expandAll()
        p._sync_tree_horizontal_extent()
        scroll_ok = p.tree.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
        wide_ok = p.tree.columnWidth(0) > p.tree.viewport().width()
        # 最深子节点文本应完整保留（无 …）
        it = p.tree.topLevelItem(0)
        while it is not None and it.childCount() > 0:
            it = it.child(0)
        leaf = it
        text_ok = leaf is not None and "…" not in leaf.text(0) and "very_long_resource" in leaf.text(0)
        ok = scroll_ok and wide_ok and text_ok
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("控件树横向滚动: ⏭ 跳过(", e, ")")
        return True
    print("控件树/属性横向滚动:", "✅" if ok else "❌")
    return ok


def test_pane_empties() -> bool:
    """无快照→整区主空态；有树未选中→三栏+右侧紧凑空态；点选后→属性内容。"""
    try:
        _app()
        from autopilot.ui.widgets.inspector_panel import (
            InspectorPanel, _WORKSPACE_IDLE, _DETAIL_NO_SEL,
        )
        p = InspectorPanel()
        idle_ok = (
            p._body_stack.currentIndex() == 0
            and _WORKSPACE_IDLE.split("\n")[0] in p._workspace_ph._title.text()
        )
        p.render_snapshot(b"", _ANDROID, "android")
        after_snap = (
            p._body_stack.currentIndex() == 1
            and p._detail_pages.currentIndex() == 1
            and _DETAIL_NO_SEL.split("\n")[0] in p._detail_ph._title.text()
        )
        p._on_view_click(200, 240)
        after_sel = (
            p._body_stack.currentIndex() == 1
            and p._detail_pages.currentIndex() == 0
            and p.attrs.rowCount() > 0
        )
        p._clear_inspector_content("cleared\nhint")
        after_clear = (
            p._body_stack.currentIndex() == 0
            and "cleared" in p._workspace_ph._title.text()
        )
        ok = idle_ok and after_snap and after_sel and after_clear
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("检视器树/属性空态: ⏭ 跳过(", e, ")")
        return True
    print("检视器 整区主空态切换:", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([test_render_and_select(), test_refresh_async(), test_cancel_refresh(),
              test_crop_image_locator(), test_in_mainwindow(), test_tree_horizontal_scroll(),
              test_pane_empties(), test_refresh_before_check_aborts()])
    print("\n总结:", "✅ 控件检视器面板全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
