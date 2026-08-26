"""Dataset stats for `kiln data inspect`."""

from __future__ import annotations

import json
from pathlib import Path

from kiln.data.stats import inspect_file


def test_stats_on_chatml(tmp_path: Path):
    row = {
        "messages": [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "abcd" * 10},  # 40 chars
        ]
    }
    p = tmp_path / "d.jsonl"
    p.write_text(json.dumps(row) + "\n", encoding="utf-8")
    stats = inspect_file(p)
    assert stats.rows == 1
    assert stats.format.value == "chatml"
    assert stats.output_chars_max == 40
    assert stats.est_tokens_total == 10  # 40 // 4


def test_stats_counts_duplicates_and_unrecognized(tmp_path: Path):
    good = {"instruction": "q", "output": "a"}
    p = tmp_path / "d.jsonl"
    lines = [json.dumps(good), json.dumps(good), json.dumps({"weird": True})]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    stats = inspect_file(p)
    assert stats.rows == 3
    assert stats.duplicates == 1
    assert stats.unrecognized == 1
