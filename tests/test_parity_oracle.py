"""Tests for the CPU↔GPU parity oracle (A8).

The pure-Python comparator (``kiln.engine.parity``) is covered by fast,
torch-free unit tests that run in the default CI matrix.  The end-to-end
cross-backend gate (``test_live_cross_backend_parity``) is marked
``parity`` and only runs in the dedicated ``parity-oracle`` CI job, where
pinned-torch fixtures and both inference engines are available.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kiln.engine.parity import (
    GenerationRecord,
    ParityFixture,
    ParityOracle,
    ParityTolerance,
    compare_to_reference,
    levenshtein_ratio,
    topk_overlap,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "parity" / "sample_parity_fixture.json"


def _ref_tokens() -> list[int]:
    return [10, 20, 30, 40, 50]


def _ref_topk() -> list[list[int]]:
    return [
        [10, 11, 12, 13, 14],
        [20, 21, 22, 23, 24],
        [30, 31, 32, 33, 34],
        [40, 41, 42, 43, 44],
        [50, 51, 52, 53, 54],
    ]


def _ref_probs() -> list[list[float]]:
    return [
        [0.6, 0.1, 0.1, 0.1, 0.1],
        [0.5, 0.2, 0.1, 0.1, 0.1],
        [0.7, 0.1, 0.1, 0.05, 0.05],
        [0.4, 0.3, 0.1, 0.1, 0.1],
        [0.8, 0.05, 0.05, 0.05, 0.05],
    ]


# ---------------------------------------------------------------------------
# Comparator unit tests (no torch / no models)
# ---------------------------------------------------------------------------


class TestLevenshtein:
    def test_identical(self):
        assert levenshtein_ratio([1, 2, 3], [1, 2, 3]) == 0.0

    def test_completely_different(self):
        assert levenshtein_ratio([1, 2, 3], [9, 9, 9]) == 1.0

    def test_empty(self):
        assert levenshtein_ratio([], []) == 0.0
        assert levenshtein_ratio([1], []) == 1.0

    def test_partial(self):
        # one substitution + one insertion over length 5 -> 2/5 = 0.4
        assert levenshtein_ratio([1, 2, 3, 4, 5], [1, 9, 3, 4, 6]) == pytest.approx(0.4)


class TestTopkOverlap:
    def test_identical(self):
        assert topk_overlap([1, 2, 3], [1, 2, 3]) == 1.0

    def test_partial(self):
        # intersection {1,2} / union {1,2,3,4} = 0.5
        assert topk_overlap([1, 2, 3], [1, 2, 4]) == pytest.approx(0.5)

    def test_empty(self):
        assert topk_overlap([], []) == 1.0


class TestFixtureLoad:
    def test_load_sample(self):
        fx = ParityFixture.load(FIXTURE)
        assert fx.name == "sample-tiny"
        assert fx.capacities == [1, 2, 8]
        assert fx.tolerance.top1_token_match_min == 0.99
        assert fx.reference[1].tokens == _ref_tokens()


class TestCompareToReference:
    def _tol(self) -> ParityTolerance:
        return ParityTolerance(
            top1_token_match_min=0.99,
            topk_window_k=5,
            topk_window_overlap_min=0.6,
            task_edit_distance_max=0.2,
            require_logit_window=False,
        )

    def test_exact_match_passes(self):
        ref = GenerationRecord(_ref_tokens(), _ref_topk(), _ref_probs())
        live = GenerationRecord(_ref_tokens(), _ref_topk(), _ref_probs())
        rep = compare_to_reference(ref, live, self._tol(), backend="cpu", capacity=1)
        assert rep.passed
        assert rep.top1_match == 1.0

    def test_first_token_mismatch_fails(self):
        ref = GenerationRecord(_ref_tokens(), _ref_topk(), _ref_probs())
        # top-1 differs on every step -> top1 match rate well below threshold
        live_tokens = [99, 99, 99, 99, 99]
        live = GenerationRecord(live_tokens)
        rep = compare_to_reference(ref, live, self._tol(), backend="cpu", capacity=1)
        assert not rep.passed
        assert rep.top1_match == 0.0

    def test_edit_distance_gate(self):
        ref = GenerationRecord(_ref_tokens(), _ref_topk(), _ref_probs())
        live = GenerationRecord([10, 99, 30, 99, 40, 99])
        tol = self._tol()
        rep = compare_to_reference(ref, live, tol, backend="cpu", capacity=2)
        assert not rep.passed
        assert rep.edit_distance > tol.task_edit_distance_max

    def test_logit_window_not_captured_relaxed(self):
        ref = GenerationRecord(_ref_tokens(), _ref_topk(), _ref_probs())
        live = GenerationRecord(_ref_tokens())  # no logits
        tol = ParityTolerance(require_logit_window=False)
        rep = compare_to_reference(ref, live, tol, backend="cpu", capacity=8)
        assert rep.passed

    def test_logit_window_required_but_missing_fails(self):
        ref = GenerationRecord(_ref_tokens(), _ref_topk(), _ref_probs())
        live = GenerationRecord(_ref_tokens())
        tol = ParityTolerance(require_logit_window=True)
        rep = compare_to_reference(ref, live, tol, backend="cpu", capacity=8)
        assert not rep.passed


class TestOracleEvaluate:
    def test_all_passed(self):
        fx = ParityFixture.load(FIXTURE)
        rec = GenerationRecord(_ref_tokens(), _ref_topk(), _ref_probs())
        results = {"cpu": {1: rec, 2: rec, 8: rec}}
        reports = ParityOracle().evaluate(fx, results)
        assert len(reports) == 3
        assert ParityOracle.all_passed(reports)

    def test_missing_capacity_fails(self):
        fx = ParityFixture.load(FIXTURE)
        rec = GenerationRecord(_ref_tokens(), _ref_topk(), _ref_probs())
        results = {"cpu": {1: rec}}  # only capacity 1 present
        reports = ParityOracle().evaluate(fx, results)
        assert not ParityOracle.all_passed(reports)
        failed = [r for r in reports if not r.passed]
        assert any("missing record" in n for r in failed for n in r.notes)


# ---------------------------------------------------------------------------
# End-to-end cross-backend gate — only in the dedicated parity CI job
# ---------------------------------------------------------------------------


@pytest.mark.parity
def test_live_cross_backend_parity() -> None:
    """Run both engines against a generated fixture and gate on parity.

    Skipped unless KILN_PARITY_FIXTURE points at a generated fixture and
    the matching inference engine(s) are importable.  Runs in the
    ``parity-oracle`` CI job with pinned torch + llama-cpp-python.
    """
    import os

    fixture_path = os.environ.get("KILN_PARITY_FIXTURE", "")
    if not fixture_path:
        pytest.skip("KILN_PARITY_FIXTURE not set (parity CI job only)")

    fx = ParityFixture.load(fixture_path)
    model_path = os.environ.get("KILN_PARITY_MODEL", "")
    gguf_path = os.environ.get("KILN_PARITY_GGUF", "")
    if not model_path and not gguf_path:
        pytest.skip("KILN_PARITY_MODEL / KILN_PARITY_GGUF not set (parity CI job only)")

    results: dict[str, dict[int, GenerationRecord]] = {}
    capacities = fx.capacities

    # CUDA / native torch backend — loads the HF reference model directly.
    cuda_available = True
    try:
        from kiln.engine.backends.cuda_native import CUDABackend
    except Exception:  # torch not importable
        cuda_available = False
    if cuda_available and model_path:
        try:
            gpu = CUDABackend()
            gpu.load_model(model_path)
            recs = {
                cap: gpu.generate_parity(fx.prompts[0], max_tokens=64, temperature=0.0)
                for cap in capacities
            }
            results["cuda"] = recs
            gpu.unload()
        except Exception as exc:  # GPU absent / OOM on CI runner
            pytest.skip(f"cuda backend unavailable: {exc}")

    # CPU / llama.cpp GGUF backend — needs the converted weights.
    cpu_available = True
    try:
        from kiln.engine.backends.llama_cpp import CPUBackend
    except Exception:  # llama_cpp not importable
        cpu_available = False
    if cpu_available and gguf_path:
        try:
            cpu = CPUBackend()
            cpu.load_model(gguf_path)
            recs = {
                cap: cpu.generate_parity(fx.prompts[0], max_tokens=64, temperature=0.0)
                for cap in capacities
            }
            results["cpu"] = recs
            cpu.unload()
        except Exception as exc:  # GGUF runtime absent
            pytest.skip(f"cpu backend unavailable: {exc}")

    if not results:
        pytest.skip("no inference backend available in this environment")

    reports = ParityOracle(fx.tolerance).evaluate(fx, results)
    failed = [r for r in reports if not r.passed]
    assert ParityOracle.all_passed(reports), "\n".join(
        f"{r.backend}@{r.capacity}: " + "; ".join(r.notes) for r in failed
    )
