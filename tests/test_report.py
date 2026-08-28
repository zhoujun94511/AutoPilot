"""阶段8 报告与批量执行测试。

验证：目录用例发现、批量执行聚合、HTML 报告生成（自包含、含汇总与步骤明细、环境信息、时间戳路径）。
"""

import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from autopilot.engine import run_directory, discover_cases
from autopilot.report import write_report, render_report, default_report_path, ReportMeta

SAMPLE_DIR = os.path.join(os.path.dirname(__file__), "sample")


def test_report_loopindex_and_screenshot() -> bool:
    """报告增强：数据驱动步骤显示轮次(loop_index)，失败步骤内嵌 base64 截图。"""
    import base64
    from autopilot.engine.executor import RunResult, StepResult
    from autopilot.engine.suite import SuiteResult

    png_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\nFAKE").decode("ascii")
    rr = RunResult(case_name="dd", source_path="/x/dd.tc", platform="android", tag="MOBILE")
    rr.results = [
        StepResult("log", "第1轮", "PASS", loop_index=1),
        StepResult("log", "第2轮", "PASS", loop_index=2),
        StepResult("verify_equals", "失败步", "FAIL", "a!=b", loop_index=2, screenshot=png_b64,
                   remark="故意制造失败用于报告演示"),
    ]
    html = render_report(
        SuiteResult(name="s", results=[rr]),
        generated_at="t",
        meta=ReportMeta(project_dir="/proj", suite_name="s", fault_strategy="continue"),
    )
    ok = ("轮次" in html
          and ">1<" in html and ">2<" in html
          and f"data:image/png;base64,{png_b64}" in html
          and "失败截图" in html
          and "执行环境" in html
          and "用例总览" in html
          and "失败焦点" in html
          and "首个失败" in html
          and "备注" in html)
    print("报告 loopIndex+截图+环境+失败摘要:", "✅" if ok else "❌")
    return ok


def test_report_fail_reason_in_focus() -> bool:
    """失败焦点与步骤表展示 fail_reason_label。"""
    from autopilot.engine.executor import RunResult, StepResult
    from autopilot.engine.suite import SuiteResult

    rr = RunResult(case_name="locate", source_path="/x/l.tc", platform="android")
    rr.results = [
        StepResult(
            "click", "点按钮", "FAIL", "element not found",
            fail_reason="element_not_found",
            fail_reason_label="元素未找到",
        ),
    ]
    html = render_report(
        SuiteResult(name="s", results=[rr]),
        generated_at="t",
        meta=ReportMeta(suite_name="s"),
    )
    ok = (
        "失败焦点" in html
        and "元素未找到" in html
        and "locate" in html
        and "定位" in html
        and "搜索用例 / 关键字" in html
    )
    print("报告 fail_reason 焦点:", "✅" if ok else "❌")
    return ok


def test_report_parallel_devices_meta() -> bool:
    """多机 meta.devices 的 ios / ios_1 等键全部出现在执行环境区。"""
    from autopilot.engine.executor import RunResult, StepResult
    from autopilot.engine.suite import SuiteResult

    rr = RunResult(
        case_name="c1", device_udid="U-AAA",
        results=[StepResult("log", "", "PASS")],
    )
    html = render_report(
        SuiteResult(name="p", results=[rr]),
        generated_at="t",
        meta=ReportMeta(
            suite_name="p",
            devices={"ios": "U-AAA", "ios_1": "U-BBB"},
        ),
    )
    ok = ("U-AAA" in html and "U-BBB" in html
          and "ios_1" in html and "执行环境" in html)
    print("报告多机设备环境区:", "✅" if ok else "❌")
    return ok


def test_report_path_timestamp() -> bool:
  tmp = tempfile.mkdtemp()
  p = default_report_path(tmp)
  ok = (p.startswith(os.path.join(tmp, "reports"))
        and re.search(r"autopilot_report_\d{8}_\d{6}\.html$", p) is not None)
  print("报告路径(reports/+时间戳):", "✅" if ok else "❌", os.path.basename(p))
  return ok


def main() -> int:
    import shutil
    tmp = tempfile.mkdtemp()
    shutil.copy(os.path.join(SAMPLE_DIR, "login.tc"), os.path.join(tmp, "login.tc"))
    with open(os.path.join(tmp, "fail.tc.yaml"), "w", encoding="utf-8") as f:
        f.write(
            "type: testcase\nformat_version: 1\nname: failcase\ntag: ''\n"
            "is_execute: true\nable_invoked: false\ndatapool: DATATABLE(NONE,false)\n"
            "desc: {}\nshells:\n  before: []\n  case:\n"
            "  - step: verify_equals\n    comment: 故意失败\n    params: {actual: a, expect: b}\n"
            "  after: []\n  fault: []\n")

    paths = discover_cases(tmp)
    print("发现用例:", [os.path.basename(p) for p in paths])

    suite = run_directory(tmp)
    cc = suite.case_counts()
    print("用例统计:", cc, "| 通过率: %.1f%%" % suite.pass_rate())
    print("步骤统计:", suite.step_counts())

    out = default_report_path(tmp)
    write_report(
        suite, out,
        generated_at="2026-06-25 12:00:00",
        meta=ReportMeta(project_dir=tmp, suite_name="batch", fault_strategy="continue"),
    )
    html = open(out, encoding="utf-8").read()
    latest = os.path.join(tmp, "autopilot_report_latest.html")

    checks = {
        "发现2个用例": len(paths) == 2,
        "1通过1失败": cc == {"total": 2, "passed": 1, "failed": 1},
        "报告含通过率": "通过率" in html or "%" in html,
        "报告含用例名": "login" in html and "failcase" in html,
        "报告自包含(无外部src)": "../codebase" not in html and "http://" not in html.split("body")[0],
        "报告含步骤状态": "失败" in html and "通过" in html,
        "报告含环境面板": "执行环境" in html and "Python" in html,
        "报告含用例总览": "用例总览" in html,
        "生成latest副本": os.path.isfile(latest),
        "时间戳文件名": "autopilot_report_" in os.path.basename(out),
    }
    ok = (
        all(checks.values())
        and test_report_loopindex_and_screenshot()
        and test_report_fail_reason_in_focus()
        and test_report_path_timestamp()
        and test_report_parallel_devices_meta()
    )
    for k, v in checks.items():
        print(("  ✅ " if v else "  ❌ ") + k)
    print("\n总结:", "✅ 全部通过" if ok else "❌ 存在失败")
    print("报告路径:", out)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
