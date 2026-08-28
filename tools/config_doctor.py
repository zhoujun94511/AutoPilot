#!/usr/bin/env python3
"""对比 IDE 本地 Platform URL 与 Platform 公开 Bootstrap（无需登录）。"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

from autopilot.runtime.platform_deploy import deploy_platform_url_source
from autopilot.runtime.platform_url import platform_base_url


def _fetch_bootstrap(base: str, timeout: float) -> dict:
    url = f"{base.rstrip('/')}/api/v1/public/bootstrap"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="校验 IDE Platform 地址与后端 Bootstrap 一致")
    p.add_argument(
        "--url",
        default="",
        help="Platform 基址（默认 platform_base_url()）",
    )
    p.add_argument("--timeout", type=float, default=5.0)
    p.add_argument("--json", action="store_true", help="输出 JSON")
    args = p.parse_args(argv)

    local = (args.url or platform_base_url()).strip().rstrip("/")
    bootstrap_url = f"{local}/api/v1/public/bootstrap"
    deploy_src = deploy_platform_url_source()
    issues: list[str] = []
    remote: dict | None = None

    try:
        remote = _fetch_bootstrap(local, args.timeout)
    except urllib.error.HTTPError as e:
        issues.append(f"Bootstrap HTTP {e.code}: {bootstrap_url}")
    except urllib.error.URLError as e:
        reason = str(getattr(e, "reason", e))
        if "10061" in reason or "Connection refused" in reason or "积极拒绝" in reason:
            issues.append(
                f"Platform 未启动或端口不可达: {bootstrap_url}\n"
                f"    请先启动 Platform，例如：\n"
                f"      cd <Autopilot-Platform 仓库根>\n"
                f"      python -m autopilot_platform.platform --port 8000\n"
                f"    非默认地址：设置 AUTOPILOT_PLATFORM_URL 或 platform.url"
            )
        else:
            issues.append(f"无法连接 Platform ({bootstrap_url}): {reason}")
    except Exception as e:
        issues.append(f"Bootstrap 请求失败 ({bootstrap_url}): {e}")

    remote_base = (remote or {}).get("platform_base_url", "").rstrip("/") if remote else ""
    if remote and remote_base and remote_base != local:
        issues.append(f"基址不一致: IDE={local} bootstrap={remote_base}")

    out = {
        "local_url": local,
        "deploy_source": deploy_src or None,
        "remote_bootstrap": remote,
        "ok": not issues,
        "issues": issues,
    }
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        if issues:
            print("配置 doctor 发现问题：")
            print(f"  目标: {bootstrap_url}")
            for i in issues:
                lines = i.split("\n")
                print(f"  - {lines[0]}")
                for extra in lines[1:]:
                    print(f"    {extra}")
        else:
            print(f"OK: {local} 与 Bootstrap 一致")
            if deploy_src:
                print(f"  部署来源: {deploy_src}")
            if remote:
                print(f"  api_prefix={remote.get('api_prefix')}")
    return 0 if not issues else 1


if __name__ == "__main__":
    sys.exit(main())
