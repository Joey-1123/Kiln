"""Platform differences live here and nowhere else (the compat.h rule)."""

from __future__ import annotations

import sys


def is_windows() -> bool:
    """True when running on Windows."""
    return sys.platform == "win32"


def is_macos() -> bool:
    """True when running on macOS."""
    return sys.platform == "darwin"


def is_linux() -> bool:
    """True when running on Linux."""
    return sys.platform.startswith("linux")
