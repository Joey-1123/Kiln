"""Tests for the safetensors-backed expert store + torch expert mover (plan B6)."""

import numpy as np
import pytest
import safetensors.numpy as sn

from kiln.engine.expert_bank import ExpertBank, Strategy
from kiln.engine.expert_mover import TorchExpertMover
from kiln.engine.safetensors_store import SafetensorsExpertStore, build_mover


def _build_model_dir(tmp_path, layer_count: int = 2, expert_count: int = 2):
    """Write a toy single-shard MoE model; return the tmp dir path."""
    tensors = {}
    for layer in range(layer_count):
        for e in range(expert_count):
            rows = 4
            up = f"layers.{layer}.experts.{e}.up_proj.weight"
            gate = f"layers.{layer}.experts.{e}.gate_proj.weight"
            down = f"layers.{layer}.experts.{e}.down_proj.weight"
            tensors[up] = np.ones((rows, 8), dtype=np.float16)
            tensors[gate] = np.ones((rows, 8), dtype=np.float16)
            tensors[down] = np.ones((8, rows), dtype=np.float16)
        # Non-expert tensors that must be ignored by the resolver.
        tensors[f"layers.{layer}.attn.q_proj.weight"] = np.ones((8, 8), dtype=np.float16)
    sn.save_file(tensors, str(tmp_path / "model.safetensors"))
    return tmp_path


def test_store_discovers_experts_and_sizes(tmp_path):
    store = SafetensorsExpertStore(_build_model_dir(tmp_path))
    exps = {e.expert_id: e for e in store.experts()}
    assert set(exps) == {"l0.e0", "l0.e1", "l1.e0", "l1.e1"}

    # Per expert: up(4x8) + gate(4x8) + down(8x4) = 64 + 64 + 64 = 192 fp16 bytes.
    for eid, e in exps.items():
        assert e.size_bytes == 192
        assert e.dims == 8  # max row count (down_proj has 8 rows)
    assert exps["l1.e0"].layer == 1


def test_store_blobs_map_every_shape_tensor(tmp_path):
    store = SafetensorsExpertStore(_build_model_dir(tmp_path))
    blobs = store.expert_blobs()
    keys = set(blobs["l0.e0"])
    assert keys == {
        "layers.0.experts.0.up_proj.weight",
        "layers.0.experts.0.gate_proj.weight",
        "layers.0.experts.0.down_proj.weight",
    }
    # Each tensor resolves to a concrete (shard_path, shard_key) pair.
    shard_path, shard_key = blobs["l0.e0"]["layers.0.experts.0.up_proj.weight"][0]
    assert shard_path.name == "model.safetensors"
    assert shard_key == "layers.0.experts.0.up_proj.weight"


def test_custom_resolver(tmp_path):
    _build_model_dir(tmp_path)
    store = SafetensorsExpertStore(
        tmp_path,
        resolver=lambda key: ("up_proj" in key and ("custom", 0)) or None,
    )
    blobs = store.expert_blobs()
    # Only up_proj tensors matched, grouped under "custom".
    assert set(blobs) == {"custom"}
    assert len(blobs["custom"]) == 4  # two layers x two experts up_proj tensors


def test_store_rejects_empty_model(tmp_path):
    _build_model_dir(tmp_path)
    store = SafetensorsExpertStore(
        tmp_path,
        resolver=lambda key: None,  # ignore everything
    )
    with pytest.raises(ValueError):
        store.experts()


# ---------------------------------------------------------------------------
# TorchExpertMover
# ---------------------------------------------------------------------------


def test_mover_loads_cpu_and_keeps_numpy(tmp_path):
    store = SafetensorsExpertStore(_build_model_dir(tmp_path))
    mover = TorchExpertMover(store.expert_blobs())
    expert = next(e for e in store.experts() if e.expert_id == "l0.e0")

    mover.move(expert, "load", "cpu")
    tensors = mover._resident_tensors["l0.e0"]
    assert set(tensors) == {
        "layers.0.experts.0.up_proj.weight",
        "layers.0.experts.0.gate_proj.weight",
        "layers.0.experts.0.down_proj.weight",
    }
    arr = tensors["layers.0.experts.0.up_proj.weight"]
    assert arr.shape == (4, 8)
    assert mover.is_resident("l0.e0", "cpu")


