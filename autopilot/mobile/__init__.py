"""移动端设备层：adb / 装包解析 / iOS 引导 / 设备信息采集。

与 ``autopilot.keywords.mobile``（用例关键字）分离；UI 与关键字均可 ``from autopilot.mobile import …``。
"""

from .errors import PackageError
from .ios_marketing import MARKETING_NAMES, marketing_name

__all__ = [
    "PackageError",
    "MARKETING_NAMES",
    "marketing_name",
]
