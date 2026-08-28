"""主窗口 · AI 辅助编写 Mixin（链路 3）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...runtime import settings

if TYPE_CHECKING:
    from .window import MainWindow
    from ...keywords.context import ExecutionContext

    _Base = MainWindow
else:
    _Base = object


class AuthoringMixin(_Base):
    # 下列实例属性由 MainWindow.__init__ 拥有；此处仅注解声明以满足静态检查（运行时不建属性）
    _inspect_ctx: ExecutionContext | None
    _inspect_platform: str
    _inspect_chosen: bool
    _inspect_udid: str

    def authoring_ai_assist(self) -> None:
        from ..widgets.ai_authoring_dialog import AiAuthoringDialog  # 延迟：仅 AI 编写弹窗

        proj = getattr(self, "project_dir", "") or ""
        default_plat = "auto"
        if proj:
            try:
                p = (settings.project_platform(proj) or "").strip().lower()
                if p in ("android", "ios", "web"):
                    default_plat = p
            except (ImportError, OSError, AttributeError, TypeError, RuntimeError):
                default_plat = "auto"

        def ensure_appium() -> bool:
            # 复用检视器同款 Appium 拉起；iOS 也可能走 WDA-direct
            if hasattr(self, "_ensure_appium_server"):
                return bool(self._ensure_appium_server("AI编写"))
            return True

        def get_ctx():
            return getattr(self, "_inspect_ctx", None)

        def open_project(directory: str) -> None:
            if directory and hasattr(self, "open_project"):
                self.open_project(directory)

        def create_project() -> str:
            # 复用主窗口新建工程对话框（含平台设置与打开工程）
            before = getattr(self, "project_dir", "") or ""
            if hasattr(self, "new_project_dialog"):
                self.new_project_dialog()
            return getattr(self, "project_dir", "") or before

        dlg = AiAuthoringDialog(
            self,
            project_dir=proj,
            default_platform=default_plat,
            get_ctx=get_ctx,
            ensure_appium=ensure_appium,
            on_request_run=self._authoring_open_and_run,
            open_project_fn=open_project,
            create_project_fn=create_project,
        )
        if dlg.exec():
            path = dlg.saved_path()
            if path and hasattr(self, "console") and self.console is not None:
                self.console.log(f"[authoring] 已生成：{path}", source="authoring")
            # 编写会话在对话框关闭时已回收（自建关 driver；复用检视器只软清理），
            # 不再把临时 ctx 挂到 _inspect_ctx，避免占住设备端口影响后续 F5/检视。
            tree = getattr(self, "project_tree", None)
            if tree is not None and hasattr(tree, "refresh"):
                try:
                    tree.refresh()
                except (OSError, RuntimeError, AttributeError, TypeError):
                    pass

    def _authoring_open_and_run(self, path: str) -> None:
        """草稿未过门禁时的收尾：打开用例并按 F5 同一条路径异步试跑。

        试跑结束后若通过，回写 ``authored/_authoring.json``，否则上传仍会提示未验证。
        """
        target = (path or "").strip()
        if not target:
            return
        tree = getattr(self, "project_tree", None)
        if tree is not None and hasattr(tree, "refresh"):
            try:
                tree.refresh()
            except (OSError, RuntimeError, AttributeError, TypeError):
                pass
        if hasattr(self, "_on_file_activated"):
            self._on_file_activated(target)
        # 记下待验证路径；``_on_suite_done`` 里按结果回写门禁
        self._authoring_pending_verify = target
        if hasattr(self, "run_current_case"):
            self.run_current_case()

    @staticmethod
    def _suite_failed_count(suite) -> int:
        """套件失败用例数；取不到时按失败处理（不敢放行上传）。"""
        try:
            return int((suite.case_counts() or {}).get("failed", 0) or 0)
        except (AttributeError, TypeError, ValueError):
            return 1

    def _authoring_record_verify_after_run(self, suite) -> None:
        """F5/套件结束后：若是链路 3 待验证草稿且全部通过，记为 dry_run 已验证。"""
        pending = getattr(self, "_authoring_pending_verify", "") or ""
        self._authoring_pending_verify = ""
        if not pending:
            return
        try:
            from ...authoring.gate import GateResult, record_gate_result
        except ImportError:
            return
        if self._suite_failed_count(suite):
            if hasattr(self, "console") and self.console is not None:
                self.console.log(
                    f"[authoring] 试跑未通过，仍禁止直接上传：{pending}",
                    source="authoring",
                )
            return
        try:
            gate = GateResult(
                ok=True,
                message="本地试跑通过，可以上传或远程批跑",
                allow_upload=True,
                details=["dry_run"],
                verified_by="dry_run",
            )
            record_gate_result(pending, gate)
            if hasattr(self, "console") and self.console is not None:
                self.console.log(
                    f"[authoring] 试跑通过，已更新验证状态：{pending}",
                    source="authoring",
                )
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            if hasattr(self, "console") and self.console is not None:
                self.console.log(
                    f"[authoring] 验证状态回写失败：{exc}",
                    source="authoring",
                )
