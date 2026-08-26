"""UTF-8 stdio bootstrap.

Must run before any console output exists. Windows defaults to cp1252 in many
environments; rich/Typer emit box-drawing characters that crash under it.
"""

from __future__ import annotations

import sys

from kiln.utils.platform import is_windows


def force_utf8_stdio() -> None:
    """Reconfigure stdout/stderr to UTF-8 where supported (Windows safety).

    Safe to call multiple times; silently no-ops on streams that do not
    support reconfiguration (e.g. already-detached or captured streams).
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            # Closed or non-reconfigurable stream; nothing to do.
            pass
    if is_windows():
        _windows_utf8_codepage()


def _windows_utf8_codepage() -> None:
    """Best-effort switch of the Windows console codepage to UTF-8 (65001)."""
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel32.SetConsoleOutputCP(65001)
    except Exception:  # noqa: BLE001 - best effort by design
        pass
