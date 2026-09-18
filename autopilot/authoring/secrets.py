"""编写 Prompt 中的敏感输入遮罩：真实值只在本地执行时还原。"""

from __future__ import annotations

import re
from typing import Any

SECRET_PLACEHOLDER_PREFIX = "__AP_SECRET_"
_SECRET_LABEL_ALT = r"密码|口令|passwd|password|secret|token|otp"
_NEAR_SECRET_LABEL = re.compile(_SECRET_LABEL_ALT, re.IGNORECASE)
_VALUE_AFTER_LABEL = re.compile(
    r"(?:密码|口令|passwd|password|secret|token|otp)\s*"
    r"(?:是|为|is|:|：|=)?\s*[「\"']?([^\s」\"'，。；;]+)",
    re.IGNORECASE,
)
_SECRET_VALUE_STOP = frozenset({
    "is", "the", "to", "for", "and", "a", "an", "of", "my", "your",
    "是", "为", "的", "登录", "输入", "填写", "提交",
})


def extract_nl_secret_values(natural_language: str) -> tuple[str, ...]:
    """从「密码 xxx / password: yyy」一类写法抽出敏感值。"""
    out: list[str] = []
    for match in _VALUE_AFTER_LABEL.finditer(natural_language or ""):
        val = (match.group(1) or "").strip("「」\"'")
        if not val or val.lower() in _SECRET_VALUE_STOP or val in out:
            continue
        # 整段才是标签词才丢；「SuperSecret99」里碰巧含 secret 仍要遮罩
        if _NEAR_SECRET_LABEL.fullmatch(val):
            continue
        out.append(val)
    return tuple(out)


def classify_secret_texts(natural_language: str, texts: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """需求里紧挨密码/口令等标签的输入值视为敏感。"""
    nl = natural_language or ""
    out: list[str] = []
    for raw in texts or ():
        text = str(raw or "").strip()
        if not text or text in out:
            continue
        escaped = re.escape(text)
        label = "(?:" + _SECRET_LABEL_ALT + ")"
        if re.search(
            label + r".{0,16}" + escaped + r"|" + escaped + r".{0,10}" + label,
            nl,
            re.IGNORECASE,
        ):
            out.append(text)
    return tuple(out)


def collect_secret_map(
    natural_language: str,
    extra_texts: tuple[str, ...] | list[str] = (),
) -> dict[str, str]:
    """合并 NL 内嵌口令与调用方给出的输入值，生成占位映射。"""
    merged: list[str] = []
    for item in list(extra_texts or ()) + list(extract_nl_secret_values(natural_language)):
        if item and item not in merged:
            merged.append(item)
    return build_secret_map(classify_secret_texts(natural_language, merged))


def secret_placeholder(index: int) -> str:
    return f"{SECRET_PLACEHOLDER_PREFIX}{index}__"


def build_secret_map(secrets: tuple[str, ...] | list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for i, value in enumerate(secrets, start=1):
        if value and value not in mapping:
            mapping[value] = secret_placeholder(i)
    return mapping


def mask_text(text: str, secret_map: dict[str, str]) -> str:
    out = text or ""
    # 先替换更长的值，避免短串误伤
    for raw, token in sorted(secret_map.items(), key=lambda kv: len(kv[0]), reverse=True):
        if raw:
            out = out.replace(raw, token)
    return out


def restore_secrets(text: str, secret_map: dict[str, str]) -> str:
    out = text or ""
    for raw, token in secret_map.items():
        out = out.replace(token, raw)
    return out


def mask_history_row(row: dict[str, Any], secret_map: dict[str, str]) -> dict[str, Any]:
    if not secret_map or not isinstance(row, dict):
        return row
    out = dict(row)
    params = out.get("params")
    if isinstance(params, dict):
        out["params"] = {
            str(k): mask_text(str(v), secret_map) if v is not None else v
            for k, v in params.items()
        }
    comment = out.get("comment")
    if isinstance(comment, str):
        out["comment"] = mask_text(comment, secret_map)
    return out


def restore_step_params(params: dict[str, str] | None, secret_map: dict[str, str]) -> dict[str, str]:
    if not params:
        return {}
    if not secret_map:
        return dict(params)
    return {
        str(k): restore_secrets("" if v is None else str(v), secret_map)
        for k, v in params.items()
    }
