"""启动前置线索解析：对话框槽位优先 → LLM 结构化抽取 → 正则兜底。

借鉴 Midscene / 常见 Agent 脚手架：
- 不把整条操作路径做成关键字 DSL；
- 只填 bootstrap 槽位（平台 / 应用 / 包名 / URL / 输入值）；
- 路径规划仍由会话 Agent + 页摘要完成。
"""

from __future__ import annotations

import os
from typing import Any

from .contract import AuthoringError
from .llm_client import ChatFn, complete_json, llm_mode
from .nl_parse import NlHints, parse_nl_hints

#: 结构化抽取专用：NL 过长则截断，避免 bootstrap 单独打爆 token
MAX_NL_EXTRACT_CHARS = 4000
#: 环境开关：0/false/off 时强制只用正则（离线/单测）
_ENV_NL_LLM = "AUTOPILOT_AUTHORING_NL_LLM"


def hints_sufficient(hints: NlHints) -> bool:
    """关键启动槽位是否已够用，够用则跳过 LLM 抽取以省调用。"""
    plat = (hints.platform or "").strip().lower()
    if plat == "http":
        return True
    if plat == "web":
        return bool(hints.start_url)
    if plat in ("ios", "android"):
        return bool(hints.package_name or hints.app_name)
    # 平台未知时，有包名或 URL 也算有线索
    return bool(hints.package_name or hints.start_url or hints.app_name)


def merge_nl_hints(*layers: NlHints) -> NlHints:
    """后面的非空字段覆盖前面（显式表单应放最后一层）。"""
    platform = ""
    app_name = ""
    package_name = ""
    start_url = ""
    input_texts: tuple[str, ...] = ()
    for layer in layers:
        if layer.platform:
            platform = layer.platform
        if layer.app_name:
            app_name = layer.app_name
        if layer.package_name:
            package_name = layer.package_name
        if layer.start_url:
            start_url = layer.start_url
        if layer.input_texts:
            input_texts = layer.input_texts
    if start_url and not platform:
        from .platform_resolve import infer_platform_from_url

        platform = infer_platform_from_url(start_url)
    return NlHints(
        platform=platform,
        app_name=app_name,
        package_name=package_name,
        start_url=start_url,
        input_texts=input_texts,
    )


def explicit_hints(
    *,
    platform: str = "",
    app_name: str = "",
    package_name: str = "",
    start_url: str = "",
    input_texts: tuple[str, ...] | list[str] = (),
) -> NlHints:
    """对话框 / AuthoringRequest 已填写的显式槽位。"""
    texts = tuple(str(x).strip() for x in input_texts if str(x).strip())
    plat = (platform or "").strip().lower()
    if plat in ("auto",):
        plat = ""
    return NlHints(
        platform=plat if plat in ("ios", "android", "web", "http") else "",
        app_name=(app_name or "").strip(),
        package_name=(package_name or "").strip(),
        start_url=(start_url or "").strip(),
        input_texts=texts,
    )


def resolve_nl_hints(
    natural_language: str,
    *,
    platform: str = "",
    app_name: str = "",
    package_name: str = "",
    start_url: str = "",
    chat: ChatFn | None = None,
    allow_llm: bool = True,
) -> tuple[NlHints, list[str]]:
    """统一入口。返回 ``(合并后的线索, 说明 notes)``。

    优先级：显式槽位 > LLM 结构化抽取 > 正则兜底。
    """
    notes: list[str] = []
    text = (natural_language or "").strip()
    explicit = explicit_hints(
        platform=platform,
        app_name=app_name,
        package_name=package_name,
        start_url=start_url,
    )
    regex = parse_nl_hints(text) if text else NlHints()

    # 显式 + 正则先合并；够用则不调 LLM
    base = merge_nl_hints(regex, explicit)
    if hints_sufficient(base) or not text:
        if hints_sufficient(explicit):
            notes.append("nl:explicit")
        elif hints_sufficient(regex):
            notes.append("nl:regex")
        else:
            notes.append("nl:partial")
        return base, notes

    if not allow_llm or not _nl_llm_enabled():
        notes.append("nl:regex")
        return base, notes

    try:
        llm_hints = extract_nl_hints_via_llm(text, chat=chat)
        merged = merge_nl_hints(regex, llm_hints, explicit)
        notes.append("nl:llm")
        return merged, notes
    except AuthoringError as exc:
        notes.append(f"nl:llm_fallback:{exc}")
        return base, notes
    except Exception as exc:  # noqa: BLE001
        notes.append(f"nl:llm_fallback:{exc}")
        return base, notes


