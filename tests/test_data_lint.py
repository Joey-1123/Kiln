"""Lint rules must fail loud with row numbers on real problems."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kiln.data.lint import lint_file


def _write(tmp_path: Path, rows: list[dict], name="d.jsonl") -> Path:
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


def test_clean_chatml_passes(tmp_path):
    row = {"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]}
    issues, fmt = lint_file(_write(tmp_path, [row]))
    assert fmt.value == "chatml"
    assert issues == []


def test_zero_loss_target_detected_chatml(tmp_path):
    """The canonical bug: no assistant turn anywhere -> zero loss targets."""
    row = {"messages": [{"role": "user", "content": "q"}, {"role": "user", "content": "q2"}]}
    issues, _ = lint_file(_write(tmp_path, [row]))
    assert any(i.rule == "no-loss-target" and i.line == 1 for i in issues)


def test_zero_loss_target_detected_alpaca(tmp_path):
    row = {"instruction": "2+2?", "output": ""}
    issues, fmt = lint_file(_write(tmp_path, [row]))
    assert fmt.value == "alpaca"
    assert any(i.rule == "no-loss-target" and i.line == 1 for i in issues)


def test_invalid_role_reports_index(tmp_path):
    row = {
        "messages": [
            {"role": "wizard", "content": "q"},
            {"role": "assistant", "content": "a"},
        ]
    }
    issues, _ = lint_file(_write(tmp_path, [row]))
    assert any("invalid role 'wizard'" in i.message for i in issues)


def test_sharegpt_missing_gpt_turn(tmp_path):
    row = {"conversations": [{"from": "human", "value": "hi"}]}
    issues, fmt = lint_file(_write(tmp_path, [row]))
    assert fmt.value == "sharegpt"
    assert any(i.rule == "no-loss-target" for i in issues)


def test_duplicates_flagged_file_level(tmp_path):
    row = {"instruction": "q", "output": "a"}
    issues, _ = lint_file(_write(tmp_path, [row, dict(row)]))
    dupes = [i for i in issues if i.rule == "duplicates"]
    assert len(dupes) == 1 and "1 duplicate" in dupes[0].message


def test_malformed_json_raises_with_line_number(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text('{"ok": 1}\n{broken\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        lint_file(p)


def test_unknown_format_reported_not_crashed(tmp_path):
    p = tmp_path / "odd.jsonl"
    p.write_text('{"foo": "bar"}\n', encoding="utf-8")
    issues, fmt = lint_file(p)
    assert fmt is None
    assert any(i.rule == "unknown-format" for i in issues)
