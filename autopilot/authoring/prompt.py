"""链路 3 Authoring Prompt（规划草稿 + 会话驱动回合）。

规则刻意通用化：不绑定具体 App / 行业场景。
借鉴 Midscene：observe → act → 再观察；优先结构化单步动作，避免盲试。
"""

from __future__ import annotations

import json
from typing import Any

from .contract import MAX_STEPS_PER_TURN, PLATFORM_KEYWORD_PREFIXES
from .system_app_aliases import prompt_definitions

#: 无平台前缀但仍应留给编写模型的公共步
_ALWAYS_KEEP_KEYWORD_IDS = frozenset({
    "elementClick",
    "sleep",
    "wait_element",
    "wait_for_element",
})

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
    return PLATFORM_KEYWORD_PREFIXES.get(plat, ())


def _compact_keyword_catalog(
    keyword_catalog: list[dict[str, Any]],
    *,
    platform: str = "",
) -> str:
    """只给模型执行所需字段，避免每回合重复发送约 20KB 展示元数据。"""
    prefixes = _catalog_keep_prefixes(platform)
    keep_ids = (
        frozenset()
        if (platform or "").strip().lower() == "http"
        else _ALWAYS_KEEP_KEYWORD_IDS
    )
    compact: list[dict[str, Any]] = []
    for item in keyword_catalog:
        kid = str(item.get("id") or "")
        # 不把 Excel/随机数/字符串等通用库整包重复发给模型。
        # parse_llm_draft 仍用完整白名单做最终校验，这里只是缩小规划候选集。
        if not (kid.startswith(prefixes) or kid in keep_ids):
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
    app_label: str = "",
) -> str:
    catalog_json = _compact_keyword_catalog(keyword_catalog, platform=platform)
    elements_text = _trim_elements(elements_text)
    entry = ""
    if package_name:
        entry += f"\n目标应用包名/Bundle：{package_name}"
    if start_url:
        entry += f"\n起始 URL：{start_url}"
    defs = prompt_definitions(platform, hint=app_label, package_name=package_name)
    if defs:
        entry += f"\n\n【已知定义】（只帮助理解说法，禁止编造页摘要里没有的控件）\n{defs}"
    role = (
        "接口自动化用例编写助手"
        if (platform or "").strip().lower() == "http"
        else "UI 自动化用例编写助手"
    )
    if (platform or "").strip().lower() == "http":
        return f"""你是{role}。根据自然语言需求与最近一次 HTTP 观察，
输出可在 AutoPilot 执行的**传统关键字步骤**（禁止 intent_act）。

平台：{platform}
最多 {max_steps} 步。{entry}

需求：
{natural_language.strip()}

可用关键字白名单（只能使用 id 字段）：
{catalog_json}

当前接口观察（session + last_request；尚未发请求时 last_request 为 null）：
{elements_text or "{{}}"}

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
- 只使用白名单关键字；禁止 mobile_* / web_* / locator
- 尚未建会话时先 http_session_begin（可带 base_url）；已有会话不要重复 begin
- 请求用 http_get / http_post / http_put / http_patch；禁止 http_delete
- 每条请求后必须有断言：http_assert_status / http_assert_body_contains / json_assert_schema
- 需要环境变量时用 api_env_use；认证用 http_set_auth_bearer / basic / apikey
- 不要编造不存在的关键字
"""
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
    navigation_context: str = "",
    app_label: str = "",
    task_note: str = "",
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
    defs = prompt_definitions(platform, hint=app_label, package_name=package_name)
    if defs:
        entry += f"\n\n【已知定义】（只帮助理解说法，禁止编造页摘要里没有的控件）\n{defs}"
    if (task_note or "").strip():
        entry += f"\n{task_note.strip()}"
    repeat_block = ""
    if (repeat_warning or "").strip():
        repeat_block = f"\n\n【重复操作提示】\n{repeat_warning.strip()}\n"
    navigation_block = ""
    if (navigation_context or "").strip():
        if platform == "web":
            navigation_guidance = (
                "寻找当前页不存在的目标时：优先使用站内搜索或当前页真实链接/按钮；"
                "长页面可用 web_browser_scroll_vertical_bar 探索；进入错误分支时使用 "
                "web_browser_back 返回。不得使用 mobile_* 关键字，且每次只根据当前 DOM 行动。"
            )
        else:
            navigation_guidance = (
                "寻找当前页不存在的目标时：优先使用应用内搜索；没有搜索入口再按语义进入分类；"
                "列表首屏没有目标时使用 mobile_swipe_direction 探索；进入错误分支时使用 "
                "mobile_presskey(oKeys=back) 返回。每次只根据当前页真实控件行动。"
            )
        navigation_block = (
            "\n\n【深层导航状态（机读）】\n"
            f"{navigation_context.strip()}\n"
            f"{navigation_guidance}\n"
        )
    if (platform or "").strip().lower() == "http":
        return f"""你是会话驱动的接口自动化编写 Agent。目标是完成用户的 HTTP / API 需求，
并输出**下一步可执行的传统关键字**。禁止 intent_act、mobile_*、web_* 和 locator。
观察对象是会话状态与最近一次响应，不是页面控件。
同回合可连续给出请求 + 断言。剩余可记录步数预算：{remaining_steps}（本回合最多 {MAX_STEPS_PER_TURN} 步）。

平台：{platform}{entry}

用户目标：
{natural_language.strip()}

已执行的步骤（``failed: true`` 表示该步执行失败，请换路径，勿原样重试）：
{hist_json}

当前接口观察（JSON）。字段：
``session.begun`` 是否已 http_session_begin｜``session.base_url`` 根地址
``last_request`` 最近一次响应（url / status / body / headers）；尚未发请求时为 null
{elements_text or "{{}}"}

可用关键字白名单：
{catalog_json}

严格输出 JSON：
{{
  "title": "短标题",
  "done": false,
  "steps": [
    {{
      "keyword_id": "白名单 id",
      "params": {{"param_id": "值"}},
      "comment": "说明",
      "action_role": "target|assert|support"
    }}
  ],
  "notes": "可选"
}}

规则：
- 尚未建会话时先 http_session_begin（可带 base_url）；历史已成功 begin 后不要重复
- 请求用 http_get / http_post / http_put / http_patch；相对路径会拼到 base_url。禁止 http_delete
- 认证用 http_set_auth_bearer / basic / apikey；切环境用 api_env_use
- 每条业务请求后必须有断言：http_assert_status、http_assert_body_contains 或 json_assert_schema
- 请求关键字的 action_role=target；断言用 assert；会话/认证/环境用 support
- 用户目标动作都已完成且已有断言时：done=true，并给出能概括整条用例的 title
- 历史里已失败的步骤不要重复提交同样的 keyword_id + URL/参数组合
{repeat_block}"""
    if platform == "web":
        element_semantics = (
            "Web 摘要来自当前 DOM；仅使用可见元素的真实 ``l``，不要推测未加载页面的控件"
        )
        wait_examples = (
            "web_browser_wait_for_exist / web_browser_wait_for_visible / "
            "web_browser_wait_for_text / sleep"
        )
        entry_rule = "Web 必须从起始 URL 的 web_browser_open 开始；历史已有同一 URL 时不要重复打开"
        snapshot_rule = (
            "web_browser_snapshot 仅当用户目标明确要求截图/留证时才输出；"
        )
        platform_action_rules = (
            "- Web 返回使用 web_browser_back；长页面探索使用 web_browser_scroll_vertical_bar；"
            "跳转 URL 使用 web_browser_locate\n"
            "- Web 输入使用 web_element_text_input，点击使用 web_element_click；"
            "执行层会根据上下文选择 Selenium 或 Playwright"
        )
    else:
        element_semantics = (
            "未标 ``ck`` 的 StaticText / Image / TextView 在移动端也可能可点；"
            "结合 ``tx`` / ``p`` / 类型判断"
        )
        wait_examples = "mobile_wait_element_* / wait_element / wait_for_element / sleep"
        entry_rule = "若尚未启动目标 App，且提供了包名，优先 mobile_app_start"
        snapshot_rule = (
            "mobile_app_snapshot 仅当用户目标明确要求截图/留证时才输出；"
        )
        platform_action_rules = (
            "- 移动端返回使用 mobile_presskey（oKeys=back）；方向滚动使用 mobile_swipe_direction；"
            "已知目标定位符时优先 mobile_slip_for_element，"
            "禁止编造 mobile_back/mobile_swipe_up 等未注册别名\n"
            "- iOS/Android 输入：mobile_element_text_input 的 text 参数放输入内容；"
            "点击用 mobile_element_click"
        )
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
``ck:1`` 确定可点｜``ed:1`` 可输入文本｜``dup:N`` 表示该 ``l`` 命中 N 个控件、不可安全执行
{element_semantics}
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
      "comment": "说明",
      "action_role": "navigate|scroll|backtrack|target|assert|support"
    }}
  ],
  "navigation": {{"strategy": "search_first|category_fallback|scroll_discover|target_action|assert"}},
  "notes": "可选"
}}

