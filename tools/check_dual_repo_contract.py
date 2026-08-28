"""比较 IDE/Platform 的公开执行契约。

原则（互补，非单向覆盖）：
- Intent / Http / 执行编排（suite/run/executor）须字节一致
- 包边界适配允许分叉：appparse 导入、无 inspector 的 mirror stub、
  Platform settings 内联 ui_theme、safe_zip 再导出、版本号 -vendored
- 会话/安全行为须语义对齐（driver terminate/KEEP_WDA、settings 密文 token）

维护边界与扩展清单见：docs/architecture/DUAL_REPO_CONTRACT.md
（Platform 仓同名文件）。
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import cast


def _major_minor(value: str) -> tuple[str, str]:
    """公开契约比较：剥掉 v / -vendored 后取 major.minor。"""
    raw = (value or "").strip().lower().removeprefix("v")
    raw = raw.replace("-vendored", "").replace("+vendored", "")
    match = re.match(r"^(\d+)\.(\d+)", raw)
    if not match:
        raise ValueError(f"无法解析 runtime_version: {value!r}")
    return match.group(1), match.group(2)


def _check_pkg_file_sync(
    ide_pkg: Path,
    plat_pkg: Path,
    rels: list[str],
    *,
    label: str,
) -> None:
    missing: list[str] = []
    mismatched: list[str] = []
    for rel in rels:
        a = ide_pkg / rel
        b = plat_pkg / rel
        if not a.is_file():
            missing.append(f"IDE缺 {rel}")
            continue
        if not b.is_file():
            missing.append(f"Platform缺 {rel}")
            continue
        if a.read_bytes() != b.read_bytes():
            mismatched.append(rel)
    if missing or mismatched:
        parts = []
        if missing:
            parts.append("缺失: " + ", ".join(missing))
        if mismatched:
            parts.append("内容不一致: " + ", ".join(mismatched))
        raise RuntimeError(f"{label}双仓同步失败 — " + "; ".join(parts))


def check_http_keyword_sync(ide_root: Path, platform_root: Path) -> None:
    """Http 关键字须字节一致（含元数据与 OpenAPI 导入桥）。"""
    rels = [
        "keywords/http/__init__.py",
        "keywords/http/client.py",
        "keywords/http/session.py",
        "keywords/http/auth.py",
        "keywords/http/assert_kw.py",
        "keywords/http/env.py",
        "keywords/context.py",
        "engine/teardown.py",
        "metadata/keyword_defs/http.xml",
        "mgmt/openapi_import.py",
    ]
    _check_pkg_file_sync(
        ide_root / "autopilot",
        platform_root / "autopilot_platform" / "ap",
        rels,
        label="Http 关键字",
    )


def check_job_platforms_sync(ide_root: Path, platform_root: Path) -> None:
    """无设备平台判定组件须字节一致。"""
    a = ide_root / "autopilot" / "runtime" / "job_platforms.py"
    b = platform_root / "autopilot_platform" / "core" / "job_platforms.py"
    if not a.is_file() or not b.is_file():
        raise RuntimeError("job_platforms.py 双仓缺失")
    if a.read_bytes() != b.read_bytes():
        raise RuntimeError("job_platforms.py 双仓内容不一致")


def check_web_keyword_sync(ide_root: Path, platform_root: Path) -> None:
    """Web 关键字须字节一致（Selenium + Playwright 双引擎执行面）。"""
    ide_web = ide_root / "autopilot" / "keywords" / "web"
    rels = sorted(f"keywords/web/{p.name}" for p in ide_web.glob("*.py") if p.is_file())
    _check_pkg_file_sync(
        ide_root / "autopilot",
        platform_root / "autopilot_platform" / "ap",
        rels,
        label="Web 关键字",
    )


def check_intent_stack_sync(ide_root: Path, platform_root: Path) -> None:
    """Intent 栈须字节一致（云端 Runner 执行 intent_act）。"""
    ide_pkg = ide_root / "autopilot"
    plat_pkg = platform_root / "autopilot_platform" / "ap"
    intent_dir = ide_pkg / "intent"
    rels = sorted(
        f"intent/{p.name}"
        for p in intent_dir.glob("*.py")
        if p.is_file() and p.name != "__main__.py"
    )
    rels.extend(
        [
            "keywords/__init__.py",
            "model/testcase.py",
            "model/serializer.py",
            "metadata/keyword_defs/intent.xml",
        ]
    )
    _check_pkg_file_sync(ide_pkg, plat_pkg, rels, label="Intent 栈")


def check_keywords_registry_sync(ide_root: Path, platform_root: Path) -> None:
    """关键字注册表（risk_level / apply_risk_levels）须字节一致。"""
    _check_pkg_file_sync(
        ide_root / "autopilot",
        platform_root / "autopilot_platform" / "ap",
        ["keywords/registry.py"],
        label="关键字注册表",
    )


def check_data_ssh_keyword_sync(ide_root: Path, platform_root: Path) -> None:
    """Data/SSH 关键字与 Public 元数据须字节一致（AUD-2026-04 主机信任策略）。"""
    _check_pkg_file_sync(
        ide_root / "autopilot",
        platform_root / "autopilot_platform" / "ap",
        [
            "keywords/data/ssh.py",
            "metadata/keyword_defs/public.xml",
        ],
        label="Data/SSH 关键字",
    )


def check_safe_zip_security_semantics(
    ide_root: Path, platform_root: Path
) -> None:
    """AUD-2026-19：双份 safe_zip 安全语义对齐；Platform ap 仅再导出 core。"""
    ide_path = ide_root / "autopilot" / "runtime" / "safe_zip.py"
    core_path = platform_root / "autopilot_platform" / "core" / "safe_zip.py"
    reexport_path = (
        platform_root / "autopilot_platform" / "ap" / "runtime" / "safe_zip.py"
    )
    for path in (ide_path, core_path, reexport_path):
        if not path.is_file():
            raise RuntimeError(f"AUD-2026-19: 缺少 {path}")

    ide_src = ide_path.read_text(encoding="utf-8")
    core_src = core_path.read_text(encoding="utf-8")
    reexport_src = reexport_path.read_text(encoding="utf-8")

    needles = (
        "DEFAULT_MAX_ENTRIES = 20_000",
        "DEFAULT_MAX_TOTAL_UNCOMPRESSED = 512 * 1024 * 1024",
        "DEFAULT_MAX_RATIO = 100",
        "def safe_extractall",
        "def _is_safe_member",
        "unsafe zip path",
        "compression ratio too high",
    )
    for label, text in (("IDE", ide_src), ("Platform.core", core_src)):
        missing = [n for n in needles if n not in text]
        if missing:
            raise RuntimeError(
                f"AUD-2026-19: {label} safe_zip 缺安全探针: {missing}"
            )

    def _fn_dumps(code: str) -> dict[str, str]:
        tree = ast.parse(code)
        wanted = {"safe_extractall", "_is_safe_member"}
        out: dict[str, str] = {}
        for node in tree.body:
            name = getattr(node, "name", None)
            if name in wanted:
                dumped = ast.dump(cast(ast.AST, node), include_attributes=False)
                out[str(name)] = dumped
        return out

    ide_fns = _fn_dumps(ide_src)
    core_fns = _fn_dumps(core_src)
    if set(ide_fns) != {"safe_extractall", "_is_safe_member"}:
        raise RuntimeError("AUD-2026-19: IDE safe_zip 缺必要函数")
    if ide_fns != core_fns:
        drift = [k for k in ide_fns if ide_fns.get(k) != core_fns.get(k)]
        raise RuntimeError(
            "AUD-2026-19: IDE runtime/safe_zip 与 Platform core/safe_zip "
            f"函数体漂移: {drift}（禁止抽 runtime wheel；请同步安全逻辑）"
        )

    if "from autopilot_platform.core.safe_zip import" not in reexport_src:
        raise RuntimeError(
            "AUD-2026-19: Platform ap/runtime/safe_zip.py 须再导出 core.safe_zip"
        )
    if "def safe_extractall" in reexport_src or "def _is_safe_member" in reexport_src:
        raise RuntimeError(
            "AUD-2026-19: ap/runtime/safe_zip.py 禁止再实现一份解压逻辑"
        )


def check_report_modules_sync(ide_root: Path, platform_root: Path) -> None:
    """报告公共组件须字节一致（HTML / result.json / 用例对比 / 失败分类）。"""
    rels = [
        "report/html_report.py",
        "report/result_json.py",
        "report/compare.py",
        "report/fail_class.py",
    ]
    _check_pkg_file_sync(
        ide_root / "autopilot",
        platform_root / "autopilot_platform" / "ap",
        rels,
        label="报告组件",
    )


def check_result_json_attachment_case_alias(
    ide_root: Path, platform_root: Path
) -> None:
    """result.v1 attachments 须同时写 case + case_name（AUD-2026-14）。"""
    rel = "report/result_json.py"
    ide_p = ide_root / "autopilot" / rel
    plat_p = platform_root / "autopilot_platform" / "ap" / rel
    for label, path in (("IDE", ide_p), ("Platform", plat_p)):
        text = path.read_text(encoding="utf-8")
        if 'item["case"] = cname' not in text:
            raise RuntimeError(f"{label} {rel}: 缺少 attachments.case 赋值")
        if 'item["case_name"] = cname' not in text:
            raise RuntimeError(
                f"{label} {rel}: 缺少 attachments.case_name 兼容别名（AUD-2026-14）"
            )


def check_mobile_destructive_risk_attrs(
    ide_root: Path, platform_root: Path
) -> None:
    """mobile.xml 允许故意分叉（录屏注释等），但高危关键字 risk_level 须一致（AUD-2026-09）。"""
    import re

    kids = (
        "mobile_app_adb_uninstall",
        "mobile_app_reset_saveinfo",
        "mobile_monkey",
    )

    def _levels(xml_path: Path) -> dict[str, str]:
        text = xml_path.read_text(encoding="utf-8")
        out: dict[str, str] = {}
        for keyword_id in kids:
            # 匹配 keyword 开标签上的 risk_level（允许属性顺序变化）
            m = re.search(
                rf'<keyword\b[^>]*\bid=["\']{re.escape(keyword_id)}["\'][^>]*>',
                text,
            )
            if not m:
                raise RuntimeError(f"{xml_path}: 缺少关键字 {keyword_id}")
            tag = m.group(0)
            rm = re.search(r"""risk_level=["']([^"']+)["']""", tag)
            out[keyword_id] = (rm.group(1) if rm else "").strip().lower()
        return out

    ide_xml = ide_root / "autopilot" / "metadata" / "keyword_defs" / "mobile.xml"
    plat_xml = (
        platform_root
        / "autopilot_platform"
        / "ap"
        / "metadata"
        / "keyword_defs"
        / "mobile.xml"
    )
    ide_lv = _levels(ide_xml)
    plat_lv = _levels(plat_xml)
    if ide_lv != plat_lv:
        raise RuntimeError(
            f"mobile 高危 risk_level 不一致: IDE={ide_lv} Platform={plat_lv}"
        )
    for kw_id, lv in ide_lv.items():
        if lv != "irreversible":
            raise RuntimeError(
                f"mobile 高危关键字未标 irreversible: {kw_id}={lv!r}"
            )


def check_mgmt_client_ops_sync(ide_root: Path, platform_root: Path) -> None:
    """MgmtClient HTTP 操作清单须与 Platform contracts 一致。"""
    import json
    import subprocess
    import sys

    plat_root = platform_root
    extract = plat_root / "tools" / "extract_mgmt_client_ops.py"
    manifest = plat_root / "contracts" / "mgmt_client_ops.json"
    if not extract.is_file() or not manifest.is_file():
        raise RuntimeError("Platform 缺少 mgmt_client_ops 工具或 manifest")

    ide_client = ide_root / "autopilot" / "mgmt" / "client.py"
    plat_client = plat_root / "autopilot_platform" / "ap" / "mgmt" / "client.py"
    py = sys.executable

    def _ops(client: Path) -> list:
        proc = subprocess.run(
            [py, str(extract), "--client", str(client)],
            cwd=str(plat_root),
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(proc.stdout)["operations"]

    if _ops(ide_client) != _ops(plat_client):
        raise RuntimeError("IDE 与 Platform MgmtClient HTTP 操作清单不一致")
    on_disk = json.loads(manifest.read_text(encoding="utf-8")).get("operations") or []
    if _ops(plat_client) != on_disk:
        raise RuntimeError(
            "contracts/mgmt_client_ops.json 过期；请运行 extract_mgmt_client_ops.py --write"
        )
    _check_pkg_file_sync(
        ide_root / "autopilot",
        platform_root / "autopilot_platform" / "ap",
        ["mgmt/client_ops_generated.py"],
        label="MgmtClient codegen stub",
    )


def check_engine_core_sync(ide_root: Path, platform_root: Path) -> None:
    """执行编排核须字节一致（含 on_context、intent meta 重试路径）。"""
    rels = [
        "engine/executor.py",
        "engine/suite.py",
        "engine/run/__init__.py",
        "engine/run/config.py",
        "engine/run/parallel.py",
        "engine/run/sequential.py",
        "runtime/port_allocator.py",
        "runtime/device_runtime.py",
        "runtime/device_session.py",
        "runtime/device_pool.py",
        "runtime/job_log.py",
        "keywords/mobile/appium_server.py",
    ]
    _check_pkg_file_sync(
        ide_root / "autopilot",
        platform_root / "autopilot_platform" / "ap",
        rels,
        label="执行编排核",
    )


def check_wda_press_button_timeout(ide_root: Path, platform_root: Path) -> None:
    """WDA Home/音量须 3s 超时（允许 wda_client.py 其它分叉，如远控 alert_buttons）。"""
    ide = (
        ide_root / "autopilot" / "keywords" / "mobile" / "wda_client.py"
    ).read_text(encoding="utf-8")
    plat = (
        platform_root
        / "autopilot_platform"
        / "ap"
        / "keywords"
        / "mobile"
        / "wda_client.py"
    ).read_text(encoding="utf-8")
    press = 'self._post("/wda/pressButton", {"name": name}, timeout=3.0)'
    extra = 'extra["timeout"] = timeout'
    missing: list[str] = []
    for label, text in (("IDE", ide), ("Platform", plat)):
        if press not in text:
            missing.append(f"{label} 缺 press_button timeout=3.0")
        if extra not in text:
            missing.append(f"{label} 缺 _request 单次 timeout 转发")
        if "def _post(self, path: str, body: dict, timeout: Optional[float] = None)" not in text:
            missing.append(f"{label} 缺 _post(..., timeout=)")
    if missing:
        raise RuntimeError("WDA press_button 超时语义对齐失败 — " + "; ".join(missing))


def check_mobile_session_semantics(ide_root: Path, platform_root: Path) -> None:
    """driver 允许包边界分叉，但会话关键行为须两边都有。"""
    ide = (ide_root / "autopilot" / "keywords" / "mobile" / "driver.py").read_text(
        encoding="utf-8"
    )
    plat = (
        platform_root
        / "autopilot_platform"
        / "ap"
        / "keywords"
        / "mobile"
        / "driver.py"
    ).read_text(encoding="utf-8")
    required = (
        "terminate_app(bundle_id)",
        "AUTOPILOT_INTENT_KEEP_WDA",
        "IOS_KEEP_WDA",
        "def mirror_control_sink",
        "_KEEP_WDA_MANAGERS",
    )
    missing: list[str] = []
    for needle in required:
        if needle not in ide:
            missing.append(f"IDE缺 {needle!r}")
        if needle not in plat:
            missing.append(f"Platform缺 {needle!r}")
    # Platform 无 inspector：须保持 stub，禁止误拷 IDE 的 ControlSink
    if "WdaControlSink" in plat or "AppiumControlSink" in plat:
        missing.append("Platform driver 不应依赖 IDE inspector ControlSink")
    sink_tail = plat.split("def mirror_control_sink", 1)[-1][:500]
    if "return None" not in sink_tail:
        missing.append("Platform mirror_control_sink 应保持 stub 返回 None")
    if missing:
        raise RuntimeError("移动会话语义对齐失败 — " + "; ".join(missing))


def check_mobile_xapk_semantics(ide_root: Path, platform_root: Path) -> None:
    """XAPK 装包路径须两边语义对齐（允许 PackageError import 分叉）。"""
    ide_xapk = ide_root / "autopilot" / "mobile" / "xapk.py"
    plat_xapk = platform_root / "autopilot_platform" / "ap" / "mobile" / "xapk.py"
    ide_sess = (
        ide_root / "autopilot" / "keywords" / "mobile" / "session.py"
    ).read_text(encoding="utf-8")
    plat_sess = (
        platform_root / "autopilot_platform" / "ap" / "keywords" / "mobile" / "session.py"
    ).read_text(encoding="utf-8")
    missing: list[str] = []
    if not ide_xapk.is_file():
        missing.append("IDE 缺 mobile/xapk.py")
    if not plat_xapk.is_file():
        missing.append("Platform 缺 ap/mobile/xapk.py")
    needles = (
        'ANDROID_PACKAGE_SUFFIXES = (".apk", ".apex", ".xapk")',
        "def extract_xapk_apks",
        "def install_android_package",
        "install-multiple",
        "install_android_package(",
        "primary_apk_for_parse",
    )
    for needle in needles:
        if needle not in ide_xapk.read_text(encoding="utf-8"):
            missing.append(f"IDE xapk 缺 {needle!r}")
        if needle not in plat_xapk.read_text(encoding="utf-8"):
            missing.append(f"Platform xapk 缺 {needle!r}")
    for needle in ('".xapk"', "install_android_package"):
        if needle not in ide_sess:
            missing.append(f"IDE session 缺 {needle!r}")
        if needle not in plat_sess:
            missing.append(f"Platform session 缺 {needle!r}")
    if missing:
        raise RuntimeError("XAPK 双仓语义对齐失败 — " + "; ".join(missing))


def check_settings_security_semantics(ide_root: Path, platform_root: Path) -> None:
    """凭证落盘语义对齐（允许 Platform 保留内联 ui_theme）。"""
    ide = (ide_root / "autopilot" / "runtime" / "settings.py").read_text(encoding="utf-8")
    plat = (
        platform_root / "autopilot_platform" / "ap" / "runtime" / "settings.py"
    ).read_text(encoding="utf-8")
    required = (
        "mc_api_token_enc",
        "mc_jwt_enc",
        "mc_refresh_enc",
        "def mc_org_id",
        'set_mc_refresh("")',
        "_dpapi_protect",
        "_harden_path_permissions",
        "_secret_keyring_store",
        "v2dpapi:",
    )
    missing: list[str] = []
    for needle in required:
        if needle not in ide:
            missing.append(f"IDE缺 {needle!r}")
        if needle not in plat:
            missing.append(f"Platform缺 {needle!r}")
    if missing:
        raise RuntimeError("settings 安全语义对齐失败 — " + "; ".join(missing))


def check_platform_ap_runtime_deps(platform_root: Path) -> None:
    """Platform ap 切片须具备 intent CLI/review 可达依赖（避免字节同步后假绿）。"""
    ap = platform_root / "autopilot_platform" / "ap"
    required_files = (
        "runtime/env_file.py",
        "mgmt/__init__.py",
        "mgmt/binding_coverage.py",
        "mgmt/logical_import.py",
        "mgmt/status_sync.py",
        "mgmt/auth_api.py",
        "mgmt/client.py",
        "inspector/__init__.py",
        "inspector/tree.py",
    )
    missing = [rel for rel in required_files if not (ap / rel).is_file()]
    if missing:
        raise RuntimeError(
            "Platform ap 缺少 intent 可达依赖 — " + ", ".join(missing)
        )

    # mgmt 子集与 IDE 字节一致（避免切片漂移）
    ide_mgmt = platform_root.parent / "AutoPilot" / "autopilot" / "mgmt"
    # platform_root 可能是 Autopilot-Platform；IDE 在 sibling AutoPilot
    ide_root_guess = platform_root.parent / "AutoPilot"
    if not ide_mgmt.is_dir():
        ide_mgmt = Path(__file__).resolve().parents[1] / "autopilot" / "mgmt"
        ide_root_guess = Path(__file__).resolve().parents[1]
    if ide_mgmt.is_dir():
        for name in (
            "binding_coverage.py",
            "logical_import.py",
            "status_sync.py",
            "auth_api.py",
            "client.py",
        ):
            a = ide_mgmt / name
            b = ap / "mgmt" / name
            if a.is_file() and b.is_file() and a.read_bytes() != b.read_bytes():
                raise RuntimeError(f"Platform ap/mgmt/{name} 与 IDE 内容不一致")
        # inspector/tree 与 IDE 同步
        ide_tree = ide_root_guess / "autopilot" / "inspector" / "tree.py"
        plat_tree = ap / "inspector" / "tree.py"
        if ide_tree.is_file() and plat_tree.is_file() and ide_tree.read_bytes() != plat_tree.read_bytes():
            raise RuntimeError("Platform ap/inspector/tree.py 与 IDE 内容不一致")

    import importlib
    import sys

    root = str(platform_root)
    inserted = False
    if root not in sys.path:
        sys.path.insert(0, root)
        inserted = True
    try:
        for mod in (
            "autopilot_platform.ap.runtime.env_file",
            "autopilot_platform.ap.mgmt.binding_coverage",
            "autopilot_platform.ap.inspector.tree",
            "autopilot_platform.ap.intent.cli",
            "autopilot_platform.ap.intent.review",
            "autopilot_platform.ap.intent.webhook_server",
            "autopilot_platform.ap.intent.ui_context",
        ):
            importlib.invalidate_caches()
            importlib.import_module(mod)
        # main() 入口依赖 env_file；--help 应可跑（argparse 可能 SystemExit）
        import contextlib
        import io

        cli = importlib.import_module("autopilot_platform.ap.intent.cli")
        buf = io.StringIO()
        code: int | None = 0
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                code = cli.main(["--help"])
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else None
        if code not in (0, None):
            raise RuntimeError(f"ap.intent.cli --help 异常退出码: {code}")

        review = importlib.import_module("autopilot_platform.ap.intent.review")
        # 空工程应安全返回，并真正走到 binding_coverage 懒加载
        import tempfile

        tmp = Path(tempfile.mkdtemp())
        path, rows = review.collect_failed_intents(tmp)
        if path is not None or rows:
            raise RuntimeError(
                f"collect_failed_intents 空工程期望 (None, [])，得到 ({path!r}, {rows!r})"
            )

        # ui_context 须能加载 Platform tree 解析器（走公开 inspector.tree 模块）
        tree = importlib.import_module("autopilot_platform.ap.inspector.tree")
        parse_android = getattr(tree, "parse_android", None)
        parse_ios = getattr(tree, "parse_ios", None)
        if parse_android is None or parse_ios is None:
            raise RuntimeError("Platform ap.inspector.tree 缺少 parse_android/parse_ios")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Platform ap intent 导入冒烟失败: {exc}") from exc
    finally:
        if inserted:
            try:
                sys.path.remove(root)
            except ValueError:
                pass


def check_jsonschema_sync(ide_root: Path, platform_root: Path) -> None:
    """公开 JSON Schema：Platform 为权威；IDE 须镜像同名文件且字节一致。"""
    ide_dir = ide_root / "contracts" / "jsonschema"
    plat_dir = platform_root / "contracts" / "jsonschema"
    if not plat_dir.is_dir():
        raise RuntimeError(f"Platform jsonschema 目录缺失: {plat_dir}")
    if not ide_dir.is_dir():
        raise RuntimeError(f"IDE jsonschema 目录缺失: {ide_dir}")
    plat_files = sorted(p.name for p in plat_dir.glob("*.json"))
    if not plat_files:
        raise RuntimeError("Platform contracts/jsonschema 无 *.json")
    missing: list[str] = []
    mismatched: list[str] = []
    for name in plat_files:
        a = ide_dir / name
        b = plat_dir / name
        if not a.is_file():
            missing.append(name)
            continue
        if a.read_bytes() != b.read_bytes():
            mismatched.append(name)
    ide_extra = sorted(
        p.name for p in ide_dir.glob("*.json") if p.name not in set(plat_files)
    )
    if missing or mismatched or ide_extra:
        parts = []
        if missing:
            parts.append("IDE 缺镜像: " + ", ".join(missing))
        if mismatched:
            parts.append("内容不一致: " + ", ".join(mismatched))
        if ide_extra:
            parts.append(
                "IDE 多余（须先协商进 Platform 权威目录）: " + ", ".join(ide_extra)
            )
        raise RuntimeError(
            "contracts/jsonschema 双仓同步失败 — "
            + "; ".join(parts)
            + "。权威在 Platform；改 schema 后须同步 IDE 镜像。"
        )


def check_contracts_version_file(ide_root: Path, platform_root: Path) -> None:
    """AUD-2026-16：公开契约 VERSION 双仓镜像（RUNTIME_PIN 仍仅 Platform）。"""
    ide_v = ide_root / "contracts" / "VERSION"
    plat_v = platform_root / "contracts" / "VERSION"
    if not plat_v.is_file():
        raise RuntimeError("Platform 缺 contracts/VERSION")
    if not ide_v.is_file():
        raise RuntimeError("IDE 缺 contracts/VERSION（须镜像 Platform）")
    if ide_v.read_text(encoding="utf-8").strip() != plat_v.read_text(encoding="utf-8").strip():
        raise RuntimeError(
            "contracts/VERSION 双仓不一致："
            f" IDE={ide_v.read_text(encoding='utf-8').strip()!r}"
            f" Platform={plat_v.read_text(encoding='utf-8').strip()!r}"
        )


def check_contracts(ide_root: Path, platform_root: Path) -> None:
    check_contracts_version_file(ide_root, platform_root)
    ide = json.loads(
        (ide_root / "contracts" / "runtime_contract.json").read_text(encoding="utf-8")
    )
    platform = json.loads(
        (platform_root / "contracts" / "runtime_contract.json").read_text(
            encoding="utf-8"
        )
    )
    if ide.get("schema_version") != platform.get("schema_version"):
        raise RuntimeError("runtime contract schema_version 不一致")
    ide_rv = str(ide.get("runtime_version") or "").strip()
    plat_rv = str(platform.get("runtime_version") or "").strip()
    try:
        ide_mm = _major_minor(ide_rv)
        plat_mm = _major_minor(plat_rv)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    if ide_mm != plat_mm:
        raise RuntimeError(
            "IDE 与 Platform runtime major.minor 不一致: "
            f"IDE={ide_rv!r} → {ide_mm[0]}.{ide_mm[1]}, "
            f"Platform={plat_rv!r} → {plat_mm[0]}.{plat_mm[1]}. "
            "公开契约 runtime_version 须用 canonical MAJOR.MINOR.PATCH（不加 -vendored）；"
            "Platform ap.__version__ / RUNTIME_PIN 才可带 -vendored 包装后缀。"
        )
    if ide_rv != plat_rv:
        # 兼容窗口：major.minor 已齐；字符串 DIFF 提示运维收敛到同一 canonical
        print(
            "DIFF: runtime_contract.runtime_version 字符串不一致但 major.minor 兼容 — "
            f"IDE={ide_rv!r} Platform={plat_rv!r}. "
            "请两边对齐为同一 canonical semver（勿把 -vendored 写入公开契约）。"
        )
    ide_caps = set(ide.get("capabilities") or [])
    platform_caps = set(platform.get("capabilities") or [])
    if ide_caps != platform_caps:
        raise RuntimeError(
            f"公开能力不一致: IDE-only={sorted(ide_caps - platform_caps)}, "
            f"Platform-only={sorted(platform_caps - ide_caps)}"
        )
    check_jsonschema_sync(ide_root, platform_root)
    check_http_keyword_sync(ide_root, platform_root)
    check_job_platforms_sync(ide_root, platform_root)
    check_web_keyword_sync(ide_root, platform_root)
    check_intent_stack_sync(ide_root, platform_root)
    check_keywords_registry_sync(ide_root, platform_root)
    check_data_ssh_keyword_sync(ide_root, platform_root)
    check_mobile_destructive_risk_attrs(ide_root, platform_root)
    check_report_modules_sync(ide_root, platform_root)
    check_result_json_attachment_case_alias(ide_root, platform_root)
    check_safe_zip_security_semantics(ide_root, platform_root)
    check_mgmt_client_ops_sync(ide_root, platform_root)
    check_engine_core_sync(ide_root, platform_root)
    check_mobile_session_semantics(ide_root, platform_root)
    check_wda_press_button_timeout(ide_root, platform_root)
    check_mobile_xapk_semantics(ide_root, platform_root)
    check_settings_security_semantics(ide_root, platform_root)
    check_platform_ap_runtime_deps(platform_root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ide-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--platform-root",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "Autopilot-Platform",
    )
    args = parser.parse_args()
    check_contracts(args.ide_root.resolve(), args.platform_root.resolve())
    print("dual-repo contracts VERSION: OK")
    print("dual-repo runtime contract: OK")
    print("dual-repo jsonschema sync: OK")
    print("dual-repo http keywords sync: OK")
    print("dual-repo job_platforms sync: OK")
    print("dual-repo web keywords sync: OK")
    print("dual-repo intent stack sync: OK")
    print("dual-repo data/ssh keywords sync: OK")
    print("dual-repo mobile destructive risk attrs: OK")
    print("dual-repo report modules sync: OK")
    print("dual-repo result_json attachment case alias: OK")
    print("dual-repo safe_zip security semantics: OK")
    print("dual-repo engine core sync: OK")
    print("dual-repo mobile session semantics: OK")
    print("dual-repo wda press_button timeout: OK")
    print("dual-repo mobile xapk semantics: OK")
    print("dual-repo settings security semantics: OK")
    print("dual-repo platform ap runtime deps: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
