"""应用多语言目录：自然语言名称 → 候选包名 / Bundle。

分两层：
- system：平台内置应用；候选不在普通安装列表时可用可信 Bundle 回落。
- popular：常用第三方应用；只作为候选，必须在设备安装列表中验证，禁止臆测已安装。

部署方可用 ``AUTOPILOT_AUTHORING_APP_ALIASES_FILE`` 指向 JSON 文件追加企业应用，
避免每增加一个业务 App 都修改本模块。
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class AppAliasEntry:
    app_id: str
    packages: tuple[str, ...]
    aliases: tuple[str, ...]
    kind: str = "popular"  # system | popular | custom
    trusted_fallback: bool = False


def _entry(
    app_id: str,
    package: str | tuple[str, ...],
    aliases: tuple[str, ...],
    *,
    kind: str = "system",
    trusted: bool = True,
) -> AppAliasEntry:
    packages = (package,) if isinstance(package, str) else package
    return AppAliasEntry(app_id, packages, aliases, kind, trusted)


# 常用系统应用。Bundle/包名有 ROM 差异时列多个候选；Android 设置另走 Intent。
_BUILTIN_SYSTEM: dict[str, tuple[AppAliasEntry, ...]] = {
    "ios": (
        _entry("settings", "com.apple.Preferences", ("设置", "設定", "系统设置", "系統設定", "settings", "preferences")),
        _entry("phone", "com.apple.mobilephone", ("电话", "電話", "phone", "dialer", "拨号", "撥號")),
        _entry("messages", "com.apple.MobileSMS", ("信息", "訊息", "短信", "messages", "sms", "imessage")),
        _entry("safari", "com.apple.mobilesafari", ("safari", "浏览器", "瀏覽器", "苹果浏览器", "apple browser")),
        _entry("camera", "com.apple.camera", ("相机", "相機", "camera")),
        _entry("photos", "com.apple.Photos", ("照片", "相簿", "相册", "相冊", "photos")),
        _entry("app_store", "com.apple.AppStore", ("app store", "苹果商店", "應用商店", "应用商店")),
        _entry("calendar", "com.apple.mobilecal", ("日历", "日曆", "calendar")),
        _entry("clock", "com.apple.mobiletimer", ("时钟", "時鐘", "闹钟", "鬧鐘", "clock", "alarm")),
        _entry("contacts", "com.apple.MobileAddressBook", ("通讯录", "通訊錄", "联系人", "聯絡人", "contacts")),
        _entry("files", "com.apple.DocumentsApp", ("文件", "档案", "檔案", "files")),
        _entry("find_my", "com.apple.findmy", ("查找", "寻找", "尋找", "find my")),
        _entry("health", "com.apple.Health", ("健康", "health")),
        _entry("home", "com.apple.Home", ("家庭", "home", "homekit")),
        _entry("mail", "com.apple.mobilemail", ("邮件", "郵件", "邮箱", "mail", "email")),
        _entry("maps", "com.apple.Maps", ("地图", "地圖", "maps", "apple maps")),
        _entry("music", "com.apple.Music", ("音乐", "音樂", "music", "apple music")),
        _entry("notes", "com.apple.mobilenotes", ("备忘录", "備忘錄", "笔记", "筆記", "notes")),
        _entry("reminders", "com.apple.reminders", ("提醒事项", "提醒事項", "提醒", "reminders")),
        _entry("shortcuts", "com.apple.shortcuts", ("快捷指令", "捷径", "捷徑", "shortcuts")),
        _entry("wallet", "com.apple.Passbook", ("钱包", "錢包", "wallet", "apple wallet")),
        _entry("weather", "com.apple.weather", ("天气", "天氣", "weather")),
        _entry("calculator", "com.apple.calculator", ("计算器", "計算機", "calculator")),
        _entry("voice_memos", "com.apple.VoiceMemos", ("语音备忘录", "語音備忘錄", "录音", "錄音", "voice memos")),
        _entry("facetime", "com.apple.facetime", ("facetime", "视频通话", "視訊通話")),
        _entry("books", "com.apple.iBooks", ("图书", "圖書", "书籍", "書籍", "books", "apple books")),
        _entry("compass", "com.apple.compass", ("指南针", "指南針", "罗盘", "羅盤", "compass")),
        _entry("measure", "com.apple.measure", ("测距仪", "測距儀", "测量", "測量", "measure")),
        _entry("podcasts", "com.apple.podcasts", ("播客", "podcasts", "apple podcasts")),
        _entry("stocks", "com.apple.stocks", ("股市", "股票", "stocks")),
        _entry("tips", "com.apple.tips", ("提示", "技巧", "tips")),
        _entry("translate", "com.apple.Translate", ("翻译", "翻譯", "translate")),
        _entry("tv", "com.apple.tv", ("apple tv", "电视", "電視", "tv")),
        _entry("freeform", "com.apple.freeform", ("无边记", "無邊記", "freeform")),
    ),
    "android": (
        _entry("settings", "com.android.settings", ("设置", "設定", "系统设置", "系統設定", "settings", "android settings")),
        _entry("phone", ("com.google.android.dialer", "com.android.dialer"), ("电话", "電話", "拨号", "撥號", "phone", "dialer"), trusted=False),
        _entry("messages", ("com.google.android.apps.messaging", "com.android.mms"), ("信息", "短信", "messages", "sms"), trusted=False),
        _entry("camera", ("com.google.android.GoogleCamera", "com.android.camera2", "com.android.camera"), ("相机", "相機", "camera"), trusted=False),
        _entry("photos", ("com.google.android.apps.photos", "com.android.gallery3d"), ("照片", "相册", "相簿", "photos", "gallery"), trusted=False),
        _entry("calendar", ("com.google.android.calendar", "com.android.calendar"), ("日历", "日曆", "calendar"), trusted=False),
        _entry("contacts", ("com.google.android.contacts", "com.android.contacts"), ("通讯录", "通訊錄", "联系人", "contacts"), trusted=False),
        _entry("calculator", ("com.google.android.calculator", "com.android.calculator2"), ("计算器", "計算機", "calculator"), trusted=False),
        _entry("clock", ("com.google.android.deskclock", "com.android.deskclock"), ("时钟", "時鐘", "闹钟", "clock", "alarm"), trusted=False),
        _entry("files", ("com.google.android.documentsui", "com.android.documentsui"), ("文件", "文件管理", "files"), trusted=False),
        _entry("play_store", "com.android.vending", ("play store", "google play", "谷歌商店", "应用商店"), trusted=False),
        _entry("maps", "com.google.android.apps.maps", ("google maps", "谷歌地图", "谷歌地圖"), trusted=False),
        _entry("drive", "com.google.android.apps.docs", ("google drive", "谷歌云端硬盘", "谷歌雲端硬碟"), trusted=False),
        _entry("keep", "com.google.android.keep", ("google keep", "keep", "谷歌笔记"), trusted=False),
        _entry("meet", "com.google.android.apps.tachyon", ("google meet", "meet"), trusted=False),
        _entry("youtube", "com.google.android.youtube", ("youtube", "油管"), trusted=False),
        _entry("gmail", "com.google.android.gm", ("gmail", "谷歌邮箱", "谷歌郵箱"), trusted=False),
    ),
}


# 热门第三方应用：包名仅用于从“已安装列表”中精确挑选，绝不据此认定已安装。
_BUILTIN_POPULAR: dict[str, tuple[AppAliasEntry, ...]] = {
    "ios": (
        _entry("wechat", "com.tencent.xin", ("微信", "wechat", "weixin"), kind="popular", trusted=False),
        _entry("alipay", "com.alipay.iphoneclient", ("支付宝", "支付寶", "alipay"), kind="popular", trusted=False),
        _entry("qq", "com.tencent.mqq", ("qq", "腾讯qq", "騰訊qq"), kind="popular", trusted=False),
        _entry("dingtalk", "com.laiwang.DingTalk", ("钉钉", "釘釘", "dingtalk"), kind="popular", trusted=False),
        _entry("feishu", "com.bytedance.ee.lark", ("飞书", "飛書", "feishu", "lark"), kind="popular", trusted=False),
        _entry("douyin", "com.ss.iphone.ugc.Aweme", ("抖音", "douyin"), kind="popular", trusted=False),
        _entry("tiktok", "com.zhiliaoapp.musically", ("tiktok", "tik tok"), kind="popular", trusted=False),
        _entry("taobao", "com.taobao.taobao4iphone", ("淘宝", "淘寶", "taobao"), kind="popular", trusted=False),
        _entry("jd", "com.360buy.jdmobile", ("京东", "京東", "jd", "jingdong"), kind="popular", trusted=False),
        _entry("chrome", "com.google.chrome.ios", ("chrome", "谷歌浏览器", "谷歌瀏覽器"), kind="popular", trusted=False),
        _entry("edge", "com.microsoft.msedge", ("edge", "微软浏览器", "微軟瀏覽器"), kind="popular", trusted=False),
        _entry("firefox", "org.mozilla.ios.Firefox", ("firefox", "火狐", "火狐浏览器"), kind="popular", trusted=False),
        _entry("gmail", "com.google.Gmail", ("gmail", "谷歌邮箱", "谷歌郵箱"), kind="popular", trusted=False),
        _entry("youtube", "com.google.ios.youtube", ("youtube", "油管"), kind="popular", trusted=False),
        _entry("spotify", "com.spotify.client", ("spotify",), kind="popular", trusted=False),
        _entry("xiaohongshu", "com.xingin.discover", ("小红书", "小紅書", "xiaohongshu", "rednote"), kind="popular", trusted=False),
        _entry("meituan", "com.meituan.imeituan", ("美团", "美團", "meituan"), kind="popular", trusted=False),
        _entry("eleme", "me.ele.ios.eleme", ("饿了么", "餓了麼", "eleme"), kind="popular", trusted=False),
        _entry("pinduoduo", "com.xunmeng.pinduoduo", ("拼多多", "pinduoduo", "temu china"), kind="popular", trusted=False),
        _entry("xianyu", "com.taobao.fleamarket", ("闲鱼", "閒魚", "xianyu"), kind="popular", trusted=False),
        _entry("weibo", "com.sina.weibo", ("微博", "weibo"), kind="popular", trusted=False),
        _entry("bilibili", "tv.danmaku.bilianime", ("哔哩哔哩", "嗶哩嗶哩", "bilibili", "b站"), kind="popular", trusted=False),
        _entry("kuaishou", "com.jiangjia.gif", ("快手", "kuaishou", "kwai"), kind="popular", trusted=False),
        _entry("zhihu", "com.zhihu.ios", ("知乎", "zhihu"), kind="popular", trusted=False),
        _entry("baidu", "com.baidu.BaiduMobile", ("百度", "baidu"), kind="popular", trusted=False),
        _entry("baidu_maps", "com.baidu.map", ("百度地图", "百度地圖", "baidu maps"), kind="popular", trusted=False),
        _entry("amap", "com.autonavi.amap", ("高德地图", "高德地圖", "amap", "gaode maps"), kind="popular", trusted=False),
        _entry("railway_12306", "cn.12306.rails12306", ("铁路12306", "鐵路12306", "12306"), kind="popular", trusted=False),
        _entry("ctrip", "ctrip.com", ("携程", "攜程", "ctrip", "trip.com"), kind="popular", trusted=False),
        _entry("netease_music", "com.netease.cloudmusic", ("网易云音乐", "網易雲音樂", "netease music"), kind="popular", trusted=False),
        _entry("qq_music", "com.tencent.QQMusic", ("qq音乐", "qq音樂", "qq music"), kind="popular", trusted=False),
        _entry("tencent_video", "com.tencent.live4iphone", ("腾讯视频", "騰訊視頻", "tencent video"), kind="popular", trusted=False),
        _entry("iqiyi", "com.qiyi.iphone", ("爱奇艺", "愛奇藝", "iqiyi"), kind="popular", trusted=False),
        _entry("youku", "com.youku.YouKu", ("优酷", "優酷", "youku"), kind="popular", trusted=False),
        _entry("whatsapp", "net.whatsapp.WhatsApp", ("whatsapp", "what's app"), kind="popular", trusted=False),
        _entry("instagram", "com.burbn.instagram", ("instagram", "ins"), kind="popular", trusted=False),
        _entry("facebook", "com.facebook.Facebook", ("facebook", "脸书", "臉書"), kind="popular", trusted=False),
        _entry("x_twitter", "com.atebits.Tweetie2", ("x", "twitter", "推特"), kind="popular", trusted=False),
        _entry("telegram", "ph.telegra.Telegraph", ("telegram", "电报", "電報"), kind="popular", trusted=False),
        _entry("slack", "com.tinyspeck.chatlyio", ("slack",), kind="popular", trusted=False),
        _entry("teams", "com.microsoft.skype.teams", ("teams", "microsoft teams", "微软teams"), kind="popular", trusted=False),
        _entry("zoom", "us.zoom.videomeetings", ("zoom", "zoom meetings"), kind="popular", trusted=False),
        _entry("outlook", "com.microsoft.Office.Outlook", ("outlook", "微软邮箱", "微軟郵箱"), kind="popular", trusted=False),
        _entry("onedrive", "com.microsoft.skydrive", ("onedrive", "微软云盘", "微軟雲端硬碟"), kind="popular", trusted=False),
        _entry("google_drive", "com.google.Drive", ("google drive", "谷歌云端硬盘", "谷歌雲端硬碟"), kind="popular", trusted=False),
        _entry("netflix", "com.netflix.Netflix", ("netflix", "奈飞", "網飛"), kind="popular", trusted=False),
        _entry(
            "birdscope",
            "com.birds.song.identifier.ai",
            ("birdscope", "bird scope", "鸟类识别", "鳥類識別"),
            kind="popular",
            trusted=False,
        ),
        _entry(
            "plantin",
            "xyz.plantin.app",
            ("plantin", "plant in", "plantscope", "植物识别", "植物識別"),
            kind="popular",
            trusted=False,
        ),
    ),
    "android": (
        _entry("wechat", "com.tencent.mm", ("微信", "wechat", "weixin"), kind="popular", trusted=False),
        _entry("alipay", "com.eg.android.AlipayGphone", ("支付宝", "支付寶", "alipay"), kind="popular", trusted=False),
        _entry("qq", "com.tencent.mobileqq", ("qq", "腾讯qq", "騰訊qq"), kind="popular", trusted=False),
        _entry("dingtalk", "com.alibaba.android.rimet", ("钉钉", "釘釘", "dingtalk"), kind="popular", trusted=False),
        _entry("feishu", "com.ss.android.lark", ("飞书", "飛書", "feishu", "lark"), kind="popular", trusted=False),
        _entry("douyin", "com.ss.android.ugc.aweme", ("抖音", "douyin"), kind="popular", trusted=False),
        _entry("tiktok", "com.zhiliaoapp.musically", ("tiktok", "tik tok"), kind="popular", trusted=False),
        _entry("taobao", "com.taobao.taobao", ("淘宝", "淘寶", "taobao"), kind="popular", trusted=False),
        _entry("jd", "com.jingdong.app.mall", ("京东", "京東", "jd", "jingdong"), kind="popular", trusted=False),
        _entry("chrome", "com.android.chrome", ("chrome", "谷歌浏览器", "谷歌瀏覽器"), kind="popular", trusted=False),
        _entry("edge", "com.microsoft.emmx", ("edge", "微软浏览器", "微軟瀏覽器"), kind="popular", trusted=False),
        _entry("firefox", "org.mozilla.firefox", ("firefox", "火狐", "火狐浏览器"), kind="popular", trusted=False),
        _entry("spotify", "com.spotify.music", ("spotify",), kind="popular", trusted=False),
        _entry("xiaohongshu", "com.xingin.xhs", ("小红书", "小紅書", "xiaohongshu", "rednote"), kind="popular", trusted=False),
        _entry("meituan", "com.sankuai.meituan", ("美团", "美團", "meituan"), kind="popular", trusted=False),
        _entry("eleme", "me.ele", ("饿了么", "餓了麼", "eleme"), kind="popular", trusted=False),
        _entry("pinduoduo", "com.xunmeng.pinduoduo", ("拼多多", "pinduoduo", "temu china"), kind="popular", trusted=False),
        _entry("xianyu", "com.taobao.idlefish", ("闲鱼", "閒魚", "xianyu"), kind="popular", trusted=False),
        _entry("weibo", "com.sina.weibo", ("微博", "weibo"), kind="popular", trusted=False),
        _entry("bilibili", "tv.danmaku.bili", ("哔哩哔哩", "嗶哩嗶哩", "bilibili", "b站"), kind="popular", trusted=False),
        _entry("kuaishou", "com.smile.gifmaker", ("快手", "kuaishou", "kwai"), kind="popular", trusted=False),
        _entry("zhihu", "com.zhihu.android", ("知乎", "zhihu"), kind="popular", trusted=False),
        _entry("baidu", "com.baidu.searchbox", ("百度", "baidu"), kind="popular", trusted=False),
        _entry("baidu_maps", "com.baidu.BaiduMap", ("百度地图", "百度地圖", "baidu maps"), kind="popular", trusted=False),
        _entry("amap", "com.autonavi.minimap", ("高德地图", "高德地圖", "amap", "gaode maps"), kind="popular", trusted=False),
        _entry("railway_12306", "com.MobileTicket", ("铁路12306", "鐵路12306", "12306"), kind="popular", trusted=False),
        _entry("ctrip", "ctrip.android.view", ("携程", "攜程", "ctrip", "trip.com"), kind="popular", trusted=False),
        _entry("netease_music", "com.netease.cloudmusic", ("网易云音乐", "網易雲音樂", "netease music"), kind="popular", trusted=False),
        _entry("qq_music", "com.tencent.qqmusic", ("qq音乐", "qq音樂", "qq music"), kind="popular", trusted=False),
        _entry("tencent_video", "com.tencent.qqlive", ("腾讯视频", "騰訊視頻", "tencent video"), kind="popular", trusted=False),
        _entry("iqiyi", "com.qiyi.video", ("爱奇艺", "愛奇藝", "iqiyi"), kind="popular", trusted=False),
        _entry("youku", "com.youku.phone", ("优酷", "優酷", "youku"), kind="popular", trusted=False),
        _entry("whatsapp", "com.whatsapp", ("whatsapp", "what's app"), kind="popular", trusted=False),
        _entry("instagram", "com.instagram.android", ("instagram", "ins"), kind="popular", trusted=False),
        _entry("facebook", "com.facebook.katana", ("facebook", "脸书", "臉書"), kind="popular", trusted=False),
        _entry("x_twitter", "com.twitter.android", ("x", "twitter", "推特"), kind="popular", trusted=False),
        _entry("telegram", "org.telegram.messenger", ("telegram", "电报", "電報"), kind="popular", trusted=False),
        _entry("slack", "com.Slack", ("slack",), kind="popular", trusted=False),
        _entry("teams", "com.microsoft.teams", ("teams", "microsoft teams", "微软teams"), kind="popular", trusted=False),
        _entry("zoom", "us.zoom.videomeetings", ("zoom", "zoom meetings"), kind="popular", trusted=False),
        _entry("outlook", "com.microsoft.office.outlook", ("outlook", "微软邮箱", "微軟郵箱"), kind="popular", trusted=False),
        _entry("onedrive", "com.microsoft.skydrive", ("onedrive", "微软云盘", "微軟雲端硬碟"), kind="popular", trusted=False),
        _entry("netflix", "com.netflix.mediaclient", ("netflix", "奈飞", "網飛"), kind="popular", trusted=False),
    ),
}

# Android「设置」类提示：应用别名表 + intent 兜底
_ANDROID_SETTINGS_HINTS = frozenset(
    {
        "设置",
        "設定",
        "系统设置",
        "系統設定",
        "settings",
        "androidsettings",
        "android settings",
    }
)


def _norm(text: str) -> str:
    value = unicodedata.normalize("NFKC", (text or "").strip()).casefold()
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", value)


def _hint_forms(text: str) -> tuple[str, ...]:
    """生成自然语言应用名的候选形态，直接形态优先。

    支持「微信应用 / 企业门户客户端 / Google Maps App」等口语，不会先把
    WhatsApp 的 ``app`` 尾部误删，因为完整别名总是先匹配。
    """
    direct = _norm(text)
    if not direct:
        return ()
    forms = [direct]
    suffixes = (
        _norm("应用程序"),
        _norm("客户端"),
        _norm("应用"),
        _norm("软件"),
        "application",
        "client",
        "app",
    )
    prefixes = (_norm("打开"), _norm("启动"), _norm("运行"), "open", "launch")
    queue = [direct]
    while queue:
        current = queue.pop(0)
        for token in prefixes:
            if current.startswith(token) and len(current) > len(token):
                value = current[len(token) :]
                if value and value not in forms:
                    forms.append(value)
                    queue.append(value)
        for token in suffixes:
            if current.endswith(token) and len(current) > len(token):
                value = current[: -len(token)]
                if value and value not in forms:
                    forms.append(value)
                    queue.append(value)
    return tuple(forms)


def _custom_entries() -> dict[str, tuple[AppAliasEntry, ...]]:
    path = (os.environ.get("AUTOPILOT_AUTHORING_APP_ALIASES_FILE") or "").strip()
    if not path:
        return {}
    return _load_custom_entries(path)


@lru_cache(maxsize=8)
def _load_custom_entries(path: str) -> dict[str, tuple[AppAliasEntry, ...]]:
    """加载外部目录；坏文件不影响内置解析。"""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    out: dict[str, tuple[AppAliasEntry, ...]] = {}
    for platform in ("ios", "android"):
        rows = raw.get(platform) if isinstance(raw, dict) else None
        if not isinstance(rows, list):
            continue
        entries: list[AppAliasEntry] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            app_id = str(row.get("id") or "").strip()
            packages = tuple(str(x).strip() for x in row.get("packages", []) if str(x).strip())
            aliases = tuple(str(x).strip() for x in row.get("aliases", []) if str(x).strip())
            if app_id and packages and aliases:
                entries.append(AppAliasEntry(app_id, packages, aliases, "custom", False))
        out[platform] = tuple(entries)
    return out


def app_catalog(platform: str) -> tuple[AppAliasEntry, ...]:
    plat = (platform or "").strip().lower()
    custom = _custom_entries().get(plat, ())
    return custom + _BUILTIN_SYSTEM.get(plat, ()) + _BUILTIN_POPULAR.get(plat, ())


def alias_entry(platform: str, hint: str) -> AppAliasEntry | None:
    keys = _hint_forms(hint)
    if not keys:
        return None
    # 先完整名称、后去“应用/客户端”等后缀，避免 WhatsApp 被当成 Whats。
    for key in keys:
        for entry in app_catalog(platform):
            if any(_norm(alias) == key for alias in entry.aliases):
                return entry
    return None


def iter_system_packages(platform: str) -> Iterable[str]:
    return tuple(
        pkg
        for entry in app_catalog(platform)
        if entry.kind == "system"
        for pkg in entry.packages
    )


def aliases_for_package(platform: str, package_name: str) -> tuple[str, ...]:
    pkg = (package_name or "").strip()
    for entry in app_catalog(platform):
        if pkg in entry.packages:
            return entry.aliases
    return ()


def canonical_system_package(platform: str, hint: str) -> str:
    """兼容旧调用：仅系统目录返回首选包名。"""
    entry = alias_entry(platform, hint)
    if entry is None or entry.kind != "system":
        return ""
    return entry.packages[0]


def is_android_settings_hint(hint: str) -> bool:
    key = _norm(hint)
    if not key:
        return False
    if key in {_norm(x) for x in _ANDROID_SETTINGS_HINTS}:
        return True
    return canonical_system_package("android", hint) == "com.android.settings"


def expand_hint_keys(platform: str, hint: str) -> set[str]:
    """匹配用：原 hint + 同目录项其它语言别名 + 候选包名。"""
    keys = {_norm(hint)}
    keys.discard("")
    entry = alias_entry(platform, hint)
    if entry is None:
        return keys
    for alias in entry.aliases:
        n = _norm(alias)
        if n:
            keys.add(n)
    keys.update(pkg.lower() for pkg in entry.packages)
    return keys
