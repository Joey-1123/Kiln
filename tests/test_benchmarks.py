"""Tests for the serving benchmark harness (torch-free).

Covers serialization / rendering and the compulsory-failure path: when no
backend/model can load, ``run_benchmark`` must surface each request failure or
the load failure loudly (RuntimeError) rather than silently skipping.
"""

from __future__ import annotations

import json

import pytest

import kiln.benchmarks.report as report_mod
from kiln.benchmarks.driver import BenchmarkResult, _load_model, as_dict, run_benchmark
from kiln.benchmarks.report import _bytes
from kiln.engine.engine import Engine
from kiln.engine.messages import QueueTransport
from kiln.engine.metrics import MemoryBars


def _result() -> BenchmarkResult:
    return BenchmarkResult(
        backend="cpu",
        model="/models/x.gguf",
        requests=20,
        avg_ttft=0.1234,
        avg_tokens_per_second=88.5,
        total_seconds=12.5,
        memory=MemoryBars(10, 100, 3, 4, "decode"),
    )


def test_as_dict_round_trip():
    """Should serialize a result into a plain dict with expected keys."""
    data = as_dict(_result())
    assert data["backend"] == "cpu"
    assert data["requests"] == 20
    assert data["avg_ttft_s"] == pytest.approx(0.1234)
    assert data["avg_tokens_per_second"] == pytest.approx(88.5)
    mem = data["memory"]
    assert mem["gpu_used_bytes"] == 10
    assert mem["gpu_capacity_bytes"] == 100
    assert mem["resident_experts"] == 3
    assert mem["registered_experts"] == 4
    assert mem["phase"] == "decode"


def test_print_report_renders():
    """Should render a rich table without raising."""
    console = report_mod.Console(force_terminal=True, width=120)
    report_mod.print_report(_result(), console=console)


def test_write_json(tmp_path):
    """Should write a valid JSON file."""
    out = tmp_path / "bench.json"
    report_mod.write_json(_result(), out)
    parsed = json.loads(out.read_text())
    assert parsed["backend"] == "cpu"
    assert parsed["avg_tokens_per_second"] == pytest.approx(88.5)


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (0, "0.0 B"),
        (512, "512.0 B"),
        (2048, "2.0 KiB"),
        (3 << 20, "3.0 MiB"),
        (5 << 30, "5.0 GiB"),
    ],
)
def test_bytes(n, expected):
    assert _bytes(n) == expected


async def test_load_failure_is_loud():
    """A bogus model path must surface a RuntimeError, not a silent skip."""
    import asyncio

    import kiln.engine.backends as backs

    backs.clear_registry()
    from kiln.engine.backends.llama_cpp import register as register_cpu

    register_cpu()

    engine = Engine(
        gateway_transport=QueueTransport(),
        engine_transport=QueueTransport(),
    )
    loop_task = asyncio.create_task(engine.run())
    try:
        with pytest.raises(RuntimeError, match="model load failed"):
            await asyncio.wait_for(
                _load_model(engine, "cpu", "/nonexistent/bench.gguf", "none"),
                timeout=30,
            )
    finally:
        engine.stop()
        loop_task.cancel()


async def test_run_benchmark_fails_loudly_on_missing_backend():
    """With no backend/llama_cpp available, the run must raise RuntimeError."""
    import kiln.engine.backends as backs

    backs.clear_registry()

    with pytest.raises(RuntimeError):
        await run_benchmark(
            backend="cpu",
            model="/nonexistent/bench.gguf",
            requests=1,
            max_tokens=8,
        )


def test_benchmark_command_fails_cleanly_without_model(tmp_path):
    """Missing --model must produce a usage-level exit, not a crash."""
    from typer.testing import CliRunner

    import kiln.cli as cli

    result = CliRunner().invoke(cli.app, ["benchmark"])
    assert result.exit_code != 0
    assert "model" in result.output.lower()


def test_benchmark_command_fails_cleanly_on_missing_backend_dep(tmp_path):
    """Without the heavy deps, benchmark must exit 1 without a raw traceback."""
    from typer.testing import CliRunner

    import kiln.cli as cli

    result = CliRunner().invoke(
        cli.app,
        ["benchmark", "--model", "/nonexistent/bench.gguf", "--backend", "cpu",
         "--requests", "1", "--max-tokens", "8"],
    )
    assert result.exit_code == 1
    assert "Traceback" not in result.output
