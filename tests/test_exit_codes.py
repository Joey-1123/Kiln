"""Contract: the exit-code taxonomy is pinned. Never merge these again.

A caught regression must never share a code with a usage error.
Verdict-fail and usage-error shared code 2 until split; operators
could not tell a caught regression from a typo'd flag.
"""

from __future__ import annotations

from kiln.utils import exitcodes


def test_taxonomy_values() -> None:
    assert exitcodes.OK == 0
    assert exitcodes.RUNTIME == 1
    assert exitcodes.VERDICT_FAIL == 2
    assert exitcodes.USAGE == 3


def test_all_codes_distinct() -> None:
    codes = {exitcodes.OK, exitcodes.RUNTIME, exitcodes.VERDICT_FAIL, exitcodes.USAGE}
    assert len(codes) == 4
