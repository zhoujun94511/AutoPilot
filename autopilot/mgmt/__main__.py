"""python -m autopilot.mgmt <subcommand>

当前子命令：
  openapi-import  OpenAPI/Postman → HTTP .tc.yaml
  create-job      触发 Platform 批跑 Job（CI / 运维）
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "用法:\n"
            "  python -m autopilot.mgmt openapi-import --spec openapi.yaml --project <dir>\n"
            "  python -m autopilot.mgmt create-job --artifact-id <id> --platform ios ...\n"
            "  python -m autopilot.mgmt.openapi_import --spec … --project …\n"
        )
        return 0 if argv else 2
    cmd = argv[0]
    rest = argv[1:]
    if cmd in ("openapi-import", "openapi_import", "import-openapi"):
        from .openapi_import import main as openapi_main

        return int(openapi_main(rest) or 0)
    if cmd in ("create-job", "create_job", "trigger-job", "job"):
        from .job_trigger import main as job_main

        return int(job_main(rest) or 0)
    print(f"未知子命令: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
