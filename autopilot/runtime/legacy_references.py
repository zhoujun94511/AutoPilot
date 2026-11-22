"""Rename references in legacy project XML without converting its format."""

from __future__ import annotations

from collections.abc import Callable
import io
import os
from pathlib import Path
import re
import shutil
import tempfile

from lxml import etree


RebaseReference = Callable[[str, str, str, str, str], tuple[str, bool]]


def _map_stem(path: str) -> str:
    name = os.path.basename(path)
    for suffix in (".map.yaml", ".map.yml", ".map"):
        if name.lower().endswith(suffix):
            return name[:-len(suffix)]
    return ""


def rewrite_legacy_references(path: str, project_root: str, old: str, new: str,
                              rebase: RebaseReference) -> bool:
    """Update only known reference nodes; retain XML extensions and comments."""
    original = Path(path).read_bytes()
    parser = etree.XMLParser(resolve_entities=False, remove_blank_text=False, strip_cdata=False)
    try:
        tree = etree.parse(io.BytesIO(original), parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError("无法解析旧格式 XML，未检查路径引用") from exc
    root = tree.getroot()
    source_before, _ = rebase(path, "", "", new, old)
    project_before, _ = rebase(project_root, "", "", new, old)
    old_source_base = os.path.dirname(source_before)
    new_source_base = os.path.dirname(path)
    is_plan = path.lower().endswith(".tp")
    old_map, new_map = _map_stem(old), _map_stem(new)
    map_marker = f"map::{old_map}::" if old_map and new_map and not os.path.isdir(new) else ""
    changed = False

    def rewrite_path(raw_value: str, *, source_relative: bool = False,
                     allow_config: bool = False) -> str:
        raw = str(raw_value or "")
        if not raw.strip() or "${" in raw or "COLUMN(" in raw:
            return raw_value
        old_base = old_source_base if source_relative else project_before
        new_base = new_source_base if source_relative else project_root
        updated, matched = rebase(raw, old_base, new_base, old, new)
        if not matched and allow_config:
            updated, matched = rebase("config/" + raw.strip(), old_base, new_base, old, new)
        if not matched:
            return raw_value
        left = raw[:len(raw) - len(raw.lstrip())]
        right = raw[len(raw.rstrip()):]
        return left + updated + right

    def rewrite_datapool(raw_value: str) -> str:
        text = str(raw_value or "")
        match = re.match(r"^(\s*DATATABLE\s*\()(.*)(\)\s*)$", text, re.IGNORECASE | re.DOTALL)
        if match is None:
            return raw_value
        inner = match.group(2)
        source, separator, private = inner.rpartition(",")
        if not separator:
            source = inner
        if source.strip().upper() == "NONE":
            return raw_value
        updated = rewrite_path(source)
        if updated == source:
            return raw_value
        return match.group(1) + updated + (separator + private if separator else "") + match.group(3)

    def set_text(node, text_value: str) -> None:
        nonlocal changed
        if text_value != node.text:
            node.text = text_value
            changed = True

    def set_attribute(node, name: str, text_value: str) -> None:
        nonlocal changed
        if text_value != node.get(name):
            node.set(name, text_value)
            changed = True

    for element in root.iter():
        if element.tag == "stepinnercase" and element.get("relativepath"):
            set_attribute(element, "relativepath", rewrite_path(
                element.get("relativepath"), source_relative=True))
        if element.get("datapool"):
            set_attribute(element, "datapool", rewrite_datapool(element.get("datapool")))
        if element.tag == "datapool" and element.text:
            set_text(element, rewrite_datapool(element.text))
        parent = element.getparent()
        if element.tag == "param" and parent is not None and parent.tag in {"step", "stepverbs"}:
            value = element.text or ""
            if map_marker:
                value = value.replace(map_marker, f"map::{new_map}::")
            if value.strip().startswith("picture::"):
                prefix, _, image = value.partition("picture::")
                value = prefix + "picture::" + rewrite_path(image)
            elif element.get("id") in {"appFile", "datapool_source_path"}:
                value = rewrite_path(value)
            if value != (element.text or ""):
                set_text(element, value)
        if is_plan and element.tag in {"member", "case"}:
            if element.get("relativepath"):
                set_attribute(element, "relativepath", rewrite_path(element.get("relativepath")))
            elif element.text:
                set_text(element, rewrite_path(element.text))
        if is_plan and element.tag == "dataconfig" and element.text:
            set_text(element, rewrite_path(element.text, allow_config=True))

    if not changed:
        return False
    declaration = re.match(r"<\?xml\b.*?\?>", original.decode(tree.docinfo.encoding or "UTF-8").lstrip("\ufeff"),
                           re.DOTALL)
    write_options = {"encoding": tree.docinfo.encoding or "UTF-8", "xml_declaration": declaration is not None}
    if declaration:
        standalone = re.search(r"\bstandalone\s*=\s*(['\"])(yes|no)\1", declaration.group())
        if standalone:
            write_options["standalone"] = standalone.group(2) == "yes"
    staged = ""
    try:
        with tempfile.NamedTemporaryFile(prefix=".autopilot-refs-", dir=os.path.dirname(path),
                                         suffix=".xml", delete=False) as output:
            staged = output.name
            tree.write(output, **write_options)
        shutil.copymode(path, staged)
        os.replace(staged, path)
    finally:
        if staged and os.path.exists(staged):
            os.unlink(staged)
    return True
