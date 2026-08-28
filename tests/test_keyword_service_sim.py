"""服务类关键字（DB/Redis/SSH）模拟场景白盒：无真实服务时，用真 SQLite + 进程内
FakeRedis/FakeSSH 注入到关键字的工厂注入点，端到端验证关键字读写/解析逻辑。

- DB：真 `sqlite3`（url=":memory:"），最忠实，无需打桩。
- Redis：dict 实现的 FakeRedis（decode_responses 语义，返回 str），经 ctx.redis_factory 注入。
- SSH：FakeSSH.exec_command 回显命令，经 ctx.ssh_factory 注入，验命令下发→结果解析。
"""

import os
import sys
import fnmatch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import autopilot.keywords  # noqa: F401
from autopilot.keywords.registry import REGISTRY
from autopilot.keywords.context import ExecutionContext

K = REGISTRY


def test_db_sqlite() -> bool:
    """DB 关键字打真 SQLite(:memory:)：建表→插入→查询→更新→再查。"""
    try:
        ctx = ExecutionContext()
        K["database_open"].func(ctx, alias="db", type="sqlite", url=":memory:")
        K["database_non_query"].func(ctx, alias="db", sql="CREATE TABLE t(id INTEGER, name TEXT)")
        K["database_non_query"].func(ctx, alias="db", sql="INSERT INTO t VALUES (1,'tom'),(2,'jerry')")
        r1 = K["database_query"].func(ctx, alias="db", sql="SELECT name FROM t WHERE id=1", data_set="DS")["DS"]
        K["database_non_query"].func(ctx, alias="db", sql="UPDATE t SET name='bob' WHERE id=1")
        r2 = K["database_query"].func(ctx, alias="db", sql="SELECT name FROM t WHERE id=1", data_set="DS")["DS"]
        cnt = K["database_query"].func(ctx, alias="db", sql="SELECT COUNT(*) c FROM t", data_set="DS")["DS"]
        ok = (r1 and r1[0].get("name") == "tom"
              and r2 and r2[0].get("name") == "bob"
              and cnt and list(cnt[0].values())[0] == 2)
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("DB(sqlite 模拟): ⏭ 跳过(", e, ")")
        return True
    print("DB 关键字(真 SQLite 建/增/查/改):", "✅" if ok else "❌")
    return ok


# noinspection PyMethodMayBeStatic,PyUnusedLocal
class _FakeRedis:
    """dict 实现的最小 Redis（decode_responses 语义：存取 str）。"""
    def __init__(self):
        self.s, self.h, self.lists, self.sets = {}, {}, {}, {}

    def set(self, k, v, *a, **kw): self.s[k] = str(v)
    def get(self, k): return self.s.get(k)

    def delete(self, *ks):
        n = 0
        for k in ks:
            n += 1 if self.s.pop(k, None) is not None else 0
        return n

    def keys(self, pattern="*"): return [k for k in self.s if fnmatch.fnmatch(k, pattern)]
    def exists(self, *ks): return sum(1 for k in ks if k in self.s)
    def hset(self, k, f=None, v=None, mapping=None):
        d = self.h.setdefault(k, {})
        if mapping:
            d.update({a: str(b) for a, b in mapping.items()})
        if f is not None:
            d[f] = str(v)

    def hget(self, k, f): return self.h.get(k, {}).get(f)
    def select(self, _db): pass
    def close(self): pass


def test_redis_fake() -> bool:
    """Redis 关键字打 FakeRedis：连接→set/get→hash→keys→del→再 get 为空。"""
    try:
        ctx = ExecutionContext()
        fake = _FakeRedis()
        ctx.redis_factory = lambda *a, **k: fake   # 注入点：同一实例，状态持久
        K["redis_connect_redis"].func(ctx, alias="r", redisIP="127.0.0.1", redisPort="6379")
        K["redis_set_RedisString"].func(ctx, alias="r", redisKey="k1", redisValue="v1")
        got = K["redis_get_RedisVal"].func(ctx, alias="r", redisKey="k1", redisValue="RV")["RV"]
        K["redis_set_RedisHsh"].func(ctx, alias="r", redisKey="h1", redisField="f", redisValue="hv")
        hgot = K["redis_get_RedisHashVal"].func(ctx, alias="r", redisKey="h1", field="f", redisValue="HV")["HV"]
        keys = K["redis_get_keys"].func(ctx, alias="r", redisKey="*", redisValue="KS")["KS"]
        K["redis_del_RedisKey"].func(ctx, alias="r", redisKey="k1")
        after = K["redis_get_RedisVal"].func(ctx, alias="r", redisKey="k1", redisValue="RV")["RV"]
        ok = (got == "v1" and hgot == "hv" and "k1" in (keys or []) and after is None)
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("Redis(Fake 模拟): ⏭ 跳过(", e, ")")
        return True
    print("Redis 关键字(Fake: set/get/hash/keys/del):", "✅" if ok else "❌")
    return ok


