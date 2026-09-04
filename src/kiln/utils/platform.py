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


# ---------------------------------------------------------------------------
# GPU discovery — vendor CLIs are parsed here (pure functions, hermetic-tested)
# so doctor / plan / tune never hand-roll nvidia-smi/rocm-smi parsing.

def parse_nvidia_smi(csv_text: str) -> list[dict]:
    """Parse ``nvidia-smi --query-gpu=name,memory.total,uuid`` csv output.

    Returns dicts with keys: family ("nvidia"), name, vram_mib, uuid.
    """
    devices: list[dict] = []
    for line in csv_text.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        name = parts[0]
        try:
            vram_mib = int(parts[1])
        except ValueError:
            vram_mib = 0
        uuid = parts[2] if len(parts) > 2 else None
        devices.append(
            {"family": "nvidia", "name": name, "vram_mib": vram_mib, "uuid": uuid}
        )
    return devices


def parse_rocm_smi_json(json_text: str) -> list[dict]:
    """Parse ``rocm-smi --json`` output into per-card device dicts.

    rocm-smi JSON wraps each card under a ``cardN`` key with string-valued
    fields; parse defensively (missing/odd keys degrade to zeros). We accept
    both the plain JSON object and the ``--json`` wrapper.
    """
    import json

    devices: list[dict] = []
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        return items if (items := _parse_rocm_smi_plain(json_text)) else devices

    cards = data.get("system") if isinstance(data.get("system"), dict) else data
    for key, value in cards.items():
        if not isinstance(value, dict):
            continue
        name = value.get("Card series") or value.get("Marketing name") or key
        vram_b = _to_int(value.get("VRAM Total Memory (B)"))
        devices.append(
            {
                "family": "amd",
                "name": str(name).strip(),
                "vram_mib": vram_b // (1024 * 1024),
                "uuid": value.get("Unique ID") or None,
            }
        )
    return devices


def _parse_rocm_smi_plain(text: str) -> list[dict]:
    """Fallback parser for non-JSON ``rocm-smi`` output (best effort)."""
    devices: list[dict] = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or "GPU[" not in line:
            continue
        name = line.split("GPU[")[1].split("]")[0]
        devices.append(
            {"family": "amd", "name": name, "vram_mib": 0, "uuid": None}
        )
    return devices


def _to_int(value) -> int:
    try:
        return int(str(value).replace(",", "").strip() or 0)
    except ValueError:
        return 0


def _run_cli(cmd: list[str]) -> str:
    import subprocess

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return ""


def gpu_devices() -> list[dict]:
    """Discover GPUs via the vendor CLI: nvidia-smi, else rocm-smi.

    Returns a list of device dicts (family/name/vram_mib/uuid). Empty when no
    vendor CLI responds. Pure detection — importing torch is not required.
    """
    nvidia_out = _run_cli(
        ["nvidia-smi", "--query-gpu=name,memory.total,uuid",
         "--format=csv,noheader,nounits"]
    )
    if nvidia_out.strip():
        return parse_nvidia_smi(nvidia_out)
    rocm_out = _run_cli(["rocm-smi", "--json"])
    if rocm_out.strip():
        return parse_rocm_smi_json(rocm_out)
    return []
