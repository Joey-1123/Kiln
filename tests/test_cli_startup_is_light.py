"""The startup-light probe: heavy deps never load outside training commands.

This replaces per-module AST guards, which proved insufficient in Soup's
history: they verify a syntactic property and miss transitive imports and
"lazy factory called at module scope" regressions. A fresh subprocess is the
only honest witness.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

HEAVY_MODULES = (
    "torch",
    "transformers",
    "accelerate",
    "peft",
    "trl",
    "datasets",
    "bitsandbytes",
)

PROBE_SCRIPT = """
import sys
import {target}
heavy = [m for m in {heavy!r} if m in sys.modules]
if heavy:
    print("HEAVY_LOADED:" + ",".join(heavy))
else:
    print("LIGHT_OK")
"""


def _probe(
    target: str, env_extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Import ``target`` in a fresh interpreter; return its completed run."""
    return subprocess.run(
        [sys.executable, "-c", PROBE_SCRIPT.format(target=target, heavy=HEAVY_MODULES)],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "src", **(env_extra or {})},
        timeout=120,
    )


def _verdict(result: subprocess.CompletedProcess[str]) -> list[str]:
    out = result.stdout.strip()
    if out.startswith("HEAVY_LOADED:"):
        return out.removeprefix("HEAVY_LOADED:").split(",")
    if out == "LIGHT_OK":
        return []
    pytest.fail(f"probe produced no verdict (stdout={out!r}, stderr={result.stderr!r})")
    return []


def test_cli_import_is_light() -> None:
    """Importing the full CLI surface must not load any heavy dependency."""
    loaded = _verdict(_probe("kiln.cli"))
    assert loaded == [], (
        f"CLI startup loads heavy deps {loaded}. Heavy deps are lazy-imported "
        "inside functions, never at module top."
    )


def test_probe_would_catch_a_regression(tmp_path) -> None:
    """Control test: the probe must actually report torch when it IS imported.

    Without this, a broken probe (wrong module list, wrong interpreter,
    swallowed output) could pass vacuously forever.
    """
    (tmp_path / "torch.py").write_text("")  # stand-in heavy dep on sys.path
    result = _probe("torch", env_extra={"PYTHONPATH": str(tmp_path)})
    assert result.returncode == 0, result.stderr
    assert _verdict(result) == ["torch"], (
        "Probe control failed: the probe did NOT detect a seeded heavy import. "
        "The probe itself is broken."
    )


def test_light_commands_stay_light() -> None:
    """`kiln version` must complete without loading heavy deps."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.argv=['kiln', 'version'];"
            "import kiln.cli as c; c.run();"
            f"heavy=[m for m in {HEAVY_MODULES!r} if m in sys.modules];"
            "sys.exit(23 if heavy else 0)",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": "src"},
        timeout=120,
    )
    assert result.returncode != 23, f"light command loaded heavy deps: {result.stdout}"
    assert result.returncode == 0, result.stderr