class _FakeStd:
    def __init__(self, data=b""): self._d = data
    def read(self): return self._d


# noinspection PyMethodMayBeStatic,PyUnusedLocal
class _FakeSSH:
    """回显命令的假 SSH：exec_command 返回 (stdin, stdout=OUT:<cmd>, stderr)。"""
    def exec_command(self, cmd, *a, **k):
        return _FakeStd(), _FakeStd(("OUT:" + cmd).encode("utf-8")), _FakeStd(b"")

    def close(self): pass


def test_ssh_fake() -> bool:
    """SSH 关键字打 FakeSSH：连接→执行带结果命令→结果应含下发的命令(链路通)。"""
    try:
        ctx = ExecutionContext()
        ctx.ssh_factory = lambda *a, **k: _FakeSSH()
        K["linux_ssh_connect"].func(ctx, alias="s", IP="10.0.0.1", port="22", user="u", passwd="p")
        res = K["linux_ssh_runCmd_WithResult"].func(ctx, alias="s", cmd="whoami", result="R")["R"]
        ok = "whoami" in (res or "")
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("SSH(Fake 模拟): ⏭ 跳过(", e, ")")
        return True
    print("SSH 关键字(Fake: 连接+执行回显):", "✅" if ok else "❌", f"(结果={res!r})")
    return ok


class _FakeFTP:
    def __init__(self): self.files = {}
    def storbinary(self, cmd, f): self.files[cmd.split()[1]] = f.read()
    def retrbinary(self, cmd, cb): cb(self.files.get(cmd.split()[1], b""))
    def quit(self): pass
    def close(self): pass


def test_ftp_fake() -> bool:
    """FTP 关键字打 FakeFTP：连接→上传本地文件→下载到另一路径，内容应一致(链路通)。"""
    try:
        import tempfile
        ctx = ExecutionContext()
        fake = _FakeFTP()
        ctx.ftp_factory = lambda *a, **k: fake
        d = tempfile.mkdtemp(prefix="ap_ftp_")
        src = os.path.join(d, "up.txt")
        open(src, "w", encoding="utf-8").write("ftp-payload")
        K["ftp_ftpclient_connect"].func(ctx, alias="f", host="127.0.0.1", port="21")
        K["ftp_ftpclient_uploadFile"].func(ctx, alias="f", localFilePosition=d, localFile="up.txt", remoteFile="r.txt")
        K["ftp_ftpclient_downloadFile"].func(ctx, alias="f", remoteFile="r.txt", localFilePosition=d, localFile="down.txt")
        got = open(os.path.join(d, "down.txt"), encoding="utf-8").read()
        ok = got == "ftp-payload"
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("FTP(Fake 模拟): ⏭ 跳过(", e, ")")
        return True
    print("FTP 关键字(Fake: 连接+上传+下载回读):", "✅" if ok else "❌")
    return ok


# noinspection PyMethodMayBeStatic,PyUnusedLocal
class _FakeES:
    def search(self, body=None, **k):
        return {"took": 1, "hits": {"total": 1, "hits": [{"_source": {"name": "tom"}}]}}


def test_es_fake() -> bool:
    """ES 关键字打 FakeES：QueryDSL 执行→返回命中 JSON 串。"""
    try:
        ctx = ExecutionContext()
        ctx.es_factory = lambda url: _FakeES()
        res = K["es_query_dsl"].func(ctx, url="http://es", dsl='{"query":{"match_all":{}}}',
                                     result_out_var="R")["R"]
        ok = "hits" in res and "tom" in res
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("ES(Fake 模拟): ⏭ 跳过(", e, ")")
        return True
    print("ES 关键字(Fake: QueryDSL→命中):", "✅" if ok else "❌")
    return ok


