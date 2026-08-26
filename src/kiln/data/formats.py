"""Dataset format auto-detection from row shape (not filename)."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path


class DataFormat(str, Enum):
    ALPACA = "alpaca"
    CHATML = "chatml"  # {messages: [{role, content}, ...]}
    SHAREGPT = "sharegpt"  # {conversations: [{from, value}, ...]}
    PLAIN = "plain"


def detect_row(row: dict) -> DataFormat | None:
    """Classify one JSON object into a format; None if unrecognized."""
    keys = set(row)
    if {"instruction", "output"} <= keys:
        return DataFormat.ALPACA
    if "messages" in keys and isinstance(row["messages"], list):
        return DataFormat.CHATML
    if "conversations" in keys and isinstance(row["conversations"], list):
        return DataFormat.SHAREGPT
    return None


def detect_format(rows: list[dict]) -> DataFormat | None:
    """Detect the dominant format across sample rows.

    Returns None when no row is recognizable. Mixed formats resolve to the
    majority vote among recognized rows.
    """
    counts: dict[DataFormat, int] = {}
    for row in rows:
        fmt = detect_row(row)
        if fmt is not None:
            counts[fmt] = counts.get(fmt, 0) + 1
    if not counts:
        return None
    best = max(counts.items(), key=lambda kv: kv[1])
    return best[0]


def read_jsonl(
    path: str | Path,
) -> list[tuple[dict, int]]:
    """Parse a JSONL file into (row, lineno) pairs.

    Raises ValueError with a human-facing line number on malformed JSON.
    """
    rows: list[tuple[dict, int]] = []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {lineno}: invalid JSON ({exc.msg})") from exc
            if not isinstance(row, dict):
                raise ValueError(f"line {lineno}: expected a JSON object, got {type(row).__name__}")
            rows.append((row, lineno))
    return rows