步骤类型（同页可组合；改页动作每回合最多一步）：
- **Act** 操作：启动/打开、点击、输入、滑动、返回（改页后停本回合）
- **Wait** 等待：{wait_examples}
- **Assert** 断言：mobile_verify_* / web_verify_*（确认文案、开关、可见性等）
若用户目标含「确认/检查/验证/断言」语义，目标动作完成后至少给一步 Assert。
纯浏览类需求可无 Assert，但 notes 须说明无需断言的原因。

规则：
- {entry_rule}
- HTTP：尚未建会话时先 http_session_begin；请求用 http_get / http_post；需要环境变量时用 api_env_use
- 同一包名/URL 的入口已在历史成功执行过时，不要重复提交（会把页面打回入口）
- 截图类步骤：{snapshot_rule}
  不要用截图代替观察——每回合都会自动给你最新页摘要
- 定位必须直接取自当前页摘要的 ``l`` 字段；也可在 params 里给 ``target``（控件中文名），
  由编写器解析成 ``l``；禁止使用带 ``dup`` 的歧义定位符，没有合适控件则 done=false，
  并在 notes 说明观察结论
- **控件名不可轻信**：accessibility name / id 可能与视觉功能不一致。需求提到方位（顶部/底部/右上角等）时，
  用 ``p`` 与屏幕尺寸判断；同名多个控件时优先匹配方位与文案语义
- 要输入文本：优先 ``ed:1`` 控件。若当前页没有 ``ed:1``，先点开与目标语义一致的入口
  （同义/近义文案、占位提示、邻近图标、需求方位对应的控件），下一回合再输入；
  不要盲点其它无关导航或试探性入口
- 路径试探失败后：回到上一层或换与目标语义更接近的控件，写清 notes；不要把盲试写进用例
- 深层页面导航：进入下一层用 action_role=navigate；探索列表用 scroll；确认走错后返回用
  backtrack；真正完成用户动作的步骤用 target；断言用 assert；输入、等待等用 support
- navigation.strategy 必须反映本回合实际策略；若状态中的 open_incident 未关闭，
  先换策略恢复，不得直接输出 target 或 done=true
{platform_action_rules}
- 用户目标动作都已完成时：done=true，并给出能概括整条用例的 title（中途回合的 title 会被忽略）
- 若本回合输出的 Assert 就是目标最终验收，必须同时返回 done=true；不要再浪费一回合只宣告完成
- 历史里已失败的步骤不要重复提交同样的 keyword_id + 定位组合
- 若出现【重复操作提示】：同一控件在页面未变化时不要再点；换路径或 done=true 并说明卡住原因
{repeat_block}{navigation_block}"""
