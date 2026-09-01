"""Serving benchmarks package."""

from __future__ import annotations

from kiln.benchmarks.driver import BenchmarkResult, as_dict, run_benchmark
from kiln.benchmarks.report import print_report, write_json

__all__ = [
    "BenchmarkResult",
    "as_dict",
    "print_report",
    "run_benchmark",
    "write_json",
]
