"""Disk preflight: know whether a model fits BEFORE downloading a byte.

The engine never lies about limits (colibri rule): `kiln fetch` refuses with
exact numbers when free space is insufficient instead of failing at 80%.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from kiln.utils.errors import KilnError


@dataclass(frozen=True)
class DiskPreflight:
    repo_id: str
    model_bytes: int
    free_bytes: int
    required_bytes: int  # model + safety margin

    @property
    def ok(self) -> bool:
        return self.free_bytes >= self.required_bytes

    def human_summary(self) -> str:
        def gb(n: int) -> str:
            return f"{n / 1e9:.2f} GB"

        return (
            f"model {gb(self.model_bytes)} + margin {gb(self.required_bytes - self.model_bytes)}"
            f" = {gb(self.required_bytes)} needed; {gb(self.free_bytes)} free"
        )


def _safety_margin(model_bytes: int) -> int:
    """Max(5% of the model, 512 MiB) — covers partial-file overhead."""
    return max(int(model_bytes * 0.05), 512 * 1024 * 1024)


def disk_free(path: str) -> int:
    """Free bytes available at ``path`` (isolated for testing)."""
    usage = shutil.disk_usage(path)
    return usage.free


def preflight(
    repo_id: str,
    dest: str,
    model_bytes: int,
    *,
    free_space_fn=disk_free,
) -> DiskPreflight:
    """Check that ``dest`` can hold ``model_bytes``; raise KilnError if not.

    ``free_space_fn`` is injectable so tests never touch a real filesystem.
    """
    report = DiskPreflight(
        repo_id=repo_id,
        model_bytes=model_bytes,
        free_bytes=free_space_fn(dest),
        required_bytes=model_bytes + _safety_margin(model_bytes),
    )
    if not report.ok:
        raise KilnError(
            message=(
                f"Not enough disk space for {repo_id}: "
                f"{report.human_summary()}"
            ),
            hint="Free up space or choose another --dest on a larger volume.",
        )
    return report
