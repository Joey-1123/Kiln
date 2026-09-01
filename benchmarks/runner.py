"""Runner — time each bench, emit JSONL + markdown."""

from __future__ import annotations

import argparse
import json
import platform
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from benchmarks.suite import SMOKE, SUITE


@dataclass(frozen=True)
class BenchmarkResult:
    name: str
    iterations: int
    elapsed_s: float
    ops_per_s: float
    skipped: bool = False
    error: str | None = None


def _run_one(name: str, fn: callable, iterations: int) -> BenchmarkResult:
    start = time.perf_counter()
    try:
        for _ in range(iterations):
            fn()
    except Exception as exc:
        return BenchmarkResult(name, iterations, 0, 0, error=str(exc))
    elapsed = time.perf_counter() - start
    ops = iterations / elapsed if elapsed > 0 else 0
    return BenchmarkResult(name, iterations, elapsed, ops)


def run_suite(*, iterations: int = 1, smoke: bool = False) -> list[BenchmarkResult]:
    suite = [(n, f) for n, f in SUITE if not smoke or n in SMOKE]
    return [_run_one(n, fn, iterations) for n, fn in suite]


def main() -> None:
    ap = argparse.ArgumentParser(description="Kiln benchmarks")
    ap.add_argument("--iterations", type=int, default=1)
    ap.add_argument("--smoke", action="store_true", help="run smoke subset only")
    ap.add_argument("--jsonl", type=Path, default=None, help="write JSONL results")
    ap.add_argument("--markdown", type=Path, default=None, help="write markdown report")
    args = ap.parse_args()

    results = run_suite(iterations=args.iterations, smoke=args.smoke)

    for r in results:
        status = f"ERR:{r.error}" if r.error else f"{r.ops_per_s:.1f} ops/s ({r.elapsed_s:.3f}s)"
        print(f"{r.name:20s}  {status}")

    if args.jsonl:
        args.jsonl.parent.mkdir(parents=True, exist_ok=True)
        meta = {"host": platform.node(), "python": platform.python_version()}
        with args.jsonl.open("w", encoding="utf-8") as fh:
            for r in results:
                fh.write(json.dumps({**asdict(r), **meta}) + "\n")

    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Benchmarks",
            "",
            f"_iterations={args.iterations}_",
            "",
            "| bench | ops/s | elapsed |",
            "|---|---|---|",
        ]
        for r in results:
            err = r.error or ""
            lines.append(f"| {r.name} | {r.ops_per_s:.1f} | {r.elapsed_s:.3f}s {err} |")
        args.markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
