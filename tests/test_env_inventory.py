"""Tests for kiln.env_inventory — AST scanner for environment variables."""

from __future__ import annotations

import json
from pathlib import Path

from kiln.env_inventory import (
    EnvInventory,
    EnvVarUsage,
    detect_drift,
    scan_directory,
    scan_file,
    write_manifest,
)

# --- EnvVarUsage ---


class TestEnvVarUsage:
    def test_creation(self) -> None:
        u = EnvVarUsage(
            name="API_KEY",
            source_file="foo.py",
            line=10,
            accessor="os.getenv(...)",
        )
        assert u.name == "API_KEY"
        assert u.default is None

    def test_with_default(self) -> None:
        u = EnvVarUsage(
            name="PORT",
            source_file="foo.py",
            line=5,
            accessor="os.getenv(...)",
            default="8080",
        )
        assert u.default == "8080"


# --- EnvInventory ---


class TestEnvInventory:
    def test_empty(self) -> None:
        inv = EnvInventory()
        assert inv.unique_vars() == {}
        assert inv.to_dict()["total_usages"] == 0

    def test_unique_vars_grouping(self) -> None:
        inv = EnvInventory(variables=[
            EnvVarUsage(name="A", source_file="a.py", line=1, accessor="os.getenv(...)"),
            EnvVarUsage(name="B", source_file="b.py", line=2, accessor="os.environ[...]"),
            EnvVarUsage(name="A", source_file="c.py", line=3, accessor="os.getenv(...)"),
        ])
        uv = inv.unique_vars()
        assert len(uv) == 2
        assert len(uv["A"]["sources"]) == 2
        assert len(uv["B"]["sources"]) == 1

    def test_to_json(self) -> None:
        inv = EnvInventory()
        j = inv.to_json()
        data = json.loads(j)
        assert "unique_vars" in data

    def test_default_propagation(self) -> None:
        inv = EnvInventory(variables=[
            EnvVarUsage(
                name="X", source_file="a.py", line=1,
                accessor="os.getenv(...)", default="1",
            ),
            EnvVarUsage(
                name="X", source_file="b.py", line=2,
                accessor="os.getenv(...)",
            ),
        ])
        uv = inv.unique_vars()
        assert uv["X"]["default"] == "1"


# --- scan_file ---


class TestScanFile:
    def test_scan_os_environ_getenv(self, tmp_path: Path) -> None:
        f = tmp_path / "test.py"
        f.write_text(
            'import os\n'
            'x = os.getenv("API_KEY")\n'
            'y = os.environ["SECRET"]\n'
        )
        usages = scan_file(str(f))
        names = {u.name for u in usages}
        assert "API_KEY" in names
        assert "SECRET" in names

    def test_scan_os_environ_get(self, tmp_path: Path) -> None:
        f = tmp_path / "test.py"
        f.write_text(
            'import os\n'
            'x = os.environ.get("PORT", "8080")\n'
        )
        usages = scan_file(str(f))
        assert len(usages) == 1
        assert usages[0].name == "PORT"
        assert usages[0].default == "8080"

    def test_scan_nothing(self, tmp_path: Path) -> None:
        f = tmp_path / "clean.py"
        f.write_text('x = 42\n')
        usages = scan_file(str(f))
        assert usages == []

    def test_scan_syntax_error(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.py"
        f.write_text('def (\n')
        usages = scan_file(str(f))
        assert usages == []


# --- scan_directory ---


class TestScanDirectory:
    def test_scan_directory(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text('import os\nprint(os.getenv("X"))\n')
        (tmp_path / "b.py").write_text('import os\nprint(os.getenv("Y"))\n')
        inv = scan_directory(str(tmp_path))
        assert inv.file_count == 2
        names = {u.name for u in inv.variables}
        assert "X" in names
        assert "Y" in names

    def test_excludes_git(self, tmp_path: Path) -> None:
        (tmp_path / "good.py").write_text('import os\nos.getenv("A")\n')
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "bad.py").write_text('import os\nos.getenv("B")\n')
        inv = scan_directory(str(tmp_path))
        assert inv.file_count == 1
        assert inv.variables[0].name == "A"

    def test_exclude_dirs(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text('import os\nos.getenv("A")\n')
        skip = tmp_path / "skip"
        skip.mkdir()
        (skip / "sub.py").write_text('import os\nos.getenv("B")\n')
        inv = scan_directory(str(tmp_path), exclude_dirs=["skip"])
        assert inv.file_count == 1


# --- detect_drift ---


class TestDetectDrift:
    def test_no_drift(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "manifest.json"
        inv = EnvInventory(variables=[
            EnvVarUsage(name="A", source_file="a.py", line=1, accessor="os.getenv(...)"),
        ])
        write_manifest(inv, str(manifest_path))

        current = EnvInventory(variables=[
            EnvVarUsage(name="A", source_file="a.py", line=1, accessor="os.getenv(...)"),
        ])
        result = detect_drift(str(manifest_path), current)
        assert result["status"] == "ok"
        assert result["drifted"] is False

    def test_added_var(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "manifest.json"
        inv = EnvInventory(variables=[
            EnvVarUsage(name="A", source_file="a.py", line=1, accessor="os.getenv(...)"),
        ])
        write_manifest(inv, str(manifest_path))

        current = EnvInventory(variables=[
            EnvVarUsage(name="A", source_file="a.py", line=1, accessor="os.getenv(...)"),
            EnvVarUsage(name="B", source_file="b.py", line=2, accessor="os.getenv(...)"),
        ])
        result = detect_drift(str(manifest_path), current)
        assert result["drifted"] is True
        assert "B" in result["added"]

    def test_removed_var(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "manifest.json"
        inv = EnvInventory(variables=[
            EnvVarUsage(name="A", source_file="a.py", line=1, accessor="os.getenv(...)"),
            EnvVarUsage(name="B", source_file="b.py", line=2, accessor="os.getenv(...)"),
        ])
        write_manifest(inv, str(manifest_path))

        current = EnvInventory(variables=[
            EnvVarUsage(name="A", source_file="a.py", line=1, accessor="os.getenv(...)"),
        ])
        result = detect_drift(str(manifest_path), current)
        assert result["drifted"] is True
        assert "B" in result["removed"]

    def test_missing_manifest(self, tmp_path: Path) -> None:
        result = detect_drift(str(tmp_path / "nope.json"), EnvInventory())
        assert result["status"] == "error"
