"""参数表单多行报文体（HTTP request / XML）回归。"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_APP = None


def _ensure_app():
    global _APP
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication([])
    return _APP


def test_multiline_rules() -> bool:
    from autopilot.ui.widgets.param_multiline_rules import is_multiline_param
    ok = (
        is_multiline_param("request")
        and is_multiline_param("xmlStr")
        and not is_multiline_param("request", is_output=True)
        and not is_multiline_param("request", label="请求报文[OUT]")
        and not is_multiline_param("url")
        and not is_multiline_param("textBody")
    )
    print("多行规则白名单:", "✅" if ok else "❌")
    return ok


def test_param_form_multiline_editors() -> bool:
    _ensure_app()
    from PyQt6.QtWidgets import QLineEdit, QPlainTextEdit, QComboBox
    from autopilot.model.testcase import Step, ParamValue
    from autopilot.metadata import KeywordMeta, ParamMeta
    from autopilot.ui.widgets.param_form import ParamForm

    pf = ParamForm()
    meta = KeywordMeta(
        keyword_id="http_post",
        name="HTTP POST",
        category="Http",
        params=[
            ParamMeta(param_id="url", name="URL", required=True),
            ParamMeta(param_id="request", name="请求消息体", required=False),
            ParamMeta(param_id="method", name="方法", values=["POST", "PUT"]),
            ParamMeta(param_id="resp", name="响应[OUT]", is_output=True),
        ],
    )
    # 输出参数同名 request 场景：用单独表单测 is_output
    step = Step("http_post", params=[
        ParamValue("url", "http://x"),
        ParamValue("request", "{\n  \"a\": 1\n}"),
    ])
    pf.show_step(step, meta, columns=["colA"])
    row_req = pf._param_rows.get("request")
    row_url = pf._param_rows.get("url")
    eds_req = row_req.findChildren(QPlainTextEdit) if row_req else []
    eds_url = row_url.findChildren(QLineEdit) if row_url else []
    ok_types = bool(eds_req) and bool(eds_url) and not row_url.findChildren(QPlainTextEdit)

    body = "{\n  \"x\": 2\n}"
    eds_req[0].setPlainText(body)
    ok_write = step.param("request") == body

    ParamForm._insert_column(eds_req[0], "colA")
    ok_col = step.param("request") == "COLUMN(colA,)"

    # OUT request → 单行
    meta_out = KeywordMeta(
        keyword_id="esb_x",
        name="esb",
        category="Http",
        params=[ParamMeta(param_id="request", name="请求报文[OUT]", is_output=True)],
    )
    step2 = Step("esb_x", params=[ParamValue("request", "v")])
    pf.show_step(step2, meta_out)
    row2 = pf._param_rows.get("request")
    ok_out = bool(row2 and row2.findChildren(QLineEdit)) and not row2.findChildren(QPlainTextEdit)

    # xmlStr
    meta_xml = KeywordMeta(
        keyword_id="xml_write",
        name="写XML",
        category="Http",
        params=[ParamMeta(param_id="xmlStr", name="xml字符串")],
    )
    step3 = Step("xml_write", params=[])
    pf.show_step(step3, meta_xml)
    row3 = pf._param_rows.get("xmlStr")
    ok_xml = bool(row3 and row3.findChildren(QPlainTextEdit))

    # 枚举仍为 Combo
    pf.show_step(step, meta)
    row_m = pf._param_rows.get("method")
    ok_combo = bool(row_m and row_m.findChildren(QComboBox))

    ok = ok_types and ok_write and ok_col and ok_out and ok_xml and ok_combo
    print("参数表单多行编辑:", "✅" if ok else "❌",
          dict(types=ok_types, write=ok_write, col=ok_col, out=ok_out, xml=ok_xml, combo=ok_combo))
    return ok


def main() -> int:
    ok = all([test_multiline_rules(), test_param_form_multiline_editors()])
    print("\n总结:", "✅" if ok else "❌")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
