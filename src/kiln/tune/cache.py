"""V2 measurement-cache for self-calibration (plan A10).

Stores a GPU-UUID (or stable host-fingerprint) keyed bandwidth measurement
in ``$XDG_CACHE_HOME/kiln/measurements/<key>.json``. Consumed by ``plan`` to
choose prod backend strategy (offload vs hybrid vs cpu). Entries carry a
measurement timestamp so stale results can be disqualified.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
import uuid as uuid_lib
from pathlib import Path

CACHE_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days


def cache_root() -> Path:
    """Resolve the measurement-cache directory (env-overridable for tests)."""
    env = os.environ.get("KILN_BENCH_CACHE")
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "kiln" / "measurements"


def _gpu_uuid() -> str | None:
    """Return the first GPU UUID via nvidia-smi, or None if unavailable."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=uuid", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    uuids = [line.strip() for line in out.stdout.splitlines() if line.strip()]
    return uuids[0] if uuids else None


def host_uuid() -> str:
    """Stable machine key: GPU UUID when present, else a host fingerprint."""
    gpu = _gpu_uuid()
    if gpu:
        return f"gpu:{gpu}"
    mid = ""
    for cand in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        p = Path(cand)
        if p.is_file():
            mid = p.read_text(encoding="utf-8").strip()
            break
    if not mid:
        mid = f"{platform.node()}-{platform.machine()}-{platform.processor()}"
    return "host:" + uuid_lib.uuid5(uuid_lib.NAMESPACE_DNS, mid).hex


class MeasurementCache:
    """Filesystem-backed key/value store for calibration measurements."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or cache_root()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        safe = key.replace(":", "_")
        return self.root / f"{safe}.json"

    def load(self, key: str) -> dict | None:
        p = self.path(key)
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def save(self, key: str, payload: dict) -> Path:
        p = self.path(key)
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return p

    def is_valid(self, entry: dict | None, ttl: int = CACHE_TTL_SECONDS) -> bool:
        """True if a cached entry exists and is younger than ``ttl`` seconds."""
        if not entry:
            return False
        ts = entry.get("measured_at")
        if not isinstance(ts, (int, float)):
            return False
        return (time.time() - ts) <= ttl
