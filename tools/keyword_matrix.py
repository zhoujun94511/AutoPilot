"""关键字核实矩阵：把全部注册关键字按「可测类型 + 是否已被测试引用」盘点成一张表。

用途：在做白盒/真机核实前，先知道 320 个关键字里——哪些已被测试触达、哪些只是“存在但没验”、
哪些必须真机、哪些要外部服务。据此决定真机冒烟重点打哪些，而非盲跑。

可测类型按实现模块归桶：
  pure    —— 纯逻辑/纯数据，离线可白盒直调断言（json/xml/字符串/断言/图像比对等）
  device  —— 需真机/浏览器（Mobile=真机、WebUI=Selenium 浏览器）
  service —— 需外部服务（DB/Redis/SSH/FTP/Kafka/HBase/ES/HTTP 服务）

“已被测试引用” = 该 keyword_id 在 tests/*.py 文本里出现过（粗信号，命中即至少被某测试触达）。

用法：.venv/Scripts/python.exe tools/keyword_matrix.py [--md 输出.md]
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import autopilot.keywords  # noqa: F401  触发全部 @keyword 注册
from autopilot.keywords.registry import REGISTRY

# 实现模块 → 可测类型
_BUCKET = {
    "builtin": "pure",
    "http.json_keywords": "pure", "http.xml_keywords": "pure",
    "http.client": "service",
    "public.common": "pure",            # 多为字符串/日期/断言/随机/列表，少数碰文件
    "web.image": "pure",                # opencv 图像比对，对图片文件操作
    "web.browser": "device", "web.element": "device", "web.verify": "device",
    "mobile.element": "device", "mobile.misc": "device", "mobile.session": "device",
    "data.database": "service", "data.redis_keywords": "service", "data.ssh": "service",
    "data.ftp": "service", "data.kafka_keywords": "service",
    "data.hbase_keywords": "service", "data.elasticsearch_keywords": "service",
}


def _bucket(module: str) -> str:
    m = module.replace("autopilot.keywords.", "")
    return _BUCKET.get(m, "pure")


def _test_referenced_ids() -> set:
    """tests/*.py 文本里出现过的所有 keyword_id（粗粒度覆盖信号）。"""
    blobs = []
    for p in glob.glob("tests/*.py"):
        blobs.append(open(p, encoding="utf-8").read())
    text = "\n".join(blobs)
    return {kid for kid in REGISTRY if kid in text}


def build_rows():
    referenced = _test_referenced_ids()
    rows = []
    for kid, d in REGISTRY.items():
        mod = getattr(d.func, "__module__", "") or ""
        module = mod.replace("autopilot.keywords.", "")
        rows.append({
            "id": kid, "name": d.name, "category": d.category or "-",
            "module": module, "bucket": _bucket(mod),
            "tested": kid in referenced,
        })
    rows.sort(key=lambda r: (r["bucket"], r["category"], r["module"], r["id"]))
    return rows


def summarize(rows) -> str:
    out = []
    total = len(rows)
    by_bucket = {}
    for r in rows:
        b = by_bucket.setdefault(r["bucket"], [0, 0])
        b[0] += 1
        if r["tested"]:
            b[1] += 1
    out.append(f"关键字总计 {total}")
    for b in ("pure", "device", "service"):
        if b in by_bucket:
            tot, tst = by_bucket[b]
            out.append(f"  {b:8} {tot:4} 个，已被测试引用 {tst}，未触达 {tot - tst}")
    tested = sum(1 for r in rows if r["tested"])
    out.append(f"  合计已被测试引用 {tested} / {total}（未触达 {total - tested}）")
    return "\n".join(out)


def to_markdown(rows) -> str:
    lines = ["# 关键字核实矩阵\n", "> bucket: pure=离线白盒可直调 / device=需真机或浏览器 / "
             "service=需外部服务；tested=该 id 在 tests/ 中出现过（粗覆盖信号）\n",
             "## 概览\n", "```", summarize(rows), "```\n", "## 明细\n",
             "| bucket | 类目 | 模块 | id | 名称 | 已测 |",
             "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['bucket']} | {r['category']} | {r['module']} | `{r['id']}` "
                     f"| {r['name']} | {'✅' if r['tested'] else '—'} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default="")
    args = ap.parse_args()
    rows = build_rows()
    print(summarize(rows))
    # 未触达的真机/服务关键字最值得后续真实核实，单独点名前几个
    untouched_dev = [r["id"] for r in rows if r["bucket"] == "device" and not r["tested"]]
    print(f"\n未被测试触达的 device 关键字 {len(untouched_dev)} 个（真机冒烟候选），示例：")
    print("  " + "，".join(untouched_dev[:12]) + (" …" if len(untouched_dev) > 12 else ""))
    if args.md:
        open(args.md, "w", encoding="utf-8").write(to_markdown(rows))
        print(f"\n已写出明细：{args.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
