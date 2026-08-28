"""链路 3 Authoring Prompt（规划草稿 + 会话驱动回合）。

规则刻意通用化：不绑定具体 App / 行业场景。
借鉴 Midscene：observe → act → 再观察；优先结构化单步动作，避免盲试。
"""

from __future__ import annotations

import json
from typing import Any

from .contract import MAX_STEPS_PER_TURN

#: 单回合上下文预算：控制历史条数；页面摘要由 capture 侧按元素裁剪，保证合法 JSON
MAX_HISTORY_ITEMS = 6
MAX_ELEMENTS_CHARS = 12000


def _trim_elements(elements_text: str) -> str:
    """兜底：正常路径下 elements_text 已是合法且受限的 JSON。"""
    text = elements_text or "[]"
    if len(text) <= MAX_ELEMENTS_CHARS:
        return text
    # 字符级截断会破坏 JSON；宁可只告诉模型「摘要过长」
    return "[]"


def _catalog_keep_prefixes(platform: str) -> tuple[str, ...]:
    plat = (platform or "").strip().lower()
    if plat == "http":
        return "http_", "json_", "xml_"
    if plat == "web":
        return "web_", "browser_"
    if plat == "ios":
        return "mobile_", "ios_"
    if plat == "android":
        return ("mobile_",)
    return "mobile_", "ios_", "web_", "browser_", "http_", "json_"


def _compact_keyword_catalog(
    keyword_catalog: list[dict[str, Any]],
    *,
    platform: str = "",
) -> str:
    """只给模型执行所需字段，避免每回合重复发送约 20KB 展示元数据。"""
    prefixes = _catalog_keep_prefixes(platform)
    compact: list[dict[str, Any]] = []
    for item in keyword_catalog:
        kid = str(item.get("id") or "")
        # 不把 Excel/随机数/字符串等通用库整包重复发给模型。
        # parse_llm_draft 仍用完整白名单做最终校验，这里只是缩小规划候选集。
        if not (
            kid.startswith(prefixes)
            or kid in {"elementClick", "sleep", "wait_element", "wait_for_element"}
        ):
            continue
        params = []
        for param in item.get("params") or []:
            pid = str(param.get("id") or "").strip()
            if not pid:
                continue
            p: dict[str, Any] = {"id": pid}
            if param.get("required"):
                p["required"] = True
            default = param.get("default")
            if default not in ("", None):
                p["default"] = default
            params.append(p)
        compact.append({"id": kid, "params": params})
    return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))


def build_authoring_prompt(
    *,
    natural_language: str,
    platform: str,
    elements_text: str,
    keyword_catalog: list[dict[str, Any]],
    max_steps: int,
    package_name: str = "",
    start_url: str = "",
) -> str:
    catalog_json = _compact_keyword_catalog(keyword_catalog, platform=platform)
    elements_text = _trim_elements(elements_text)
    entry = ""
    if package_name:
        entry += f"\n目标应用包名/Bundle：{package_name}"
    if start_url:
        entry += f"\n起始 URL：{start_url}"
    role = (
        "接口自动化用例编写助手"
        if (platform or "").strip().lower() == "http"
        else "UI 自动化用例编写助手"
    )
    return f"""你是{role}。根据自然语言需求与当前页面控件摘要，
输出可在 AutoPilot 执行的**传统关键字步骤**（禁止 intent_act）。

平台：{platform}
最多 {max_steps} 步。{entry}

需求：
{natural_language.strip()}

可用关键字白名单（只能使用 id 字段）：
{catalog_json}

当前页控件摘要（compact，可能为空表示尚未启动）：
{elements_text or "[]"}

严格输出 JSON（不要 Markdown）：
{{
  "title": "短标题",
  "steps": [
    {{
      "keyword_id": "白名单中的 id",
      "params": {{"param_id": "值"}},
      "comment": "中文步骤说明"
    }}
  ],
  "notes": "可选备注"
}}

规则：
- 只使用白名单关键字；定位符必须直接使用页面摘要里的 ``l`` 字段（已是可执行格式，如 name::xxx / id::xxx / xpath::xxx），不要改成 i: / a: 等缩写
- 需要启动 App 时用 mobile_app_start（type=android|ios，packageName=包名；iOS activityName 可空串）
- Web 首次打开页面用 web_browser_open（params: url, type）；已在浏览器内跳转用 web_browser_locate
- HTTP / API：先 http_session_begin（可带 base_url），再用 http_get / http_post 等；断言用 http_assert_status / http_assert_body_contains；环境用 api_env_use
- Android/iOS：输入用 mobile_element_text_input（params: locator, text）；点击用 mobile_element_click
- 路径按 Act（操作）→ Wait（等待）→ Assert（断言）组织；含「确认/检查/验证」语义时至少一步 verify_*
- 不要编造不存在的关键字；路径要从入口写到目标动作
"""


