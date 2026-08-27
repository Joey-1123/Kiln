"""Tests for the V2 self-calibration measurement-cache (plan A10)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from kiln.cli import app
from kiln.tune.cache import MeasurementCache, host_uuid
from kiln.tune.measure import recommend

runner = CliRunner()


def test_cache_roundtrip(tmp_path: Path) -> None:
    cache = MeasurementCache(root=tmp_path)
    key = "gpu:abc-123"
    assert cache.load(key) is None
    payload = {"measured_at": 1, "bandwidth_gbps": 500.0, "recommendation": "cuda-native"}
    cache.save(key, payload)
    assert cache.load(key) == payload


def test_is_valid_ttl(tmp_path: Path) -> None:
    cache = MeasurementCache(root=tmp_path)
    key = "host:xyz"
    cache.save(key, {"measured_at": 1, "bandwidth_gbps": 100.0})
    assert cache.is_valid(cache.load(key), ttl=10) is False  # ancient -> invalid
    cache.save(key, {"measured_at": __import__("time").time(), "bandwidth_gbps": 100.0})
    assert cache.is_valid(cache.load(key)) is True


def test_recommend_thresholds() -> None:
    assert recommend(None) == "cpu"
    assert recommend(10.0) == "cpu"
    assert recommend(50.0) == "hybrid-offload"
    assert recommend(400.0) == "cuda-native"
    assert recommend(900.0) == "cuda-native"


def test_host_uuid_deterministic_without_gpu(monkeypatch) -> None:
    # Force the GPU path off so we exercise the host-fingerprint branch.
    import kiln.tune.cache as cache_mod

    monkeypatch.setattr(cache_mod, "_gpu_uuid", lambda: None)
    first = host_uuid()
    second = host_uuid()
    assert first == second
    assert first.startswith("host:")


def test_tune_uses_cache_when_valid(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KILN_BENCH_CACHE", str(tmp_path))
    import kiln.tune.cache as cache_mod

    monkeypatch.setattr(cache_mod, "_gpu_uuid", lambda: None)
    cache = MeasurementCache(root=tmp_path)
    cache.save(
        host_uuid(),
        {"measured_at": __import__("time").time(), "bandwidth_gbps": None, "recommendation": "cpu"},
    )
    result = runner.invoke(app, ["tune"])
    assert result.exit_code == 0, result.output
    assert "Using cached calibration" in result.output


def test_tune_runs_without_torch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KILN_BENCH_CACHE", str(tmp_path))
    import kiln.tune.cache as cache_mod

    monkeypatch.setattr(cache_mod, "_gpu_uuid", lambda: None)
    result = runner.invoke(app, ["tune"])
    assert result.exit_code == 0, result.output
    # No CUDA/torch in this env -> conservative cpu recommendation written.
    assert "recommendation" in result.output.lower()
    assert (tmp_path / f"{host_uuid().replace(':', '_')}.json").is_file()
