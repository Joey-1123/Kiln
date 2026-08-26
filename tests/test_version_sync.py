"""Contract: pyproject version and kiln.__version__ must agree."""

from __future__ import annotations

from pathlib import Path

import tomllib

import kiln

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_version_sync() -> None:
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    declared = pyproject["project"]["name"]
    version = pyproject["project"]["dynamic"][0] if "dynamic" in pyproject["project"] else None
    assert declared == "kiln-cli"
    assert version == "version"  # version comes from src/kiln/__init__.py via hatch
    assert isinstance(kiln.__version__, str)
    assert kiln.__version__


def test_version_matches_hatch_source() -> None:
    """The hatch [tool.hatch.version] path must point at the module we read."""
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    path = pyproject["tool"]["hatch"]["version"]["path"]
    source = (PYPROJECT.parent / path).read_text(encoding="utf-8")
    assert f'__version__ = "{kiln.__version__}"' in source
