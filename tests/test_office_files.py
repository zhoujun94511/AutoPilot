"""阶段13.4 Public 工具补齐回归：CSV 生成 + Excel 写读 round-trip；附 aapt 回退 sanity。"""

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
from autopilot.keywords.registry import REGISTRY
from autopilot.keywords.context import ExecutionContext


def test_csv_create() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.csv")
        REGISTRY["common_CSVFile_create"].func(
            ExecutionContext(), FilePosition="本地", filePath=path,
            tableHead="name,age", tableData="alice,30;bob,25")
        with open(path, encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
    ok = lines == ["name,age", "alice,30", "bob,25"]
    print("CSV 生成:", "✅" if ok else "❌")
    return ok


def test_excel_roundtrip() -> bool:
    try:
        import openpyxl
    except ImportError:
        print("Excel 写读: ⏭ 跳过(无 openpyxl)")
        return True
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "book.xlsx")
        openpyxl.Workbook().save(path)            # 建空表
        ctx = ExecutionContext()
        REGISTRY["common_excel_writeCellValue"].func(
            ctx, filePosition="本地", filePath=path, rowIndex="2", colIndex="3", value="hello")
        out = REGISTRY["common_excel_readCellValue"].func(
            ctx, filePosition="本地", filePath=path, rowIndex="2", colIndex="3", value="cell")
    ok = out == {"cell": "hello"}
    print("Excel 写入→读取 round-trip:", "✅" if ok else "❌")
    return ok


def test_aapt_fallback_sanity() -> bool:
    # 不强制成功（取决于平台 zip）；只验证调用不抛、解析失败时回退路径可达
    from autopilot.mobile import aapt, apk
    try:
        aapt.ensure_aapt()                       # 不应抛
        empty = apk._parse_via_aapt("不存在.apk")  # badging 空 → None
        ok = empty is None
    except Exception as e:  # noqa: BLE001
        print("aapt 回退 sanity: ❌", e)
        return False
    print("aapt 回退 sanity:", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([test_csv_create(), test_excel_roundtrip(), test_aapt_fallback_sanity()])
    print("\n总结:", "✅ Public 工具补齐全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
