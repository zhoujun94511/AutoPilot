"""设备会话与并行分片（离线可测）。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autopilot.runtime.device_session import DeviceSession
from autopilot.runtime.port_allocator import PortAllocator
from autopilot.runtime.device_pool import shard_cases, build_sessions, normalize_platform
from autopilot.model.testcase import TestCase


def test_port_slots_distinct() -> bool:
    pa = PortAllocator()
    p0 = pa.ports_for_slot(0)
    p1 = pa.ports_for_slot(1)
    ok = (p0.wda_port == 8100 and p1.wda_port == 8101
          and p0.tunnel_port == 28100 and p1.tunnel_port == 28110
          and p0.mjpeg_port == 9100 and p1.mjpeg_port == 9101
          and p0.appium_port == 4723 and p1.appium_port == 4724
          and p0.system_port == 8200 and p1.system_port == 8201)
    print("port slots:", "OK" if ok else "FAIL", p0, p1)
    return ok


def test_device_session_ctx_vars() -> bool:
    sess = DeviceSession.from_slot("android", "DEV1", slot=1)
    v = sess.to_ctx_vars()
    ok = (v["__device_udid__"] == "DEV1"
          and v["__wda_local_port__"] == 8101
          and v["__tunnel_info_port__"] == 28110
          and v["__worker_slot__"] == 1
          and v["__appium_server__"] == "http://127.0.0.1:4724"
          and v["__appium_caps__"]["appium:systemPort"] == 8201)
    print("ctx vars:", "OK" if ok else "FAIL", v)
    return ok


def test_ios_session_caps_per_slot() -> bool:
    """iOS Appium 路径：各 slot 独立 webDriverAgentUrl。"""
    from unittest.mock import patch
    with patch("autopilot.runtime.device_session.DeviceSession._ios_appium_caps",
               lambda self: {
                   "appium:udid": self.udid,
                   "appium:webDriverAgentUrl": f"http://127.0.0.1:{self.wda_port}",
               }):
        s0 = DeviceSession.from_slot("ios", "A", slot=0, backend_mode="appium")
        s1 = DeviceSession.from_slot("ios", "B", slot=1, backend_mode="appium")
        v0, v1 = s0.to_ctx_vars(), s1.to_ctx_vars()
    ok = (v0["__appium_caps__"]["appium:webDriverAgentUrl"] == "http://127.0.0.1:8100"
          and v1["__appium_caps__"]["appium:webDriverAgentUrl"] == "http://127.0.0.1:8101"
          and v0["__appium_caps__"]["appium:udid"] == "A"
          and v1["__appium_caps__"]["appium:udid"] == "B")
    print("ios caps per slot:", "OK" if ok else "FAIL",
          v0.get("__appium_caps__"), v1.get("__appium_caps__"))
    return ok


def test_shard_round_robin() -> bool:
    cases = [TestCase(name=f"c{i}") for i in range(5)]
    shards = shard_cases(cases, 2)
    ok = (len(shards) == 2 and [c.name for c in shards[0]] == ["c0", "c2", "c4"]
          and [c.name for c in shards[1]] == ["c1", "c3"])
    print("shard:", "OK" if ok else "FAIL", [[c.name for c in s] for s in shards])
    return ok


def test_build_sessions_workers() -> bool:
    sess = build_sessions("ios", ["A", "B", "C"], workers=2)
    ok = len(sess) == 2 and sess[0].udid == "A" and sess[1].udid == "B"
    print("build_sessions:", "OK" if ok else "FAIL", [s.udid for s in sess])
    return ok


def test_normalize_platform() -> bool:
    ok = normalize_platform("iOS") == "ios" and normalize_platform("Android") == "android"
    print("normalize:", "OK" if ok else "FAIL")
    return ok


def main() -> int:
    ok = all([
        test_port_slots_distinct(),
        test_device_session_ctx_vars(),
        test_ios_session_caps_per_slot(),
        test_shard_round_robin(),
        test_build_sessions_workers(),
        test_normalize_platform(),
    ])
    print("\n总结:", "全部通过" if ok else "存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
