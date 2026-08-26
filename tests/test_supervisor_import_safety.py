"""Import-sentinel for the torch-free zone.

Everything under kiln.utils (and the future supervisor package) must import
without any heavy dependency present at all — not merely unloaded, but
unavailable. Runs in a fresh subprocess with a meta-path finder that raises
on any attempt to import a heavy module.
"""

from __future__ import annotations

import os
import subprocess
import sys

from test_cli_startup_is_light import HEAVY_MODULES

SENTINEL_SCRIPT = """
import sys

class _Blocker:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {heavy!r}:
            raise ImportError(f"{fullname} is forbidden in the torch-free zone")
        return None

sys.meta_path.insert(0, _Blocker())
import {target}
print("SENTINEL_OK")
""".replace("{", "{{").replace("}", "}}").replace("{{heavy!r}}", "{heavy!r}").replace(
    "{{target}}", "{target}"
)


def test_utils_package_never_touches_heavy_deps() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            SENTINEL_SCRIPT.format(target="kiln.utils", heavy=HEAVY_MODULES),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "src"},
        timeout=60,
    )
    assert result.returncode == 0, (
        f"torch-free zone violated:\n{result.stdout}\n{result.stderr}"
    )
    assert "SENTINEL_OK" in result.stdout


def test_config_package_stays_light_under_sentinel() -> None:
    """config must be importable with heavy deps unavailable (yaml/pydantic only)."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            SENTINEL_SCRIPT.format(target="kiln.config", heavy=HEAVY_MODULES),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "src"},
        timeout=60,
    )
    assert result.returncode == 0, (
        f"config package reached for heavy deps:\n{result.stdout}\n{result.stderr}"
    )
    assert "SENTINEL_OK" in result.stdout