def build_agent_turn_prompt(
    *,
    natural_language: str,
    platform: str,
    elements_text: str,
    keyword_catalog: list[dict[str, Any]],
    history: list[dict[str, Any]],
    package_name: str = "",
    start_url: str = "",
    remaining_steps: int = 8,
    input_text: str = "",
    screen: str = "",
    repeat_warning: str = "",
) -> str:
    catalog_json = _compact_keyword_catalog(keyword_catalog, platform=platform)
    hist_json = json.dumps(
        history[-MAX_HISTORY_ITEMS:], ensure_ascii=False, separators=(",", ":")
    )
    elements_text = _trim_elements(elements_text)
    entry = ""
    if package_name:
        entry += f"\n目标应用包名/Bundle：{package_name}"
    if start_url:
        entry += f"\n起始 URL：{start_url}"
    if input_text:
        entry += f"\n需求中要输入的文本：{input_text}"
    if screen:
        entry += f"\n屏幕尺寸（宽x高）：{screen}"
    repeat_block = ""
    if (repeat_warning or "").strip():
        repeat_block = f"\n\n【重复操作提示】\n{repeat_warning.strip()}\n"
    return f"""你是会话驱动的 UI 自动化编写 Agent。目标是完成用户需求，并输出**下一步可执行的传统关键字**。
禁止 intent_act。借鉴 Midscene：本回合只规划当前页可确定的动作；可能改变页面的动作
（点击、启动、打开 URL、返回、滑动）每回合最多一步，执行后会重新采页再规划。
同页可连续给出输入/等待/断言。剩余可记录步数预算：{remaining_steps}（本回合最多 {MAX_STEPS_PER_TURN} 步）。

平台：{platform}{entry}

用户目标：
{natural_language.strip()}

已执行的步骤（``failed: true`` 表示该步执行失败，请换定位或换路径，勿原样重试）：
{hist_json}

当前页控件摘要（compact）。字段含义：
``t`` 控件类型｜``tx`` 文案/占位｜``l`` 可直接使用的定位符｜``p`` 位置 ``x,y,宽,高``（左上角原点）
``ck:1`` 确定可点｜``ed:1`` 可输入文本
未标 ``ck`` 的 StaticText / Image / TextView 在移动端也可能可点；结合 ``tx`` / ``p`` / 类型判断
{elements_text or "[]"}

可用关键字白名单：
{catalog_json}

严格输出 JSON：
{{
  "title": "短标题",
  "done": false,
  "steps": [
    {{
      "keyword_id": "白名单 id",
      "params": {{"param_id": "值", "target": "可选：控件中文描述，便于定位解析"}},
      "comment": "说明"
    }}
  ],
  "notes": "可选"
}}

步骤类型（同页可组合；改页动作每回合最多一步）：
- **Act** 操作：启动/打开、点击、输入、滑动、返回（改页后停本回合）
- **Wait** 等待：mobile_wait_element_* / wait_element / wait_for_element / sleep
- **Assert** 断言：mobile_verify_* / web_verify_*（确认文案、开关、可见性等）
若用户目标含「确认/检查/验证/断言」语义，目标动作完成后至少给一步 Assert。
纯浏览类需求可无 Assert，但 notes 须说明无需断言的原因。

规则：
- 若尚未启动目标 App，且提供了包名，优先 mobile_app_start；Web 首次打开用 web_browser_open
- HTTP：尚未建会话时先 http_session_begin；请求用 http_get / http_post；需要环境变量时用 api_env_use
- 同一包名/URL 的入口已在历史成功执行过时，不要重复提交（会把页面打回入口）
- 截图类步骤（mobile_app_snapshot / web_browser_snapshot）仅当用户目标明确要求截图/留证时才输出；
  不要用截图代替观察——每回合都会自动给你最新页摘要
- 定位必须直接取自当前页摘要的 ``l`` 字段；也可在 params 里给 ``target``（控件中文名），
  由编写器解析成 ``l``；没有合适控件则 done=false，并在 notes 说明观察结论
- **控件名不可轻信**：accessibility name / id 可能与视觉功能不一致。需求提到方位（顶部/底部/右上角等）时，
  用 ``p`` 与屏幕尺寸判断；同名多个控件时优先匹配方位与文案语义
- 要输入文本：优先 ``ed:1`` 控件。若当前页没有 ``ed:1``，先点开与目标语义一致的入口
  （同义/近义文案、占位提示、邻近图标、需求方位对应的控件），下一回合再输入；
  不要盲点其它无关导航或试探性入口
- 路径试探失败后：回到上一层或换与目标语义更接近的控件，写清 notes；不要把盲试写进用例
- 用户目标动作都已完成时：done=true，并给出能概括整条用例的 title（中途回合的 title 会被忽略）
- iOS/Android 输入：mobile_element_text_input 的 text 参数放输入内容；点击用 mobile_element_click
- 历史里已失败的步骤不要重复提交同样的 keyword_id + 定位组合
- 若出现【重复操作提示】：同一控件在页面未变化时不要再点；换路径或 done=true 并说明卡住原因
{repeat_block}"""
