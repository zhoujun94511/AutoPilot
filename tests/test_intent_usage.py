"""Intent Vision usage 记录。"""

from __future__ import annotations

import json
from pathlib import Path

from autopilot.intent.usage import extract_usage, record_vision_usage


def test_extract_usage():
    assert extract_usage({"usage": {"prompt_tokens": 3, "completion_tokens": 2}})[
        "total_tokens"
    ] == 5


def test_extract_usage_cache_fields():
    u = extract_usage(
        {
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 5,
                "prompt_tokens_details": {"cached_tokens": 15},
            }
        }
    )
    assert u["cached_tokens"] == 15
    assert u["cache_miss_tokens"] == 0

    ds = extract_usage(
        {
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 1,
                "prompt_cache_hit_tokens": 12,
                "prompt_cache_miss_tokens": 8,
            }
        }
    )
    assert ds["cached_tokens"] == 12
    assert ds["cache_miss_tokens"] == 8


def test_record_vision_usage(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOPILOT_VISION_USAGE_DIR", str(tmp_path))
    u = record_vision_usage(
        {
            "prompt_tokens": 11,
            "completion_tokens": 4,
            "total_tokens": 15,
            "cached_tokens": 7,
        },
        model="gpt-4o-mini",
    )
    assert u["total_tokens"] == 15
    assert u["cached_tokens"] == 7
    files = list(Path(tmp_path).glob("usage-*.jsonl"))
    assert len(files) == 1
    row = json.loads(files[0].read_text(encoding="utf-8").strip())
    assert row["source"] == "vision"
    assert row["usage"]["prompt_tokens"] == 11
    assert row["usage"]["cached_tokens"] == 7
