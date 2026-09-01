"""Kiln benchmarks — memory-bound regression harness.

Published as-written (plan §8.5); failures included. Rejected
optimizations recorded with measurements, never silently dropped.
"""

from benchmarks.runner import BenchmarkResult, run_suite

__all__ = ["BenchmarkResult", "run_suite"]
