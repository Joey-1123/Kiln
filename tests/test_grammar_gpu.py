"""GPU-only: prove real constrained decoding with xgrammar (J/C4).

Skipped unless KILN_QUANT_TEST_MODEL points at a tiny fp16 model and CUDA is
available. Runs only in the dedicated GPU CI job (`-m gpu`). The CPU / wiring
side is covered by ``tests/test_grammar_constraint.py`` (orchestration-only
with stubs); this gate proves actual xgrammar masking produces grammar-valid
output on real hardware.
"""

from __future__ import annotations

import json
import os

import pytest


def _gpu_available() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except Exception:
        return False


@pytest.mark.gpu
def test_cuda_decoded_constraint_yields_valid_json(tmp_path) -> None:
    model_dir = os.environ.get("KILN_QUANT_TEST_MODEL", "")
    if not model_dir:
        pytest.skip("KILN_QUANT_TEST_MODEL not set (GPU CI only)")
    if not _gpu_available():
        pytest.skip("CUDA unavailable")

    try:
        import xgrammar  # noqa: F401
    except ImportError:
        pytest.skip("xgrammar not installed (install the [grammar] extra)")

    from kiln.engine.backends.cuda_native import _INFO, CUDABackend

    assert _INFO.supports_grammar, "CUDA backend should advertise grammar"

    backend = CUDABackend()

    backend.load_model(model_dir, quantization="none")

    schema = (
        '{"type": "object", "properties": {"ok": {"type": "boolean"}},'
        ' "required": ["ok"], "additionalProperties": false}'
    )
    text = backend.generate(
        "Return one JSON object answering: is today Friday?",
        max_tokens=64,
        temperature=0.0,
        grammar=schema,
    )
    assert text, "expected non-empty constrained output"
    parsed = json.loads(text)
    assert isinstance(parsed, dict)
    assert "ok" in parsed and isinstance(parsed["ok"], bool)

    backend.unload()


@pytest.mark.gpu
def test_cuda_streaming_grammar_terminates_and_is_valid_json(tmp_path) -> None:
    model_dir = os.environ.get("KILN_QUANT_TEST_MODEL", "")
    if not model_dir:
        pytest.skip("KILN_QUANT_TEST_MODEL not set (GPU CI only)")
    if not _gpu_available():
        pytest.skip("CUDA unavailable")

    try:
        import xgrammar  # noqa: F401
    except ImportError:
        pytest.skip("xgrammar not installed (install the [grammar] extra)")

    from kiln.engine.backends.cuda_native import CUDABackend

    backend = CUDABackend()
    backend.load_model(model_dir, quantization="none")

    schema = (
        '{"type": "object", "properties": {"n": {"type": "integer"}},'
        ' "required": ["n"], "additionalProperties": false}'
    )
    chunks = list(
        backend.generate_stream(
            "Return one JSON object with an integer field.",
            max_tokens=64,
            temperature=0.0,
            grammar=schema,
        )
    )
    text = "".join(t for t, _ in chunks)
    parsed = json.loads(text)
    assert isinstance(parsed, dict)
    assert isinstance(parsed["n"], int)

    backend.unload()
