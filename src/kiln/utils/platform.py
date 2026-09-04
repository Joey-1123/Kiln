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


def _import_torch():
    """Import torch lazily. Starting any probe imports torch here, never at
    module import, so the light control plane stays torch-free."""
    import torch

    return torch


def torch_gpu_available() -> bool:
    """True when a GPU-capable torch build sees usable hardware.

    Single source of truth for "can this process actually use a GPU". CUDA and
    ROCm/HIP builds both surface ``torch.cuda.is_available()``, so this works
    for NVIDIA and AMD alike. Returns False (never raises) if torch is absent.
    """
    try:
        torch = _import_torch()
    except ImportError:
        return False
    try:
        return torch.cuda.is_available()
    except Exception:
        return False


def torch_accel_version() -> str | None:
    """Return the accelerator toolkit banner (``"cuda 12.1"`` or ``"hip 6.0"``).

    Returns None when no GPU torch build is importable or reachable. Kept
    torch-free at module import (lazy import inside the call).
    """
    try:
        torch = _import_torch()
    except ImportError:
        return None
    cuda = getattr(torch.version, "cuda", None)
    if cuda:
        return f"cuda {cuda}"
    hip = getattr(torch.version, "hip", None)
    if hip:
        return f"hip {hip}"
    return None


def accelerator() -> str:
    """Return ``"nvidia"``, ``"amd"``, or ``"none"``.

    Centralized probe used across the tool so accelerator detection never
    diverges. ROCm builds set ``torch.version.hip`` while ``torch.cuda`` stays
    available; CUDA builds set ``torch.version.cuda``.
    """
    try:
        torch = _import_torch()
    except ImportError:
        return "none"
    try:
        if not getattr(torch, "cuda", None) or not torch.cuda.is_available():
            return "none"
    except Exception:
        return "none"
    if getattr(torch.version, "hip", None):
        return "amd"
    return "nvidia"
