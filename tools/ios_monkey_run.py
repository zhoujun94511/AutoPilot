#!/usr/bin/env python3
"""iOS Monkey 独立 CLI（参考 Fastmonkey HTTP 启停 / ios_parity_run 结构）。

装包或启动 App 后执行 mobile_monkey iOS 分支，输出报告目录。

示例：
  python tools/ios_monkey_run.py --validate-only
  python tools/ios_monkey_run.py --udid <UDID> --bundle-id com.example.app \\
      --ipa path/to/app.ipa --duration-sec 60 --monkey-steps 50 --backend-mode wda
  python tools/ios_monkey_run.py --udid <UDID> --bundle-id com.example.app \\
      --monkey-steps 100 --monkey-policy safe --throttle-ms 800
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# noinspection PyBroadException
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (OSError, ValueError, UnicodeError):
    pass

from autopilot.runtime.log import get_logger, run_log, setup_logging

log = get_logger("ios_monkey")


def _list_ios() -> list[str]:
    from autopilot.ui.device_monitor import DeviceMonitor
    return DeviceMonitor.list_ios()


def _resolve_udid(explicit: str, project_dir: str = "") -> tuple[str, bool]:
    """解析目标 UDID；多设备时自动认领空闲设备。返回 (udid, need_release)。"""
    from autopilot.runtime.ios_device_lease import acquire_udid

    env_udid = (os.getenv("IOS_MONKEY_UDID") or os.getenv("IOS_PARITY_UDID") or "").strip()
    if (explicit or env_udid).strip():
        return (explicit or env_udid).strip(), False

    devices = _list_ios()
    udid, leased = acquire_udid(
        devices, project_dir or os.getcwd(), always_lease=True,
    )
    if udid:
        if leased:
            log.info("设备自适应: 已认领 UDID=%s", udid)
        return udid, leased

    if len(devices) > 1:
        log.error("多台 iOS 设备均在运行中，暂无空闲设备可认领：")
        for d in devices:
            log.error("  %s", d)
        log.error("可显式指定 --udid 或等待其它 Monkey 进程结束。")
    return "", False


def _apply_ios_parallel_ports(ctx, udid: str) -> None:
    """按 UDID 自动分配 WDA/隧道/MJPEG 端口（多 CLI 并行时避免 8100/28100 冲突）。

    若 ctx 或环境变量已显式指定端口则跳过。
    """
    if ctx.get_var("__wda_local_port__") not in (None, ""):
        return
    if os.getenv("IOS_WDA_LOCAL_PORT", "").strip():
        return

    from autopilot.runtime.port_allocator import assign_ports_for_udid, port_set_to_ctx_vars

    devices = _list_ios()
    ps = assign_ports_for_udid(udid, devices=devices)
    for key, val in port_set_to_ctx_vars(ps).items():
        ctx.set_var(key, val)
    log.info(
        "端口自适应: slot=%s WDA=%s tunnel=%s mjpeg=%s",
        ps.slot, ps.wda_port, ps.tunnel_port, ps.mjpeg_port,
    )


def _latest_report_dir(project_dir: str) -> str:
    root = os.path.join(project_dir, "logs", "ios_monkey")
    if not os.path.isdir(root):
        return ""
    entries = [
        os.path.join(root, name)
        for name in os.listdir(root)
        if os.path.isdir(os.path.join(root, name))
    ]
    if not entries:
        return ""
    return max(entries, key=os.path.getmtime)


def _validate_offline() -> bool:
    from autopilot.mobile.ios.monkey.policy import clamp_duration, clamp_steps
    from autopilot.mobile.ios.monkey.config import build_monkey_config
    from autopilot.keywords.context import ExecutionContext

    assert clamp_steps(10) == 20
    assert clamp_duration(3600) == 3600
    ctx = ExecutionContext()
    cfg = build_monkey_config(
        ctx, "com.test.app", 50,
        durationSec=60, monkeyPolicy="safe", throttleMs=800,
    )
    assert cfg.duration_sec == 60
    assert cfg.policy_preset == "safe"
    return True


def _run_pre_case(ctx, case_path: str, pre_steps: int = 0, pre_skip: int = 0, project_dir: str = "") -> None:
    """在同一 ExecutionContext 上跑前置用例；**不**关闭 mobile 会话。"""
    from autopilot.engine.executor import Executor, FaultStrategy
    from autopilot.engine.keyword_store import discover_keywords
    from autopilot.engine.suite import load_case
    from autopilot.keywords.registry import KeywordError

    path = os.path.abspath(case_path.strip())
    if not os.path.isfile(path):
        raise KeywordError(f"前置用例不存在: {path}")
    tc = load_case(path)
    steps = list(tc.case.steps)
    if pre_skip > 0:
        steps = steps[pre_skip:]
    if pre_steps > 0:
        steps = steps[:pre_steps]
    tc.case.steps = steps
    proj = project_dir or os.path.dirname(path)
    store = discover_keywords(proj)
    rr = Executor(ctx, FaultStrategy.STOP, keyword_store=store).run_testcase(tc)
    if not rr.passed:
        raise KeywordError(f"前置用例失败: {path}")


def _cleanup_cli(
    *,
    udid: str,
    udid_leased: bool,
    proj: str,
    ctx,
    args,
    reg,
) -> None:
    """释放 CLI 占用的 lease；默认关闭 mobile 会话以便并行 CLI 不抢端口。

    ``--no-close`` 时仅释放 lease，保留 WDA/驱动供后续用例或 IDE 复用。
    """
    if udid_leased and udid:
        from autopilot.runtime.ios_device_lease import release_udid
        release_udid(udid, proj)

    if ctx is None or reg is None or args.skip_session:
        return

    if args.no_close:
        log.info("保留 WDA/驱动会话（--no-close），供后续用例复用")
        return

    try:
        reg["mobile_app_close"].func(ctx)
    except (RuntimeError, OSError) as exc:
        log.warning("关闭移动会话失败（忽略）: %s", exc)


def _run_monkey_body(args, proj: str, udid: str) -> int:
    """执行 Monkey 主流程；异常由 main 捕获。"""
    from autopilot.keywords.registry import KeywordError, REGISTRY

    bundle_id = (args.bundle_id or os.getenv("IOS_MONKEY_BUNDLE_ID") or "").strip()
    if not bundle_id and not args.ipa.strip() and not args.skip_session:
        log.error("请指定 --bundle-id 或 --ipa（解析 Bundle ID）")
        return 2

    import autopilot.keywords  # noqa: F401  注册关键字
    from autopilot.keywords.context import ExecutionContext

    ctx = ExecutionContext()
    ctx.set_var("__device_udid__", udid)
    ctx.set_var("__current_platform__", "ios")
    ctx.set_var("__mobile_backend_mode__", args.backend_mode)
    if bundle_id:
        ctx.set_var("app_package", bundle_id)
    ctx.set_var("__project_path__", proj)

    if args.wda_port > 0:
        ctx.set_var("__wda_local_port__", args.wda_port)
    if args.tunnel_port > 0:
        ctx.set_var("__tunnel_info_port__", args.tunnel_port)
    if args.backend_mode in ("auto", "wda", ""):
        _apply_ios_parallel_ports(ctx, udid)

    caps: dict = {}
    if args.wda_bundle:
        caps["wdaBundleId"] = args.wda_bundle
    from autopilot.mobile import ios_bootstrap as ib
    merged = {"__appium_caps__": caps} if caps else {}
    ib.merge_appium_ios_caps(merged, udid, args.wda_bundle, args.backend_mode)
    if merged.get("__appium_caps__"):
        ctx.set_var("__appium_caps__", merged["__appium_caps__"])

    reg = REGISTRY
    try:
        if not args.skip_session:
            if args.ipa.strip():
                log.info("安装并启动: %s", args.ipa)
                reg["mobile_app_install_and_open"].func(
                    ctx,
                    appFile=args.ipa.strip(),
                    type="iOS",
                    udid=udid,
                    backendMode=args.backend_mode,
                )
            else:
                log.info("启动 App: %s", bundle_id)
                reg["mobile_app_start"].func(
                    ctx,
                    type="iOS",
                    packageName=bundle_id,
                    activityName="",
                    udid=udid,
                    backendMode=args.backend_mode,
                )
            if not bundle_id:
                bundle_id = str(ctx.get_var("app_package") or "").strip()
        else:
            from autopilot.keywords.mobile.driver import get_manager
            mgr = get_manager(ctx)
            if mgr.optional_driver() is None:
                raise KeywordError("--skip-session 要求已有 iOS 会话")

        if args.pre_case.strip():
            log.info(
                "前置用例: %s skip=%s steps=%s",
                args.pre_case, args.pre_skip, args.pre_steps or "全部",
            )
            _run_pre_case(ctx, args.pre_case, args.pre_steps, args.pre_skip, proj)

        kw_kwargs: dict = {
            "monkeySteps": str(args.monkey_steps),
        }
        if args.no_device_logs:
            kw_kwargs["collectDeviceLogs"] = "false"
        if args.device_logs_backend:
            kw_kwargs["deviceLogsBackend"] = args.device_logs_backend
        if args.no_report_html:
            kw_kwargs["reportHtml"] = "false"
        if args.syslog_mode:
            kw_kwargs["syslogMode"] = args.syslog_mode
        if args.duration_sec > 0:
            kw_kwargs["durationSec"] = str(args.duration_sec)
        if args.throttle_ms > 0:
            kw_kwargs["throttleMs"] = str(args.throttle_ms)
        if args.monkey_policy:
            kw_kwargs["monkeyPolicy"] = args.monkey_policy
        if args.seed.strip():
            kw_kwargs["seed"] = args.seed.strip()

        log.info(
            "Monkey 开始: udid=%s bundle=%s steps=%s duration=%s backend=%s wda=%s",
            udid, bundle_id or ctx.get_var("app_package"),
            args.monkey_steps, args.duration_sec or "-",
            args.backend_mode, ctx.get_var("__wda_local_port__") or "-",
        )
        reg["mobile_monkey"].func(ctx, **kw_kwargs)
        report_dir = _latest_report_dir(proj)
        if report_dir:
            html_path = os.path.join(report_dir, "report.html")
            log.info("Monkey 完成，报告: %s", report_dir)
            if os.path.isfile(html_path):
                log.info("HTML: %s", html_path)
        else:
            log.info("Monkey 完成，详见 logs/ios_monkey/")
        return 0
    finally:
        _cleanup_cli(
            udid=udid, udid_leased=False, proj=proj,
            ctx=ctx, args=args, reg=reg,
        )


def main() -> int:
    ap = argparse.ArgumentParser(description="iOS Monkey 独立运行器（WDA-direct / Appium iOS）")
    ap.add_argument("--validate-only", action="store_true", help="离线校验参数与配置解析")
    ap.add_argument("--udid", default="", help="目标 iOS 设备 UDID")
    ap.add_argument("--bundle-id", default="", help="被测 App Bundle ID")
    ap.add_argument("--ipa", default="", help="可选：安装并启动 IPA 后再 Monkey")
    ap.add_argument("--project", default="", help="工程目录（写入 __project_path__ 与报告路径）")
    ap.add_argument("--wda-bundle", default="", help="WDA Runner Bundle ID（可选）")
    ap.add_argument("--backend-mode", default="auto", choices=["auto", "appium", "wda"])
    ap.add_argument("--monkey-steps", type=int, default=50, help="事件数 20~200")
    ap.add_argument("--duration-sec", type=int, default=0, help=">0 按时长跑（秒），最长 6h")
    ap.add_argument("--throttle-ms", type=int, default=0, help="事件间隔毫秒（0=settings 默认）")
    ap.add_argument("--monkey-policy", default="", choices=["", "safe", "balanced", "aggressive"])
    ap.add_argument("--seed", default="", help="随机种子（整数）")
    ap.add_argument("--skip-session", action="store_true",
                    help="跳过装包/启动（要求外部已建立 iOS 会话，仅调试用）")
    ap.add_argument("--no-close", action="store_true",
                    help="结束后不关闭 WDA/驱动（供后续用例复用；仍释放 UDID lease）")
    ap.add_argument("--no-device-logs", action="store_true", help="不采集设备 syslog/crash")
    ap.add_argument("--device-logs-backend", default="", choices=["", "auto", "go-ios", "pmd3"],
                    help="设备日志后端（默认 settings auto）")
    ap.add_argument("--no-report-html", action="store_true", help="不生成 report.html")
    ap.add_argument("--pre-case", default="", help="Monkey 前执行的 .tc.yaml（共用当前会话）")
    ap.add_argument("--pre-steps", type=int, default=0, help="前置用例 case 段最多 N 步（0=全部）")
    ap.add_argument("--pre-skip", type=int, default=0, help="前置用例 case 段跳过前 N 步")
    ap.add_argument("--syslog-mode", default="", choices=["", "full", "ostrace"],
                    help="设备日志模式：full 全量 syslog / ostrace 按进程过滤（go-ios）")
    ap.add_argument("--wda-port", type=int, default=0, help="强制 WDA 本机端口（默认自动分配）")
    ap.add_argument("--tunnel-port", type=int, default=0, help="强制 go-ios 隧道 info 端口（默认自动）")
    ap.add_argument("-v", "--verbose", action="store_true", help="DEBUG 级别日志")
    args = ap.parse_args()

    if args.validate_only:
        setup_logging()
        ok = _validate_offline()
        log.info("ios_monkey_run 离线校验: %s", "OK" if ok else "FAIL")
        return 0 if ok else 1

    proj = (args.project or os.getcwd()).strip()
    log_dir = os.path.join(proj, "logs")
    setup_logging(
        level=logging.DEBUG if args.verbose else logging.INFO,
        directory=log_dir,
    )

    udid, udid_leased = _resolve_udid(args.udid, proj)
    if udid_leased and udid:
        from autopilot.runtime.ios_device_lease import register_release_on_exit
        register_release_on_exit(udid, proj)

    exit_code = 1
    from autopilot.keywords.registry import KeywordError

    with run_log("ios_monkey"):
        try:
            if not udid:
                log.error("未找到可用 iOS 设备")
                exit_code = 2
            else:
                exit_code = _run_monkey_body(args, proj, udid)
        except KeyboardInterrupt:
            log.warning("已中断，正在释放资源…")
            exit_code = 130
        except (RuntimeError, KeywordError):
            log.exception("运行失败")
            exit_code = 1
        finally:
            if udid_leased and udid:
                from autopilot.runtime.ios_device_lease import release_udid
                release_udid(udid, proj)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
