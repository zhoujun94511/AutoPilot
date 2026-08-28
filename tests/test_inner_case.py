"""阶段10.2 内嵌用例引用(StepInnerCase)执行回归。

验证：<stepinnercase relativepath> 能加载被引用 .tc 并把其 before/case/after 内联执行，
共享当前上下文；含相对路径解析、循环引用防护、文件缺失处理。
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

import autopilot.keywords  # noqa: F401
from autopilot.model import loader
from autopilot.engine import FaultStrategy
from autopilot.engine.executor import Executor
from autopilot.keywords.context import ExecutionContext

_PARENT = """<?xml version="1.0" encoding="UTF-8"?>
<root ver="1.0" db_id="p1" tag="WEB">
  <case>
    <step id="log" comment="父" isrun="true"><param id="message">parent</param></step>
    <stepinnercase relativepath="child.tc" comment="引用子用例" isrun="true"/>
  </case>
</root>
"""

_CHILD = """<?xml version="1.0" encoding="UTF-8"?>
<root ver="1.0" db_id="c1" tag="WEB">
  <case>
    <step id="log" comment="子" isrun="true"><param id="message">child-ran</param></step>
    <step id="set_var" comment="子产出" isrun="true">
      <param id="name">greeted</param><param id="value">ok</param>
    </step>
  </case>
</root>
"""

# 循环引用：a → b → a
_A = """<?xml version="1.0" encoding="UTF-8"?>
<root ver="1.0" db_id="a1" tag="WEB"><case>
  <stepinnercase relativepath="b.tc" isrun="true"/>
</case></root>
"""
_B = """<?xml version="1.0" encoding="UTF-8"?>
<root ver="1.0" db_id="b1" tag="WEB"><case>
  <stepinnercase relativepath="a.tc" isrun="true"/>
</case></root>
"""


def _write(tmp: str, name: str, content: str) -> str:
    p = os.path.join(tmp, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return p


def test_inline_execute() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        parent = _write(tmp, "parent.tc", _PARENT)
        _write(tmp, "child.tc", _CHILD)
        ctx = ExecutionContext()
        ex = Executor(ctx, FaultStrategy.CONTINUE)
        res = ex.run_testcase(loader.load_testcase(parent))
        ok = ("parent" in ctx.logs and "child-ran" in ctx.logs
              and ctx.get_var("greeted") == "ok" and res.passed)
    print("内嵌用例内联执行:", "✅" if ok else "❌", f"logs={ctx.logs}")
    return ok


def test_cycle_guard() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        a = _write(tmp, "a.tc", _A)
        _write(tmp, "b.tc", _B)
        ex = Executor(ExecutionContext(), FaultStrategy.CONTINUE)
        res = ex.run_testcase(loader.load_testcase(a))
        ok = any(r.status == "SKIP" and "循环引用" in r.message for r in res.results)
    print("循环引用防护:", "✅" if ok else "❌")
    return ok


def test_missing_file() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        parent = _write(tmp, "parent.tc", _PARENT)  # child.tc 不写 → 缺失
        ex = Executor(ExecutionContext(), FaultStrategy.CONTINUE)
        res = ex.run_testcase(loader.load_testcase(parent))
        ok = any(r.status == "FAIL" and "未找到" in r.message for r in res.results)
    print("内嵌文件缺失→FAIL:", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([test_inline_execute(), test_cycle_guard(), test_missing_file()])
    print("\n总结:", "✅ 内嵌用例引用执行全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
