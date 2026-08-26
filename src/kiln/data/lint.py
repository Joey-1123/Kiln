"""Data lint: fail loud with human-facing row numbers before GPU hours burn.

The canonical bug this exists to prevent is Soup's "assistant-only masking
trained on zero tokens": a dataset where no row has an assistant/output turn
produces a perfectly healthy-looking loss curve while teaching nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from kiln.data.formats import DataFormat, detect_format, read_jsonl

VALID_ROLES = {"system", "user", "assistant"}
SHAREGPT_VALID_FROM = {"human", "gpt", "system"}


@dataclass(frozen=True)
class LintIssue:
    line: int  # 0 = file-level issue
    rule: str
    message: str

    def render(self) -> str:
        where = f"line {self.line}" if self.line else "file"
        return f"[{self.rule}] {where}: {self.message}"


def _lint_alpaca(row: dict, lineno: int, issues: list[LintIssue]) -> None:
    if not str(row.get("instruction", "")).strip():
        issues.append(LintIssue(lineno, "empty-instruction", "instruction is empty"))
    if not str(row.get("output", "")).strip():
        issues.append(
            LintIssue(
                lineno,
                "no-loss-target",
                "output is empty; this row contributes zero loss targets",
            )
        )


def _lint_chatml(row: dict, lineno: int, issues: list[LintIssue]) -> None:
    messages = row.get("messages")
    if not isinstance(messages, list) or not messages:
        issues.append(LintIssue(lineno, "missing-messages", "messages must be a non-empty list"))
        return
    roles = [m.get("role") for m in messages if isinstance(m, dict)]
    for i, role in enumerate(roles):
        if role not in VALID_ROLES:
            issues.append(
                LintIssue(lineno, "invalid-role", f"messages[{i}] has invalid role {role!r}")
            )
    if "assistant" not in roles:
        issues.append(
            LintIssue(
                lineno,
                "no-loss-target",
                "no assistant turn; this row contributes zero loss targets",
            )
        )


def _lint_sharegpt(row: dict, lineno: int, issues: list[LintIssue]) -> None:
    convs = row.get("conversations")
    if not isinstance(convs, list) or not convs:
        issues.append(
            LintIssue(lineno, "missing-conversations", "conversations must be a non-empty list")
        )
        return
    sources = [c.get("from") for c in convs if isinstance(c, dict)]
    for i, src in enumerate(sources):
        if src not in SHAREGPT_VALID_FROM:
            issues.append(
                LintIssue(lineno, "invalid-role", f"conversations[{i}] has invalid 'from' {src!r}")
            )
    if "gpt" not in sources:
        issues.append(
            LintIssue(
                lineno,
                "no-loss-target",
                "no gpt turn; this row contributes zero loss targets",
            )
        )


_LINTERS = {
    DataFormat.ALPACA: _lint_alpaca,
    DataFormat.CHATML: _lint_chatml,
    DataFormat.SHAREGPT: _lint_sharegpt,
}


def lint_file(path: str | Path) -> tuple[list[LintIssue], DataFormat | None]:
    """Lint a JSONL dataset. Returns (issues, detected_format).

    Malformed JSON raises ValueError with the offending line number.
    """
    rows = read_jsonl(path)
    fmt = detect_format([row for row, _ in rows])
    issues: list[LintIssue] = []
    if fmt is None:
        if rows:
            issues.append(
                LintIssue(0, "unknown-format", "could not recognize any row's format")
            )
        return issues, None
    linter = _LINTERS.get(fmt)
    seen_rows: set[str] = set()
    duplicates = 0
    for row, lineno in rows:
        if linter:
            linter(row, lineno, issues)
        key = repr(sorted(row.items(), key=str))
        if key in seen_rows:
            duplicates += 1
        seen_rows.add(key)
    if duplicates:
        issues.append(
            LintIssue(0, "duplicates", f"{duplicates} duplicate row(s) found")
        )
    return issues, fmt
