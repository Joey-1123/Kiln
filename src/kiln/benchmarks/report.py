"""Rich/JSON rendering for serving benchmarks."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table

from kiln.benchmarks.driver import BenchmarkResult, as_dict


def print_report(result: BenchmarkResult, console: Console | None = None) -> None:
    """Render a serving benchmark result as a rich table."""
    console = console or Console()
    table = Table(title="Kiln serving benchmark")
    table.add_column("Metric")
    table.add_column("Value")

    table.add_row("Backend", result.backend)
    table.add_row("Model", result.model)
    table.add_row("Requests", str(result.requests))
    table.add_row("Avg TTFT (s)", f"{result.avg_ttft:.4f}")
    table.add_row("Avg tokens/s", f"{result.avg_tokens_per_second:.2f}")
    table.add_row("Wall time (s)", f"{result.total_seconds:.2f}")

    mem = result.memory
    if mem.gpu_capacity_bytes or mem.registered_experts:
        table.add_section()
        table.add_row("GPU used", _bytes(mem.gpu_used_bytes))
        table.add_row("GPU capacity", _bytes(mem.gpu_capacity_bytes))
        table.add_row("Resident experts", str(mem.resident_experts))
        table.add_row("Registered experts", str(mem.registered_experts))
        table.add_row("Phase", mem.phase or "—")

    console.print(table)


def write_json(result: BenchmarkResult, path: str | Path) -> None:
    """Write a benchmark result to a JSON file."""
    Path(path).write_text(json.dumps(as_dict(result), indent=2) + "\n", encoding="utf-8")


def _bytes(n: int) -> str:
    """Human-readable byte count."""
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024.0 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TiB"
