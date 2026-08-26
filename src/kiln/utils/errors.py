"""Friendly error mapping: raw exceptions -> short message + exact fix hint.

Skeleton for M1; the mapping table grows per milestone. Raw exception text is
never shown to users directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from kiln.utils.exitcodes import RUNTIME


@dataclass(frozen=True)
class FriendlyError:
    message: str
    hint: str | None
    exit_code: int


class KilnError(Exception):
    """Base class for errors Kiln raises intentionally (mapped, not raw)."""

    def __init__(self, message: str, hint: str | None = None, exit_code: int = RUNTIME):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.exit_code = exit_code


# Substring -> friendly error. First match wins; order matters.
_MAPPINGS: tuple[tuple[str, FriendlyError], ...] = (
    (
        "No module named 'torch'",
        FriendlyError(
            message="This command needs the training stack.",
            hint='Install it with: pip install "kiln-cli[train]"',
            exit_code=RUNTIME,
        ),
    ),
)


def map_exception(exc: Exception) -> FriendlyError:
    """Map a raw exception to a user-facing FriendlyError."""
    if isinstance(exc, KilnError):
        return FriendlyError(exc.message, exc.hint, exc.exit_code)
    text = f"{type(exc).__name__}: {exc}"
    for needle, friendly in _MAPPINGS:
        if needle in text:
            return friendly
    return FriendlyError(
        message=f"Unexpected error: {text}",
        hint="Please report this at the project issue tracker.",
        exit_code=RUNTIME,
    )
