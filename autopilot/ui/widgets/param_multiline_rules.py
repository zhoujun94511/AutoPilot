"""步骤参数：大文本报文体用多行编辑器（HTTP request / XML 等）。

按 param_id 白名单触发；排除输出参数（is_output / 名称含 [OUT]）。
不依赖 keyword_defs XML 扩展节点。
"""

from __future__ import annotations

# HTTP/XML 报文体主字段（入参）；不含 textBody（multipart 表单串）
_MULTILINE_PARAM_IDS: frozenset[str] = frozenset({
    "request",
    "httpBody",
    "xmlStr",
    "xml_act",
    "xml_exp",
})


def is_multiline_param(param_id: str, *, is_output: bool = False, label: str = "") -> bool:
    """是否用 QPlainTextEdit 编辑该入参。"""
    if is_output or "[OUT]" in (label or "").upper():
        return False
    return (param_id or "").strip() in _MULTILINE_PARAM_IDS
