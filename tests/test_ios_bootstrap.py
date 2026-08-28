"""阶段14.1 iOS 工具链代码化回归（离线纯逻辑：二进制定位 + 命令构造 + caps）。

真机端到端"跑通"需 iOS 设备 + 已装 WDA，由使用方在真机上验证；此处验证可离线的部分。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from autopilot.mobile import ios_bootstrap as ib


def test_resolve_binary() -> bool:
    # Windows 上内置 resources/re_go_ios/executable/win/ios.exe 应被定位到
    p = ib.resolve_go_ios()
    ok = ib.available() and p is not None and p.name.lower().startswith("ios")
    print("go-ios 二进制定位:", "✅" if ok else "❌", p)
    return ok


def test_commands() -> bool:
    t = " ".join(ib.tunnel_cmd(28100))
    img = " ".join(ib.image_cmd())
    wda = " ".join(ib.runwda_cmd("com.x.WDA", udid="UDID1", env={"USE_PORT": 8100}))
    fwd = ib.forward_cmd(8100, 8100, "UDID1")
    uninst = ib.uninstall_cmd("com.demo.ios", "UDID1")
    ok = ("tunnel start --userspace" in t and "--tunnel-info-port 28100" in t
          and "image auto" in img and "devimages" in img
          and "runwda" in wda and "--bundleid=com.x.WDA" in wda
          and "--udid UDID1" in wda and "USE_PORT=8100" in wda
          and fwd[:3] == ["pymobiledevice3", "usbmux", "forward"] and "8100" in fwd
          and uninst[1:3] == ["uninstall", "com.demo.ios"]
          and uninst[-1] == "--udid=UDID1")
    print("命令构造(tunnel/image/runwda/forward):", "✅" if ok else "❌")
    return ok


def test_caps() -> bool:
    caps = ib.build_ios_caps("UDID1", 8100, extra={"appium:bundleId": "com.app"})
    ok = (caps["platformName"] == "iOS"
          and caps["appium:automationName"] == "XCUITest"
          and caps["appium:udid"] == "UDID1"
          and caps["appium:webDriverAgentUrl"] == "http://127.0.0.1:8100"
          # 纯外部直连不得带 usePreinstalledWDA，否则 xcuitest 驱动会卸载自定义 WDA
          and "appium:usePreinstalledWDA" not in caps
          and caps["appium:bundleId"] == "com.app")
    print("Appium iOS caps 构造:", "✅" if ok else "❌")
    return ok


def test_managed_caps() -> bool:
    # updatedWDABundleId 应去掉传入的 .xctrunner 后缀（Appium 自己补）
    c = ib.build_ios_caps_managed("UDID1", "com.x.WDA.test.xctrunner")
    ok = (c["appium:usePreinstalledWDA"] is True
          and c["appium:updatedWDABundleId"] == "com.x.WDA.test"
          and "tunneld" in " ".join(ib.tunneld_cmd()))
    print("managed caps + tunneld 命令:", "✅" if ok else "❌")
    return ok


def test_prep_offline() -> bool:
    # 健壮编排器：离线只验证可实例化 + 端口工具 + reclaim 不抛
    prep = ib.IosDevicePrep("UDID1", "com.x.WDA", log=lambda _m: None)
    free_ok = ib.is_port_listening(59999) is False   # 大概率空闲端口未监听
    # noinspection PyBroadException
    try:
        prep.reclaim()                                # 无残留时应为无害空操作
        reclaim_ok = True
    except Exception:
        reclaim_ok = False
    ok = (prep.udid == "UDID1" and prep.wda_port == 8100 and free_ok and reclaim_ok)
    print("健壮编排器(离线 sanity):", "✅" if ok else "❌")
    return ok


def test_wda_alive_gate() -> bool:
    """wda_alive 是「真探活」：未监听→False；监听但 /status 非 200（陈旧转发）→False；
    /status 返回 200→True。锁住「端口监听被误当 WDA 可达」的链路 bug。"""
    import http.server
    import threading

    free_ok = ib.wda_alive(59999) is False          # 没人监听 → False

    # 起一个「假转发」：端口在听，但 /status 不返回 200（模拟死 WDA 背后的残留转发）
    # noinspection PyPep8Naming
    class _Dead(http.server.BaseHTTPRequestHandler):
        def do_GET(self):                            # noqa: N802
            self.send_response(500)
            self.end_headers()

        def log_message(self, *_a):                  # 静音
            pass

    # noinspection PyTypeChecker
    dead = http.server.HTTPServer(("127.0.0.1", 0), _Dead)
    threading.Thread(target=dead.serve_forever, daemon=True).start()
    dead_port = dead.server_address[1]
    stale_ok = ib.is_port_listening(dead_port) and ib.wda_alive(dead_port) is False
    dead.shutdown()

    # 起一个「真 WDA」：/status 返回 200
    # noinspection PyPep8Naming
    class _Wda(http.server.BaseHTTPRequestHandler):
        def do_GET(self):                            # noqa: N802
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"value":{"ready":true}}')

        def log_message(self, *_a):
            pass

    # noinspection PyTypeChecker
    live = http.server.HTTPServer(("127.0.0.1", 0), _Wda)
    threading.Thread(target=live.serve_forever, daemon=True).start()
    live_ok = ib.wda_alive(live.server_address[1]) is True
    live.shutdown()

    ok = free_ok and stale_ok and live_ok
    print("WDA 真探活(未监听/陈旧转发/真活):", "✅" if ok else "❌", (free_ok, stale_ok, live_ok))
    return ok


def test_mjpeg_alive_gate() -> bool:
    """mjpeg_alive：须返回 multipart/jpeg 流，不能仅凭端口 LISTENING。"""
    import http.server
    import threading
    from typing import Any, cast

    free_ok = ib.mjpeg_alive(59998) is False

    # noinspection PyPep8Naming
    class _Dead(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(500)
            self.end_headers()

        def log_message(self, *_a):
            pass

    _Handler = cast(Any, _Dead)
    dead = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=dead.serve_forever, daemon=True).start()
    dead_port = dead.server_address[1]
    stale_ok = ib.is_port_listening(dead_port) and ib.mjpeg_alive(dead_port) is False
    dead.shutdown()

    # noinspection PyPep8Naming
    class _Mjpeg(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            self.wfile.write(b"\xff\xd8\xff")

        def log_message(self, *_a):
            pass

    live = http.server.HTTPServer(("127.0.0.1", 0), cast(Any, _Mjpeg))
    threading.Thread(target=live.serve_forever, daemon=True).start()
    live_ok = ib.mjpeg_alive(live.server_address[1]) is True
    live.shutdown()

    ok = free_ok and stale_ok and live_ok
    print("MJPEG 真探活(未监听/假监听/真流):", "✅" if ok else "❌")
    return ok


def test_wda_discovery() -> bool:
    """parse_wda_bundles：双后缀命中 / 无 WDA→空 / 多个全列（自动发现纯逻辑）。"""
    single = ib.parse_wda_bundles(
        "com.x.app A 1.0\n"
        "com.facebook.WebDriverAgentRunner.crts.test.xctrunner.xctrunner Runner 1.0")
    none = ib.parse_wda_bundles("com.x.app A 1.0\ncn.y.b B 2.0")
    multi = ib.parse_wda_bundles("a.WebDriverAgentRunner.x.xctrunner R 1\n"
                                 "b.WebDriverAgentRunner.y.xctrunner R 1")
    ok = (single == ["com.facebook.WebDriverAgentRunner.crts.test.xctrunner.xctrunner"]
          and none == [] and len(multi) == 2)
    # pymobiledevice3 JSON：只取顶层 key；Entitlements 里的 team 前缀串不能误当包名
    import json
    pj = json.dumps({
        "com.x.app": {"CFBundleDisplayName": "X"},
        "com.facebook.WebDriverAgentRunner.crts.test.xctrunner.xctrunner": {
            "Entitlements": {"application-identifier":
                             "3Y478B6ZDD.com.facebook.WebDriverAgentRunner.crts.test.xctrunner.xctrunner"}},
    })
    pmd3 = ib.wda_bundles_from_pmd3_json(pj)
    pmd3_ok = pmd3 == ["com.facebook.WebDriverAgentRunner.crts.test.xctrunner.xctrunner"]
    # 自动发现不得改写包名（输入 key 与输出一致）
    raw_key = "com.team.WebDriverAgentRunner.foo.test.xctrunner"
    no_mutate = ib.wda_bundles_from_pmd3_json(json.dumps({raw_key: {}})) == [raw_key]
    print("WDA 自动发现解析(双后缀/无/多个/pmd3-JSON):", "✅" if ok and pmd3_ok and no_mutate else "❌")
    return ok and pmd3_ok and no_mutate


def test_reclaim_stale_local_ios_prep() -> bool:
    """启动回收：函数可调用且不抛（离线）。"""
    tunnels, ports = ib.reclaim_stale_local_ios_prep(log=lambda _m: None)
    ok = isinstance(tunnels, list) and isinstance(ports, list)
    print("启动回收残留隧道/端口:", "✅" if ok else "❌")
    return ok


def test_preferred_ddi_restore_dirs() -> bool:
    """DDI：按设备 ChipID/BoardId 匹配 BuildManifest，而非盲猜目录名。"""
    root = ib.DEVIMAGE_DIR
    dirs = ib.list_local_ddi_restore_dirs(root)
    names = [p.parent.name for p in dirs]
    ok_order = True
    if "ddi-17E5179g" in names and "ddi-15F31d" in names:
        ok_order = names.index("ddi-17E5179g") < names.index("ddi-15F31d")

    # iPhone 16 系：ChipID 0x8140 BoardId 4 → 仅新个性化 DDI 应命中；旧 15F31d 不得误匹配
    chip, board = 0x8140, 4
    hit = {p.parent.name for p in dirs if ib.ddi_identity_matches(p, chip, board)}
    if any(n.lower() == "ddi-17e5179g" for n in names):
        ok_match = "ddi-17E5179g" in hit and "ddi-15F31d" not in hit
    else:
        # 大体积 DDI 可不进仓库；此时 0x8140 不应命中旧镜像
        ok_match = "ddi-15F31d" not in hit

    mount = " ".join(ib.image_mount_cmd(r"D:\x\Restore", "UDID1"))
    ok_cmd = ("image mount" in mount and "--path" in mount
              and "Restore" in mount and "--udid UDID1" in mount)

    # 离线：无真机时 query 返回 None，应回退到本地列表
    ranked = ib.ddi_restore_dirs_for_device("00000000-0000000000000000")
    ok_fallback = ranked == dirs

    ok = ok_order and ok_match and ok_cmd and ok_fallback and all(
        p.name == "Restore" for p in dirs)
    print("DDI 身份匹配 + mount 命令:", "✅" if ok else "❌", names[:3], "hit", hit)
    return ok


def main() -> int:
    ok = all([test_resolve_binary(), test_commands(), test_caps(),
              test_prep_offline(), test_wda_alive_gate(), test_mjpeg_alive_gate(),
              test_wda_discovery(), test_reclaim_stale_local_ios_prep(),
              test_preferred_ddi_restore_dirs()])
    print("\n总结:", "✅ iOS 工具链代码化全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
