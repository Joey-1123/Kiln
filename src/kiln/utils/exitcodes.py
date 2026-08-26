"""Semantic exit codes — the CLI's machine-readable API.

Taxonomy (pinned by tests/test_exit_codes.py):
  0  OK            - command succeeded / ship verdict SHIP
  1  RUNTIME       - something failed at runtime
  2  VERDICT_FAIL  - an eval gate produced a DON'T-SHIP verdict (NOT a user error)
  3  USAGE         - bad flags/config/validation

Soup lesson (v0.71.38): a caught regression must never share a code with a
usage error — they were both `2` and operators could not tell them apart.
"""

from __future__ import annotations

OK = 0
RUNTIME = 1
VERDICT_FAIL = 2
USAGE = 3

__all__ = ["OK", "RUNTIME", "USAGE", "VERDICT_FAIL"]
