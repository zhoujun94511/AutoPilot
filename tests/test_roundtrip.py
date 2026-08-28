"""任务2.2：旧→新格式转换 + round-trip 等价测试。

链路：旧 .tc XML --loader--> 模型 --serializer--> YAML --serializer.load--> 模型
断言两次模型的 dict 表示完全一致（无损）。
另测一个 .map 的 YAML round-trip。
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from autopilot.model import loader, serializer
from autopilot.model.mapfile import MapFile, MapElement, Locator

SAMPLE_TC = os.path.join(os.path.dirname(__file__), "sample", "login.tc")


def test_testcase_roundtrip() -> bool:
    tc = loader.load_testcase(SAMPLE_TC)
    d1 = serializer.testcase_to_dict(tc)

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "login.tc.yaml")
        serializer.save_testcase(tc, out)
        tc2 = serializer.load(out)
        d2 = serializer.testcase_to_dict(tc2)

    # source_path 不进 dict，比较纯内容
    ok = d1 == d2
    print("TestCase round-trip:", "✅" if ok else "❌")
    if not ok:
        print("  d1:", d1)
        print("  d2:", d2)
    # 额外结构校验
    print(f"  case 步骤数: {len(tc2.case.steps)}  含嵌套条件子步骤: "
          f"{any(getattr(n,'children',[]) for n in tc2.case.steps)}")
    return ok


def test_mapfile_roundtrip() -> bool:
    mf = MapFile(name="login")
    mf.elements = [
        MapElement(
            name="login", comment="登录区",
            locator=Locator(type="ID", value="loginForm", mode=0),
            children=[MapElement(name="user", locator=Locator(type="XPATH", value="//input[@id='u']"))],
        ),
        MapElement(
            name="combo", comment="复合定位",
            locator=Locator(type="AND", tag="input",
                            properties=[{"name": "type", "mode": 0, "value": "text"}]),
        ),
    ]
    d1 = serializer.mapfile_to_dict(mf)
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "login.map.yaml")
        serializer.save_mapfile(mf, out)
        mf2 = serializer.load(out)
        d2 = serializer.mapfile_to_dict(mf2)
    ok = d1 == d2
    print("MapFile  round-trip:", "✅" if ok else "❌")
    if not ok:
        print("  d1:", d1)
        print("  d2:", d2)
    return ok


def main() -> int:
    results = [test_testcase_roundtrip(), test_mapfile_roundtrip()]
    allok = all(results)
    print("\n总结:", "✅ 全部通过" if allok else "❌ 存在失败")
    return 0 if allok else 1


if __name__ == "__main__":
    raise SystemExit(main())
