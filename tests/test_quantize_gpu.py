"""GPU-only: quantize a tiny model and gate on parity vs fp16.

Skipped unless KILN_QUANT_TEST_MODEL / KILN_QUANT_TEST_CALIB point at a tiny
fp16 model + calibration JSONL, CUDA is available, and the quantizer libs are
installed.  Runs only in the dedicated GPU CI job (`-m gpu`).
"""

from __future__ import annotations

import os

import pytest

from kiln.quant.quantize import QuantJob, _run_quantize


def _gpu_available() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except Exception:
        return False


@pytest.mark.gpu
def test_quantize_preserves_parity(tmp_path) -> None:
    model_path = os.environ.get("KILN_QUANT_TEST_MODEL", "")
    calib_path = os.environ.get("KILN_QUANT_TEST_CALIB", "")
    if not model_path or not calib_path:
        pytest.skip("KILN_QUANT_TEST_MODEL / KILN_QUANT_TEST_CALIB not set (GPU CI only)")
    if not _gpu_available():
        pytest.skip("CUDA unavailable")

    scheme = os.environ.get("KILN_QUANT_TEST_SCHEME", "gptq")
    try:
        import auto_gptq  # noqa: F401
        import awq  # noqa: F401
    except Exception as exc:
        pytest.skip(f"quantizer libs unavailable: {exc}")

    from kiln.engine.backends.cuda_native import CUDABackend

    job = QuantJob(
        scheme=scheme,
        model_dir=model_path,
        output_dir=str(tmp_path / "out"),
        calibration_data=calib_path,
    )
    result = _run_quantize(job)
    assert result.scheme == scheme
    assert result.output_paths

    prompt = "The capital of France is"
    # Reference: fp16 model.
    ref = CUDABackend()
    ref.load_model(model_path, quantization="none")
    ref_rec = ref.generate_parity(prompt, max_tokens=32, temperature=0.0)
    ref.unload()

    # Quantized artifact.
    q = CUDABackend()
    q.load_model(result.output_paths[0], quantization="none")
    q_rec = q.generate_parity(prompt, max_tokens=32, temperature=0.0)
    q.unload()

    # Correctness anchor: greedy argmax path must match the fp16 reference.
    assert q_rec.tokens == ref_rec.tokens, (
        "Quantized model diverged from fp16 reference under greedy decode."
    )
