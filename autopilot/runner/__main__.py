"""启动 IDE Runner：python -m autopilot.runner"""

from __future__ import annotations

import argparse
import os

from .agent import run_forever
from .contract import DEFAULT_API_TOKEN
from .devices import format_probe_report
from ..runtime.platform_url import platform_base_url


def resolve_runner_token(*, token: str | None, token_env: str) -> str:
    """解析执行通道 Token：显式 ``--token`` 优先，否则读 ``--token-env`` 指定的环境变量。"""
    explicit = (token or "").strip()
    if explicit:
        return explicit
    name = (token_env or "MC_API_TOKEN").strip() or "MC_API_TOKEN"
    value = os.environ.get(name, "").strip()
    if value:
        return value
    if name == "MC_API_TOKEN":
        return DEFAULT_API_TOKEN
    raise SystemExit(f"环境变量 {name} 未设置或为空；请先写入后再启动 Runner")


def main() -> None:
    ap = argparse.ArgumentParser(description="AutoPilot IDE Runner（本机执行节点）")
    ap.add_argument(
        "--server",
        default=os.environ.get("MC_SERVER", platform_base_url()),
        help="Platform base URL",
    )
    ap.add_argument(
        "--token",
        default=None,
        help="X-API-Token（会进入命令历史；生产与共享环境请改用 --token-env）",
    )
    ap.add_argument(
        "--token-env",
        default="MC_API_TOKEN",
        help="存放 X-API-Token 的环境变量名（默认 MC_API_TOKEN）",
    )
    ap.add_argument("--runner-id", default=os.environ.get("MC_RUNNER_ID", ""))
    ap.add_argument("--poll-interval", type=float, default=3.0)
    ap.add_argument(
        "--dry-probe",
        action="store_true",
        help="只探测本机设备/后端能力并打印，不注册、不领任务",
    )
    args = ap.parse_args()

    if args.dry_probe:
        print(format_probe_report(), flush=True)
        raise SystemExit(0)

    run_forever(
        args.server,
        resolve_runner_token(token=args.token, token_env=args.token_env),
        runner_id=args.runner_id or None,
        poll_interval=args.poll_interval,
    )


if __name__ == "__main__":
    main()