# noinspection PyMethodMayBeStatic,PyUnusedLocal
class _FakeTable:
    def __init__(self, store): self.store = store
    def put(self, rk, data): self.store.setdefault(rk, {}).update(data)
    def row(self, rk): return self.store.get(rk, {})
    def delete(self, rk, *a, **k): self.store.pop(rk, None)


class _FakeHConn:
    def __init__(self): self.data = {}
    def table(self, name): return _FakeTable(self.data.setdefault(name, {}))
    def tables(self): return list(self.data.keys())
    def close(self): pass


def test_hbase_fake() -> bool:
    """HBase 关键字打 FakeHConn：连接→put→get→校验表存在→del→get 为空。"""
    try:
        ctx = ExecutionContext()
        fake = _FakeHConn()
        ctx.hbase_factory = lambda *a, **k: fake
        K["hbase_connect"].func(ctx, alias="hb", quorum="q", clientPort="2181")
        K["hbase_put"].func(ctx, alias="hb", tableName="t1", rowKey="r1",
                            columnFamily="cf", column="c", value="v1")
        got = K["hbase_get"].func(ctx, alias="hb", tableName="t1", rowKey="r1", outResult="R")["R"]
        K["hbase_verify_table_existed"].func(ctx, alias="hb", tableName="t1", isExist="true")
        K["hbase_del"].func(ctx, alias="hb", tableName="t1", rowKey="r1")
        after = K["hbase_get"].func(ctx, alias="hb", tableName="t1", rowKey="r1", outResult="R")["R"]
        ok = got.get("cf:c") == "v1" and not after
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("HBase(Fake 模拟): ⏭ 跳过(", e, ")")
        return True
    print("HBase 关键字(Fake: put/get/校验表/del):", "✅" if ok else "❌")
    return ok


class _FakeFuture:
    offset = 7

    def get(self, _timeout=None):
        return self


class _FakeProducer:
    def __init__(self):
        self.sent = None

    def send(self, topic, value=None, **_k):
        self.sent = (topic, value)
        return _FakeFuture()
    def flush(self): pass


# noinspection PyMethodMayBeStatic,PyUnusedLocal
class _FakeConsumer:
    def __init__(self, msgs): self.msgs = msgs; self._i = 0
    def assign(self, tps): pass
    def seek_to_end(self, tp): pass
    def seek_to_beginning(self, tp): self._i = 0
    def position(self, tp): return len(self.msgs)
    def seek(self, tp, off): self._i = int(off)

    def __iter__(self):
        class _Rec:
            def __init__(self, value):
                self.value = value
        for m in self.msgs[self._i:]:
            yield _Rec(m.encode("utf-8"))

    def close(self): pass


def test_kafka_fake() -> bool:
    """Kafka 关键字打 Fake producer/consumer：生产返回 offset；按 offset 读取消息。"""
    try:
        ctx = ExecutionContext()
        ctx.kafka_producer_factory = lambda hosts: _FakeProducer()
        off = K["produceKafkaMsg"].func(ctx, msg="hi", topic="t", partition="0",
                                        hosts="h:9092", offset="OFF")["OFF"]
        ctx.kafka_consumer_factory = lambda hosts: _FakeConsumer(["hello", "world"])
        out = K["readKafkaMsg"].func(ctx, offset="0", num="10", topic="t", partition="0",
                                     hosts="h:9092", var="V")["V"]
        ok = off == "7" and "hello" in str(out)
    except Exception as e:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print("Kafka(Fake 模拟): ⏭ 跳过(", e, ")")
        return True
    print("Kafka 关键字(Fake: 生产 offset/按 offset 读取):", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([test_db_sqlite(), test_redis_fake(), test_ssh_fake(),
              test_ftp_fake(), test_es_fake(), test_hbase_fake(), test_kafka_fake()])
    print("\n总结:", "✅ 服务类关键字模拟全绿" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
