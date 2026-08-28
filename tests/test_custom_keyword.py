"""阶段10.1 自定义关键字(.ks)执行回归。

验证：引擎能把 <stepverbs> 调用的 .ks 步骤序列内联展开执行，含
实参→局部变量绑定、形参默认值补缺、局部作用域恢复、递归防护，以及 .ks 加载与索引。
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

import autopilot.keywords  # noqa: F401  注册内置关键字
from autopilot.model import loader
from autopilot.model.testcase import TestCase, StepVerbs, ParamValue
from autopilot.engine import FaultStrategy
from autopilot.engine.executor import Executor
from autopilot.engine.keyword_store import discover_keywords
from autopilot.keywords.context import ExecutionContext

_KS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<root ver="1.0" db_id="ks001" tag="WEB">
  <id>greet_verb</id>
  <params>
    <param id="who"><name>对象</name><default>world</default><required>F</required></param>
  </params>
  <steps>
    <step id="log" comment="打日志" isrun="true">
      <param id="message">${who}</param>
    </step>
    <step id="set_var" comment="产出变量" isrun="true">
      <param id="name">greeted</param>
      <param id="value">hi ${who}</param>
    </step>
  </steps>
</root>
"""

# 递归 .ks：自己调用自己，用于验证递归防护
_KS_REC_XML = """<?xml version="1.0" encoding="UTF-8"?>
<root ver="1.0" db_id="ks002" tag="WEB">
  <id>rec_verb</id>
  <steps>
    <stepverbs id="rec_verb" comment="自调用" isrun="true"/>
  </steps>
</root>
"""


def _write_project(tmp: str) -> None:
    ks_dir = os.path.join(tmp, "keywords")
    os.makedirs(ks_dir, exist_ok=True)
    with open(os.path.join(ks_dir, "greet.ks"), "w", encoding="utf-8") as f:
        f.write(_KS_XML)
    with open(os.path.join(ks_dir, "rec.ks"), "w", encoding="utf-8") as f:
        f.write(_KS_REC_XML)


def _case_calling(ks_id: str, **params) -> TestCase:
    tc = TestCase(name="caller")
    sv = StepVerbs(ks_id=ks_id, comment=f"调用{ks_id}",
                   params=[ParamValue(k, v) for k, v in params.items()])
    tc.case.steps = [sv]
    return tc


def test_load_keyword() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        _write_project(tmp)
        kd = loader.load_keyword(os.path.join(tmp, "keywords", "greet.ks"))
        ok = (kd.ks_id == "greet_verb" and kd.data_id == "ks001"
              and len(kd.steps) == 2 and kd.param("who") is not None
              and kd.param("who").default == "world")
    print("加载 .ks 定义:", "✅" if ok else "❌")
    return ok


def test_expand_and_scope() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        _write_project(tmp)
        store = discover_keywords(tmp)
        ctx = ExecutionContext()
        ex = Executor(ctx, FaultStrategy.CONTINUE, keyword_store=store)
        res = ex.run_testcase(_case_calling("greet_verb", who="alice"))
        ids = [r.keyword_id for r in res.results]
        ok = (
            "alice" in ctx.logs                      # 实参绑定 + 子步骤执行 + 变量解析
            and ctx.get_var("greeted") == "hi alice"  # 非实参变量持久化
            and "who" not in ctx.variables            # 实参局部作用域已恢复
            and "log" in ids and "set_var" in ids     # 子步骤进入结果
            and res.passed
        )
    print("展开+局部作用域:", "✅" if ok else "❌", f"logs={ctx.logs} greeted={ctx.get_var('greeted')}")
    return ok


def test_default_param() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        _write_project(tmp)
        store = discover_keywords(tmp)
        ctx = ExecutionContext()
        ex = Executor(ctx, FaultStrategy.CONTINUE, keyword_store=store)
        ex.run_testcase(_case_calling("greet_verb"))   # 不传 who → 用默认 world
        ok = "world" in ctx.logs
    print("形参默认值补缺:", "✅" if ok else "❌", f"logs={ctx.logs}")
    return ok


def test_recursion_guard() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        _write_project(tmp)
        store = discover_keywords(tmp)
        ex = Executor(ExecutionContext(), FaultStrategy.CONTINUE, keyword_store=store)
        res = ex.run_testcase(_case_calling("rec_verb"))
        skipped = [r for r in res.results if r.status == "SKIP" and "递归" in r.message]
        ok = len(skipped) >= 1   # 第二层自调用被拦截
    print("递归防护:", "✅" if ok else "❌")
    return ok


def test_missing_ks() -> bool:
    ex = Executor(ExecutionContext(), FaultStrategy.CONTINUE, keyword_store=None)
    res = ex.run_testcase(_case_calling("nonexistent"))
    ok = any(r.status == "NOIMPL" for r in res.results)
    print("未找到定义→NOIMPL:", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([
        test_load_keyword(), test_expand_and_scope(), test_default_param(),
        test_recursion_guard(), test_missing_ks(),
    ])
    print("\n总结:", "✅ 自定义关键字(.ks)执行全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
