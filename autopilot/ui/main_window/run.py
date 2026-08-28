"""主窗口·运行/调度 Mixin：异步执行、运行选中、批量套件、停止、本地计划执行。

混入 MainWindow（依赖其 self.console/case_editor/_worker/_fault_strategy/cmb_fault/
act_stop/project_dir/_current_case_editor 等属性）。拆出以控制 main_window 体量、便于迭代。
"""

from __future__ import annotations

import copy
import datetime
import os
import shutil

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox

from ..confirm import confirm
from ..runner import ExecutionWorker
from ..widgets.list_pick_dialog import pick_list_item
from .device_readiness import DeviceLists, auto_run_udid, missing_runtime_platforms
from .device_select import friendly_pick_labels
from ...engine.keyword_store import discover_keywords as _disc
from ...engine.scheduler import first_delay_ms, interval_ms, should_continue
from ...engine.suite import (
    discover_cases,
    discover_maps,
    expand_testplan_members,
    load_case,
    load_map,
)
from ...metadata.case_platform_lint import lint_testcase
from ...model import loader, serializer
from ...model.testcase import TestCase
from ...model.testplan import TestPlan
from ...runtime import settings
from ...keywords.registry import KeywordError


# 仅供静态检查解析 self.* —— 运行时 Mixin 实际由 MainWindow 组合，这里"继承"只在类型检查时生效（运行时为 object，无循环依赖）。
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .window import MainWindow
    from ...engine.scheduler import Schedule
    _Base = MainWindow
else:
    _Base = object


