"""主窗口·管理台投递 Mixin：工程上传 / 逻辑用例 / 远程入队（AUD-2026-17 Wave 1）。

混入链：MainWindow → MgmtMixin → MgmtDeliveryMixin。
登录/会话/本机 Runner/打开网页仍在 mgmt.py。
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QCheckBox, QDialog, QFileDialog, QInputDialog, QMessageBox

from ..mgmt_http_worker import MgmtHttpWorker
from ...mgmt import (
    build_artifact_manifest,
    collect_logical_case_ids,
    collect_logical_ids_from_project,
    ensure_user_session,
    list_runnable_entries,
    mgmt_error_message,
    patch_automation_status,
    write_logical_cases_as_drafts,
    zip_project_dir,
)
from ...mgmt.runtime_contract import required_runtime_version, validate_artifact_runtime
from ...mgmt.project_context import assert_project_membership, require_cached_project_id
from ...mgmt.save_sync import (
    push_logical_case_update,
    save_sync_action_label,
    should_offer_save_sync,
)
from ...runtime import settings

if TYPE_CHECKING:
    from .window import MainWindow
    _Base = MainWindow
else:
    _Base = object


class MgmtDeliveryMixin(_Base):
    """远程投递与工程同步（由 MgmtMixin 继承）。"""

    # 与 MgmtSessionMixin / MgmtMixin 对齐：HTTP worker 槽位
    _mgmt_http_worker = None

    def mgmt_prompt_sync_after_save(self, tc) -> None:
        """UX-P2-001：保存仅写本地；可选同步 Platform（设计域回写或上传制品）。"""

        if not should_offer_save_sync(tc):
            return
        action = save_sync_action_label(tc)
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setWindowTitle("同步 Platform")
        msg.setText(
            "用例已保存到本地文件。\n"
            "Platform 不会自动更新，远程执行/设计域需手动同步。\n\n"
            f"是否现在{action}？"
        )
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        chk = QCheckBox("不再提示")
        msg.setCheckBox(chk)
        accepted = msg.exec() == QMessageBox.StandardButton.Yes
        if chk.isChecked():
            settings.set_mc_save_sync_prompt(False)
        if not accepted:
            return

        lid = str(getattr(tc, "logical_case_id", "") or "").strip()
        if lid:
            self._mgmt_sync_saved_logical_case(tc)
        else:
            self.mgmt_upload_project()

    def _mgmt_sync_saved_logical_case(self, tc) -> None:
        """后台 PATCH 单条逻辑用例（intent 步骤 / 标题）。"""

        if not self._mgmt_require_user_session(purpose="同步逻辑用例"):
            return
        pid = self._mgmt_require_project_id(title="同步逻辑用例")
        if not pid:
            return
        tc_pid = str(getattr(tc, "project_id", "") or "").strip()
        if tc_pid and tc_pid != pid:
            QMessageBox.warning(
                self,
                "同步逻辑用例",
                f"当前用例绑定项目 {tc_pid}，连接设置选择的是 {pid}。\n"
                "为避免跨项目误写，请先切回用例所属项目。",
            )
            return
        proj = getattr(self, "project_dir", "") or ""
        if not self._mgmt_confirm_project_mapping(
            project_dir=proj, project_id=pid, action="同步逻辑用例"
        ):
            return

        def _work():

            client, _ = ensure_user_session(require=True)
            try:
                return push_logical_case_update(client, tc)
            finally:
                client.close()

        def _ok(out) -> None:
            lid = str(getattr(tc, "logical_case_id", "") or "").strip()
            title = str(out.get("title") or tc.name or "").strip() if isinstance(out, dict) else ""
            self.console.log(
                f"已同步逻辑用例到 Platform：{title or lid}",
                "管理台",
            )
            QMessageBox.information(
                self,
                "同步 Platform",
                f"设计域已更新\nlogical_case_id={lid}",
            )

        self._mgmt_run_http(title="同步逻辑用例", work=_work, on_ok=_ok)

    def _mgmt_require_project(self) -> str:
        proj = getattr(self, "project_dir", "") or ""
        if not proj or not os.path.isdir(proj):
            QMessageBox.information(self, "管理台", "请先打开工程。")
            return ""
        return proj

    @staticmethod
    def _mgmt_default_project_id(proj: str = "") -> str:
        """仅使用已缓存的成员项目；禁止回退工程目录名。"""

        _ = proj  # 保留签名兼容；真源为缓存 project_id
        return require_cached_project_id()

    def _mgmt_require_project_id(self, *, title: str = "管理台") -> str:
        try:
            return self._mgmt_default_project_id()
        except Exception as exc:  # noqa: BLE001

            QMessageBox.warning(self, title, mgmt_error_message(exc))
            return ""

    def _mgmt_confirm_project_mapping(
        self, *, project_dir: str, project_id: str, action: str
    ) -> bool:
        """首次/变更时确认映射；同一本地工程与项目组合不重复打扰。"""
        raw_dir = (project_dir or "").strip()
        pid = (project_id or "").strip()
        if not raw_dir or not pid:
            return False
        local = os.path.abspath(raw_dir)
        bound = settings.mc_bound_project_id(local)
        if bound == pid:
            return True
        previous = (
            f"\n此前绑定：{bound}\n"
            if bound
            else "\n此前尚未为这个本地工程确认 Platform 项目。\n"
        )
        answer = QMessageBox.question(
            self,
            action,
            "请确认并记住数据归属：\n\n"
            f"本地工程：{local}\n"
            f"Platform 项目：{pid}\n"
            f"{previous}\n"
            "继续后，上传、导入或任务结果都会归入上述 Platform 项目。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        settings.set_mc_bound_project_id(local, pid)
        return True

    def _mgmt_busy_http(self) -> bool:
        w = getattr(self, "_mgmt_http_worker", None)
        return bool(w is not None and w.isRunning())

    def _mgmt_run_http(self, *, title: str, work, on_ok) -> None:
        """后台执行网络/打 zip；回调在 UI 线程。"""

        if self._mgmt_busy_http():
            QMessageBox.information(self, title, "已有管理台上传/提交进行中，请稍候。")
            return
        self.console.log(f"{title}：进行中…", "管理台")
        worker = MgmtHttpWorker(work, self)
        self._mgmt_http_worker = worker

        def _done(result) -> None:
            if isinstance(result, BaseException):

                QMessageBox.warning(self, title, mgmt_error_message(result))
                return
            try:
                on_ok(result)
            except Exception as exc:  # noqa: BLE001

                QMessageBox.warning(self, title, mgmt_error_message(exc))

        worker.done.connect(_done)
        worker.start()

    @staticmethod
    def _mgmt_ensure_project_space(client, project_id: str, *, name: str = "") -> None:
        """校验当前账号是项目成员；不再静默创建项目空间。"""

        _ = name  # 历史参数；不再用于静默建项
        assert_project_membership(client, project_id)

    def mgmt_upload_project(self) -> None:
        if not self._mgmt_require_user_session(purpose="上传工程制品"):
            return
        proj = self._mgmt_require_project()
        if not proj:
            return
        # 链路 3 门禁：会话驱动编写已逐步验证的草稿直接放行；未验证的必须人工同意。
        # 这里刻意不做硬拦截——机器判不了「AI 写的用例是否符合预期」，只有人能担这个责。
        from ...authoring.gate import project_upload_blocked_reason  # 延迟：仅上传门禁

        blocked = project_upload_blocked_reason(proj)
        if blocked:

            ans = QMessageBox.question(
                self,
                "上传工程",
                f"{blocked}\n\n"
                "这些草稿还没在本机跑通过，是否符合预期只能由你确认。\n"
                "建议先本地运行（F5）验证，确认无误后再上传。\n\n"
                "仍要继续上传吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
        pid = self._mgmt_require_project_id(title="上传工程")
        if not pid:
            return
        if not self._mgmt_confirm_project_mapping(
            project_dir=proj, project_id=pid, action="上传工程"
        ):
            return
        basename = os.path.basename(proj)

        def _work():
            client, _ = ensure_user_session(require=True)
            try:
                runtime_pin = required_runtime_version(client)
                local_man = build_artifact_manifest(
                    proj,
                    project_id=pid,
                    required_runtime_version=runtime_pin,
                )
                data = zip_project_dir(
                    proj,
                    project_id=pid,
                    required_runtime_version=runtime_pin,
                )
                self._mgmt_ensure_project_space(client, pid, name=basename)
                art = client.upload_artifact(
                    data,
                    filename=f"{basename}.zip",
                    name=basename,
                    project_id=pid,
                )
                # 尽力回写：制品发布 → PUBLISHED
                ids = collect_logical_ids_from_project(proj)
                sync_ok, sync_fail = patch_automation_status(client, ids, "PUBLISHED")
                if isinstance(art, dict):
                    art = dict(art)
                    art["_status_sync"] = {"ok": sync_ok, "failed": sync_fail, "total": len(ids)}
                    readiness = local_man.get("intent_readiness")
                    if isinstance(readiness, dict):
                        art["_intent_readiness"] = readiness
                return art
            finally:
                client.close()

        def _ok(art) -> None:
            self._mgmt_refresh_session_ui()
            aid = art.get("id", "") if isinstance(art, dict) else ""
            mstatus = (art.get("manifest_status") if isinstance(art, dict) else "") or ""
            sync = (art.get("_status_sync") if isinstance(art, dict) else None) or {}
            self.console.log(
                f"已上传工程制品 {aid}" + (f"（manifest={mstatus}）" if mstatus else ""),
                "管理台",
            )
            if sync.get("total"):
                self.console.log(
                    f"automation_status→PUBLISHED：成功 {sync.get('ok', 0)}/"
                    f"{sync.get('total', 0)}"
                    + (f"，失败 {sync.get('failed')}" if sync.get("failed") else ""),
                    "管理台",
                )
            readiness = (art.get("_intent_readiness") if isinstance(art, dict) else None) or {}
            if readiness.get("missing_binding_case_ids") or (
                int(readiness.get("logical_case_count") or 0) > 0
                and int(readiness.get("binding_file_count") or 0) == 0
            ):
                hint = str(readiness.get("hint") or "Intent 用例 Binding 未齐").strip()
                self.console.log(f"⚠ {hint}", "管理台")
            extra = ""
            if mstatus and mstatus != "valid":
                warns = art.get("manifest_warnings") if isinstance(art, dict) else None
                errs = art.get("manifest_errors") if isinstance(art, dict) else None
                bits = []
                if errs:
                    bits.extend(str(x) for x in errs[:3])
                if warns:
                    bits.extend(str(x) for x in warns[:3])
                if bits:
                    extra = "\n\n" + "\n".join(bits)
            QMessageBox.information(
                self,
                "上传工程",
                f"上传成功\nartifact_id={aid}\nmanifest={mstatus or 'n/a'}{extra}",
            )
            settings.set_value("mc_last_artifact_id", aid)

        self._mgmt_run_http(title="上传工程", work=_work, on_ok=_ok)

    def mgmt_import_logical_cases(self) -> None:
        """从 Platform 导出 APPROVED 逻辑用例 → 工程目录草稿 .tc.yaml。"""
        if not self._mgmt_require_user_session(purpose="导入逻辑用例"):
            return
        proj = self._mgmt_require_project()
        if not proj:
            return
        pid = self._mgmt_require_project_id(title="导入逻辑用例")
        if not pid:
            return
        if not self._mgmt_confirm_project_mapping(
            project_dir=proj, project_id=pid, action="导入逻辑用例"
        ):
            return

        def _work():
            client, _ = ensure_user_session(require=True)
            try:
                self._mgmt_ensure_project_space(
                    client, pid, name=os.path.basename(proj)
                )
                bundle = client.export_approved_logical_cases(pid)
                cases = list((bundle or {}).get("cases") or [])
                if not cases:
                    return {"count": 0, "paths": [], "sync_ok": 0, "sync_fail": 0}
                paths = write_logical_cases_as_drafts(
                    proj, cases, project_id=pid, subdir="imported_logical"
                )

                ids = collect_logical_case_ids(cases)
                sync_ok, sync_fail = patch_automation_status(
                    client, ids, "INTENT_READY"
                )
                return {
                    "count": len(paths),
                    "paths": [str(p) for p in paths],
                    "sync_ok": sync_ok,
                    "sync_fail": sync_fail,
                }
            finally:
                client.close()

        def _ok(out) -> None:
            self._mgmt_refresh_session_ui()
            n = int((out or {}).get("count") or 0)
            if n <= 0:
                QMessageBox.information(
                    self,
                    "导入逻辑用例",
                    f"项目 {pid} 暂无审核通过的逻辑用例。\n请先在管理台审核通过后再导入。",
                )
                return
            # 刷新工程树
            refresh = getattr(self, "refresh_project_tree", None) or getattr(
                self, "_refresh_project_tree", None
            )
            if callable(refresh):
                try:
                    refresh()
                except (RuntimeError, TypeError, AttributeError):
                    pass
            sync_ok = int((out or {}).get("sync_ok") or 0)
            sync_fail = int((out or {}).get("sync_fail") or 0)
            self.console.log(f"已导入 {n} 个逻辑用例草稿 → imported_logical/", "管理台")
            if sync_ok or sync_fail:
                self.console.log(
                    f"automation_status→INTENT_READY：成功 {sync_ok}"
                    + (f"，失败 {sync_fail}" if sync_fail else ""),
                    "管理台",
                )
            QMessageBox.information(
                self,
                "导入逻辑用例",
                f"已写入 {n} 个意图用例草稿。\n"
                f"首次运行时会自动解析控件绑定。",
            )
            _ = settings

        self._mgmt_run_http(title="导入逻辑用例", work=_work, on_ok=_ok)

    def mgmt_review_failed_intents(self) -> None:
        """人只审失败：展示最近一次运行中 binding_hit=failed 的意图步。"""
        proj = self._mgmt_require_project()
        if not proj:
            return
        from ..widgets.failed_intent_dialog import show_failed_intent_review  # 延迟：仅失败意图复核

        show_failed_intent_review(proj, self)

    def mgmt_solidify_stable_intents(self) -> None:
        """D2：批量固化 success_streak 达标的 Intent 步。"""

        proj = self._mgmt_require_project()
        if not proj:
            return
        min_n, ok = QInputDialog.getInt(
            self,
            "固化稳定意图步",
            "连续成功次数阈值（success_streak ≥ N）：",
            3,
            1,
            100,
            1,
        )
        if not ok:
            return
        from ...intent.bindings import list_stable_bindings  # 延迟：仅固化绑定
        from ...intent.solidify import solidify_stable  # 延迟：仅固化稳定绑定

        cands = list_stable_bindings(proj, min_streak=min_n)
        if not cands:
            QMessageBox.information(
                self,
                "固化稳定意图步",
                f"没有 success_streak≥{min_n} 的候选步。",
            )
            return
        preview = "\n".join(
            f"- {c['logical_case_id']} / {c['intent_id']} → {c['keyword_id']} "
            f"(streak={c['success_streak']})"
            for c in cands[:20]
        )
        more = "" if len(cands) <= 20 else f"\n…共 {len(cands)} 条"
        confirm = QMessageBox.question(
            self,
            "固化稳定意图步",
            f"将固化 {len(cands)} 个 Intent 步：\n{preview}{more}\n\n继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        out = solidify_stable(proj, min_streak=min_n, dry_run=False)
        QMessageBox.information(
            self,
            "固化稳定意图步",
            str(out.get("message") or f"solidified={out.get('solidified')}"),
        )

    def mgmt_upload_app_build(self) -> None:
        if not self._mgmt_require_user_session(purpose="上传应用资源"):
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 apk / ipa",
            "",
            "App Builds (*.apk *.apex *.xapk *.ipa);;All Files (*)",
        )
        if not path:
            return
        pid = self._mgmt_require_project_id(title="上传应用资源")
        if not pid:
            return
        proj = getattr(self, "project_dir", "") or ""
        fname = os.path.basename(path)
        name = os.path.splitext(fname)[0]

        def _work():
            with open(path, "rb") as fh:
                data = fh.read()
            client, _ = ensure_user_session(require=True)
            try:
                self._mgmt_ensure_project_space(
                    client, pid, name=os.path.basename(proj) if proj else pid
                )
                return client.upload_app_build(
                    data,
                    filename=fname,
                    name=name,
                    project_id=pid,
                )
            finally:
                client.close()

        def _ok(out) -> None:
            self._mgmt_refresh_session_ui()
            bid = out.get("id", "") if isinstance(out, dict) else ""
            reused = bool(out.get("reused")) if isinstance(out, dict) else False
            ver = str((out.get("version_name") if isinstance(out, dict) else "") or "")
            pkg = str((out.get("package_id") if isinstance(out, dict) else "") or "")
            bits = [f"app_build_id={bid}"]
            if reused:
                bits.append("相同内容已存在，已复用")
            if ver:
                bits.append(f"version={ver}")
            if pkg:
                bits.append(f"package={pkg}")
            self.console.log("已上传应用资源 " + " ".join(bits), "管理台")
            QMessageBox.information(
                self,
                "上传应用资源",
                "上传成功\n" + "\n".join(bits),
            )
            settings.set_value("mc_last_app_build_id", bid)

        self._mgmt_run_http(title="上传应用资源", work=_work, on_ok=_ok)

    def mgmt_enqueue_approved_cases(self) -> None:
        """导入、打包并通过设计域 enqueue-job 提交 APPROVED 逻辑用例。"""
        if not self._mgmt_require_user_session(purpose="已通过逻辑用例一键入队"):
            return
        proj = self._mgmt_require_project()
        if not proj:
            return
        from ..widgets.mgmt_submit_job_dialog import MgmtSubmitJobDialog  # 延迟：仅提交作业弹窗

        pid = self._mgmt_require_project_id(title="逻辑用例一键入队")
        if not pid:
            return
        if not self._mgmt_confirm_project_mapping(
            project_dir=proj, project_id=pid, action="逻辑用例一键入队"
        ):
            return

        def _fetch():
            client, _ = ensure_user_session(require=True)
            try:
                return {
                    "cases": client.list_logical_cases(
                        project_id=pid, review_status="APPROVED"
                    ),
                    "app_builds": client.list_app_builds(project_id=pid) or [],
                    "devices": client.list_devices() or [],
                }
            finally:
                client.close()

        def _after_fetch(payload) -> None:
            approved = list((payload or {}).get("cases") or [])
            if not approved:
                QMessageBox.information(
                    self,
                    "逻辑用例一键入队",
                    f"项目 {pid} 暂无审核通过的逻辑用例。",
                )
                return
            dlg = MgmtSubmitJobDialog(
                self,
                default_name=f"approved-{os.path.basename(proj)}",
                default_project_id=pid,
                default_app_build_id=str(
                    settings.get("mc_last_app_build_id", "") or ""
                ),
                app_builds=list((payload or {}).get("app_builds") or []),
                devices=list((payload or {}).get("devices") or []),
                entries=[],
            )
            dlg.setWindowTitle(f"已通过逻辑用例一键入队（{len(approved)} 条）")
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            try:
                vals = dlg.values()
            except ValueError as exc:

                QMessageBox.warning(self, "逻辑用例一键入队", mgmt_error_message(exc))
                return

            def _work():
                client, _ = ensure_user_session(require=True)
                try:
                    runtime_pin = required_runtime_version(client)
                    paths = write_logical_cases_as_drafts(
                        proj,
                        approved,
                        project_id=pid,
                        subdir="imported_logical",
                    )
                    logical_case_ids = collect_logical_case_ids(approved)
                    data = zip_project_dir(
                        proj,
                        project_id=pid,
                        required_runtime_version=runtime_pin,
                    )
                    self._mgmt_ensure_project_space(client, pid, name=vals["name"])
                    art = client.upload_artifact(
                        data,
                        filename=f"{os.path.basename(proj)}.zip",
                        name=vals["name"],
                        project_id=pid,
                    )
                    artifact_id = str(art.get("id") or "")
                    body = {
                        "name": vals["name"],
                        "project_id": pid,
                        "artifact_id": artifact_id,
                        "logical_case_ids": logical_case_ids,
                        "platform": vals["platform"],
                        "device_udids": vals["device_udids"],
                        "preferred_runner_id": vals["preferred_runner_id"],
                        "parallel": bool(vals.get("parallel")),
                        "parallel_workers": int(vals.get("parallel_workers") or 0),
                        "backend_mode": vals.get("backend_mode") or "auto",
                        "web_engine": vals.get("web_engine") or "selenium",
                        "wda_bundle": vals.get("wda_bundle") or "",
                        "app_build_id": vals.get("app_build_id") or "",
                        "webhook_url": vals.get("webhook_url") or "",
                    }
                    job = client.enqueue_approved_cases_job(body)
                    settings.set_value("mc_last_artifact_id", artifact_id)
                    return {
                        "job": job,
                        "artifact_id": artifact_id,
                        "case_count": len(logical_case_ids),
                        "draft_count": len(paths),
                    }
                finally:
                    client.close()

            def _ok(result) -> None:
                job = result.get("job") or {}
                self._mgmt_refresh_session_ui()
                refresh = getattr(self, "refresh_project_tree", None) or getattr(
                    self, "_refresh_project_tree", None
                )
                if callable(refresh):
                    refresh()
                warns = [
                    str(w).strip()
                    for w in (job.get("warnings") or [])
                    if str(w).strip()
                ]
                self.console.log(
                    f"已通过 enqueue-job 入队 {result.get('case_count', 0)} 条 "
                    f"APPROVED 用例：job={job.get('id', '')}",
                    "管理台",
                )
                for w in warns:
                    self.console.log(w, "管理台")
                detail = (
                    f"已创建任务\nid={job.get('id', '')}\n"
                    f"logical_cases={result.get('case_count', 0)}\n"
                    f"artifact_id={result.get('artifact_id', '')}"
                )
                if warns:
                    detail += "\n\n⚠ " + "\n⚠ ".join(warns)
                QMessageBox.information(self, "逻辑用例一键入队", detail)

            self._mgmt_run_http(title="逻辑用例一键入队", work=_work, on_ok=_ok)

        self._mgmt_run_http(title="加载已通过逻辑用例", work=_fetch, on_ok=_after_fetch)

    def mgmt_submit_remote_job(self) -> None:
        if not self._mgmt_require_user_session(purpose="提交远程批跑"):
            return
        proj = self._mgmt_require_project()
        if not proj:
            return
        from ..widgets.mgmt_submit_job_dialog import MgmtSubmitJobDialog  # 延迟：仅提交作业弹窗

        pid = self._mgmt_require_project_id(title="提交远程批跑")
        if not pid:
            return
        if not self._mgmt_confirm_project_mapping(
            project_dir=proj, project_id=pid, action="提交远程批跑"
        ):
            return
        try:
            local_entries = list_runnable_entries(proj)
        except (OSError, UnicodeError, ValueError, TypeError, KeyError, RuntimeError):
            local_entries = []

        def _fetch():
            try:
                client, _ = ensure_user_session(require=True)
                try:
                    app_builds = client.list_app_builds(project_id=pid) or []
                    if not app_builds and pid:
                        app_builds = client.list_app_builds() or []
                    devices = client.list_devices() or []
                    return {"app_builds": app_builds, "devices": devices, "warn": ""}
                finally:
                    client.close()
            except Exception as exc:  # noqa: BLE001

                return {"app_builds": [], "devices": [], "warn": mgmt_error_message(exc)}

        def _after_fetch(payload) -> None:
            warn = str((payload or {}).get("warn") or "")
            if warn:
                self.console.log(f"拉取应用资源/设备列表失败，仍可手填: {warn}", "管理台")
            app_builds = list((payload or {}).get("app_builds") or [])
            devices = list((payload or {}).get("devices") or [])
            dlg = MgmtSubmitJobDialog(
                self,
                default_name=os.path.basename(proj),
                default_project_id=pid,
                default_app_build_id=str(settings.get("mc_last_app_build_id", "") or ""),
                app_builds=app_builds,
                devices=devices,
                entries=local_entries,
            )
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            try:
                vals = dlg.values()
            except ValueError as exc:

                QMessageBox.warning(self, "提交远程批跑", mgmt_error_message(exc))
                return

            def _work():
                client, _ = ensure_user_session(require=True)
                try:
                    runtime_pin = required_runtime_version(client)
                    artifact_id = str(settings.get("mc_last_artifact_id", "") or "")
                    if vals["reupload"] or not artifact_id:
                        data = zip_project_dir(
                            proj,
                            project_id=vals["project_id"] or pid,
                            required_runtime_version=runtime_pin,
                        )
                        self._mgmt_ensure_project_space(
                            client, vals["project_id"], name=vals["name"]
                        )
                        art = client.upload_artifact(
                            data,
                            filename=f"{os.path.basename(proj)}.zip",
                            name=vals["name"],
                            project_id=vals["project_id"],
                        )
                        artifact_id = str(art.get("id") or "")
                        settings.set_value("mc_last_artifact_id", artifact_id)
                    elif vals["project_id"]:
                        self._mgmt_ensure_project_space(
                            client, vals["project_id"], name=vals["name"]
                        )
                        artifacts = client.list_artifacts(
                            project_id=vals["project_id"], limit=100
                        )
                        selected = next(
                            (
                                item
                                for item in artifacts
                                if str(item.get("id") or "") == artifact_id
                            ),
                            None,
                        )
                        if selected is None:
                            raise ValueError(
                                "缓存的 artifact_id 已不存在，请勾选重新打包上传"
                            )
                        validate_artifact_runtime(selected, runtime_pin)
                    body = {
                        "name": vals["name"],
                        "artifact_id": artifact_id,
                        "platform": vals["platform"],
                        "device_udids": vals["device_udids"],
                        "preferred_runner_id": vals["preferred_runner_id"],
                        "parallel": vals["parallel"],
                        "parallel_workers": int(vals.get("parallel_workers") or 0),
                        "backend_mode": vals.get("backend_mode") or "auto",
                        "web_engine": vals.get("web_engine") or "selenium",
                        "wda_bundle": vals.get("wda_bundle") or "",
                        "project_id": vals["project_id"] or "",
                    }
                    if vals.get("webhook_url"):
                        body["webhook_url"] = vals["webhook_url"]
                    if vals.get("app_build_id"):
                        body["app_build_id"] = vals["app_build_id"]
                        settings.set_value("mc_last_app_build_id", vals["app_build_id"])
                    if vals.get("entry_paths"):
                        body["entry_paths"] = list(vals["entry_paths"])
                    job = client.create_job(body)
                    return {"job": job, "artifact_id": artifact_id, "vals": vals}
                finally:
                    client.close()

            def _ok(result) -> None:
                self._mgmt_refresh_session_ui()
                job = result.get("job") or {}
                artifact_id = result.get("artifact_id") or ""
                vals_ok = result.get("vals") or {}
                jid = job.get("id", "")
                app_note = (
                    f" app_build={vals_ok.get('app_build_id')}"
                    if vals_ok.get("app_build_id")
                    else ""
                )
                self.console.log(
                    f"已提交远程任务 {jid}（artifact={artifact_id}{app_note}）", "管理台"
                )
                warns = [
                    str(w).strip()
                    for w in (job.get("warnings") or [])
                    if str(w).strip()
                ]
                for w in warns:
                    self.console.log(f"⚠ {w}", "管理台")
                extra = ("\n\n" + "\n".join(warns[:5])) if warns else ""
                QMessageBox.information(
                    self,
                    "远程批跑",
                    f"已创建任务\nid={jid}\nstatus={job.get('status')}\n\n"
                    "任务进度、日志、设备与报告请在 Web 管理台查看。"
                    f"{extra}",
                )

            self._mgmt_run_http(title="远程批跑", work=_work, on_ok=_ok)

        self._mgmt_run_http(title="加载批跑选项", work=_fetch, on_ok=_after_fetch)
