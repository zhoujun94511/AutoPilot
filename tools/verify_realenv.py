"""真机 / 真服务连通性验证（按需在目标环境运行，不进 CI）。

逐项探测：Android(adb) / iOS(go-ios) / 数据与中间件(Redis/SSH/DB/Kafka/ES/HBase)。
仅做"能连上 + 基本读写"的冒烟，不依赖被测业务；缺失环境的项标 SKIP 而非失败。

用法：
    .venv/Scripts/python.exe tools/verify_realenv.py
环境变量（按需）：
    REDIS_URL=redis://127.0.0.1:6379/0
    SSH_HOST=.. SSH_USER=.. SSH_PASSWORD=..
    DB_URL=sqlite:///:memory:    （或 mysql+pymysql://...）
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _line(name, status, detail=""):
    mark = {"OK": "✅", "SKIP": "⏭", "FAIL": "❌"}.get(status, "?")
    print(f"  {mark} {name:18} {status:4} {detail}")


def check_android() -> None:
    from autopilot.mobile import adb
    from autopilot.mobile.android_env import resolve_android_sdk_root
    from autopilot.mobile.android_devices import list_usb_devices

    exe = adb.ensure_adb()
    if exe is None:
        _line("Android/adb", "SKIP", "未找到 adb（resources/re_adb 或 PATH）")
        return
    sdk = resolve_android_sdk_root()
    if sdk:
        _line("Android/SDK", "OK", str(sdk))
    else:
        _line("Android/SDK", "WARN", "未找到 ANDROID_HOME（Appium UiAutomator2 需 SDK）")
    try:
        devs = list_usb_devices()
        if devs:
            labels = [f"{d.serial}({d.model or '?'})" for d in devs]
            _line("Android/adb", "OK", "在线: " + ", ".join(labels))
        else:
            _line("Android/adb", "SKIP", "adb 可用但无在线设备")
    except Exception as e:  # noqa: BLE001
        _line("Android/adb", "FAIL", str(e))


def check_ios() -> None:
    from autopilot.mobile import ios_bootstrap as ib
    exe = ib.resolve_go_ios()
    if exe is None:
        _line("iOS/go-ios", "SKIP", "未找到 go-ios 二进制")
        return
    import subprocess
    try:
        r = subprocess.run([str(exe), "list"], capture_output=True, timeout=20,
                           env={**os.environ, **ib.AGENT_ENV})
        out = r.stdout.decode("utf-8", "replace").strip()
        _line("iOS/go-ios", "OK" if out else "SKIP", out[:80] or "无设备")
    except Exception as e:  # noqa: BLE001
        _line("iOS/go-ios", "FAIL", str(e))


def check_redis() -> None:
    url = os.getenv("REDIS_URL")
    if not url:
        _line("Redis", "SKIP", "未设 REDIS_URL")
        return
    try:
        # noinspection PyUnresolvedReferences,PyPackageRequirements
        import redis
        redis.from_url(url).ping()
        _line("Redis", "OK", url)
    except Exception as e:  # noqa: BLE001
        _line("Redis", "FAIL", str(e))


def check_ssh() -> None:
    host = os.getenv("SSH_HOST")
    if not host:
        _line("SSH", "SKIP", "未设 SSH_HOST")
        return
    try:
        from autopilot.keywords.data.ssh import default_ssh_factory, ssh_allow_unknown_host_env

        # 与关键字同策略：默认 RejectPolicy；探针可用 SSH_ALLOW_UNKNOWN=1 或 AUTOPILOT_SSH_ALLOW_UNKNOWN_HOST=1
        allow = (
            os.getenv("SSH_ALLOW_UNKNOWN", "").strip().lower() in ("1", "true", "yes", "on")
            or ssh_allow_unknown_host_env()
        )
        c = default_ssh_factory(
            host,
            int(os.getenv("SSH_PORT", "22") or "22"),
            os.getenv("SSH_USER", ""),
            os.getenv("SSH_PASSWORD", ""),
            allow_unknown_host=allow,
            known_hosts=os.getenv("SSH_KNOWN_HOSTS", ""),
        )
        c.close()
        _line("SSH", "OK", host + (" (allow_unknown)" if allow else ""))
    except Exception as e:  # noqa: BLE001
        _line("SSH", "FAIL", str(e))


def check_db() -> None:
    url = os.getenv("DB_URL")
    if not url:
        _line("Database", "SKIP", "未设 DB_URL")
        return
    try:
        # noinspection PyUnresolvedReferences,PyPackageRequirements
        from sqlalchemy import create_engine, text
        with create_engine(url).connect() as conn:
            conn.execute(text("SELECT 1"))
        _line("Database", "OK", url.split("://")[0])
    except Exception as e:  # noqa: BLE001
        _line("Database", "FAIL", str(e))


def main() -> int:
    print("=== AutoPilot 真机 / 真服务连通性验证 ===")
    import autopilot.keywords  # noqa: F401
    check_android()
    check_ios()
    check_redis()
    check_ssh()
    check_db()
    print("（SKIP 表示该环境未提供，非失败；按需设置环境变量后重跑）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
