"""Contract: every PR adds a changelog fragment under changelog.d/<version>/."""

from __future__ import annotations

from pathlib import Path

CHANGELOG_D = Path(__file__).resolve().parent.parent / "changelog.d"

KNOWN_TYPES = {"feature", "fix", "docs", "perf", "breaking"}


def test_changelog_dir_exists() -> None:
    assert CHANGELOG_D.is_dir()


def test_fragments_use_known_types() -> None:
    for version_dir in CHANGELOG_D.iterdir():
        if not version_dir.is_dir() or version_dir.name.startswith("."):
            continue
        for fragment in version_dir.glob("*.md"):
            parts = fragment.stem.split(".")
            assert len(parts) >= 2, (
                f"{fragment} must be named <slug>.<type>.md "
                f"(types: {sorted(KNOWN_TYPES)})"
            )
            assert parts[-1] in KNOWN_TYPES, (
                f"{fragment}: unknown type {parts[-1]!r}; expected one of {sorted(KNOWN_TYPES)}"
            )
