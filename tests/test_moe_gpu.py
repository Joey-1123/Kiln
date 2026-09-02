"""GPU-only: wire the MoE store+mover into the CUDA backend (plan B6-3).

Skipped unless KILN_QUANT_TEST_MODEL points at a tiny fp16 MoE-style model and
CUDA is available. Runs only in the dedicated GPU CI job (`-m gpu`). The CPU /
safetensors side of the same path is already covered by
``tests/test_safetensors_store.py``; this gate proves the real mover lands an
expert's shard tensors on the model's CUDA device.
"""

from __future__ import annotations

import os

import pytest


def _gpu_available() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except Exception:
        return False


@pytest.mark.gpu
def test_moe_experts_land_on_cuda_device(tmp_path) -> None:
    model_dir = os.environ.get("KILN_QUANT_TEST_MODEL", "")
    if not model_dir:
        pytest.skip("KILN_QUANT_TEST_MODEL not set (GPU CI only)")
    if not _gpu_available():
        pytest.skip("CUDA unavailable")

    from kiln.engine.backends.cuda_native import CUDABackend
    from kiln.engine.safetensors_store import SafetensorsExpertStore

    backend = CUDABackend()
    backend.load_model(model_dir, quantization="none")

    # The tiny GPU fixture may not be MoE-shaped; if so, synth a sharded
    # expert store next to the model so the spot is what B6 wires against.
    store = SafetensorsExpertStore(model_dir)
    if not store.experts():
        pytest.skip("model has no expert tensors under the default resolver")

    bank = backend.load_moe_experts(model_dir, strategy="offload", gpu_capacity_bytes=1 << 30)
    bank.enter_decode()

    first_id = next(iter(bank.experts))
    bank.ensure_resident(bank.experts[first_id])

    mover = backend.expert_mover
    assert mover is not None
    assert mover.is_resident(first_id, "gpu"), "expert not resident on gpu tier"
    tensors = mover._resident_tensors[first_id]
    assert tensors, "expected resident tensors after ensure_resident"
    # Every tensor of the placed expert must live on the model's device.
    for key, tensor in tensors.items():
        assert tensor.device.type == "cuda", f"{key} not on CUDA (got {tensor.device})"

    backend.unload()