def extract_nl_hints_via_llm(
    natural_language: str,
    *,
    chat: ChatFn | None = None,
) -> NlHints:
    """一次廉价结构化抽取；失败抛 AuthoringError，由调用方降级。"""
    text = (natural_language or "").strip()
    if not text:
        return NlHints()
    if len(text) > MAX_NL_EXTRACT_CHARS:
        text = text[:MAX_NL_EXTRACT_CHARS] + "…"

    prompt = f"""从用户的 UI 自动化需求中，只抽取**启动前置槽位**。
不要规划点击/滑动/进入某页等操作步骤（那是后续 Agent 的事）。

用户需求：
{text}

严格输出 JSON（不要 Markdown）：
{{
  "platform": "ios 或 android 或 web 或 http 或空字符串",
  "app_name": "应用显示名，没有则空",
  "package_name": "包名或 Bundle ID，没有则空",
  "start_url": "Web 起始 URL 或 API base URL，没有则空",
  "input_texts": ["需求中要填入的文本，按出现顺序"]
}}

规则：
- platform 只能是 ios / android / web / http / ""
- 提到接口测试 / API / REST / OpenAPI 时 platform=http
- 有页面 URL（登录页、官网）且未提接口时 platform=web
- URL 含 /api、/openapi、/swagger、/graphql 或主机以 api. 开头时 platform=http
- 不要仅因为出现 http(s) 就判成 web
- 「设置」可以是 iOS/Android 系统应用名
- input_texts 只收要键入的值，不要收控件名（如「输入栏」「搜索框」）
- 不确定的字段留空字符串或空数组，禁止编造包名
"""
    data = complete_json(prompt, chat=chat, purpose="planning")
    return _hints_from_llm_dict(data)


def _hints_from_llm_dict(data: dict[str, Any]) -> NlHints:
    if not isinstance(data, dict):
        raise AuthoringError("NL 抽取返回非对象")
    plat = str(data.get("platform") or "").strip().lower()
    if plat not in ("", "ios", "android", "web", "http"):
        plat = ""
    app_name = str(data.get("app_name") or "").strip()
    package_name = str(data.get("package_name") or "").strip()
    start_url = str(data.get("start_url") or "").strip()
    raw_inputs = data.get("input_texts")
    texts: list[str] = []
    if isinstance(raw_inputs, list):
        for item in raw_inputs:
            val = str(item or "").strip()
            if val and val not in texts:
                texts.append(val)
    # 兼容模型偶发返回单字符串
    single = str(data.get("input_text") or "").strip()
    if single and single not in texts:
        texts.insert(0, single)
    if start_url and not plat:
        from .platform_resolve import infer_platform_from_url

        plat = infer_platform_from_url(start_url)
    return NlHints(
        platform=plat,
        app_name=app_name,
        package_name=package_name,
        start_url=start_url,
        input_texts=tuple(texts),
    )


def _nl_llm_enabled() -> bool:
    raw = (os.environ.get(_ENV_NL_LLM) or "1").strip().lower()
    if raw in ("0", "false", "off", "no", "regex"):
        return False
    # 未登录且无本机 Key 时不要在 resolve 里硬撞 LLM；complete_json 会失败再降级，
    # 这里提前短路省一次往返。
    try:
        mode = llm_mode()
        if mode == "platform":
            from ..runtime import settings

            return bool(settings.mc_is_logged_in())
        from ..intent.config import vision_api_key

        return bool(vision_api_key())
    except (ImportError, OSError, AttributeError, TypeError, RuntimeError, ValueError):
        return False