class RunMixin(_Base):
    # 下列实例属性由 MainWindow.__init__ 拥有；此处仅注解声明以满足静态检查
    _schedule: Schedule | None
    _schedule_runs: int
    _schedule_last_passed: bool | None
    _schedule_gen: int
    _schedule_owned_run: bool

    # ---- 异步执行 ----
    def run_current_case(self) -> None:
        tc = self.case_editor.case
        if tc is None:
            self.console.log("没有打开的用例，请先在编辑器中打开或新建", "运行", "WARNING")
            return
        if self._worker is not None and self._worker.isRunning():
            self.console.log("已有执行进行中，请先停止当前执行", "运行", "WARNING")
            return
        if not self._platform_guard([tc]):
            return
        self.console.log(f"开始执行用例：{tc.name}（失败策略：{self._fault_strategy.value}）",
                         "运行")
        # 单用例调试（F5）生成 HTML 报告，便于本地调试后查看结果
        self._start_worker([tc], tc.name, self._project_maps(), report=True,
                           allow_parallel=False)

    def run_suite(self, *, allow_parallel: bool = True, unattended: bool = False) -> bool:
        """批量执行当前工程目录下所有用例（异步），完成后生成 HTML 报告。

        返回 True 表示已启动 worker；False 表示前置条件未满足（无工程/无用例/校验拦截等）。
        计划执行走 ``allow_parallel=False, unattended=True``：禁并行弹窗，且多设备/
        混合平台等交互确认一律自动拒绝，避免无人值守被对话框卡住。
        """
        if not self.project_dir or not os.path.isdir(self.project_dir):
            self.console.log("没有有效的工程目录", "运行", "WARNING")
            return False
        if self._worker is not None and self._worker.isRunning():
            self.console.log("已有执行进行中，请先停止当前执行", "运行", "WARNING")
            return False
        cases = [load_case(p) for p in discover_cases(self.project_dir)]
        maps = [load_map(p) for p in discover_maps(self.project_dir)]
        if not cases:
            self.console.log("工程目录下没有用例", "运行", "WARNING")
            return False
        if not self._platform_guard(cases, unattended=unattended):
            return False
        self.console.log(f"开始批量执行：{self.project_dir}（共 {len(cases)} 个用例）", "运行")
        name = os.path.basename(self.project_dir.rstrip("/\\")) or "Suite"
        return self._start_worker(
            cases, name, maps, report=True,
            keyword_store=_disc(self.project_dir),
            allow_parallel=allow_parallel,
            unattended=unattended,
        )

    def run_current_testplan(self) -> bool:
        """运行当前打开的测试计划（或工程树选中的 .tp），消费 fault_times。"""

        if self._worker is not None and self._worker.isRunning():
            self.console.log("已有执行进行中，请先停止当前执行", "运行", "WARNING")
            return False
        if not self.project_dir or not os.path.isdir(self.project_dir):
            self.console.log("没有有效的工程目录", "运行", "WARNING")
            return False

        tp = None
        # 优先：当前中心页是测试计划编辑器
        if self.center.currentWidget() is getattr(self, "testplan_editor", None):
            tp = getattr(self.testplan_editor, "testplan", None)
        # 其次：工程树选中 .tp / .tp.yaml
        if tp is None:
            # noinspection PyBroadException
            try:
                path = (self.project_tree.selected_path()
                        if hasattr(self, "project_tree") else "") or ""
            except Exception:
                path = ""
            if path.endswith(".tp") or path.endswith(".tp.yaml") or path.endswith(".tp.yml"):
                # noinspection PyBroadException
                try:
                    tp = (serializer.load(path) if path.endswith((".yaml", ".yml"))
                          else loader.load_testplan(path))
                except Exception as e:  # noqa: BLE001
                    self.console.log(f"加载测试计划失败：{e}", "运行", "ERROR")
                    return False
        if not isinstance(tp, TestPlan):
            self.console.log("请先打开或选中一个测试计划（.tp）", "运行", "WARNING")
            return False
        if not tp.members:
            self.console.log("测试计划没有成员用例/套件", "运行", "WARNING")
            return False
        # noinspection PyBroadException
        try:
            cases = expand_testplan_members(tp, self.project_dir)
        except Exception as e:  # noqa: BLE001
            self.console.log(f"展开测试计划成员失败：{e}", "运行", "ERROR")
            return False
        if not cases:
            self.console.log("测试计划展开后没有可执行用例", "运行", "WARNING")
            return False
        if not self._platform_guard(cases):
            return False
        maps = [load_map(p) for p in discover_maps(self.project_dir)]
        name = tp.name or "TestPlan"
        ft = int(tp.fault_times or 0)
        self.console.log(
            f"开始执行测试计划：{name}（{len(cases)} 用例，失败重试 {ft}）", "运行")
        return self._start_worker(
            cases, name, maps, report=True,
            keyword_store=_disc(self.project_dir),
            allow_parallel=True,
            fault_times=ft,
        )

    def run_checked(self, paths) -> None:
        """运行工程树中勾选的用例（对标参考实现的运行选中），完成后生成 HTML 报告。"""
        paths = [p for p in (paths or []) if os.path.isfile(p)]
        if not paths:
            self.console.log("没有勾选任何用例", "运行", "WARNING")
            return
        if self._worker is not None and self._worker.isRunning():
            self.console.log("已有执行进行中，请先停止当前执行", "运行", "WARNING")
            return
        cases = [load_case(p) for p in paths]
        if not self._platform_guard(cases):
            return
        self.console.log(f"批量运行：共 {len(cases)} 个勾选用例", "运行")
        ks = _disc(self.project_dir) if (self.project_dir and os.path.isdir(self.project_dir)) else None
        self._start_worker(cases, "选中用例", self._project_maps(), report=True, keyword_store=ks)

    def run_checked_from_menu(self) -> None:
        """菜单「批量运行已勾选」：读取工程树当前勾选集。"""
        tree = getattr(self, "project_tree", None)
        paths = tree.checked_paths() if tree is not None else []
        self.run_checked(paths)

    def _platform_guard(self, cases, *, unattended: bool = False) -> bool:
        """执行前平台校验：用例标记了 android/ios 但未连对应设备 → 拦截。
        未标平台或对应设备已连 → 放行。返回 True 表示可继续执行。
        unattended=True（计划拍）：混合平台不弹确认，直接中止。"""
        default = settings.project_platform(getattr(self, "project_dir", ""))   # 工程默认，省得每条标
        need = self._target_platforms(cases, default)
        mixed = self._mixed_platform_cases(cases)
        if mixed:
            names = "、".join(getattr(c, "name", "") or "未命名用例" for c in mixed[:5])
            more = f" 等 {len(mixed)} 个用例" if len(mixed) > 5 else ""
            if unattended:
                self.console.log(
                    f"计划执行中止：检测到 {names}{more} 同时包含 Android 和 iOS 步骤"
                    "（无人值守不弹确认）", "计划", "WARNING")
                return False
            if not confirm(
                    self, "单用例混合平台",
                    f"检测到 {names}{more} 同时包含 Android 和 iOS 步骤。"
                    "单个用例只有一个当前移动会话，后续点击/滑动会作用在最近创建的会话上，"
                    "建议拆分到不同用例、用例组或工程后再运行。仍要继续吗？",
                    danger=True, yes_text="仍要执行", no_text="取消"):
                self.console.log("已取消执行：单个用例同时包含 Android 和 iOS 步骤，建议拆分后运行",
                                 "运行", "WARNING")
                return False
            self.console.log("已强制执行：检测到单用例混合 Android/iOS，后续移动操作将作用在最近创建的会话",
                             "运行", "WARNING")
        if not need:
            return True

        devices = DeviceLists.from_lists(*getattr(self, "_devices", ([], []))[:2])
        missing = missing_runtime_platforms(need, devices)
        if not missing:
            return True
        label = "、".join({"android": "Android", "ios": "iOS"}[m] for m in sorted(missing))
        self.console.log(f"已取消执行：用例平台「{label}」无匹配设备", "运行", "WARNING")
        return False

    def _project_maps(self):
        if not (self.project_dir and os.path.isdir(self.project_dir)):
            return []
        return [load_map(p) for p in discover_maps(self.project_dir)]

    def _target_platforms(self, cases, default: str = "") -> set[str]:
        platforms: set[str] = set()
        for case in cases:
            platforms.update(self._case_target_platforms(case, default))
        return platforms

    def _case_target_platforms(self, case, default: str = "") -> set[str]:
        case_platform = (getattr(case, "platform", "") or "").lower()
        if case_platform in ("android", "ios", "web", "http"):
            return {case_platform}
        inferred = self._infer_mobile_platforms(case)
        if inferred:
            return inferred
        if self._infer_web_platform(case):
            return {"web"}
        if self._infer_http_platform(case):
            return {"http"}
        return {default} if default in ("android", "ios", "web", "http") else set()

    def _mixed_platform_cases(self, cases) -> list:
        return [case for case in cases if len(self._infer_mobile_platforms(case)) > 1]

    @staticmethod
    def _infer_mobile_platforms(case) -> set[str]:
        inferred: set[str] = set()

        def visit(nodes) -> None:
            for node in nodes or []:
                keyword_id = getattr(node, "keyword_id", "")
                params = {getattr(p, "param_id", ""): str(getattr(p, "value", "") or "")
                          for p in getattr(node, "params", [])}
                typ = (params.get("type") or params.get("platform") or "").strip().lower()
                app_file = (params.get("appFile") or params.get("app") or "").strip().lower()
                if typ in ("android", "ios"):
                    inferred.add(typ)
                elif app_file.endswith((".apk", ".apex", ".xapk")):
                    inferred.add("android")
                elif app_file.endswith(".ipa"):
                    inferred.add("ios")
                elif keyword_id == "mobile_browser_open":
                    inferred.add("android")
                visit(getattr(node, "children", []))

        for shell in getattr(case, "shells", []):
            visit(getattr(shell, "steps", []))
        return inferred

    @staticmethod
    def _infer_web_platform(case) -> bool:
        def visit(nodes) -> bool:
            for node in nodes or []:
                keyword_id = str(getattr(node, "keyword_id", "") or "").lower()
                if keyword_id.startswith("web_") or keyword_id.startswith("browser_"):
                    return True
                if visit(getattr(node, "children", [])):
                    return True
            return False

        for shell in getattr(case, "shells", []):
            if visit(getattr(shell, "steps", [])):
                return True
        return False

    @staticmethod
    def _infer_http_platform(case) -> bool:
        def visit(nodes) -> bool:
            for node in nodes or []:
                keyword_id = str(getattr(node, "keyword_id", "") or "").lower()
                if (
                    keyword_id.startswith("http_")
                    or keyword_id.startswith("json_")
                    or keyword_id.startswith("xml_")
                    or keyword_id == "api_env_use"
                ):
                    return True
                if visit(getattr(node, "children", [])):
                    return True
            return False

        for shell in getattr(case, "shells", []):
            if visit(getattr(shell, "steps", [])):
                return True
        return False

    def _run_base_vars(self, cases, *, unattended: bool = False,
                       skip_device_pick: bool = False) -> dict | None:
        """Runtime variables injected into every testcase context.

        unattended=True（计划拍）：多台设备无法自动选定时直接中止，不弹选设备框。
        skip_device_pick=True（并行拍）：不弹选设备；多机时不写单机 __device_udid__
        （各 shard 自行注入），仅校验目标平台有设备。
        """

        base: dict = {}
        # 相对 picture:: / 截图落盘等依赖工程根；CLI run_directory 已注入，GUI 须对齐
        proj = getattr(self, "project_dir", "") or ""
        if proj and os.path.isdir(proj):
            base["__project_path__"] = proj
        default = settings.project_platform(proj)
        platforms = self._target_platforms(cases, default)
        devices = DeviceLists.from_lists(*getattr(self, "_devices", ([], []))[:2])
        inspect_plat = getattr(self, "_inspect_platform", "") or ""
        inspect_udid = getattr(self, "_inspect_udid", "") or ""

        selections: dict[str, str] = {}
        plat_labels = {"android": "Android", "ios": "iOS"}
        for platform in sorted(platforms):
            avail = devices.for_platform(platform)
            if platform in ("android", "ios") and not avail:
                label = plat_labels.get(platform, platform)
                self.console.log(
                    f"已取消执行：用例需要 {label} 设备，当前未连接", "运行", "WARNING")
                return None
            if skip_device_pick:
                # 并行：设备列表由并行对话框决定，此处只校验有机，不选单机
                continue
            udid = auto_run_udid(
                platform, devices,
                inspect_platform=inspect_plat, inspect_udid=inspect_udid)
            if avail and not udid:
                if unattended:
                    label = plat_labels.get(platform, platform)
                    self.console.log(
                        f"计划执行中止：{label} 有多台设备且无法自动选定"
                        "（无人值守不弹选设备）", "计划", "WARNING")
                    return None
                title = "选择运行设备"
                prompt = "Android 运行目标：" if platform == "android" else "iOS 运行目标："
                default_idx = avail.index(inspect_udid) if inspect_udid in avail else 0
                choice, ok = pick_list_item(
                    self,
                    title,
                    prompt,
                    friendly_pick_labels(platform, list(avail)),
                    default_idx,
                    values=list(avail),
                )
                udid = choice if ok and choice else None
            if avail and not udid:
                self.console.log("已取消执行：未选择运行设备", "运行", "WARNING")
                return None
            if udid:
                selections[platform] = udid

        if selections:
            labels = {"android": "Android", "ios": "iOS"}
            summary = "，".join(f"{labels.get(p, p)} {u}" for p, u in sorted(selections.items()))
            self.console.log(f"运行设备：{summary}", "运行")

        if len(selections) == 1:
            base["__device_udid__"] = next(iter(selections.values()))
        elif selections:
            base["__device_udid_by_platform__"] = selections
            case_platforms: dict[str, str] = {}
            for case in cases:
                targets = self._case_target_platforms(case, default)
                if len(targets) == 1:
                    platform = next(iter(targets))
                    if getattr(case, "source_path", ""):
                        case_platforms[getattr(case, "source_path")] = platform
                    case_platforms[getattr(case, "name", "")] = platform
            base["__case_platforms__"] = case_platforms
        if default in ("android", "ios", "web", "http"):
            base["__default_platform__"] = default
        if "android" in platforms or "ios" in platforms:
            base["__mobile_backend_mode__"] = getattr(self, "_ios_backend_mode", "auto") or "auto"
        if "web" in platforms:
            eng = getattr(self, "_web_engine", None) or settings.web_engine()
            if eng in ("selenium", "playwright"):
                base["__web_engine__"] = eng
            br = getattr(self, "_inspect_browser", "") or settings.web_browser()
            if br in ("chrome", "edge", "firefox", "headless"):
                base["__web_browser__"] = br
        if "http" in platforms:
            from ...keywords.http.env import apply_job_http_env  # 延迟：仅 HTTP 作业

            profile = getattr(self, "_http_env_profile", None)
            if profile is None:
                profile = settings.http_env_profile()
            try:
                apply_job_http_env(base, project_dir=proj, profile=str(profile or ""))
            except KeywordError as env_err:
                self.console.log(str(env_err), "运行", "ERROR")
                return None
        if "ios" in selections:
            wda = getattr(self, "_inspect_wda", "")
            if wda:
                base["__appium_caps__"] = {"wdaBundleId": wda}
        return base

    def _resolve_parallel_run(
        self, cases,
    ) -> tuple[str, str, int, list[str] | None, bool] | None:
        """返回 (run_mode, platform, workers, device_udids, fault_isolation) 或 None 取消。

        设备不足 2 台时静默串行；≥2 台弹窗。
        并行语义：每台设备完整跑本次全部用例（N 条 × M 台）。
        fault_isolation 默认 True（某台失败不杀其它）。
        """
        default = settings.project_platform(getattr(self, "project_dir", ""))
        platforms = self._target_platforms(cases, default)
        if len(platforms) != 1:
            return "sequential", "", 0, None, True
        plat = next(iter(platforms))

        avail = DeviceLists.from_lists(*getattr(self, "_devices", ([], []))[:2]).for_platform(plat)
        n_cases = len(cases or [])
        if len(avail) < 2:
            return "sequential", "", 0, None, True
        from ..parallel_run_dialog import ask_parallel_run  # 延迟：仅并行确认
        choice = ask_parallel_run(self, plat, len(avail), case_count=n_cases)
        if choice is None:
            return None
        parallel, workers, isolate = choice
        if not parallel:
            return "sequential", "", 0, None, True
        if not avail:
            self.console.log(
                f"已取消并行：{plat} 设备列表为空（可能已断开）", "运行", "WARNING")
            return None
        n = workers if workers > 0 else len(avail)
        n = min(n, len(avail))
        if n < 2:
            self.console.log(
                f"并行设备不足 2 台，改为串行（当前 {len(avail)} 台）", "运行", "WARNING")
            return "sequential", "", 0, None, True
        udids = avail[:n]
        self.console.log(
            f"并行执行：每台跑 {n_cases} 条 × {plat} {len(udids)} 台"
            f"（合计 {n_cases * len(udids)} 次；{', '.join(udids)}；"
            f"失败隔离：{'开' if isolate else '关'}）", "运行")
        return "parallel_device", plat, n, udids, bool(isolate)

    def _warn_cases_platform_lint(self, cases) -> None:
        default = settings.project_platform(getattr(self, "project_dir", "")) or ""
        maps = self._project_maps()
        ios_bm = getattr(self, "_ios_backend_mode", "auto") or "auto"
        seen: set[tuple[str, str, str, str, str]] = set()
        for tc in cases:
            path = getattr(tc, "source_path", "") or tc.name or ""
            for iss in lint_testcase(
                tc, self.catalog, default_platform=default, maps=maps,
                ios_backend_mode=ios_bm if ios_bm in ("wda", "appium") else "",
            ):
                key = (path, iss.shell, iss.keyword_id, iss.param_id, iss.issue_type)
                if key in seen:
                    continue
                seen.add(key)
                label = iss.comment or iss.keyword_id
                where = f"{path} " if path else ""
                if iss.issue_type in ("locator", "map") and iss.param_id:
                    self.console.log(
                        f"平台校验 {where}[{iss.shell}] {label} 参数 {iss.param_id}：{iss.reason}",
                        "运行",
                        "WARNING",
                    )
                else:
                    self.console.log(
                        f"平台校验 {where}[{iss.shell}] {label} ({iss.keyword_id})：{iss.reason}",
                        "运行",
                        "WARNING",
                    )

    def _start_worker(self, cases, name, maps, report: bool, keyword_store=None, *,
                      allow_parallel: bool = True, unattended: bool = False,
                      fault_times: int = 0) -> bool:
        # 先解析并行：若走多机，跳过「单机选设备」弹窗（设备列表由并行对话框决定）
        run_mode, platform, workers, udids = "sequential", "", 0, None
        fault_isolation = True
        self._parallel_running = False
        if allow_parallel:
            resolved = self._resolve_parallel_run(cases)
            if resolved is None:
                self.console.log("已取消执行", "运行", "WARNING")
                return False
            run_mode, platform, workers, udids, fault_isolation = resolved
            self._parallel_running = run_mode == "parallel_device"
        # 并行拍：不弹单机选设备；串行拍仍走原选机逻辑
        skip_device_pick = run_mode == "parallel_device"
        base_vars = self._run_base_vars(
            cases, unattended=unattended, skip_device_pick=skip_device_pick)
        if base_vars is None:
            self._parallel_running = False
            return False
        if run_mode == "parallel_device" and udids:
            # 报告元数据用全部并行设备；单机 __device_udid__ 由各 shard 覆盖
            base_vars["__parallel_device_udids__"] = list(udids)
            base_vars["__parallel_platform__"] = platform
            base_vars.pop("__device_udid__", None)
            base_vars.pop("__appium_caps__", None)
        self._warn_cases_platform_lint(cases)
        wda = getattr(self, "_inspect_wda", "") if platform == "ios" else ""
        self._run_step_count = 0
        self._run_paused = False
        self._set_pause_indicator(False)
        self._report_on_finish = report
        self._run_started_at = datetime.datetime.now()
        self._run_case_paths = [getattr(c, "source_path", "") or "" for c in cases]
        self._run_case_total = len(cases)
        self._run_case_done = 0
        # 计划拍归属：仅本 worker 的 suiteDone 才推进计划计数（避免手动跑干扰计划）
        self._schedule_owned_run = bool(unattended and self._schedule is not None)
        bar = getattr(self, "_sb_progress", None)
        # 并行复跑：进度分母 = 用例数 × 设备数（与 caseDone 触发次数对齐）
        progress_total = len(cases)
        if run_mode == "parallel_device" and workers and workers >= 2:
            progress_total = len(cases) * int(workers)
        self._run_case_total = progress_total
        if bar is not None and hasattr(bar, "begin"):
            bar.begin(progress_total)
        elif bar is not None:
            if progress_total > 1:
                bar.setRange(0, progress_total)
                bar.setValue(0)
                bar.setFormat("用例 %v/%m")
            else:
                bar.setRange(0, 0)
                bar.setFormat("执行中…")
            bar.setVisible(True)
        self._worker = ExecutionWorker(
            cases, name=name, fault_strategy=self._fault_strategy,
            base_vars=base_vars,
            maps=maps, keyword_store=keyword_store,
            run_mode=run_mode, platform=platform,
            parallel_workers=workers, device_udids=udids,
            wda_bundle=wda,
            backend_mode=getattr(self, "_ios_backend_mode", "auto") or "auto",
            parallel_fault_isolation=fault_isolation,
            fault_times=int(fault_times or 0),
            parent=self)
        # noinspection PyUnresolvedReferences
        self._worker.stepDone.connect(self._on_step_done)
        # noinspection PyUnresolvedReferences
        self._worker.caseDone.connect(self._on_case_done)
        # noinspection PyUnresolvedReferences
        self._worker.suiteDone.connect(self._on_suite_done)
        self.act_stop.setEnabled(True)
        self.act_pause.setChecked(False)
        self.act_pause.setText("暂停")
        self.act_pause.setEnabled(True)
        self._refresh_run_control_tips(idle=False)
        self._worker.start()
        return True

    def _on_fault_changed(self, _idx: int) -> None:
        self._fault_strategy = self.cmb_fault.currentData()
        self.console.log(f"失败策略已切换：{self._fault_strategy.value}", "运行")

    def _on_ios_backend_changed(self, _idx: int) -> None:
        mode = str(self.cmb_ios_backend.currentData() or "auto")
        self._ios_backend_mode = mode
        settings.set_ios_backend_mode(mode)
        if hasattr(self, "_sync_keyword_editor_platform"):
            self._sync_keyword_editor_platform()
        if getattr(self, "_inspect_platform", "") == "iOS" and getattr(self, "_inspect_ctx", None) is not None:
            self._reset_inspect_session()
            self.console.log("iOS 后端已切换，检视会话已重置", "检视")
        if hasattr(self, "_refresh_open_case_platform_ui"):
            self._refresh_open_case_platform_ui()
        self.console.log(f"iOS 后端模式：{mode}", "运行")

    def _on_web_engine_changed(self, _idx: int) -> None:
        eng = str(self.cmb_web_engine.currentData() or "selenium")
        if eng not in ("selenium", "playwright"):
            eng = "selenium"
        self._web_engine = eng
        settings.set_web_engine(eng)
        if getattr(self, "_inspect_platform", "") == "Web" and getattr(self, "_inspect_ctx", None) is not None:
            self._reset_inspect_session()
            self.console.log("Web 引擎已切换，检视会话已重置", "检视")
        self.console.log(f"Web 引擎：{eng}", "运行")

    def _on_http_env_changed(self, profile: str) -> None:
        name = str(profile or "").strip()
        if name.lower() in ("用例内切换", "auto"):
            name = ""
        self._http_env_profile = name
        settings.set_http_env_profile(name)
        self.console.log(f"API 环境：{name or '用例内切换'}", "运行")

    def run_selected_step(self) -> None:
        """只运行当前选中的步骤（含其子步骤/循环体），便于调试单步。"""
        editor = self._current_case_editor()
        if editor is None or editor.case is None:
            self.console.log("请先在用例/套件编辑器中选中一个步骤", "运行", "WARNING")
            return
        node = editor.selected_node()
        if node is None:
            self.console.log("请先选中一个步骤", "运行", "WARNING")
            return
        if self._worker is not None and self._worker.isRunning():
            self.console.log("已有执行进行中，请先停止当前执行", "运行", "WARNING")
            return
        if getattr(self, "_parallel_running", False):
            self.console.log("并行执行进行中，单步调试已禁用", "运行", "WARNING")
            return
        tc = TestCase(name=f"{editor.case.name}::选中步骤")
        tc.source_path = editor.case.source_path  # 继承目录：用于 .ks 发现与内嵌相对路径
        tc.case.steps = [copy.deepcopy(node)]
        if not self._platform_guard([tc]):
            return
        self.console.log(f"运行当前步骤（失败策略：{self._fault_strategy.value}）", "运行")
        self._start_worker([tc], tc.name, self._project_maps(), report=False, allow_parallel=False)

    def run_to_selected_step(self) -> None:
        """运行至此：从 case 主体首步跑到「选中步骤所属顶层步骤」(含前置)，便于定位失败前一步。"""
        editor = self._current_case_editor()
        if editor is None or editor.case is None:
            self.console.log("请先在用例编辑器中选中一个步骤", "运行", "WARNING")
            return
        prefix = editor.case_prefix_to_selected()
        if not prefix:
            self.console.log("请在用例「主体」中选中一个步骤（运行至此仅作用于主体）", "运行", "WARNING")
            return
        if self._worker is not None and self._worker.isRunning():
            self.console.log("已有执行进行中，请先停止当前执行", "运行", "WARNING")
            return
        tc = TestCase(name=f"{editor.case.name}::运行至此")
        tc.source_path = editor.case.source_path
        tc.before.steps = copy.deepcopy(editor.case.before.steps)   # 前置照跑
        tc.case.steps = [copy.deepcopy(n) for n in prefix]
        # 列出实际会跑的关键字 id，避免「以为选中了第 N 步、实际停在上一行」的误解
        ids = [getattr(n, "keyword_id", None) or getattr(n, "name", type(n).__name__)
               for n in prefix]
        self.console.log(
            f"运行至此（{len(prefix)} 步，止于「{ids[-1]}」，失败策略：{self._fault_strategy.value}）"
            f"：{' → '.join(ids)}",
            "运行")
        if not self._platform_guard([tc]):
            return
        self._start_worker([tc], tc.name, self._project_maps(), report=False, allow_parallel=False)

    def _set_pause_indicator(self, visible: bool) -> None:
        self._run_paused = visible
        lab = getattr(self, "_sb_pause", None)
        if lab is not None and hasattr(lab, "set_paused"):
            lab.set_paused(visible)
        elif lab is not None:
            lab.setVisible(visible)

    def toggle_pause_run(self, paused: bool) -> None:
        """暂停/继续当前执行（步骤边界协作式挂起）。"""
        if self._worker is None or not self._worker.isRunning():
            self.act_pause.setChecked(False)
            self.act_pause.setText("暂停")
            self._set_pause_indicator(False)
            return
        if paused:
            self._worker.request_pause()
            self.act_pause.setText("继续")
            self.console.log("已暂停执行（当前步骤完成后挂起）", "运行", "WARNING")
            self._set_pause_indicator(True)
        else:
            self._worker.request_resume()
            self.act_pause.setText("暂停")
            self.console.log("已恢复执行", "运行")
            self._set_pause_indicator(False)
            self.statusBar().showMessage(
                f"执行中… 已完成 {getattr(self, '_run_step_count', 0)} 步")

    def stop_run(self) -> None:
        self.stop_schedule()
        if self._worker is not None and self._worker.isRunning():
            self._worker.request_stop()
            self._set_pause_indicator(False)
            self.act_pause.blockSignals(True)
            self.act_pause.setChecked(False)
            self.act_pause.setText("暂停")
            self.act_pause.blockSignals(False)
            self.console.log("已请求停止，将在当前步骤结束后中断", "运行", "WARNING")

    # ---- 本地执行调度 ----
    def schedule_dialog(self) -> None:

        from ..scheduler_input import ask_schedule  # 轻量对话框封装

        if not (self.project_dir and os.path.isdir(self.project_dir)):
            QMessageBox.information(self, "计划执行", "请先打开工程。")
            return
        sch = ask_schedule(self)
        if sch is not None:
            self.start_schedule(sch)

    def start_schedule(self, schedule) -> None:
        if not (self.project_dir and os.path.isdir(self.project_dir)):
            self.console.log("没有有效的工程目录，无法计划执行", "计划", "WARNING")
            return
        if not getattr(schedule, "is_valid", lambda: True)():
            self.console.log("计划参数无效（延迟/间隔/次数须 ≥ 0）", "计划", "WARNING")
            return
        # 新计划作废旧定时器（含「停止后再排」与「覆盖重排」）
        self._schedule_gen = int(getattr(self, "_schedule_gen", 0)) + 1
        gen = self._schedule_gen
        self._schedule = schedule
        self._schedule_runs = 0
        self._schedule_last_passed = None
        self._schedule_owned_run = False
        self.console.log(
            f"已计划执行：延迟 {schedule.delay_sec}s、间隔 {schedule.interval_sec}s、"
            f"次数 {schedule.repeat or '不限'}、失败即停："
            f"{'是' if schedule.stop_on_fail else '否'}", "计划")
        # 等待期也允许「停止」取消计划（否则 delay 很长时无法从工具栏中止）
        self.act_stop.setEnabled(True)
        self._refresh_run_control_tips(idle=False)
        self.statusBar().showMessage(
            f"计划等待中… 首次延迟 {schedule.delay_sec}s")
        QTimer.singleShot(first_delay_ms(schedule), lambda g=gen: self._schedule_tick(g))

    def stop_schedule(self) -> None:
        if self._schedule is not None:
            self.console.log("已取消计划执行", "计划", "WARNING")
        self._schedule = None
        self._schedule_owned_run = False
        self._schedule_gen = int(getattr(self, "_schedule_gen", 0)) + 1
        # 若无 worker 在跑，恢复停止按钮为闲置态
        if self._worker is None or not self._worker.isRunning():
            self.act_stop.setEnabled(False)
            self._refresh_run_control_tips(idle=True)

    def _schedule_tick(self, gen: int | None = None) -> None:
        if gen is not None and gen != getattr(self, "_schedule_gen", 0):
            return   # 已取消或已被新计划覆盖
        if self._schedule is None:
            return
        if not should_continue(self._schedule, self._schedule_runs, self._schedule_last_passed):
            self.console.log("计划执行结束", "计划")
            self._schedule = None
            self._schedule_owned_run = False
            if self._worker is None or not self._worker.isRunning():
                self.act_stop.setEnabled(False)
                self._refresh_run_control_tips(idle=True)
            return
        if self._worker is not None and self._worker.isRunning():
            # 上一次还在跑：稍后重试，仍带同一代次（取消后不会误触发）
            cur = getattr(self, "_schedule_gen", 0)
            QTimer.singleShot(2000, lambda g=cur: self._schedule_tick(g))
            return
        self.console.log(f"第 {self._schedule_runs + 1} 次计划执行开始", "计划")
        # 计划拍：禁并行弹窗 + 禁设备/混合平台确认（无人值守）
        if not self.run_suite(allow_parallel=False, unattended=True):
            self.console.log("计划执行中止：未能启动批量执行", "计划", "WARNING")
            self._schedule = None
            self._schedule_owned_run = False
            self.act_stop.setEnabled(False)
            self._refresh_run_control_tips(idle=True)
            return

    def _on_step_done(self, sr) -> None:
        self._run_step_count += 1
        self.console.add_step(sr)
        if getattr(self, "_run_paused", False):
            return
        self.statusBar().showMessage(
            f"执行中… 已完成 {self._run_step_count} 步  [{sr.status}] {sr.keyword_id}")

    def _on_case_done(self, rr) -> None:
        bar = getattr(self, "_sb_progress", None)
        if bar is not None and hasattr(bar, "advance_case"):
            bar.advance_case()
        else:
            self._run_case_done = getattr(self, "_run_case_done", 0) + 1
            total = getattr(self, "_run_case_total", 0)
            if bar is not None and total > 1:
                bar.setValue(min(self._run_case_done, total))
        self.console.log(f"{rr.case_name}：{rr.counts()}", "结果")

    def _on_suite_done(self, suite) -> None:
        cc = suite.case_counts()
        level = "ERROR" if cc["failed"] else "INFO"
        self.console.log(
            f"执行完成：用例 {cc['total']}，通过 {cc['passed']}，未通过 {cc['failed']}，"
            f"通过率 {suite.pass_rate():.1f}%", "结果", level)
        if hasattr(self, "_authoring_record_verify_after_run"):
            self._authoring_record_verify_after_run(suite)
        # 多机：按 device_udid 汇总通过/失败
        by_dev: dict[str, list[int]] = {}
        for rr in getattr(suite, "results", None) or []:
            udid = (getattr(rr, "device_udid", "") or "").strip() or "(未标设备)"
            pair = by_dev.setdefault(udid, [0, 0])  # passed, failed
            if getattr(rr, "passed", False):
                pair[0] += 1
            else:
                pair[1] += 1
        if len(by_dev) >= 2:
            parts = [
                f"{u} 通过 {p}/失败 {f}"
                for u, (p, f) in sorted(by_dev.items())
            ]
            self.console.log("按设备：" + "；".join(parts), "结果", level)
        if self._report_on_finish and self.project_dir:
            # 延迟：仅出报告时加载 HTML/result.json 写入
            from ...report import (
                ReportMeta,
                cases_from_suite,
                default_report_path,
                default_result_json_path,
                write_report,
                write_result_json,
            )
            finished = datetime.datetime.now()
            ts = finished.strftime("%Y-%m-%d %H:%M:%S")
            started = getattr(self, "_run_started_at", None)
            base_vars = getattr(self._worker, "_base_vars", None) or {}
            by_platform = base_vars.get("__device_udid_by_platform__")
            devices = {}
            parallel_udids = base_vars.get("__parallel_device_udids__")
            parallel_plat = str(base_vars.get("__parallel_platform__") or "").lower()
            if isinstance(parallel_udids, (list, tuple)) and parallel_udids:
                # 多机：报告 meta 列出全部并行设备
                label = parallel_plat if parallel_plat in ("android", "ios") else "parallel"
                for i, u in enumerate(parallel_udids):
                    if u:
                        devices[f"{label}_{i}" if i else label] = str(u)
            elif isinstance(by_platform, dict):
                devices = {k: str(v) for k, v in by_platform.items() if v}
            elif base_vars.get("__device_udid__"):
                devices["default"] = str(base_vars["__device_udid__"])
            platforms = sorted({
                str(p).lower() for p in (
                    list((base_vars.get("__case_platforms__") or {}).values())
                    + ([base_vars["__default_platform__"]] if base_vars.get("__default_platform__") else [])
                    + ([parallel_plat] if parallel_plat else [])
                ) if str(p).lower() in ("android", "ios", "web", "http")
            })
            meta = ReportMeta(
                project_dir=self.project_dir,
                suite_name=suite.name,
                generated_at=ts,
                started_at=started.strftime("%Y-%m-%d %H:%M:%S") if started else "",
                fault_strategy=getattr(self._fault_strategy, "value", str(self._fault_strategy)),
                platforms=platforms,
                devices=devices,
                case_paths=[p for p in getattr(self, "_run_case_paths", []) if p],
            )
            out = default_report_path(self.project_dir, finished)
            write_report(suite, out, generated_at=ts, meta=meta)
            self.console.log(f"报告已生成：{out}", "报告")
            self.console.log(f"最近报告：{os.path.join(self.project_dir, 'autopilot_report_latest.html')}", "报告")
            try:
                cc = suite.case_counts()
                failed_n = int(cc.get("failed", 0))
                job_id = f"local-{finished.strftime('%Y%m%d%H%M%S')}"
                result_path = default_result_json_path(self.project_dir, out)
                # 另存一份固定名，便于外部工具抓取最近一次
                latest_result = os.path.join(self.project_dir, "reports", "result_latest.json")
                platforms = meta.platforms or []
                write_result_json(
                    result_path,
                    job_id=job_id,
                    status="succeeded" if failed_n == 0 else "failed",
                    suite_name=suite.name or "local",
                    passed=int(cc.get("passed", 0)),
                    failed=failed_n,
                    total=int(cc.get("total", 0)),
                    duration_ms=int(getattr(suite, "duration_ms", 0) or 0),
                    summary=(
                        f"{suite.name}: {cc.get('passed', 0)}/{cc.get('total', 0)} passed, "
                        f"{getattr(suite, 'duration_ms', 0)}ms"
                    ),
                    project_id=settings.mc_project_id() or "",
                    platform=",".join(platforms) if platforms else "",
                    device_udids=[str(v) for v in (meta.devices or {}).values() if v],
                    html_report_path=os.path.abspath(out),
                    cases=cases_from_suite(suite, project_dir=self.project_dir),
                )
                if os.path.abspath(result_path) != os.path.abspath(latest_result):

                    os.makedirs(os.path.dirname(latest_result), exist_ok=True)
                    shutil.copyfile(result_path, latest_result)
                self.console.log(f"结构化结果：{result_path}", "报告")
            except Exception as result_err:  # noqa: BLE001
                self.console.log(f"result.json 写入跳过：{result_err}", "报告", "WARNING")
            # 通过→EXECUTABLE，失败→DEBUGGING
            try:
                from ...mgmt.run_status_sync import try_sync_run_statuses_with_session  # 延迟：仅管理台回写

                try_sync_run_statuses_with_session(
                    suite,
                    log=lambda m: self.console.log(m, "管理台"),
                )
            except Exception as sync_err:  # noqa: BLE001
                self.console.log(f"状态回写跳过：{sync_err}", "管理台", "WARNING")
        self.act_stop.setEnabled(False)
        self.act_pause.blockSignals(True)
        self.act_pause.setChecked(False)
        self.act_pause.setText("暂停")
        self.act_pause.setEnabled(False)
        self.act_pause.blockSignals(False)
        self._refresh_run_control_tips(idle=True)
        bar = getattr(self, "_sb_progress", None)
        if bar is not None and hasattr(bar, "end"):
            bar.end()
        elif bar is not None:
            bar.setVisible(False)
        self._set_pause_indicator(False)
        self.statusBar().showMessage(f"执行结束  通过率 {suite.pass_rate():.1f}%")
        self._parallel_running = False
        self._worker = None
        # 计划执行：仅「计划拍启动的 worker」才推进计数（手动跑不干扰计划）
        owned = bool(getattr(self, "_schedule_owned_run", False))
        self._schedule_owned_run = False
        if owned and self._schedule is not None:
            self._schedule_runs += 1
            self._schedule_last_passed = (cc["failed"] == 0)
            if should_continue(self._schedule, self._schedule_runs, self._schedule_last_passed):
                gen = getattr(self, "_schedule_gen", 0)
                QTimer.singleShot(interval_ms(self._schedule),
                                  lambda g=gen: self._schedule_tick(g))
                # 间隔等待期仍可停止取消
                self.act_stop.setEnabled(True)
                self._refresh_run_control_tips(idle=False)
                self.statusBar().showMessage(
                    f"计划间隔等待… 已完成 {self._schedule_runs} 次")
            else:
                self.console.log("计划执行结束", "计划")
                self._schedule = None    # 计划完成，清空（否则状态残留、下次无法重排）
