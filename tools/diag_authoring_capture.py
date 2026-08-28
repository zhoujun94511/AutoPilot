"""链路 3 采页取证：把「模型实际看到的页面」原样打出来。

模型规划跑偏时，先看它拿到的是什么，而不是猜。输出三段：
原始控件（type/name/label/value/rect）、compact 摘要（送模型的内容）、
以及是否按预算裁剪。

用法::

    python tools/diag_authoring_capture.py [自然语言] [max_elements]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from autopilot.authoring.capture import capture_settled_ui_context  # noqa: E402
from autopilot.authoring.contract import (  # noqa: E402
    AuthoringError,
    AuthoringRequest,
    GeneratedStep,
)
from autopilot.authoring.nl_parse import parse_nl_hints  # noqa: E402
from autopilot.authoring.session_bootstrap import (  # noqa: E402
    BootstrapResult,
    prepare_authoring_session,
    release_authoring_session,
)
from autopilot.authoring.step_runner import execute_keyword_step  # noqa: E402
from autopilot.intent.ui_context import collect_ui_elements  # noqa: E402
from autopilot.keywords.context import ExecutionContext  # noqa: E402


def _print_release_notes(ctx: ExecutionContext, *, reused: bool) -> None:
    notes = release_authoring_session(ctx, reused=reused)
    for note in notes:
        print(f"[release] {note}")


def _run_capture(boot: BootstrapResult, ctx: ExecutionContext, max_elements: int) -> int:
    """执行采页取证；成功返回 0，AuthoringError 打印后返回 1。"""
    try:
        if boot.request.package_name and boot.request.platform in ("ios", "android"):
            execute_keyword_step(
                GeneratedStep(
                    keyword_id="mobile_app_start",
                    params={
                        "type": boot.request.platform,
                        "packageName": boot.request.package_name,
                        "activityName": boot.request.activity_name or "",
                    },
                ),
                ctx,
            )
        plat = boot.request.platform or "ios"
        cap = capture_settled_ui_context(ctx, plat, max_elements=max_elements)
        raw = collect_ui_elements(ctx, platform=plat)
        print(f"[raw] total={len(raw)} screen={cap.get('screen')}")
        for i, el in enumerate(raw):
            print(
                f"[raw] {i:>3} type={el.get('type') or el.get('tag')} "
                f"name={el.get('name')!r} label={el.get('label')!r} "
                f"text={el.get('text')!r} editable={el.get('editable')} "
                f"clickable={el.get('clickable')} rect={el.get('bounds')}"
            )
        compact = json.loads(str(cap.get("elements_text") or "[]"))
        print(
            f"[compact] sent={len(compact)} max_elements={max_elements} "
            f"raw_total={len(raw)}"
        )
        for i, item in enumerate(compact):
            print(f"[compact] {i:>3} {json.dumps(item, ensure_ascii=False)}")
        return 0
    except AuthoringError as exc:
        print(f"[FAIL] {exc}")
        return 1


def main(argv: list[str]) -> int:
    nl = argv[1] if len(argv) > 1 else "打开当前应用首页"
    max_elements = int(argv[2]) if len(argv) > 2 else 50
    hints = parse_nl_hints(nl)
    req = AuthoringRequest(
        natural_language=nl,
        platform=hints.platform or "",
        mode="session",
        app_label=hints.app_name,
    )
    boot = prepare_authoring_session(req)
    print(f"[bootstrap] {boot.request.app_label} ({boot.request.package_name})")
    print(f"[bootstrap] platform={boot.request.platform}")

    ctx = boot.ctx
    try:
        code = _run_capture(boot, ctx, max_elements)
    finally:
        _print_release_notes(ctx, reused=boot.reused_ctx)
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
