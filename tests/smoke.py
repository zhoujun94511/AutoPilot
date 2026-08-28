"""端到端冒烟测试：导入旧格式 .tc → 执行引擎跑通（无浏览器）。

验证：旧 XML 解析、变量池 ${x} 展开、条件步骤、校验关键字、被砍关键字降级为 NOIMPL。
运行：.venv/Scripts/python.exe tests/smoke.py
"""

import os
import sys

# Windows 终端默认 GBK，强制 UTF-8 输出避免中文/符号乱码
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autopilot.model.loader import load_testcase
from autopilot.engine import Executor, FaultStrategy
from autopilot.keywords.context import ExecutionContext

SAMPLE = os.path.join(os.path.dirname(__file__), "sample", "login.tc")


def main() -> int:
    tc = load_testcase(SAMPLE)
    print(f"导入用例: {tc.name}  tag={tc.tag}  db_id={tc.data_id}")
    print(f"  before={len(tc.before.steps)} case={len(tc.case.steps)} "
          f"after={len(tc.after.steps)} fault={len(tc.fault.steps)}")

    ctx = ExecutionContext()
    ex = Executor(ctx, fault_strategy=FaultStrategy.CONTINUE)
    res = ex.run_testcase(tc)

    print("\n执行结果:")
    for r in res.results:
        print(f"  [{r.status:6}] {r.keyword_id:22} {r.comment}  {r.message}")

    print("\n变量池:", ctx.variables)
    print("日志:", ctx.logs)
    print("统计:", res.counts())

    # 断言期望：有 PASS、有 1 个 NOIMPL（sap_login），无 FAIL
    counts = res.counts()
    ok = counts.get("FAIL", 0) == 0 and counts.get("NOIMPL", 0) == 1 and counts.get("PASS", 0) >= 5
    print("\n结果:", "✅ 通过" if ok else "❌ 不符合预期")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
