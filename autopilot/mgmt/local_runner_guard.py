"""IDE 本机 Runner 与检视/镜像：同一 UDID 确认，不做硬互斥。

三条链路互不感知：检视/镜像占 WDA，本机 Runner 默认把 USB 全进 TR 池。
空闲心跳一般能共存；同一 UDID 上 Job 会话会抢检视。只挡这一台，
多机时一边检视一边给别的手机上报是正常用法。
"""

from __future__ import annotations

from dataclasses import dataclass

KIND_INSPECT = "检视"
KIND_MIRROR = "镜像"

ACTION_EXCLUDE = "exclude"
ACTION_REPORT_ALL = "report_all"
ACTION_CANCEL = "cancel"

SCENARIO_START_MULTI = "start_multi"
SCENARIO_START_SINGLE = "start_single"
SCENARIO_OPEN_INSPECT = "open_inspect"

TITLE_START = "本机 Runner 与检视/镜像"


def bound_mobile_udid(*, platform: str = "", udid: str = "") -> str:
    """仅 Android/iOS 真机有冲突面；Web 检视不占 USB。"""
    plat = (platform or "").strip().lower()
    if plat not in ("android", "ios"):
        return ""
    return (udid or "").strip()


def inspect_kind(
    *,
    inspect_ctx=None,
    mirror_active: bool = False,
    inspect_chosen: bool = False,
    udid: str = "",
) -> str:
    """当前占用面：镜像优先（共用 _inspect_ctx），否则检视。"""
    if mirror_active:
        return KIND_MIRROR
    if inspect_ctx is not None or (inspect_chosen and (udid or "").strip()):
        return KIND_INSPECT
    return ""


def collect_local_udids(*groups) -> list[str]:
    """合并本机探测列表，保序去重。元素可以是 UDID 字符串或带 udid 属性的对象。"""
    out: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group or []:
            uid = str(getattr(item, "udid", item) or "").strip()
            if uid and uid not in seen:
                seen.add(uid)
                out.append(uid)
    return out


@dataclass(frozen=True)
class ConfirmPrompt:
    scenario: str
    title: str
    text: str
    yes_text: str
    no_text: str
    cancel_text: str
    default_action: str


def start_runner_prompt(
    *,
    inspect_udid: str,
    inspect_kind_label: str,
    local_udids: list[str],
) -> ConfirmPrompt | None:
    """启动本机 Runner 时：已绑检视/镜像真机则确认。无绑定不弹。"""
    uid = (inspect_udid or "").strip()
    if not uid:
        return None
    kind = (inspect_kind_label or "").strip() or KIND_INSPECT
    others = [u for u in local_udids if (u or "").strip() and (u or "").strip() != uid]
    if others:
        return ConfirmPrompt(
            scenario=SCENARIO_START_MULTI,
            title=TITLE_START,
            text=(
                f"当前正在{kind}设备 {uid}。\n\n"
                "启动本机 Runner 后该机将进入组织设备池，"
                "远程批跑会抢走检视/镜像会话。\n"
                "本机还有其他设备，建议先把这台从上报中摘除。"
            ),
            yes_text="启动并摘除该机",
            no_text="仍上报全部",
            cancel_text="取消",
            default_action=ACTION_EXCLUDE,
        )
    return ConfirmPrompt(
        scenario=SCENARIO_START_SINGLE,
        title=TITLE_START,
        text=(
            f"当前正在{kind}设备 {uid}。\n\n"
            "本机只有这一台。启动 Runner 后它会进入组织设备池，"
            "远程批跑会抢走检视/镜像。确定仍要启动？"
        ),
        yes_text="仍然启动",
        no_text="",
        cancel_text="取消",
        default_action=ACTION_CANCEL,
    )


def open_inspect_prompt(
    *,
    runner_running: bool,
    reports_udid: bool,
    udid: str,
    kind: str,
) -> ConfirmPrompt | None:
    """开检视/镜像时：本机 Runner 已在上报该 UDID 则确认。"""
    uid = (udid or "").strip()
    if not runner_running or not reports_udid or not uid:
        return None
    label = (kind or "").strip() or KIND_INSPECT
    return ConfirmPrompt(
        scenario=SCENARIO_OPEN_INSPECT,
        title=f"{label}与本机 Runner",
        text=(
            f"本机 Runner 已在上报设备 {uid}。\n\n"
            f"对该机开启{label}时，远程批跑可能抢走 WDA/会话。\n"
            "建议先把它从 Runner 上报中摘除。"
        ),
        yes_text="继续并摘除上报",
        no_text="继续且保持上报",
        cancel_text="取消",
        default_action=ACTION_EXCLUDE,
    )


def resolve_prompt_action(scenario: str, clicked: str) -> str:
    """把确认框按钮映射成 exclude / report_all / cancel。"""
    if clicked not in ("yes", "no", "cancel"):
        return ACTION_CANCEL
    if clicked == "cancel":
        return ACTION_CANCEL
    if scenario == SCENARIO_START_SINGLE:
        return ACTION_REPORT_ALL if clicked == "yes" else ACTION_CANCEL
    if clicked == "yes":
        return ACTION_EXCLUDE
    return ACTION_REPORT_ALL
