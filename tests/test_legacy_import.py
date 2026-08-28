"""阶段9 旧工程导入回归套件。

验证构造的既有 .ts/.tc/.map/.properties 工程能稳定导入，覆盖全部节点类型
（step/stepset/stepverbs/stepinnercase/condition-if_else/loop 标记）与定位方式（ID/XPATH/CSS/AND），
并通过 旧→模型→YAML→再导入 的 round-trip 保持结构等价。
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

from autopilot.model import loader, serializer, dataconfig
from autopilot.model.testcase import Step, StepSet, StepVerbs, StepInnerCase
from autopilot.engine import discover_cases, run_directory, FaultStrategy

PROJ = os.path.join(os.path.dirname(__file__), "legacy_project")


def _flatten(nodes):
    out = []
    for n in nodes:
        out.append(n)
        out.extend(_flatten(getattr(n, "children", []) or []))
    return out


def test_import_ts() -> bool:
    ts = loader.load_testsuite(os.path.join(PROJ, "testcases", "testcases.ts"))
    ok = (ts.data_id == "suite001" and len(ts.before.steps) == 1
          and len(ts.after.steps) == 1)
    print("导入 .ts:", "✅" if ok else "❌", f"before={len(ts.before.steps)} after={len(ts.after.steps)}")
    return ok


def test_import_tc_allnodes() -> bool:
    tc = loader.load_testcase(os.path.join(PROJ, "testcases", "login", "login.tc"))
    flat = _flatten(tc.case.steps)
    types = {type(n).__name__ for n in flat}
    has_stepset = any(isinstance(n, StepSet) for n in flat)
    has_verbs = any(isinstance(n, StepVerbs) for n in flat)
    has_inner = any(isinstance(n, StepInnerCase) for n in flat)
    cond = next((n for n in flat if isinstance(n, Step) and n.is_condition), None)
    cond_ok = cond is not None and len(cond.children) >= 3  # if体 + else标记 + else体
    loop_markers = [n for n in flat if isinstance(n, Step) and n.keyword_id in
                    ("keyword_loop_start", "keyword_loop_end")]
    ok = has_stepset and has_verbs and has_inner and cond_ok and len(loop_markers) == 2
    print("导入 .tc 全节点:", "✅" if ok else "❌",
          f"类型={types} 条件子步={len(cond.children) if cond else 0} 循环标记={len(loop_markers)}")
    return ok


def test_import_map_locators() -> bool:
    mf = loader.load_mapfile(os.path.join(PROJ, "maps", "login.map"))
    login = mf.find("login")
    user = mf.find("userInput")
    submit = mf.find("submitBtn")
    banner = mf.find("banner")
    ok = (login.locator.type == "ID" and login.locator.value == "loginForm"
          and user.locator.type == "XPATH" and "username" in user.locator.value
          and submit.locator.type == "AND" and submit.locator.tag == "button"
          and len(submit.locator.properties) == 2
          and banner.locator.type == "CSS" and banner.locator.value == ".top-banner")
    print("导入 .map 全定位:", "✅" if ok else "❌",
          f"ID/XPATH/AND({len(submit.locator.properties)}属性)/CSS")
    return ok


def test_import_properties() -> bool:
    cfg = dataconfig.load(os.path.join(PROJ, "config", "DataConfig.properties"))
    d = cfg.as_dict()
    ok = (d.get("baseUrl") == "http://www.example.com" and d.get("timeout") == "30"
          and cfg.comments.get("baseUrl") == "被测系统首页地址")
    print("导入 .properties:", "✅" if ok else "❌", d)
    return ok


def test_roundtrip_stability() -> bool:
    """旧 .tc/.map → 模型 → YAML → 再导入，结构等价。"""
    tc = loader.load_testcase(os.path.join(PROJ, "testcases", "login", "login.tc"))
    mf = loader.load_mapfile(os.path.join(PROJ, "maps", "login.map"))
    d_tc1, d_mf1 = serializer.testcase_to_dict(tc), serializer.mapfile_to_dict(mf)
    with tempfile.TemporaryDirectory() as tmp:
        p1 = os.path.join(tmp, "c.tc.yaml")
        p2 = os.path.join(tmp, "m.map.yaml")
        serializer.save_testcase(tc, p1)
        serializer.save_mapfile(mf, p2)
        d_tc2 = serializer.testcase_to_dict(serializer.load(p1))
        d_mf2 = serializer.mapfile_to_dict(serializer.load(p2))
    ok = d_tc1 == d_tc2 and d_mf1 == d_mf2
    print("round-trip 稳定性:", "✅" if ok else "❌")
    return ok


def test_batch_run_legacy() -> bool:
    """整目录批量执行旧工程，不应崩溃（缺实现关键字降级 NOIMPL）。"""
    paths = discover_cases(PROJ)
    suite = run_directory(PROJ, fault_strategy=FaultStrategy.CONTINUE)
    ok = 1 <= len(paths) == len(suite.results)
    print("批量执行旧工程:", "✅" if ok else "❌",
          f"发现{len(paths)}用例 执行{len(suite.results)} 步骤统计={suite.step_counts()}")
    return ok


def main() -> int:
    ok = all([
        test_import_ts(), test_import_tc_allnodes(), test_import_map_locators(),
        test_import_properties(), test_roundtrip_stability(), test_batch_run_legacy(),
    ])
    print("\n总结:", "✅ 旧工程导入回归全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
