#!/usr/bin/env python3
"""CI / 运维入口：触发 Platform 批跑。

用法见 docs/CI_TRIGGER.md：

  python tools/trigger_platform_job.py --artifact-id <id> --platform ios ...
  python -m autopilot.mgmt create-job --artifact-id <id> ...
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from autopilot.mgmt.job_trigger import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
