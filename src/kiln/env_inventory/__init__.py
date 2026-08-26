"""Environment variable inventory generator (A6).

AST-scans Python files for os.environ / os.getenv / os.environ.get usage,
produces a JSON manifest of all env vars referenced, and can detect drift
between the manifest and the actual codebase.
"""

from __future__ import annotations

import ast
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EnvVarUsage:
    name: str
    source_file: str
    line: int
    accessor: str  # "os.environ[X]", "os.getenv(X)", "os.environ.get(X)"
    default: str | None = None


@dataclass
class EnvInventory:
    variables: list[EnvVarUsage] = field(default_factory=list)
    source_root: str = ""
    file_count: int = 0

    def unique_vars(self) -> dict[str, dict[str, Any]]:
        """Group by env var name, collect sources."""
        result: dict[str, dict[str, Any]] = {}
        for usage in self.variables:
            if usage.name not in result:
                result[usage.name] = {
                    "name": usage.name,
                    "sources": [],
                    "default": usage.default,
                }
            entry = result[usage.name]
            entry["sources"].append({
                "file": usage.source_file,
                "line": usage.line,
                "accessor": usage.accessor,
            })
            if usage.default is not None and entry["default"] is None:
                entry["default"] = usage.default
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_root": self.source_root,
            "file_count": self.file_count,
            "total_usages": len(self.variables),
            "unique_vars": list(self.unique_vars().values()),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def _extract_string_value(node: ast.expr) -> str | None:
    """Extract a string constant from an AST node."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


class _EnvVarVisitor(ast.NodeVisitor):
    """Walks AST to find os.environ / os.getenv / os.environ.get usages."""

    def __init__(self, filepath: str) -> None:
        self.filepath = filepath
        self.usages: list[EnvVarUsage] = []

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # os.environ[X] pattern
        if (
            isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "os"
            and node.value.attr == "environ"
            and node.attr == "__getitem__"
        ):
            return  # handled by visit_Subscript

        # os.environ.get(X, default) pattern
        if (
            isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "os"
            and node.value.attr == "environ"
            and node.attr == "get"
        ):
            return  # handled by visit_Call

        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        # os.environ["VAR"] or os.environ.get("VAR")
        if (
            isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "os"
            and node.value.attr == "environ"
        ):
            key = _extract_string_value(node.slice)
            if key:
                self.usages.append(EnvVarUsage(
                    name=key,
                    source_file=self.filepath,
                    line=node.lineno,
                    accessor="os.environ[...]",
                ))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # os.getenv("VAR") or os.getenv("VAR", default) or os.environ.get("VAR")
        func = node.func

        if isinstance(func, ast.Attribute) and func.attr == "get":
            # os.environ.get("VAR", "default")
            if isinstance(func.value, ast.Attribute):
                if (
                    isinstance(func.value.value, ast.Name)
                    and func.value.value.id == "os"
                    and func.value.attr == "environ"
                ):
                    if node.args:
                        key = _extract_string_value(node.args[0])
                        default = None
                        if len(node.args) > 1:
                            default = _extract_string_value(node.args[1])
                        if key:
                            self.usages.append(EnvVarUsage(
                                name=key,
                                source_file=self.filepath,
                                line=node.lineno,
                                accessor="os.environ.get(...)",
                                default=default,
                            ))
        elif isinstance(func, ast.Attribute) and func.attr == "getenv":
            # os.getenv("VAR", "default")
            if isinstance(func.value, ast.Name) and func.value.id == "os":
                if node.args:
                    key = _extract_string_value(node.args[0])
                    default = None
                    if len(node.args) > 1:
                        default = _extract_string_value(node.args[1])
                    if key:
                        self.usages.append(EnvVarUsage(
                            name=key,
                            source_file=self.filepath,
                            line=node.lineno,
                            accessor="os.getenv(...)",
                            default=default,
                        ))

        # Recurse into func expression (not visited by generic_visit on Call)
        self.visit(func)
        self.generic_visit(node)


def scan_file(filepath: str) -> list[EnvVarUsage]:
    """AST-scan a single Python file for env var usages."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)
    except (SyntaxError, OSError):
        return []

    visitor = _EnvVarVisitor(filepath)
    visitor.visit(tree)
    return visitor.usages


def scan_directory(
    root: str,
    exclude_dirs: list[str] | None = None,
    include_tests: bool = True,
) -> EnvInventory:
    """Recursively scan a directory tree for env var usages."""
    exclude = set(exclude_dirs or [
        ".git", "__pycache__", ".venv",
        "node_modules", ".mypy_cache", ".ruff_cache",
    ])
    if not include_tests:
        exclude.add("tests")

    inventory = EnvInventory(source_root=root)
    root_path = Path(root).resolve()

    for dirpath, dirnames, filenames in os.walk(root_path):
        # Prune excluded dirs in-place
        dirnames[:] = [d for d in dirnames if d not in exclude]

        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            filepath = os.path.join(dirpath, filename)
            relpath = os.path.relpath(filepath, root_path)
            usages = scan_file(filepath)
            for u in usages:
                u.source_file = relpath
            inventory.variables.extend(usages)
            inventory.file_count += 1

    return inventory


def detect_drift(
    manifest_path: str,
    current_inventory: EnvInventory,
) -> dict[str, Any]:
    """Compare a saved manifest against current scan results."""
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            old = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "status": "error",
            "message": f"Cannot read manifest: {manifest_path}",
        }

    old_vars = {v["name"] for v in old.get("unique_vars", [])}
    new_vars = set(current_inventory.unique_vars().keys())

    added = sorted(new_vars - old_vars)
    removed = sorted(old_vars - new_vars)

    return {
        "status": "ok",
        "old_manifest": manifest_path,
        "old_count": len(old_vars),
        "new_count": len(new_vars),
        "added": added,
        "removed": removed,
        "drifted": bool(added or removed),
    }


def write_manifest(inventory: EnvInventory, path: str) -> None:
    """Write the inventory to a JSON manifest file."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(inventory.to_json())
