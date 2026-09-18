"""链路 3 Authoring 契约：输入输出、入口策略、安全策略。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SUPPORTED_PLATFORMS = frozenset({"android", "ios", "web", "http"})

# session：observe-act 驱动会话并固化；plan_only：只规划不执行（无会话时的草稿）
AuthoringMode = Literal["session", "plan_only"]

DEFAULT_MAX_STEPS = 20
#: 步数硬顶只为防跑飞；业务上更长的流程应拆用例，而不是靠一条用例堆到底
HARD_MAX_STEPS = 60
DEFAULT_MAX_TURNS = 8
HARD_MAX_TURNS = 40
#: 每回合允许落库的步数上限；越大则同长度用例消耗的 AI 调用越少
MAX_STEPS_PER_TURN = 4

FORBIDDEN_KEYWORD_IDS = frozenset({
    "intent_act",
    # 数据面删除类（即便 XML 漏标 irreversible，链路 3 也不得 NL 生成）
    "http_delete",
    "json_delete_json_value",
    "deleteRedisKey",
    "deleteRedisKeyWithResult",
    "deleteRedisScoredSet",
    "deleteRedisKeyFromFile",
})

# AUD-2026-15：链路 3 禁止扩展到 Data/SSH（前缀黑名单，与 irreversible 闸门互补）
AUTHORING_BLOCKED_PREFIXES: tuple[str, ...] = (
    "linux_ssh_",
    "redis_",
    "jdbc_",
    "mongo_",
    "kafka_",
    "mysql_",
    "oracle_",
    "sqlserver_",
    "db_",
    "ssh_",
)


def is_authoring_blocked_keyword(keyword_id: str) -> bool:
    """链路 3 硬禁止：intent_act、Data/SSH 前缀、显式危险 id。"""
    kid = (keyword_id or "").strip()
    if not kid:
        return True
    if kid in FORBIDDEN_KEYWORD_IDS:
        return True
    low = kid.lower()
    if "sftp" in low:
        return True
    return any(kid.startswith(p) for p in AUTHORING_BLOCKED_PREFIXES)


PLATFORM_KEYWORD_PREFIXES: dict[str, tuple[str, ...]] = {
    # 不含 data/SSH 域前缀（AUD-2026-15）
    "android": ("mobile_", "public_", "common_"),
    "ios": ("mobile_", "ios_", "public_", "common_"),
    "web": ("web_", "browser_", "public_", "common_"),
    "http": ("http_", "json_", "xml_", "api_", "public_", "common_"),
}


@dataclass
class AuthoringRequest:
    natural_language: str
    platform: str
    title: str = ""
    max_steps: int = DEFAULT_MAX_STEPS
    max_turns: int = DEFAULT_MAX_TURNS
    include_screenshot: bool = False
    draft_only: bool = False
    # session = 驱动会话编写（正式主路径）；plan_only = 仅规划草稿
    mode: AuthoringMode = "session"
    # 启动目标：移动为 package/bundle；Web 为起始 URL
    package_name: str = ""
    activity_name: str = ""
    start_url: str = ""
    app_label: str = ""
    #: 使用设备当前前台应用：跳过包名解析与自动启动（适用于已开检视器/手动打开 App）
    use_current_app: bool = False
    #: NL / 结构化抽取得到的待输入文本（账号、关键词等）
    input_texts: tuple[str, ...] = ()
    #: 工程目录：空平台时读工程默认平台，避免硬回落到 iOS
    project_dir: str = ""


@dataclass
class GeneratedStep:
    keyword_id: str
    params: dict[str, str] = field(default_factory=dict)
    comment: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "keyword_id": self.keyword_id,
            "params": dict(self.params),
            "comment": self.comment,
        }


NavigationRole = Literal[
    "navigate",
    "scroll",
    "backtrack",
    "target",
    "assert",
    "support",
]


@dataclass
class NavigationPlan:
    """UI 深层导航的机读计划；不替代最终关键字步骤。"""

    goal: str
    platform: str = ""
    strategies: tuple[str, ...] = (
        "search_first",
        "category_fallback",
        "scroll_discover",
        "target_action",
        "assert",
    )
    active_strategy: str = "search_first"
    max_depth: int = 8
    max_scrolls: int = 12
    max_backtracks: int = 5
    max_perception_failures: int = 2
    visited_pages: int = 0
    tried_strategies: list[str] = field(default_factory=list)


@dataclass
class NavigationFrame:
    """到达某页时最终路径已有的步骤数，用于返回后裁掉错误分支。"""

    page_sig: str
    path_length: int
    depth: int


@dataclass
class NavigationIncident:
    """从执行反馈回灌下一回合的结构化故障。"""

    kind: str
    reason: str
    role: NavigationRole
    keyword_id: str = ""
    page_sig_before: str = ""
    page_sig_after: str = ""
    consecutive_failures: int = 1
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "reason": self.reason,
            "role": self.role,
            "keyword_id": self.keyword_id,
            "page_sig_before": self.page_sig_before,
            "page_sig_after": self.page_sig_after,
            "consecutive_failures": self.consecutive_failures,
            "evidence": dict(self.evidence),
        }


@dataclass
class PendingTransition:
    """已派发但尚待下一次采页确认后果的导航动作。"""

    step: GeneratedStep
    role: NavigationRole
    page_sig_before: str
    target_locator: str = ""


@dataclass
class AuthoringDraft:
    title: str
    platform: str
    steps: list[GeneratedStep]
    warnings: list[str] = field(default_factory=list)
    raw_llm: str = ""
    mode: str = "plan_only"
    #: 步骤是否已在会话中逐步执行成功（会话驱动模式的天然试跑证据）
    session_verified: bool = False
    #: 模型是否宣告用户目标已完成。逐步执行成功 ≠ 达成目标：回合耗尽或连续失败
    #: 收手时也会得到一堆「执行成功」的步骤，此时不能当成可直接上传的用例。
    goal_completed: bool = False
    #: 编写回合决策轨迹（可落盘为 _authoring_trace.json）；无则空
    decision_trace: dict[str, Any] | None = None

    def to_step_dicts(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self.steps]


class AuthoringError(ValueError):
    """Authoring 校验 / 契约错误。"""


def normalize_platform(raw: str) -> str:
    p = (raw or "").strip().lower()
    if p in ("android", "a"):
        return "android"
    if p in ("web", "w", "browser"):
        return "web"
    if p in ("ios", "i"):
        return "ios"
    if p in ("http", "api", "rest"):
        return "http"
    raise AuthoringError(f"不支持的平台: {raw!r}（android / ios / web / http）")


def clamp_max_steps(n: int) -> int:
    try:
        v = int(n)
    except (TypeError, ValueError):
        return DEFAULT_MAX_STEPS
    return max(1, min(v, HARD_MAX_STEPS))


def clamp_max_turns(n: int) -> int:
    try:
        v = int(n)
    except (TypeError, ValueError):
        return DEFAULT_MAX_TURNS
    return max(1, min(v, HARD_MAX_TURNS))


def turns_for_steps(max_steps: int, requested_turns: int) -> int:
    """回合预算至少要够把步数预算走完，否则护栏会在业务没写完时截断。

    按每回合 ``MAX_STEPS_PER_TURN`` 步折算，再留 2 回合给失败重规划。
    """
    steps = clamp_max_steps(max_steps)
    need = -(-steps // MAX_STEPS_PER_TURN) + 2
    return clamp_max_turns(max(clamp_max_turns(requested_turns), need))


#: 只给排查用的 note 前缀。加上它的条目不进界面，只进日志。
DEBUG_NOTE_PREFIX = "debug:"
#: NL 解析走哪条分支属于实现细节，同样不进界面
_INTERNAL_NOTE_PREFIXES = (DEBUG_NOTE_PREFIX, "nl:")


def debug_note(text: str) -> str:
    return f"{DEBUG_NOTE_PREFIX}{text}"


def user_facing_notes(notes: list[str] | tuple[str, ...]) -> list[str]:
    """筛出可以直接给用户看的进度说明。

    界面上只该出现「用了哪台设备、哪个应用」这类和使用有关的信息；模式名、
    降级分支、caps 预置失败之类属于排查线索，交给日志。
    """
    return [n for n in notes if not str(n).startswith(_INTERNAL_NOTE_PREFIXES)]
