"""从 actions.ACTIONS 构建 QAction 字典（单一事实源 → Qt 动作）。"""

from __future__ import annotations

from PyQt6.QtGui import QAction, QKeySequence

from ...actions import label, qicon


def build_qactions(parent, specs: tuple) -> dict[str, QAction]:
    """将 ActionSpec 列表转为 id → QAction，并绑定 parent 上的槽方法。"""
    from ...theme import effective_theme, icon_color
    from ....runtime import settings

    tone = icon_color("tool", effective_theme(settings.ui_theme()))
    actions: dict[str, QAction] = {}
    for spec in specs:
        act = QAction(label(spec), parent)
        act.setProperty("_ap_icon", spec.icon)
        ic = qicon(spec.icon, color=tone) if spec.icon else None
        if ic is not None:
            act.setIcon(ic)
        if spec.shortcut:
            act.setShortcut(QKeySequence(spec.shortcut))
        tip = (spec.tip or spec.text).strip()
        if tip:
            if spec.shortcut:
                act.setToolTip(f"{tip}（{spec.shortcut}）")
            else:
                act.setToolTip(tip)
        if spec.checkable:
            act.setCheckable(True)
            slot = getattr(parent, spec.slot)
            # noinspection PyUnresolvedReferences
            act.toggled.connect(lambda checked, s=slot: s(checked))
        else:
            slot = getattr(parent, spec.slot)
            # noinspection PyUnresolvedReferences
            act.triggered.connect(
                lambda _checked=False, s=slot, a=spec.args: s(*a))
        actions[spec.id] = act
    return actions


def refresh_action_icons(actions: dict[str, QAction], theme: str) -> None:
    """主题切换后刷新菜单/工具栏 QAction 图标色。"""
    from ...theme import icon_color

    tone = icon_color("tool", theme)
    for act in actions.values():
        icon_name = act.property("_ap_icon")
        if not icon_name:
            continue
        ic = qicon(str(icon_name), color=tone)
        if ic is not None:
            act.setIcon(ic)


def init_run_control_actions(actions: dict[str, QAction]) -> tuple[QAction, QAction]:
    """取出暂停/停止动作并设为初始禁用。"""
    act_stop = actions["run.stop"]
    act_stop.setEnabled(False)
    act_pause = actions["run.pause"]
    act_pause.setEnabled(False)
    return act_pause, act_stop
