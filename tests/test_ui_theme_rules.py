"""UI 主题静态规则（无 Qt）——委托 skills/autopilot-lint/check_ui_theme.py。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "skills", "autopilot-lint",
))

# noinspection PyUnresolvedReferences
from check_ui_theme import audit_ui_theme


def test_ui_theme_audit_passes() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    violations = audit_ui_theme(root)
    if violations:
        print("UI 主题规则:")
        for v in violations:
            print(" ", v.format())
    assert not violations, f"UI 主题静态审计发现 {len(violations)} 处违规"


def main() -> int:
    try:
        test_ui_theme_audit_passes()
    except AssertionError:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
