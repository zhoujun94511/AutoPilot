"""阶段5 数据驱动与逻辑控制测试。

验证：DataConfig(.properties) 基线变量、if/else(param1/param2/expResult 算子)、
定次循环(cycle_times)、Excel 数据驱动循环(COLUMN 取列值)。
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

from autopilot.keywords.context import ExecutionContext
from autopilot.model import dataconfig
from autopilot.model.testcase import TestCase, Step, StepSet, ParamValue
from autopilot.engine import Executor, FaultStrategy


def test_dataconfig() -> bool:
    cfg = dataconfig.loads("!baseUrl:首页地址\nbaseUrl=http://x\nuser=admin\n# 注释行\n")
    ok = cfg.as_dict() == {"baseUrl": "http://x", "user": "admin"} and \
        cfg.comments.get("baseUrl") == "首页地址"
    print("DataConfig 解析:", "✅" if ok else "❌", cfg.as_dict())
    return ok


def test_if_else() -> bool:
    ctx = ExecutionContext()
    ctx.set_var("score", "80")
    tc = TestCase(name="ifelse")
    cond = Step("exec_control_if_end", "分数>=60?", params=[
        ParamValue("param1", "${score}"), ParamValue("param2", "60"),
        ParamValue("expResult", "大于等于")])
    cond.children = [
        Step("set_var", "及格", params=[ParamValue("name", "result"), ParamValue("value", "pass")]),
        Step("else", "否则"),
        Step("set_var", "不及格", params=[ParamValue("name", "result"), ParamValue("value", "fail")]),
    ]
    tc.case.steps = [cond]
    Executor(ctx).run_testcase(tc)
    ok = ctx.get_var("result") == "pass"
    print("if/else(大于等于):", "✅" if ok else "❌", "result=", ctx.get_var("result"))
    return ok


def test_cycle_loop() -> bool:
    ctx = ExecutionContext()
    ctx.set_var("count", "0")
    # 用 log 累计：循环 3 次，每次 log，验证循环体执行 3 次
    tc = TestCase(name="cycle")
    tc.case.steps = [
        Step("keyword_loop_start", "循环3次", params=[
            ParamValue("datapool_source_type", "无"), ParamValue("cycle_times", "3"),
            ParamValue("loop_failure_strategy", "break")]),
        Step("log", "记一次", params=[ParamValue("message", "iter")]),
        Step("keyword_loop_end", "结束"),
    ]
    Executor(ctx).run_testcase(tc)
    logs = [x for x in ctx.logs if x == "iter"]
    ok = len(logs) == 3
    print("定次循环 cycle_times=3:", "✅" if ok else "❌", "log次数=", len(logs))
    return ok


def test_excel_datadriven() -> bool:
    from openpyxl import Workbook
    tmp = tempfile.mkdtemp()
    xlsx = os.path.join(tmp, "data.xlsx")
    wb = Workbook()
    ws = wb.active
    ws.append(["username", "expect"])
    ws.append(["alice", "alice"])
    ws.append(["bob", "bob"])
    ws.append(["carol", "carol"])
    wb.save(xlsx)

    ctx = ExecutionContext()
    tc = TestCase(name="ddt")
    tc.case.steps = [
        Step("keyword_loop_start", "按Excel行循环", params=[
            ParamValue("datapool_source_type", "Excel"),
            ParamValue("datapool_source_path", xlsx),
            ParamValue("loop_failure_strategy", "break")]),
        # COLUMN(username) 取当前行；与 expect 列校验一致
        Step("set_var", "存名字", params=[
            ParamValue("name", "lastUser"), ParamValue("value", "COLUMN(username,none)")]),
        Step("verify_equals", "校验", params=[
            ParamValue("actual", "COLUMN(username,none)"),
            ParamValue("expect", "COLUMN(expect,none)")]),
        Step("log", "记录", params=[ParamValue("message", "COLUMN(username,none)")]),
        Step("keyword_loop_end", "结束"),
    ]
    res = Executor(ctx, fault_strategy=FaultStrategy.CONTINUE).run_testcase(tc)
    names = [x for x in ctx.logs if x in ("alice", "bob", "carol")]
    ok = (names == ["alice", "bob", "carol"]
          and res.counts().get("FAIL", 0) == 0
          and ctx.get_var("lastUser") == "carol")
    print("Excel 数据驱动(3行):", "✅" if ok else "❌", "迭代名字=", names,
          "| 统计=", res.counts())
    return ok


def test_stepset_datadriven() -> bool:
    """步骤组绑定数据池 DATATABLE(路径,私有)：children 按行执行，COLUMN 取列值；未污染外层。"""
    ctx = ExecutionContext()
    ctx.set_var("outer", "keep")
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "rows.csv")
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write("name\nalice\nbob\n")
        tc = TestCase(name="ss")
        ss = StepSet(name="g", datapool=f"DATATABLE({p},true)")
        ss.children = [Step("log", "记录", params=[ParamValue("message", "COLUMN(name,none)")])]
        tc.case.steps.append(ss)
        res = Executor(ctx, fault_strategy=FaultStrategy.CONTINUE).run_testcase(tc)
    names = [x for x in ctx.logs if x in ("alice", "bob")]
    ok = (names == ["alice", "bob"] and res.counts().get("FAIL", 0) == 0
          and not ctx.data_row)   # 私有作用域：行末已还原
    print("步骤组数据驱动(逐行/COLUMN/私有还原):", "✅" if ok else "❌", names)
    return ok


def test_case_datadriven() -> bool:
    """用例级绑定数据池：case 主体整体逐行循环；before/after 各一次。"""
    ctx = ExecutionContext()
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "rows.csv")
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write("who\nx\ny\nz\n")
        tc = TestCase(name="cd", datapool=f"DATATABLE({p},false)")
        tc.before.steps.append(Step("log", "前置", params=[ParamValue("message", "B")]))
        tc.case.steps.append(Step("log", "主体", params=[ParamValue("message", "COLUMN(who,none)")]))
        tc.after.steps.append(Step("log", "后置", params=[ParamValue("message", "A")]))
        res = Executor(ctx, fault_strategy=FaultStrategy.CONTINUE).run_testcase(tc)
    body = [x for x in ctx.logs if x in ("x", "y", "z")]
    ok = (body == ["x", "y", "z"]                 # 主体跑 3 行
          and ctx.logs.count("B") == 1            # 前置一次
          and ctx.logs.count("A") == 1            # 后置一次
          and res.counts().get("FAIL", 0) == 0)
    print("用例级数据驱动(主体3行/前后各1次):", "✅" if ok else "❌", body)
    return ok


def test_datatable_columns() -> bool:
    """engine.datatable_columns：从绑定数据文件读表头列名；未绑定/NONE/缺文件→[]。"""
    from autopilot.engine.executor import datatable_columns
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "r.csv")
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write("user,pwd,note\na,b,c\n")
        cols = datatable_columns(f"DATATABLE({p},false)")
        cols_rel = datatable_columns("DATATABLE(r.csv,false)", d)   # 相对 base_dir
        none = datatable_columns("DATATABLE(NONE,false)")
        missing = datatable_columns("DATATABLE(nope.csv,false)", d)
    ok = (cols == ["user", "pwd", "note"] and cols_rel == ["user", "pwd", "note"]
          and none == [] and missing == [])
    print("engine.datatable_columns(表头/相对路径/NONE空/缺文件空):", "✅" if ok else "❌")
    return ok


def test_fallback_values() -> bool:
    """参数 || 容错值：取首个非空；空值回退；COLUMN 空→回退字面量；无 || 不受影响。"""
    ctx = ExecutionContext()
    ctx.set_var("empty", "")
    ctx.set_var("name", "alice")
    a = ctx.resolve("${empty}||${name}") == "alice"       # 首段空 → 回退
    b = ctx.resolve("${name}||x") == "alice"              # 首段非空即用
    c = ctx.resolve("COLUMN(missing,)||default") == "default"   # 列缺+默认空 → 回退
    d = ctx.resolve("plain") == "plain"                   # 无 || 原样
    ok = a and b and c and d
    print("参数 || 容错值(非空优先/空回退/COLUMN回退/无||不变):", "✅" if ok else "❌")
    return ok


def _inject_kw(kid, func, out=None):
    """临时往 REGISTRY 注册一个测试关键字，返回清理函数。"""
    from autopilot.keywords.registry import REGISTRY, KeywordDef
    REGISTRY[kid] = KeywordDef(keyword_id=kid, func=func, out_params=list(out or []))
    return lambda: REGISTRY.pop(kid, None)


def test_shell_semantics() -> bool:
    """壳语义：after 为 finally 总执行；fault 仅失败时执行；成功时不跑 fault。"""
    hits = []
    undo = _inject_kw("_t_mark", lambda _c, tag="": hits.append(tag))
    undo_fail = _inject_kw("_t_boom", lambda _c: (_ for _ in ()).throw(RuntimeError("boom")))
    try:
        def mk():
            t = TestCase(name="s")
            t.before.steps.append(Step("_t_mark", params=[ParamValue("tag", "before")]))
            t.after.steps.append(Step("_t_mark", params=[ParamValue("tag", "after")]))
            t.fault.steps.append(Step("_t_mark", params=[ParamValue("tag", "fault")]))
            return t
        # 1) case 失败(STOP)：after 仍跑(finally)，fault 跑(失败兜底)
        hits.clear()
        tc = mk()
        tc.case.steps.append(Step("_t_boom", "会失败"))
        Executor(ExecutionContext(), fault_strategy=FaultStrategy.STOP).run_testcase(tc)
        fail_case = hits == ["before", "after", "fault"]
        # 2) 全成功：after 跑，fault 不跑
        hits.clear()
        tc = mk()
        tc.case.steps.append(Step("_t_mark", params=[ParamValue("tag", "case")]))
        Executor(ExecutionContext(), fault_strategy=FaultStrategy.STOP).run_testcase(tc)
        ok_case = hits == ["before", "case", "after"]
        ok = fail_case and ok_case
    finally:
        undo(); undo_fail()
    print("壳语义(after=finally/fault=失败兜底):", "✅" if ok else "❌", hits)
    return ok


def test_step_timeout() -> bool:
    """步骤超时熔断(opt-in)：step_timeout_ms>0 时慢关键字被熔断记 FAIL；默认0不影响。"""
    import time as _t
    undo = _inject_kw("_t_slow", lambda _c: _t.sleep(2))
    try:
        tc = TestCase(name="to")
        tc.case.steps.append(Step("_t_slow", "慢步骤"))
        res = Executor(ExecutionContext(), step_timeout_ms=200).run_testcase(tc)
        fired = res.counts().get("FAIL", 0) == 1 and any(
            "熔断" in r.message for r in res.results)
        # 默认(0=关闭)：同样的慢步骤应正常跑完(PASS)，不熔断
        tc2 = TestCase(name="to2")
        tc2.case.steps.append(Step("_t_slow", "慢步骤"))
        res2 = Executor(ExecutionContext()).run_testcase(tc2)
        off_ok = res2.counts().get("PASS", 0) == 1 and res2.counts().get("FAIL", 0) == 0
        ok = fired and off_ok
    finally:
        undo()
    print("步骤超时熔断(开启熔断/关闭不影响):", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([test_dataconfig(), test_if_else(), test_cycle_loop(), test_excel_datadriven(),
              test_shell_semantics(), test_step_timeout(),
              test_stepset_datadriven(), test_case_datadriven(),
              test_fallback_values(), test_datatable_columns()])
    print("\n总结:", "✅ 全部通过" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
