"""阶段15.1 平台专有能力划"不支持"回归。

验证：按 implement 类名将 SAP/Mock/MQ/WindQ/Hessian 标为 unsupported；
引擎构造(循环/条件)不被误标；覆盖率口径(可实现范围)正确。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from autopilot.metadata import load_catalog
from autopilot.metadata.keyword_meta import KeywordCatalog, KeywordMeta, classify_unsupported


def test_classify() -> bool:
    yes = all(classify_unsupported(c + ":m")[0] for c in
              ["SAPKeyword", "MockKeyword", "MqKeyword", "WindqKeyword", "HessianKeyword"])
    no = not any(classify_unsupported(c + ":m")[0] for c in
                 ["LogicKeyword", "ExecControlKeyword", "WebElementKeyword", "HttpKeyword"])
    ok = yes and no
    print("implement 类名分类:", "✅" if ok else "❌")
    return ok


def test_catalog_counts() -> bool:
    c = load_catalog()
    total = len(c)
    unsup = c.unsupported_count()
    sup = c.supported_total()
    # 循环/条件标记不应被标为不支持
    loop_if = [c.get(k) for k in
               ("keyword_loop_start", "exec_control_if_end", "mobile_loop_start")]
    engine_ok = all(m is not None and not m.unsupported for m in loop_if)
    # 已剔除永不可实现占位(灰显54+web桩7)，并补齐 7 个中性占位实现(MQ_get_UID/Hessian×2/
    # Mock桩服务×4)→ 已注册即视为支持，灰显归零。
    ok = (total > 0 and unsup == 0 and sup == total and engine_ok)
    assert ok, f"关键字目录统计异常：总数={total} 不支持={unsup} 可实现={sup} 引擎标记={engine_ok}"
    print("覆盖率口径:", "✅" if ok else "❌",
          f"(总 {total} / 不支持 {unsup} / 可实现 {sup})")
    return ok


def test_coverage_denominator() -> bool:
    """用固定目录验证不支持项从可实现分母扣除，不依赖业务关键字总量。"""
    catalog = KeywordCatalog()
    catalog.add(KeywordMeta("implemented"))
    catalog.add(KeywordMeta("engine_marker"))
    catalog.add(KeywordMeta("platform_specific", unsupported=True))
    ok = (len(catalog) == 3 and catalog.unsupported_count() == 1
          and catalog.supported_total() == 2)
    assert ok, "覆盖率分母未扣除不支持项"
    print("覆盖率分母扣除不支持项:", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([test_classify(), test_catalog_counts(), test_coverage_denominator()])
    print("\n总结:", "✅ 平台专有划不支持全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
