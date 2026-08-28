"""从自然语言抽取**启动前置线索**（正则兜底）。

主路径请用 ``nl_bootstrap.resolve_nl_hints``：
显式槽位 → LLM 结构化抽取 → 本模块正则。

职责边界（刻意收窄）：
- 只服务会话 bootstrap 与 Prompt 提示，不解析完整操作路径。
- 「进入某页 / 点某按钮 / 打开开关」留给会话 Agent 结合页摘要规划。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class NlHints:
    platform: str = ""  # android|ios|web|http|""
    app_name: str = ""
    #: NL 里直接写出的包名 / Bundle ID（``com.xxx.yyy``）
    package_name: str = ""
    #: Web 起始地址
    start_url: str = ""
    #: 需求里要填入的文本，按出现顺序；登录等多字段场景可有多项
    input_texts: tuple[str, ...] = ()

    @property
    def input_text(self) -> str:
        """兼容旧调用：取第一个输入值。"""
        return self.input_texts[0] if self.input_texts else ""


_PLATFORM_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"ios|苹果|iphone|ipad", "ios"),
    (r"android|安卓", "android"),
    (r"\bhttp\b|\bapi\b|接口测试|接口用例", "http"),
    (r"\bweb\b|浏览器|网页|chrome|safari|网址|网站", "web"),
)

#: 应用名线索。从具体到宽泛；命中后还要过停用词。
_APP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"打开了?\s*(?:iOS|Android|安卓|苹果)?\s*(?:手机|设备)?(?:上的|上)?\s*"
        r"([A-Za-z0-9_\-.一-鿿]+)\s*应用",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:打开|启动|进入)\s*([A-Za-z0-9_\-.一-鿿]+)\s*(?:应用|App|APP)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:打开|启动|进入)\s*([A-Za-z0-9_\-.一-鿿]{1,24})"
        r"(?=\s*(?:，|,|。|；|;|在|并|然后|接着|里|中|里的|中的|$))",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:用|使用)\s*([A-Za-z0-9_\-.一-鿿]+)\s*(?:应用|App|APP)?\s*[来去做]?",
        re.IGNORECASE,
    ),
    re.compile(r"\bopen\s+(?:the\s+)?([A-Za-z0-9_\-.]+)\s+app\b", re.IGNORECASE),
)

_PACKAGE_RE = re.compile(r"\b([a-zA-Z]\w*\.[a-zA-Z][\w.]*)\b")

_URL_RE = re.compile(
    r"(https?://[^\s，,。；;\"'「」]+)"
    r"|(?:打开|访问|浏览|前往)\s*(?:网页|网站|网址)?\s*"
    r"[「\"']?((?:www\.)?[A-Za-z0-9][\w.-]+\.[A-Za-z]{2,}(?:/[^\s，,。；;\"'「」]*)?)"
    r"[」\"']?",
    re.IGNORECASE,
)

# 「输入栏 / 搜索框 / 账号框」是控件名而非动作，先剔除再匹配输入值
_INPUT_FIELD_NOISE = re.compile(
    r"(?:输入|搜索|账号|密码|用户名|邮箱)[栏框]|文本框|输入框"
)

# 动作后紧跟的值；支持引号与多段；在连接词处截断
_INPUT_TEXT_RE = re.compile(
    r"(?:输入|填写|键入|填入)\s*[中里]?\s*"
    r"[「\"']?([A-Za-z0-9_\-@.+一-鿿]+?)[」\"']?"
    r"(?=\s*(?:并|然后|接着|后|，|,|。|；|;|和|与|点击|提交|搜索|登录|$))"
)

#: 不是应用名的词。注意：不要把「设置」放进来——系统设置是真实 App。
_STOP_APP_WORDS = frozenset({
    "手机", "设备", "系统", "应用", "app", "ios", "android", "web",
    "网页", "网站", "浏览器", "页面", "首页", "界面",
    "这个", "那个", "一个", "当前", "目标",
})


def parse_nl_hints(natural_language: str) -> NlHints:
    text = (natural_language or "").strip()
    if not text:
        return NlHints()

    platform = _parse_platform(text)
    package_name = _parse_package(text)
    start_url = _parse_url(text)
    app_name = _parse_app_name(text, package_name=package_name)
    input_texts = _parse_input_texts(text)

    # 写出了 URL 但没说平台时：API 形态走 http，否则 web
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


def _parse_platform(text: str) -> str:
    for pat, plat in _PLATFORM_PATTERNS:
        if re.search(pat, text, flags=re.IGNORECASE):
            return plat
    return ""


def _parse_package(text: str) -> str:
    m = _PACKAGE_RE.search(text)
    return (m.group(1) or "").strip() if m else ""


def _parse_url(text: str) -> str:
    m = _URL_RE.search(text)
    if not m:
        return ""
    raw = (m.group(1) or m.group(2) or "").strip().rstrip(")。）]")
    if not raw:
        return ""
    if not re.match(r"^https?://", raw, flags=re.IGNORECASE):
        raw = "https://" + raw
    return raw


def _parse_app_name(text: str, *, package_name: str = "") -> str:
    for cre in _APP_PATTERNS:
        m = cre.search(text)
        if not m:
            continue
        cand = (m.group(1) or "").strip(" 　「」\"'.")
        if not cand:
            continue
        low = cand.lower()
        if low in _STOP_APP_WORDS:
            continue
        # 包名形态留给 package_name，不当作显示名
        if _PACKAGE_RE.fullmatch(cand):
            continue
        # 「https」之类不是应用名
        if low in {"http", "https", "www"}:
            continue
        # 「登录页 / 首页」是页面描述，不是 App
        if cand.endswith(("页", "页面", "界面")):
            continue
        return cand
    if package_name:
        # 仅有包名时，用末段作弱显示名（bootstrap 仍以 package 为准）
        return package_name.rsplit(".", 1)[-1]
    return ""


def _parse_input_texts(text: str) -> tuple[str, ...]:
    cleaned = _INPUT_FIELD_NOISE.sub("", text)
    found: list[str] = []
    for m in _INPUT_TEXT_RE.finditer(cleaned):
        val = (m.group(1) or "").strip(" 　「」\"'")
        if val and val not in found:
            found.append(val)
    return tuple(found)
