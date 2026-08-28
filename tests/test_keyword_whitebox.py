"""纯逻辑关键字白盒回归：直接 REGISTRY[id].func(ctx, **真实入参) 断言输出。

覆盖 data/json/xml/字符串/断言 等离线纯逻辑关键字——确认"关键字真的算对"，
而非仅"能跑"。期望值均由真机/离线实跑确认后固化（见会话核实记录）。
"""

import os
import sys
import hashlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import autopilot.keywords  # noqa: F401  触发注册
from autopilot.keywords.registry import REGISTRY
from autopilot.keywords.context import ExecutionContext

_J = '{"user":{"name":"tom","ids":[1,2,3]}}'

# (keyword_id, kwargs, out_key, expected)：out_key 为出参名；其值应等于 expected
_OUT_CASES = [
    ("getMd5", dict(string="abc", result="R"), "R", hashlib.md5(b"abc").hexdigest()),
    ("common_string_case_transform", dict(str="Hello", type="UP", value="R"), "R", "HELLO"),
    ("common_string_case_transform", dict(str="Hello", type="DOWN", value="R"), "R", "hello"),
    ("common_trim_str", dict(fromStr="  hi  ", toStr="R"), "R", "hi"),
    ("common_sreplace_Str", dict(fromStr="a-b-c", oldChar="-", newChar="_", toStr="R"), "R", "a_b_c"),
    ("common_subString_ByLength", dict(string="abcdef", beginIndex="1", length="3", sepValue="R"), "R", "bcd"),
    ("common_subString_BetweenBeginAndEnd", dict(string="abcdef", beginIndex="1", endIndex="4", sepValue="R"), "R", "bcd"),
    ("common_split_AndGetValue", dict(sourceStr="a,b,c", splitStr=",", col="2", value="R"), "R", "b"),
    ("common_split_AndGetLength", dict(sourceStr="a,b,c", splitStr=",", length="R"), "R", "3"),
    ("common_get_str_length", dict(str="hello", length="R"), "R", "5"),
    ("common_generate_empty_str", dict(length="3", reference="R"), "R", "   "),
    ("roundValue", dict(value="3.14159", length="2", targetData="R"), "R", "3.14"),
    ("common_data_calc", dict(data1="2", data2="3", operator="加", targetData="R"), "R", "5"),
    ("json_get_json_value_byjsonpath", dict(json=_J, jsonpath="$.user.name", value="R"), "R", "tom"),
    ("json_to_string", dict(json=_J, string="R"), "R", '{"user": {"name": "tom", "ids": [1, 2, 3]}}'),
    ("xml_get_xml_value", dict(xml="<r><a>x</a><a>y</a></r>", xpath="/r/a", value="R"), "R", "x,y"),
]

# 校验类（不返回值，断言通过=不抛异常）
_VERIFY_OK = [
    ("common_data_compare", dict(data1="5", data2="3", expResult="大于")),
    ("json_exist_key_byjsonpath", dict(json=_J, jsonpath="$.user.name", matched="true")),
    ("xml_verify_xml_value", dict(xml="<r><a>x</a></r>", xpath="/r/a", text="x", matched="true", mode="精确")),
    ("verify_equals", dict(actual="ok", expect="ok")),
    ("verify_contains", dict(text="hello world", sub="world")),
    ("common_verify_String", dict(text="abc", expect="abc", matched="true")),
]


def test_pure_outputs() -> bool:
    ctx = ExecutionContext()
    bad = []
    for kid, kw, key, exp in _OUT_CASES:
        try:
            got = REGISTRY[kid].func(ctx, **kw).get(key)
        except Exception as e:  # noqa: BLE001
            bad.append(f"{kid}: 抛异常 {e}")
            continue
        if got != exp:
            bad.append(f"{kid}: 期望 {exp!r} 实得 {got!r}")
    ok = not bad
    print(f"纯逻辑关键字输出({len(_OUT_CASES)}):", "✅" if ok else "❌")
    for b in bad:
        print("   ", b)
    return ok


def test_verify_keywords() -> bool:
    """校验类：相等条件应通过(不抛)，不等条件应抛 —— 确认断言真的在判。"""
    ctx = ExecutionContext()
    bad = []
    for kid, kw in _VERIFY_OK:
        try:
            REGISTRY[kid].func(ctx, **kw)
        except Exception as e:  # noqa: BLE001
            bad.append(f"{kid}(应通过): 反而抛 {e}")
    # 负向：相等校验给不等输入应抛
    for kid, kw in [("verify_equals", dict(actual="a", expect="b")),
                    ("verify_contains", dict(text="abc", sub="zzz"))]:
        # noinspection PyBroadException
        try:
            REGISTRY[kid].func(ctx, **kw)
            bad.append(f"{kid}(应失败): 却通过了")
        except Exception:  # noqa: BLE001
            pass
    ok = not bad
    print(f"校验类关键字({len(_VERIFY_OK)}正+2负):", "✅" if ok else "❌")
    for b in bad:
        print("   ", b)
    return ok


def main() -> int:
    ok = all([test_pure_outputs(), test_verify_keywords()])
    print("\n总结:", "✅ 纯逻辑关键字白盒全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
