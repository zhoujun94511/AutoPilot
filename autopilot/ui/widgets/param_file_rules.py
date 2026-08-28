"""步骤参数：本地文件路径的规则、文件对话框过滤器与扩展名校验。

按 (keyword_id, param_id) 登记；运行时可结合步骤平台（如 appFile 的 .apk/.ipa）
解析过滤器与允许的后缀。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from ...model.testcase import Step
from .step_param_rules import effective_platform

# 含变量引用或表达式时跳过扩展名校验（仍允许手填 COLUMN / ${var} 等）
_DYNAMIC_MARKERS = ("${", "COLUMN(", "VAR_", "DATATABLE(", "STR.")


@dataclass(frozen=True)
class FileParamSpec:
    """本地文件参数字段规格。"""

    kind: str
    dialog_title: str = "选择文件"
    save_dialog: bool = False


_KIND_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "mobile_app_ios": (".ipa",),
    "mobile_app_android": (".apk", ".apex", ".xapk"),
    "mobile_app_any": (".apk", ".apex", ".xapk", ".ipa"),
    "image_png": (".png",),
    "csv": (".csv",),
    "excel": (".xls", ".xlsx"),
    "json": (".json",),
    "xml": (".xml",),
    "text": (".txt",),
    "yaml_case": (".tc.yaml", ".yaml", ".yml"),
    "any": (),
}

_DIALOG_FILTERS: dict[str, str] = {
    "mobile_app_ios": "iOS 应用 (*.ipa)",
    "mobile_app_android": "Android 应用 (*.apk *.apex *.xapk)",
    "mobile_app_any": "安装包 (*.apk *.apex *.xapk *.ipa)",
    "image_png": "PNG 图片 (*.png)",
    "csv": "CSV (*.csv)",
    "excel": "Excel (*.xls *.xlsx)",
    "json": "JSON (*.json)",
    "xml": "XML (*.xml)",
    "text": "文本 (*.txt)",
    "yaml_case": "用例 (*.tc.yaml *.yaml *.yml)",
    "any": "所有文件 (*)",
}

# (keyword_id, param_id) → 规格；仅登记「本机可选文件」类参数（不含纯远程路径）
_EXACT_RULES: dict[tuple[str, str], FileParamSpec] = {
    # --- Mobile ---
    ("mobile_app_install_and_open", "appFile"): FileParamSpec("mobile_app", "选择安装包"),
    ("mobile_app_get_package_and_activity", "appFile"): FileParamSpec("mobile_app", "选择安装包"),
    ("mobile_SDK_ergodic", "appFile"): FileParamSpec("mobile_app", "选择安装包"),
    ("mobile_app_snapshot", "fileName"): FileParamSpec("image_png", "保存截图", save_dialog=True),
    ("mobile_pull_file_to_mobile", "path"): FileParamSpec("any", "选择本地文件"),
    # --- WebUI ---
    ("web_browser_snapshot", "fileName"): FileParamSpec("image_png", "保存截图", save_dialog=True),
    ("web_element_uploadfile_common", "text"): FileParamSpec("any", "选择上传文件"),
    # --- HTTP ---
    ("http_post_Multipart", "filePath"): FileParamSpec("any", "选择上传文件"),
    ("http_get_download", "file_path"): FileParamSpec("any", "保存文件", save_dialog=True),
    ("http_get_download", "download_file_path"): FileParamSpec("any", "保存下载文件", save_dialog=True),
    ("json_load_json_file", "path"): FileParamSpec("json", "选择 JSON 文件"),
    ("json_load_json_file_fastjson", "path"): FileParamSpec("json", "选择 JSON 文件"),
    ("xml_load_xml_file", "path"): FileParamSpec("xml", "选择 XML 文件"),
    # --- Public / 文件与传输 ---
    ("read_file", "path"): FileParamSpec("any", "选择文件"),
    ("redis_del_RedisKeyFromFile", "filePath"): FileParamSpec("text", "选择 key 列表文件"),
    ("linux_ssh_sftp_fileUpload", "srcFile"): FileParamSpec("any", "选择待上传文件"),
    ("linux_ssh_sftp_fileDownload", "dstFile"): FileParamSpec("any", "选择保存位置", save_dialog=True),
    ("ftp_ftpclient_uploadFile", "localFile"): FileParamSpec("any", "选择待上传文件"),
    ("ftp_ftpclient_downloadFile", "localFile"): FileParamSpec("any", "选择保存位置", save_dialog=True),
    ("common_CSVFile_create", "filePath"): FileParamSpec("csv", "保存 CSV 文件", save_dialog=True),
    ("common_excel_editCellValue", "filePath"): FileParamSpec("excel", "选择 Excel 文件"),
    ("common_excel_writeCellValue", "filePath"): FileParamSpec("excel", "选择 Excel 文件"),
    ("common_excel_readCellValue", "filePath"): FileParamSpec("excel", "选择 Excel 文件"),
    ("common_excel_delRow", "filePath"): FileParamSpec("excel", "选择 Excel 文件"),
}

_INNERCASE_PATH = FileParamSpec("yaml_case", "选择用例文件")


def is_dynamic_path(value: str) -> bool:
    """是否为变量/表达式路径（不做扩展名硬校验）。"""
    s = (value or "").strip()
    if not s:
        return True
    return any(m in s for m in _DYNAMIC_MARKERS)


def path_extension(value: str) -> str:
    base = os.path.basename(str(value).strip().strip('"'))
    _, ext = os.path.splitext(base)
    return ext.lower()


def file_param_spec(keyword_id: str, param_id: str) -> Optional[FileParamSpec]:
    return _EXACT_RULES.get((keyword_id, param_id))


def innercase_path_spec() -> FileParamSpec:
    return _INNERCASE_PATH


def iter_file_param_rules() -> list[tuple[str, str, FileParamSpec]]:
    return [(kid, pid, spec) for (kid, pid), spec in sorted(_EXACT_RULES.items())]


def _resolve_kind(spec: FileParamSpec, step: Optional[Step], case_platform: str) -> str:
    if spec.kind != "mobile_app":
        return spec.kind
    if step is not None:
        plat = effective_platform(step, case_platform)
    else:
        plat = (case_platform or "").strip().lower()
    if plat.startswith("ios"):
        return "mobile_app_ios"
    if plat.startswith("android"):
        return "mobile_app_android"
    return "mobile_app_any"


def resolve_extensions(
    spec: FileParamSpec,
    step: Optional[Step] = None,
    case_platform: str = "",
) -> tuple[str, ...]:
    kind = _resolve_kind(spec, step, case_platform)
    return _KIND_EXTENSIONS.get(kind, ())


def resolve_dialog_filter(
    spec: FileParamSpec,
    step: Optional[Step] = None,
    case_platform: str = "",
) -> str:
    kind = _resolve_kind(spec, step, case_platform)
    return _DIALOG_FILTERS.get(kind, "所有文件 (*)")


def validate_literal_path(
    value: str,
    spec: FileParamSpec,
    step: Optional[Step] = None,
    case_platform: str = "",
) -> Optional[str]:
    """校验手填/浏览得到的字面路径；通过或跳过时返回 None，否则返回错误说明。"""
    s = (value or "").strip()
    if not s or is_dynamic_path(s):
        return None
    allowed = resolve_extensions(spec, step, case_platform)
    if not allowed:
        return None
    ext = path_extension(s)
    if not ext:
        return None
    if ext not in allowed:
        hint = "、".join(allowed)
        return f"文件类型不符：当前为「{ext}」，需要 {hint}"
    return None


def kind_label(spec: FileParamSpec, step: Optional[Step] = None, case_platform: str = "") -> str:
    """人类可读的类型说明（用于 tooltip）。"""
    exts = resolve_extensions(spec, step, case_platform)
    if not exts:
        return "任意本地文件"
    return "、".join(exts)
