"""QSS 不得给 QSpinBox 上 border/padding，否则上下调节箭头会整块消失。

Qt 的规则：一旦样式表命中某个控件的盒模型（border/padding），该控件改由 QStyleSheetStyle
绘制，包含 ``::up-button`` / ``::down-button``。我们没有箭头图片资源，于是微调按钮画成空白
方块——表现就是「步数上限右侧只剩一条竖线，没有上下箭头」。只写 background/color 不触发接管。
"""

from __future__ import annotations

import re

import pytest

from autopilot.ui.theme import qss_dark, qss_light

_BLOCK = re.compile(r"([^{}]+)\{([^{}]*)}", re.MULTILINE)
#: 触发 QSS 接管子控件绘制的盒模型属性
_BOX_MODEL = ("border", "padding")


def _qss_blocks(module) -> list[tuple[str, str, str]]:
    """展开模块内所有 *_QSS 常量为 (常量名, 选择器, 声明体)。"""
    out: list[tuple[str, str, str]] = []
    for name in dir(module):
        if not name.endswith("_QSS"):
            continue
        text = getattr(module, name)
        if not isinstance(text, str):
            continue
        # 去掉 /* 注释 */，避免注释里的说明文字被当成声明
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
        for selector, body in _BLOCK.findall(text):
            out.append((name, selector.strip(), body))
    return out


@pytest.mark.parametrize("module", [qss_light, qss_dark], ids=["light", "dark"])
def test_spinbox_keeps_native_arrows(module):
    offenders: list[str] = []
    for const, selector, body in _qss_blocks(module):
        if "QSpinBox" not in selector or "::" in selector:
            continue
        for prop in _BOX_MODEL:
            if re.search(rf"(^|\s|;){prop}[-a-z]*\s*:", body):
                offenders.append(f"{const} → {selector} 声明了 {prop}")
    assert not offenders, (
        "QSpinBox 被赋予盒模型属性，上下箭头会消失；只保留 background-color/color："
        + "；".join(offenders)
    )


@pytest.mark.parametrize("module", [qss_light, qss_dark], ids=["light", "dark"])
def test_spinbox_still_themed(module):
    """箭头修复不能把配色一起丢掉（深色主题下白底 spinbox 很刺眼）。"""
    bodies = [
        body
        for _, selector, body in _qss_blocks(module)
        if selector.strip() == "QSpinBox"
    ]
    assert bodies, "缺少 QSpinBox 配色规则"
    assert any("background-color" in b and "color" in b for b in bodies)
