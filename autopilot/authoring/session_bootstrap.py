"""链路 3：自动选设备、解析应用、创建执行会话（无需手动开检视器）。"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Callable

from ..keywords.context import ExecutionContext
from ..runtime.job_platforms import is_job_platform
from .app_resolve import (
    AppResolveAmbiguousError,
    AppResolveNotFoundError,
    InstalledApp,
    resolve_installed_app,
)
from .contract import (
    AuthoringError,
    AuthoringRequest,
    debug_note,
    normalize_platform,
)
from .platform_resolve import inspect_platform_from_ctx, resolve_authoring_platform
from .llm_client import ChatFn
from .nl_bootstrap import resolve_nl_hints
from .nl_parse import parse_nl_hints  # noqa: F401 — 兼容旧导入

log = logging.getLogger(__name__)

_ENV_UNATTENDED = "AUTOPILOT_AUTHORING_UNATTENDED"
_ENV_DEVICE_UDID = "AUTOPILOT_AUTHORING_DEVICE_UDID"

EnsureAppiumFn = Callable[[], bool]
#: 多设备时向调用方（UI）征询选哪台；返回空串表示放弃自动选择
PickDeviceFn = Callable[[str, list[str]], str]
#: 应用歧义/未命中时向调用方征询选哪个；返回 None 表示放弃
PickAppFn = Callable[[str, list[InstalledApp]], InstalledApp | None]


@dataclass
class BootstrapResult:
    ctx: ExecutionContext
    request: AuthoringRequest
    udid: str
    resolved_app: InstalledApp | None
    notes: list[str]
    #: True = 复用了检视器/镜像已建好的会话，调用方不应接管其生命周期
    reused_ctx: bool = False


def _ctx_platform(ctx: Any) -> str:
    """已有 ctx 绑定的平台（检视器写 ``__inspect_platform__``）。"""
    if ctx is None or not hasattr(ctx, "get_var"):
        return ""
    raw = str(ctx.get_var("__inspect_platform__") or "").strip().lower()
    if is_job_platform(raw):
        return raw
    return str(ctx.get_var("__current_platform__") or "").strip().lower()


def _platform_from_project(project_dir: str) -> str:
    proj = (project_dir or "").strip()
    if not proj:
        return ""
    try:
        from ..runtime import settings

        plat = (settings.project_platform(proj) or "").strip().lower()
    except (ImportError, OSError, AttributeError, TypeError, RuntimeError):
        return ""
    return plat if is_job_platform(plat) else ""


def reusable_ctx(ctx: Any, platform: str, *, udid: str = "") -> bool:
    """已有会话能否直接给 AI 编写用。

    检视器/镜像建的会话已带齐 caps、Appium server 与活跃 driver，能复用就别新建：
    重复建 iOS 会话会抢 WDA 端口，实践里比复用更容易失败。平台或设备不一致时不复用。
    """
    if ctx is None or not hasattr(ctx, "get_var"):
        return False
    plat = _ctx_platform(ctx)
    if plat and plat != platform:
        return False
    if platform in ("android", "ios"):
        bound = str(ctx.get_var("__device_udid__") or "").strip()
        if not bound:
            return False
        if udid and bound != udid:
            return False
    return True


def _apply_mobile_session_vars(
    ctx: Any,
    *,
    platform: str,
    udid: str,
    package_name: str,
    notes: list[str],
) -> None:
    """给新建 ctx 补齐与检视器同款的移动会话变量（含 iOS Appium caps）。"""
    ctx.set_var("__device_udid__", udid)
    ctx.set_var("__inspect_platform__", "iOS" if platform == "ios" else "Android")
    ctx.set_var("__current_platform__", platform)
    backend_mode = _ios_backend_mode()
    ctx.set_var("__mobile_backend_mode__", backend_mode)
    ctx.set_var("app_package", package_name)
    ctx.set_var("packageName", package_name)
    if platform != "ios":
        return

    try:
        from ..keywords.mobile import platform as mp
        from ..mobile import ios_bootstrap as ib

        uses_appium = mp.ios_inspector_uses_appium(backend_mode)
        # WDA 发现要跑设备侧命令，只在真正需要 caps 的 Appium 路径上做
        wda = _wda_bundle_id(udid) if uses_appium else ""
        base_vars: dict[str, Any] = {}
        if wda:
            base_vars["__appium_caps__"] = {"wdaBundleId": wda}
        if uses_appium:
            ib.merge_appium_ios_caps(base_vars, udid, wda, backend_mode)
            ctx.set_var("__appium_server__", _appium_server_url())
        for k, v in base_vars.items():
            ctx.set_var(k, v)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        notes.append(debug_note(f"iOS caps 预置跳过：{exc}"))


def _ios_backend_mode() -> str:
    try:
        from ..runtime import settings

        mode = str(settings.ios_backend_mode() or "").strip().lower()
    except (ImportError, AttributeError, OSError, RuntimeError, TypeError, ValueError):
        mode = ""
    if mode:
        return mode
    return (os.environ.get("IOS_BACKEND") or "auto").strip().lower() or "auto"


def _wda_bundle_id(udid: str) -> str:
    """WDA bundle：环境变量优先，其次按设备自动发现（与检视器同一来源）。"""
    env = (os.environ.get("IOS_WDA_BUNDLE_ID") or "").strip()
    if env:
        return env
    try:
        from ..mobile import ios_bootstrap as ib

        return str(ib.IosDevicePrep(udid, "").discover_wda() or "").strip()
    except (ImportError, AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return ""


def _appium_server_url() -> str:
    return (os.environ.get("APPIUM_SERVER_URL") or "http://127.0.0.1:4723").strip()


def authoring_unattended() -> bool:
    raw = (os.environ.get(_ENV_UNATTENDED) or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def preferred_authoring_udid(explicit: str = "") -> str:
    return (explicit or "").strip() or (os.environ.get(_ENV_DEVICE_UDID) or "").strip()


def _pick_udid(
    platform: str,
    preferred: str = "",
    *,
    pick_device: PickDeviceFn | None = None,
) -> str:
    from ..mgmt.local_devices import list_android_devices, list_ios_devices

    pref = preferred_authoring_udid(preferred)
    if platform == "ios":
        found = list(list_ios_devices())
    elif platform == "android":
        found = list(list_android_devices())
    else:
        return ""
    devices = [d for d in found if getattr(d, "state", "") == "ready"]
    log.info(
        "编写设备探测：platform=%s 枚举=%d 可用=%d %s",
        platform,
        len(found),
        len(devices),
        [f"{getattr(d, 'udid', '?')}:{getattr(d, 'state', '?')}" for d in found],
    )
    if not devices:
        raise AuthoringError(_no_device_message(platform, found))
    if pref:
        for d in devices:
            if d.udid == pref:
                return d.udid
        raise AuthoringError(f"指定设备不在线：{pref}")
    if len(devices) == 1:
        return devices[0].udid
    udids = [d.udid for d in devices]
    interactive = pick_device is not None and not authoring_unattended()
    if interactive:
        chosen = (pick_device(platform, udids) or "").strip()
        if not chosen:
            raise AuthoringError("已取消：多台设备在线，未选择编写目标设备")
        if chosen not in udids:
            raise AuthoringError(f"所选设备不在线：{chosen}")
        return chosen
    if authoring_unattended():
        raise AuthoringError(
            "无人值守时检测到多台设备，请设置 AUTOPILOT_AUTHORING_DEVICE_UDID"
        )
    # CLI 无回调：取第一台 ready（兼容旧脚本）；无人值守不会走到这里
    return udids[0]


def _unusable_device_detail(found: Sequence[Any]) -> str:
    """已枚举到但状态不可用的设备摘要（udid + state + 健康备注）。"""
    bits: list[str] = []
    for d in found or ():
        udid = str(getattr(d, "udid", "") or "?")
        state = str(getattr(d, "state", "") or "?")
        note = str(getattr(d, "health_note", "") or "")
        bits.append(f"{udid} state={state}" + (f"（{note}）" if note else ""))
    return "；".join(bits[:3])


def _no_device_message(platform: str, found: Sequence[Any] = ()) -> str:
    """设备不可用时给出可行动的原因。

    两种情况要说清楚，别混成一句「请先插 USB」：设备根本没枚举到（多为工具链装坏），
    还是枚举到了但状态不可用（如本机缺 iOS 后端、adb unauthorized）。
    """
    shown = {"ios": "iOS", "android": "Android", "web": "Web"}.get(platform, platform)
    detail = _unusable_device_detail(found)
    if detail:
        return f"检测到 {len(found)} 台 {shown} 设备，但都不可用：{detail}"
    base = f"未检测到可用的 {shown} 设备，请先用 USB 连接并信任本机"
    if platform != "ios":
        return base
    try:
        from ..mobile.ios_devices import ios_tooling_error
    except ImportError:
        return base
    reason = ios_tooling_error()
    if reason:
        return f"{base}；iOS 设备通道异常 → {reason}"
    return base


def _resolve_app_with_picker(
    platform: str,
    *,
    udid: str,
    app_name: str,
    package_name: str,
    pick_app: PickAppFn | None,
    chat: ChatFn | None = None,
) -> InstalledApp:
    """解析应用；歧义或未命中时可选回调让用户择一。"""
    hint = (app_name or package_name or "").strip()
    try:
        return resolve_installed_app(
            platform,
            udid=udid,
            app_name=app_name,
            package_name=package_name,
            chat=chat,
        )
    except AppResolveAmbiguousError as exc:
        if pick_app is not None and not authoring_unattended():
            picked = pick_app(hint, list(exc.candidates))
            if picked is not None:
                return picked
        raise AuthoringError(
            f"应用「{hint}」存在多个候选，请指定包名或从列表选择"
        ) from exc
    except AppResolveNotFoundError as exc:
        if pick_app is not None and exc.candidates and not authoring_unattended():
            picked = pick_app(hint, list(exc.candidates))
            if picked is not None:
                return picked
        raise AuthoringError(str(exc)) from exc


def prepare_authoring_session(
    request: AuthoringRequest,
    *,
    preferred_udid: str = "",
    ensure_appium: EnsureAppiumFn | None = None,
    existing_ctx: Any = None,
    pick_device: PickDeviceFn | None = None,
    pick_app: PickAppFn | None = None,
    chat: ChatFn | None = None,
    allow_nl_llm: bool = True,
) -> BootstrapResult:
    """除 API Key 外的会话前置：平台/应用/设备/ExecutionContext。"""
    notes: list[str] = []
    hints, nl_notes = resolve_nl_hints(
        request.natural_language,
        platform=request.platform,
        app_name=request.app_label,
        package_name=request.package_name,
        start_url=request.start_url,
        chat=chat,
        allow_llm=allow_nl_llm,
    )
    notes.extend(nl_notes)
    start_url = (request.start_url or hints.start_url or "").strip()
    try:
        plat_raw = resolve_authoring_platform(
            explicit=request.platform,
            hints_platform=hints.platform,
            start_url=start_url,
            inspect_platform=inspect_platform_from_ctx(existing_ctx),
            project_platform=_platform_from_project(
                getattr(request, "project_dir", "") or ""
            ),
        )
    except AuthoringError as exc:
        raise AuthoringError(
            "未能识别平台：请指定 android / ios / web / http，或在描述中写明（Web 可填起始 URL）。"
        ) from exc
    platform = normalize_platform(plat_raw)
    if bool(getattr(request, "use_current_app", False)) and platform not in ("android", "ios"):
        raise AuthoringError("「使用当前前台应用」仅适用于 Android / iOS")
    req = AuthoringRequest(
        natural_language=request.natural_language,
        platform=platform,
        title=request.title,
        max_steps=request.max_steps,
        max_turns=request.max_turns,
        include_screenshot=request.include_screenshot,
        draft_only=request.draft_only,
        mode=request.mode,
        package_name=request.package_name or hints.package_name,
        activity_name=request.activity_name,
        start_url=start_url,
        app_label=request.app_label or hints.app_name,
        input_texts=request.input_texts or hints.input_texts,
        project_dir=getattr(request, "project_dir", "") or "",
        use_current_app=bool(getattr(request, "use_current_app", False)),
    )

    if platform == "web":
        # Web 编写必须从 start_url 建立确定起点，不能继承检视器的任意历史页面。
        ctx = ExecutionContext()
        _apply_web_session_vars(ctx)
        if req.start_url:
            notes.append(f"起始网址：{req.start_url}")
        return BootstrapResult(
            ctx=ctx,
            request=req,
            udid="",
            resolved_app=None,
            notes=notes,
            reused_ctx=False,
        )

    if platform == "http":
        ctx = ExecutionContext()
        proj = str(getattr(req, "project_dir", "") or "").strip()
        if proj:
            ctx.set_var("__project_path__", proj)
        from ..keywords.http.env import apply_job_http_env, resolve_http_env_profile
        from ..runtime import settings as _settings

        profile = _settings.http_env_profile()
        env_res = resolve_http_env_profile(project_dir=proj, profile=profile)
        if env_res.error:
            notes.append(f"API 环境未加载：{env_res.error}")
        apply_job_http_env(
            ctx.variables,
            project_dir=proj,
            profile=profile,
            strict=False,
        )
        notes.append("接口编写不占用设备；环境来自 api_env.yaml 或步骤内切换")
        if req.start_url:
            ctx.set_var("base_url", req.start_url)
            notes.append(f"接口 Base URL：{req.start_url}")
        return BootstrapResult(
            ctx=ctx,
            request=req,
            udid="",
            resolved_app=None,
            notes=notes,
            reused_ctx=False,
        )

    udid = _pick_udid(platform, preferred_udid, pick_device=pick_device)
    notes.append(f"设备：{udid}")

    if req.use_current_app:
        if platform not in ("android", "ios"):
            raise AuthoringError("「使用当前前台应用」仅适用于 Android / iOS")
        app_label = (req.app_label or hints.app_name or "").strip() or "当前应用"
        notes.append("使用当前前台应用（跳过启动与包名解析）")
        req = AuthoringRequest(
            natural_language=req.natural_language,
            platform=req.platform,
            title=req.title,
            max_steps=req.max_steps,
            max_turns=req.max_turns,
            include_screenshot=req.include_screenshot,
            draft_only=req.draft_only,
            mode=req.mode,
            package_name="",
            activity_name="",
            start_url=req.start_url,
            app_label=app_label,
            input_texts=req.input_texts,
            project_dir=req.project_dir,
            use_current_app=True,
        )
        reuse = reusable_ctx(existing_ctx, platform, udid=udid)
        if reuse:
            ctx = existing_ctx
            notes.append("沿用当前已连接的设备会话")
        else:
            ctx = ExecutionContext()
            _apply_mobile_session_vars(
                ctx,
                platform=platform,
                udid=udid,
                package_name="",
                notes=notes,
            )
        if not reuse and platform in ("android", "ios") and ensure_appium is not None:
            try:
                ensure_appium()
            except Exception as exc:  # noqa: BLE001
                notes.append(debug_note(f"Appium 预检：{exc}"))
        return BootstrapResult(
            ctx=ctx,
            request=req,
            udid=udid,
            resolved_app=None,
            notes=notes,
            reused_ctx=reuse,
        )

    app_hint = (req.app_label or hints.app_name or "").strip()
    package = (req.package_name or "").strip()
    resolved: InstalledApp | None = None
    looks_like_id = "." in package and not package.startswith(".")
    if package and looks_like_id:
        try:
            resolved = _resolve_app_with_picker(
                platform,
                udid=udid,
                app_name=app_hint,
                package_name=package,
                pick_app=pick_app,
                chat=chat,
            )
            package = resolved.package_name
            app_label = resolved.app_label or app_hint or package
            notes.append(f"应用：{app_label}")
            notes.append(debug_note(f"已确认安装：{app_label} ({package})"))
        except AuthoringError as exc:
            app_label = app_hint or package
            notes.append(debug_note(f"安装校验跳过：{exc}"))
    elif app_hint or package:
        resolved = _resolve_app_with_picker(
            platform,
            udid=udid,
            app_name=app_hint or package,
            package_name="",
            pick_app=pick_app,
            chat=chat,
        )
        package = resolved.package_name
        app_label = resolved.app_label or app_hint or package
        notes.append(f"应用：{app_label}")
        notes.append(debug_note(f"应用解析：{app_label} → {package}"))
    else:
        raise AuthoringError("未提供应用名/包名，无法自动解析；可勾选「使用当前前台应用」")

    activity = (req.activity_name or "").strip()
    if platform == "android" and not activity and package:
        from .app_resolve import android_launch_activity

        activity = android_launch_activity(package, udid)
        if activity:
            notes.append(debug_note(f"启动 Activity：{activity}"))

    req = AuthoringRequest(
        natural_language=req.natural_language,
        platform=req.platform,
        # 不要拿应用名当用例名：app_label 已单独传递，用例名交给 NL / 模型收尾时决定
        title=req.title,
        max_steps=req.max_steps,
        max_turns=req.max_turns,
        include_screenshot=req.include_screenshot,
        draft_only=req.draft_only,
        mode=req.mode,
        package_name=package,
        activity_name=activity,
        start_url=req.start_url,
        app_label=app_label,
        input_texts=req.input_texts,
        project_dir=req.project_dir,
        use_current_app=False,
    )

    if not req.package_name:
        raise AuthoringError("未能解析目标应用包名/Bundle ID")

    reuse = reusable_ctx(existing_ctx, platform, udid=udid)
    if reuse:
        ctx = existing_ctx
        # 复用会话只补目标应用，caps / server / driver 保持检视器建好的那套
        ctx.set_var("app_package", req.package_name)
        ctx.set_var("packageName", req.package_name)
        notes.append("沿用当前已连接的设备会话")
    else:
        ctx = ExecutionContext()
        _apply_mobile_session_vars(
            ctx,
            platform=platform,
            udid=udid,
            package_name=req.package_name,
            notes=notes,
        )

    if not reuse and platform in ("android", "ios") and ensure_appium is not None:
        try:
            ensure_appium()
        except Exception as exc:  # noqa: BLE001
            notes.append(debug_note(f"Appium 预检：{exc}"))

    return BootstrapResult(
        ctx=ctx,
        request=req,
        udid=udid,
        resolved_app=resolved,
        notes=notes,
        reused_ctx=reuse,
    )


def _apply_web_session_vars(ctx: Any) -> None:
    """Web 会话与 F5 对齐：引擎、浏览器类型和当前平台一并注入。"""
    try:
        from ..runtime import settings

        eng = str(settings.web_engine() or "").strip().lower()
        browser = str(settings.web_browser() or "").strip()
    except (ImportError, AttributeError, OSError, RuntimeError, TypeError, ValueError):
        eng = ""
        browser = ""
    if eng in ("selenium", "playwright"):
        ctx.set_var("__web_engine__", eng)
    if browser:
        ctx.set_var("__web_browser__", browser)
    ctx.set_var("__current_platform__", "web")


def release_authoring_session(
    ctx: Any,
    *,
    reused: bool = False,
) -> list[str]:
    """编写结束后的资源回收。

    - ``reused=True``：会话归检视器/镜像所有，**不**关 driver、不杀 WDA/Appium，
      避免把正在用的检视器打挂。只清编写临时写入的包名变量。
    - ``reused=False``（本轮 AI 编写自己建的会话）：关移动 driver（含 iOS prep）
      与浏览器，释放端口与进程，避免挡住后续 F5 / 检视。共享 Appium 服务进程
      由主窗口管理，这里不动。
    """
    notes: list[str] = []
    if ctx is None:
        return notes
    if reused:
        for key in ("app_package", "packageName"):
            try:
                if hasattr(ctx, "set_var"):
                    ctx.set_var(key, "")
            except (AttributeError, TypeError, RuntimeError):
                pass
        notes.append("复用会话：保留检视器 driver，已清编写临时包名")
        return notes

    # 自建会话：尽力关干净，单点失败不挡后续
    try:
        from ..keywords.mobile.driver import get_manager as get_mobile

        get_mobile(ctx).close()
        notes.append("已关闭移动端 driver")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"移动端回收跳过：{exc}")

    try:
        from ..keywords.web.driver import get_manager as get_web

        get_web(ctx).quit_all()
        notes.append("已关闭浏览器")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"浏览器回收跳过：{exc}")

    return notes
