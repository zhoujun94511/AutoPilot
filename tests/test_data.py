"""阶段7 数据类关键字测试。

Database：真实 SQLite 端到端（建表→插入→查询→取数据→行数）。
Redis/SSH/FTP：注入 Fake 客户端验证派发与 OUT 回写。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from autopilot.keywords.context import ExecutionContext
from autopilot.model.testcase import TestCase, Step, ParamValue
from autopilot.engine import Executor, FaultStrategy


def step(kid, comment="", **params):
    return Step(kid, comment, params=[ParamValue(k, v) for k, v in params.items()])


def test_database() -> bool:
    ctx = ExecutionContext()
    tc = TestCase(name="db")
    tc.case.steps = [
        step("database_open", "开库", alias="db1", type="sqlite", url=":memory:"),
        step("database_non_query", "建表", alias="db1",
          sql="CREATE TABLE users(id INTEGER, name TEXT)"),
        step("database_non_query", "插入1", alias="db1",
          sql="INSERT INTO users VALUES(1,'alice')"),
        step("database_non_query", "插入2", alias="db1",
          sql="INSERT INTO users VALUES(2,'bob')"),
        step("database_query", "查询", alias="db1", sql="SELECT * FROM users ORDER BY id",
          data_set="rows"),
        step("database_get_rowcount", "行数", data_set="rows", value="cnt"),
        step("database_get_data", "取第2行name", data_set="rows", row="1", column="name",
          value="name2"),
        step("database_close", "关库", alias="db1"),
    ]
    res = Executor(ctx, fault_strategy=FaultStrategy.STOP).run_testcase(tc)
    for r in res.results:
        if r.status != "PASS":
            print("   ", r.status, r.keyword_id, r.message)
    ok = ctx.get_var("cnt") == 2 and ctx.get_var("name2") == "bob" and \
        res.counts().get("FAIL", 0) == 0
    print("Database(真实SQLite):", "✅" if ok else "❌", "行数=", ctx.get_var("cnt"),
          "第2行name=", ctx.get_var("name2"))
    return ok


class FakeRedis:
    def __init__(self): self.store = {}
    def set(self, k, v): self.store[k] = v
    def get(self, k): return self.store.get(k)
    def delete(self, k): self.store.pop(k, None)
    def close(self): pass


def test_redis() -> bool:
    ctx = ExecutionContext()
    ctx.redis_factory = lambda _ip, _port, _pwd, _db: FakeRedis()
    tc = TestCase(name="redis")
    tc.case.steps = [
        step("redis_connect_redis", "连接", alias="r1", redisIP="127.0.0.1", redisPort="6379"),
        step("redis_set_RedisString", "设值", alias="r1", redisKey="k1", redisValue="v1"),
        step("redis_get_RedisVal", "取值", alias="r1", redisKey="k1", redisValue="out"),
        step("redis_del_RedisKey", "删除", alias="r1", redisKey="k1"),
        step("redis_get_RedisVal", "取已删", alias="r1", redisKey="k1", redisValue="out2"),
        step("redis_quit_Redis", "断开", alias="r1"),
    ]
    res = Executor(ctx, fault_strategy=FaultStrategy.CONTINUE).run_testcase(tc)
    ok = ctx.get_var("out") == "v1" and ctx.get_var("out2") is None and \
        res.counts().get("FAIL", 0) == 0
    print("Redis(Fake):", "✅" if ok else "❌", "取值=", ctx.get_var("out"))
    return ok


class FakeSSH:
    @staticmethod
    def exec_command(cmd):
        class R:
            @staticmethod
            def read(): return f"out:{cmd}".encode()
        return None, R(), R()
    def close(self): pass


def test_ssh() -> bool:
    ctx = ExecutionContext()
    ctx.ssh_factory = lambda _ip, _port, _user, _pwd: FakeSSH()
    tc = TestCase(name="ssh")
    tc.case.steps = [
        step("linux_ssh_connect", "连接", alias="s1", IP="1.2.3.4", port="22", user="root"),
        step("linux_ssh_runCmd_WithResult", "执行", alias="s1", cmd="ls /tmp", result="cmdout"),
        step("linux_ssh_close", "关闭", alias="s1"),
    ]
    res = Executor(ctx, fault_strategy=FaultStrategy.STOP).run_testcase(tc)
    ok = ctx.get_var("cmdout") == "out:ls /tmp" and res.counts().get("FAIL", 0) == 0
    print("SSH(Fake):", "✅" if ok else "❌", "结果=", ctx.get_var("cmdout"))
    return ok


class FakeFTP:
    def __init__(self): self.stored = {}
    def storbinary(self, cmd, f): self.stored[cmd] = f.read()
    @staticmethod
    def retrbinary(_cmd, cb): cb(b"downloaded")
    def quit(self): pass


def test_ftp() -> bool:
    import tempfile
    tmp = tempfile.mkdtemp()
    src = os.path.join(tmp, "up.txt")
    with open(src, "w") as f:
        f.write("hello ftp")
    ctx = ExecutionContext()
    fake = FakeFTP()
    ctx.ftp_factory = lambda _host, _port, _user, _pwd, _path: fake
    tc = TestCase(name="ftp")
    tc.case.steps = [
        step("ftp_ftpclient_connect", "连接", alias="f1", host="1.2.3.4", port="21"),
        step("ftp_ftpclient_uploadFile", "上传", alias="f1", localFilePosition=tmp,
          localFile="up.txt", remoteFile="remote.txt"),
        step("ftp_ftpclient_downloadFile", "下载", alias="f1", remoteFile="remote.txt",
          localFilePosition=tmp, localFile="down.txt"),
        step("ftp_ftpclient_closeFtp", "关闭", alias="f1"),
    ]
    res = Executor(ctx, fault_strategy=FaultStrategy.STOP).run_testcase(tc)
    down = os.path.join(tmp, "down.txt")
    ok = (fake.stored.get("STOR remote.txt") == b"hello ftp"
          and os.path.exists(down) and open(down, "rb").read() == b"downloaded"
          and res.counts().get("FAIL", 0) == 0)
    print("FTP(Fake):", "✅" if ok else "❌")
    return ok


def test_redis_dbindex_delmode() -> bool:
    """redis dbIndex 生效(切分片) + del 模糊匹配前缀批量删（修断参数）。"""
    class FakeRedis2:
        def __init__(self):
            self.store = {}
            self.selected = None
        def select(self, db):
            self.selected = db
        def set(self, k, v):
            self.store[k] = v
        def keys(self, pat):
            pre = pat.rstrip("*")
            return [k for k in self.store if k.startswith(pre)]
        def delete(self, *ks):
            for k in ks:
                self.store.pop(k, None)
        def close(self):
            pass
    fake = FakeRedis2()
    ctx = ExecutionContext()
    ctx.redis_factory = lambda _ip, _port, _pwd, _db: fake
    tc = TestCase(name="r")
    tc.case.steps = [
        step("redis_connect_redis", alias="r1", redisIP="127.0.0.1", redisPort="6379"),
        step("redis_set_RedisString", alias="r1", redisKey="u:1", redisValue="a", dbIndex="3"),
        step("redis_set_RedisString", alias="r1", redisKey="u:2", redisValue="b", dbIndex="3"),
        step("redis_set_RedisString", alias="r1", redisKey="x:1", redisValue="c", dbIndex="3"),
        step("redis_del_RedisKey", alias="r1", redisKey="u:*", dbIndex="3", delMode="模糊匹配"),
    ]
    res = Executor(ctx, fault_strategy=FaultStrategy.CONTINUE).run_testcase(tc)
    ok = (fake.selected == 3                              # dbIndex 切到了 db3
          and "u:1" not in fake.store and "u:2" not in fake.store   # 模糊前缀删掉 u:*
          and "x:1" in fake.store                          # 非前缀保留
          and res.counts().get("FAIL", 0) == 0)
    print("Redis dbIndex/delMode(切分片/模糊删):", "✅" if ok else "❌")
    return ok


def test_database_maxtimeout() -> bool:
    """database_query.maxTimeOut：结果空时轮询重试到有数据（修断参数）。"""
    from autopilot.keywords.data import database as db

    class FakeConn:
        def __init__(self):
            self.n = 0
        def query(self, _sql):
            self.n += 1
            return [] if self.n < 2 else [{"id": 1}]   # 第2次才有数据
    ctx = ExecutionContext()
    db._manager(ctx)["d1"] = FakeConn()
    out = db.database_query(ctx, alias="d1", sql="select 1", data_set="rows", maxTimeOut="3")
    ok = out["rows"] == [{"id": 1}]                        # 轮询到第2次拿到数据
    # maxTimeOut 空 → 只查一次(空)
    ctx2 = ExecutionContext()
    ec = FakeConn(); ec.query = lambda _s: []
    db._manager(ctx2)["d1"] = ec
    out2 = db.database_query(ctx2, alias="d1", sql="x", data_set="rows", maxTimeOut="")
    ok = ok and out2["rows"] == []
    print("database maxTimeOut(空则轮询重试):", "✅" if ok else "❌")
    return ok


def main() -> int:
    ok = all([test_database(), test_redis(), test_ssh(), test_ftp(),
              test_redis_dbindex_delmode(), test_database_maxtimeout()])
    print("\n总结:", "✅ 全部通过" if ok else "❌ 存在失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