def test_mover_drop_disk_frees_memory(tmp_path):
    store = SafetensorsExpertStore(_build_model_dir(tmp_path))
    mover = TorchExpertMover(store.expert_blobs())
    expert = next(e for e in store.experts() if e.expert_id == "l0.e0")

    mover.move(expert, "load", "cpu")
    assert "l0.e0" in mover._resident_tensors
    mover.move(expert, "cpu", "disk")
    assert "l0.e0" not in mover._resident_tensors
    assert mover.is_resident("l0.e0", "disk") is False


def test_mover_unknown_tier_raises(tmp_path):
    store = SafetensorsExpertStore(_build_model_dir(tmp_path))
    mover = TorchExpertMover(store.expert_blobs())
    expert = next(e for e in store.experts() if e.expert_id == "l0.e0")
    with pytest.raises(ValueError):
        mover.move(expert, "cpu", "nowhere")


def test_store_populate_bank_registers_all(tmp_path):
    """populate registers every discovered expert into the bank (cpu by default)."""
    store = SafetensorsExpertStore(_build_model_dir(tmp_path))
    bank = ExpertBank(gpu_capacity_bytes=1 << 20, strategy=Strategy.cpu)
    store.populate(bank)
    assert set(bank.experts) == {"l0.e0", "l0.e1", "l1.e0", "l1.e1"}


def test_build_mover_returns_callable(tmp_path):
    store = SafetensorsExpertStore(_build_model_dir(tmp_path))
    mover = build_mover(store)
    import inspect

    assert inspect.ismethod(mover) or callable(mover)


def test_bank_with_real_mover_offloads(tmp_path):
    """End-to-end: bank drives a real mover; evicted experts drop to cpu."""
    store = SafetensorsExpertStore(_build_model_dir(tmp_path))
    mover = TorchExpertMover(store.expert_blobs())
    # 2 * 192 fits; a third forced eviction pushes one back to cpu.
    bank = ExpertBank(gpu_capacity_bytes=400, strategy=Strategy.offload, mover=mover.move)
    exps = {e.expert_id: e for e in store.experts()}
    for eid, e in exps.items():
        bank.register(e)

    bank.enter_decode()
    bank.ensure_resident(exps["l0.e0"])
    bank.ensure_resident(exps["l0.e1"])
    bank.ensure_resident(exps["l1.e0"])  # forces one resident off (400 < 3*192)
    assert "l1.e0" in bank.resident_ids
    assert len(bank.resident_ids) == 2
    assert any(mover.is_resident(eid, "cpu") for eid in ("l0.e0", "l0.e1"))


def test_backend_load_moe_wires_mover(tmp_path):
    """CUDABackend.load_moe_experts builds a real, mover-backed bank (CPU path)."""
    _build_model_dir(tmp_path)
    from kiln.engine.backends.cuda_native import CUDABackend

    backend = CUDABackend()
    bank = backend.load_moe_experts(
        str(tmp_path),
        strategy="offload",
        gpu_capacity_bytes=1 << 30,
    )
    assert set(bank.experts) == {"l0.e0", "l0.e1", "l1.e0", "l1.e1"}
    assert isinstance(backend.expert_mover, TorchExpertMover)

    # Driving the bank moves the expert's shard tensors into memory on the
    # (mock) CPU device, proving the backend->store->mover->bank path.
    bank.enter_decode()
    bank.ensure_resident(bank.experts["l0.e0"])
    assert bank.is_resident("l0.e0")
    # The gpu tier is marked resident; on a CPU box the tensor itself lives on
    # cpu (auto-detect), but the bank->mover placement contract is satisfied.
    assert backend.expert_mover.is_resident("l0.e0", "gpu")
