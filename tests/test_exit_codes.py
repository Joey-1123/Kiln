"""Contract: the exit-code taxonomy is pinned. Never merge these again.

Soup lesson (v0.71.38): verdict-fail shared a code with usage errors until it
was split; operators could not tell a caught regression from a typo'd flag.
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
