"""Dataset statistics for `kiln data inspect`."""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path

from kiln.data.formats import DataFormat, detect_format, detect_row, read_jsonl


@dataclass(frozen=True)
class DatasetStats:
    rows: int
    format: DataFormat | None
    unrecognized: int
    duplicates: int
    output_chars_min: int | None
    output_chars_median: float | None
    output_chars_max: int | None
    est_tokens_total: int  # chars/4 heuristic — honest estimate, not tokenizer count

    def render(self) -> str:
        lines = [
            f"rows          : {self.rows}",
            f"format        : {self.format.value if self.format else 'unrecognized'}",
        ]
        if self.unrecognized:
            lines.append(f"unrecognized  : {self.unrecognized} row(s)")
        if self.duplicates:
            lines.append(f"duplicates    : {self.duplicates}")
        if self.output_chars_median is not None:
            lines.extend(
                [
                    f"output chars  : min={self.output_chars_min}"
                    f" median={self.output_chars_median:.0f} max={self.output_chars_max}",
                    f"~tokens total : {self.est_tokens_total:,} (chars/4 heuristic)",
                ]
            )
        return "\n".join(lines)


def _output_text(fmt: DataFormat | None, row: dict) -> str | None:
    if fmt is DataFormat.ALPACA:
        text = row.get("output")
        return text if isinstance(text, str) else None
    if fmt is DataFormat.CHATML:
        msgs = row.get("messages")
        if isinstance(msgs, list):
            parts = [
                m.get("content", "")
                for m in msgs
                if isinstance(m, dict) and m.get("role") == "assistant"
            ]
            return "".join(p for p in parts if isinstance(p, str)) or None
    if fmt is DataFormat.SHAREGPT:
        convs = row.get("conversations")
        if isinstance(convs, list):
            parts = [
                c.get("value", "")
                for c in convs
                if isinstance(c, dict) and c.get("from") == "gpt"
            ]
            return "".join(p for p in parts if isinstance(p, str)) or None
    return None


def inspect_file(path: str | Path) -> DatasetStats:
    rows = read_jsonl(path)
    sample = rows[:200]
    fmt = detect_format([r for r, _ in sample])
    recognized_fmts = [detect_row(r) for r, _ in rows]
    unrecognized = sum(1 for f in recognized_fmts if f is None)

    outputs = []
    seen: set[str] = set()
    dupes = 0
    total_chars = 0
    for (row, _) in rows:
        key = json.dumps(row, sort_keys=True, default=str)
        if key in seen:
            dupes += 1
        seen.add(key)
        text = _output_text(fmt, row)
        if text is not None:
            outputs.append(len(text))
            total_chars += len(text)

    return DatasetStats(
        rows=len(rows),
        format=fmt,
        unrecognized=unrecognized,
        duplicates=dupes,
        output_chars_min=min(outputs) if outputs else None,
        output_chars_median=statistics.median(outputs) if outputs else None,
        output_chars_max=max(outputs) if outputs else None,
        est_tokens_total=total_chars // 4,
    )
