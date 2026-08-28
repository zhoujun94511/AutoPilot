"""中间件关键字测试（Kafka/ES/HBase，注入 fake 客户端验证派发与 OUT，无需真实环境）。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import autopilot.keywords  # noqa: F401
from autopilot.keywords.context import ExecutionContext
from autopilot.keywords.registry import REGISTRY
from autopilot.model.testcase import TestCase, Step, ParamValue, Shell
from autopilot.engine import Executor, FaultStrategy


def step(k, **p):
    return Step(k, "", params=[ParamValue(i, v) for i, v in p.items()])


def run(ctx, steps):
    tc = TestCase(name="mw")
    tc.case = Shell("case", steps)
    return Executor(ctx, fault_strategy=FaultStrategy.CONTINUE).run_testcase(tc)


def test_kafka() -> bool:
    sent = {}

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class FakeProducer:
        def send(self, topic, value=None, _partition=None, **_k):
            sent["topic"] = topic
            sent["value"] = value

            class F:
                @staticmethod
                def get(_t=None): return type("M", (), {"offset": 42})()
            return F()
        def flush(self): pass
        def close(self): pass

    ctx = ExecutionContext()
    ctx.kafka_producer_factory = lambda _hosts: FakeProducer()
    res = run(ctx, [step("produceKafkaMsg", msg="hello", topic="t1", hosts="h:9092")])
    ok = res.counts().get("FAIL", 0) == 0 and sent.get("topic") == "t1"
    print("Kafka produce(fake):", "✅" if ok else "❌", "sent=", sent.get("topic"))
    return "produceKafkaMsg" in REGISTRY and ok


def test_es() -> bool:
    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class FakeES:
        def search(self, _index=None, _body=None, **_k):
            return {"hits": {"hits": [{"_source": {"msg": "log1"}}], "total": 1}}
    ctx = ExecutionContext()
    ctx.es_factory = lambda _url: FakeES()
    res = run(ctx, [step("es_query_dsl", url="http://es:9200",
                      dsl='{"query":{"match_all":{}}}', result_out_var="r")])
    ok = res.counts().get("FAIL", 0) == 0 and ctx.get_var("r")
    print("ES query_dsl(fake):", "✅" if ok else "❌", "有结果=", bool(ctx.get_var("r")))
    return "es_query_dsl" in REGISTRY and ok


def test_hbase() -> bool:
    store = {}

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class FakeTable:
        def __init__(self, name): self.name = name
        def put(self, rk, data): store.setdefault(self.name, {}).setdefault(rk, {}).update(data)
        def row(self, rk): return store.get(self.name, {}).get(rk, {})
        def delete(self, rk): store.get(self.name, {}).pop(rk, None)

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    class FakeConn:
        def table(self, name): return FakeTable(name)
        def tables(self): return [b"t1"]

    ctx = ExecutionContext()
    ctx.hbase_factory = lambda *_a, **_k: FakeConn()
    res = run(ctx, [
        step("hbase_connect", alias="h1", quorum="zk", clientPort="2181"),
        step("hbase_put", alias="h1", tableName="t1", rowKey="r1",
          columnFamily="cf", column="c", value="v1"),
        step("hbase_get", alias="h1", tableName="t1", rowKey="r1", outResult="row"),
    ])
    got = ctx.get_var("row")
    ok = res.counts().get("FAIL", 0) == 0 and got and any(b"v1" in (str(v).encode() if not isinstance(v, bytes) else v)
                                                          or v == "v1" for v in (got.values() if isinstance(got, dict) else []))
    print("HBase connect/put/get(fake):", "✅" if ok else "❌", "row=", got)
    return all(k in REGISTRY for k in ("hbase_connect", "hbase_put", "hbase_get")) and res.counts().get("FAIL", 0) == 0


def main() -> int:
    ok = all([test_kafka(), test_es(), test_hbase()])
    print("\n总结:", "✅ 全部通过" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
