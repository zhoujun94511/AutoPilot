"""G8：Intent CLI webhook 文档契约。"""

from __future__ import annotations

from autopilot.intent.cli import CLI_WEBHOOK_EPILOG, build_parser


def test_cli_webhook_epilog():
    assert "serve-webhook" in CLI_WEBHOOK_EPILOG
    assert "MC_DESIGN_WEBHOOK_URL" in CLI_WEBHOOK_EPILOG
    assert "--sync-status" in CLI_WEBHOOK_EPILOG


def test_serve_webhook_parser_help():
    import argparse

    p = build_parser()
    for action in p._actions:
        if isinstance(action, argparse._SubParsersAction):
            sub = action.choices.get("serve-webhook")
            assert sub is not None
            assert "MC_DESIGN_WEBHOOK_URL" in (sub.description or "")
            return
    raise AssertionError("serve-webhook subparser not found")


def test_webhook_server_module_doc():
    import autopilot.intent.webhook_server as wh

    doc = wh.__doc__ or ""
    assert "serve-webhook" in doc
    assert "--sync-status" in doc
