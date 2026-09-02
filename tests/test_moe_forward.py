"""Tests for the B6 MoE forward block (``moe_forward``).

These drive the full weight path introduced by B6 — a toy safetensors
shard -> :class:`SafetensorsExpertStore` -> :class:`TorchExpertMover` ->
:class:`ExpertBank` -> :class:`MoeForward` — and assert that routing through the
bank produces a correct, eviction-stable routed output. They run on CPU only.
"""

import numpy as np
import pytest
import safetensors.numpy as sn

from kiln.engine.expert_bank import Expert, ExpertBank, Strategy
from kiln.engine.expert_mover import TorchExpertMover
from kiln.engine.moe_forward import (
    MoeForward,
    _projection_key,
    route_experts,
    route_experts_batch,
    route_from_bank,
)
from kiln.engine.safetensors_store import SafetensorsExpertStore


def _build_model_dir(tmp_path, layer_count: int = 1, expert_count: int = 2):
    """Write a toy single-shard MoE model; return the tmp dir path.

    Hidden size is fixed at 8; each expert owns up(4x8), gate(4x8), down(8x4)
    so ``d_model=8``, ``expert_dim=4`` and a projection is (out, in). We load
    with distractor weights so a mix-up of experts or projections changes
    output measurably.
    """
    tensors = {}
    for layer in range(layer_count):
        for e in range(expert_count):
            # Distinct weights per expert: gate differs from up, and index by e.
            up = np.ones((4, 8), dtype=np.float16) * (e + 1)
            gate = np.ones((4, 8), dtype=np.float16) * (e + 1) * -1
            down = np.ones((8, 4), dtype=np.float16) * (e + 1)
            tensors[f"layers.{layer}.experts.{e}.up_proj.weight"] = up
            tensors[f"layers.{layer}.experts.{e}.gate_proj.weight"] = gate
            tensors[f"layers.{layer}.experts.{e}.down_proj.weight"] = down
    sn.save_file(tensors, str(tmp_path / "model.safetensors"))
    return tmp_path


def _bank(tmp_path, gpu_capacity: int, strategy: Strategy = Strategy.offload):
    """Build a full B6 stack: store -> mover -> bank. Return ``(store, mover, bank)``."""
    store = SafetensorsExpertStore(_build_model_dir(tmp_path))
    mover = TorchExpertMover(store.expert_blobs())
    bank = ExpertBank(gpu_capacity, strategy=strategy, mover=mover.move)
    for e in store.experts():
        bank.register(e)
    return store, mover, bank


def _bank_in_decode(tmp_path, gpu_capacity: int):
    """Build the stack and enter the decode phase (eviction is now legal)."""
    _, mover, bank = _bank(tmp_path, gpu_capacity)
    bank.enter_decode()
    return mover, bank


def _weave(bank, mover, hidden=8):
    return MoeForward(bank, mover=mover, hidden_size=hidden)


# ---------------------------------------------------------------------------
# Projection-key resolver
# ---------------------------------------------------------------------------


def test_projection_key_rebuilds_safetensors_names():
    assert _projection_key("l0.e0", "up_proj") == "layers.0.experts.0.up_proj.weight"
    assert _projection_key("l2.e5", "down_proj") == "layers.2.experts.5.down_proj.weight"
    assert _projection_key("l10.e3", "gate_proj") == "layers.10.experts.3.gate_proj.weight"


# ---------------------------------------------------------------------------
# Forward compute (routed, real weights through the mover)
# ---------------------------------------------------------------------------


def test_routed_produces_weighted_sum_of_expert_projections(tmp_path):
    _, mover, bank = _bank(tmp_path, gpu_capacity=10_000)
    fwd = _weave(bank, mover)
    x = np.linspace(-1, 1, 8, dtype=np.float32)

    out = fwd.routed(x, ["l0.e0", "l0.e1"], [0.4, 0.6])

    # Manual reference: for expert e with scale s,
    #   contrib_e = s * ( (x @ up.T) * (x @ gate.T) ) @ down.T
    contribs = []
    for ei, s in (("e0", 0.4), ("e1", 0.6)):
        exp_num = ei[1:]
        up = mover._resident_tensors[f"l0.{ei}"][f"layers.0.experts.{exp_num}.up_proj.weight"]
        gate = mover._resident_tensors[f"l0.{ei}"][f"layers.0.experts.{exp_num}.gate_proj.weight"]
        down = mover._resident_tensors[f"l0.{ei}"][f"layers.0.experts.{exp_num}.down_proj.weight"]
        # Mover holds torch CPU tensors; the forward coerces to numpy for x.
        up, gate, down = (np.asarray(t.detach().cpu().numpy()) for t in (up, gate, down))
        x_up = x @ up.T
        x_gate = x @ gate.T
        inner = x_up * x_gate
        contribs.append(s * (inner @ down.T))
    expected = contribs[0] + contribs[1]

    np.testing.assert_allclose(np.asarray(out), expected, atol=1e-2, rtol=1e-2)


def test_routed_single_expert_matches_direct_computation(tmp_path):
    _, mover, bank = _bank(tmp_path, gpu_capacity=10_000)
    fwd = _weave(bank, mover)
    x = np.linspace(-1, 1, 8, dtype=np.float32)

    out = fwd.routed(x, ["l0.e0"], [1.0])

    up = mover._resident_tensors["l0.e0"]["layers.0.experts.0.up_proj.weight"]
    gate = mover._resident_tensors["l0.e0"]["layers.0.experts.0.gate_proj.weight"]
    down = mover._resident_tensors["l0.e0"]["layers.0.experts.0.down_proj.weight"]
    up, gate, down = (np.asarray(t.detach().cpu().numpy()) for t in (up, gate, down))
    expected = ((x @ up.T) * (x @ gate.T)) @ down.T

    np.allclose(np.asarray(out), expected, atol=1e-2)


# ---------------------------------------------------------------------------
# Parity: all-resident vs evict-reload must be bit-identical
# ---------------------------------------------------------------------------


def test_routed_identical_under_evict_reload_parity(tmp_path):
    """Routing 2 experts must be deterministic regardless of residency policy.

    A tiny GPU budget forces the bank to evict one expert to fit the other, so
    the mover reloads between the two expert projections; the routed output
    must not change.
    """
    # Budget fits exactly one expert (192 bytes each), forcing evict-reload.
    mover_a, bank_a = _bank_in_decode(tmp_path, gpu_capacity=192)
    fwd_a = _weave(bank_a, mover_a)
    x = np.linspace(-1, 1, 8, dtype=np.float32)
    out_a = fwd_a.routed(x, ["l0.e0", "l0.e1"], [0.5, 0.5])

    # Same model, generous budget: both stay resident, no eviction.
    mover_b, bank_b = _bank_in_decode(tmp_path, gpu_capacity=10_000)
    fwd_b = _weave(bank_b, mover_b)
    out_b = fwd_b.routed(x, ["l0.e0", "l0.e1"], [0.5, 0.5])

    np.testing.assert_allclose(
        np.asarray(out_a), np.asarray(out_b), atol=1e-2, rtol=1e-2
    )
    # And the evict-reload path really did evict: with a one-expert budget the
    # second routed expert cannot be resident simultaneously with the first.
    assert not (bank_a.is_resident("l0.e0") and bank_a.is_resident("l0.e1"))
    assert bank_b.is_resident("l0.e0") and bank_b.is_resident("l0.e1")


def test_ensure_resident_materializes_through_mover(tmp_path):
    """Before routing, requested experts are resident; the mover holds tensors."""
    _, mover, bank = _bank(tmp_path, gpu_capacity=10_000)
    fwd = _weave(bank, mover)
    fwd.routed(np.linspace(0, 1, 8), ["l0.e0"], [1.0])
    assert bank.is_resident("l0.e0")
    assert "l0.e0" in mover._resident_tensors


def test_cpu_strategy_never_promotes_to_gpu(tmp_path):
    _, mover, bank = _bank(tmp_path, gpu_capacity=10_000, strategy=Strategy.cpu)
    fwd = _weave(bank, mover)
    fwd.routed(np.linspace(0, 1, 8), ["l0.e0"], [1.0])
    assert not bank.is_resident("l0.e0")


def test_unknown_expert_without_hidden_raises(tmp_path):
    _, mover, bank = _bank(tmp_path, gpu_capacity=10_000)
    fwd = MoeForward(bank, mover=mover, hidden_size=0)
    with pytest.raises(KeyError):
        fwd.routed(np.zeros(8), ["l99.e9"], [1.0])


def test_synthetic_identity_projection_no_mover(tmp_path):
    """Without a mover, identity projections route x through the MoE math.

    With up=gate=down=identity the routed single-expert result is
    ``(x * x) @ I == x ** 2`` (MoE gate is a pointwise product, not a no-op).
    """
    bank = ExpertBank(10_000, strategy=Strategy.offload)
    bank.register(Expert("l0.e0", size_bytes=192, dims=8))
    fwd = MoeForward(bank, mover=None, hidden_size=8)
    x = np.linspace(-1, 1, 8)
    out = fwd.routed(x, ["l0.e0"], [1.0])
    np.testing.assert_allclose(np.asarray(out), x * x, rtol=1e-6, atol=1e-6)



# ---------------------------------------------------------------------------
# Backend integration: CUDABackend.load_moe_experts binds a routed forward
# ---------------------------------------------------------------------------


def test_backend_load_moe_experts_binds_forward(tmp_path):
    """The backend exposes the bound forward + bank after load_moe_experts."""
    from kiln.engine.backends.cuda_native import CUDABackend
    from kiln.engine.moe_forward import MoeForward

    _build_model_dir(tmp_path)
    backend = CUDABackend()
    bank = backend.load_moe_experts(str(tmp_path), strategy="offload")
    assert backend.moe_bank is bank
    assert isinstance(backend.moe_forward, MoeForward)
    assert backend.expert_mover is not None


def test_backend_routed_forward_matches_direct(tmp_path):
    """routed_forward returns the correctly routed expert output on CPU."""
    from kiln.engine.backends.cuda_native import CUDABackend

    _build_model_dir(tmp_path)
    backend = CUDABackend()
    bank = backend.load_moe_experts(str(tmp_path), strategy="offload")
    bank.enter_decode()

    x = np.linspace(-1, 1, 8, dtype=np.float32)
    out = backend.routed_forward(x, ["l0.e0"], [1.0])

    up = backend.expert_mover._resident_tensors["l0.e0"]["layers.0.experts.0.up_proj.weight"]
    gate = backend.expert_mover._resident_tensors["l0.e0"]["layers.0.experts.0.gate_proj.weight"]
    down = backend.expert_mover._resident_tensors["l0.e0"]["layers.0.experts.0.down_proj.weight"]
    up, gate, down = (np.asarray(t.detach().cpu().numpy()) for t in (up, gate, down))
    expected = ((x @ up.T) * (x @ gate.T)) @ down.T

    np.allclose(np.asarray(out), expected, atol=1e-2)


def test_backend_routed_forward_requires_load(tmp_path):
    """routed_forward before load_moe_experts raises a clear error."""
    from kiln.engine.backends.cuda_native import CUDABackend

    backend = CUDABackend()
    import pytest as _pytest

    with _pytest.raises(RuntimeError):
        backend.routed_forward(np.zeros(8), ["l0.e0"], [1.0])



# ---------------------------------------------------------------------------
# Batch routing (sequence of tokens with per-position expert sets)
# ---------------------------------------------------------------------------


def test_routed_batch_routes_each_position_independently(tmp_path):
    _, mover, bank = _bank(tmp_path, gpu_capacity=10_000)
    fwd = _weave(bank, mover)
    x = np.linspace(-1, 1, 32, dtype=np.float32).reshape(4, 8)

    # Position 0 -> e0, position 1..3 -> e1.
    routes = [
        (["l0.e0"], [1.0]),
        (["l0.e1"], [1.0]),
        (["l0.e1"], [1.0]),
        (["l0.e1"], [1.0]),
    ]
    out = fwd.routed_batch(x, routes)

    # Reference per row against the mover's real weights.
    expected = []
    for i, (ei, sc) in enumerate(routes):
        eid = ei[0]  # "l<L>.e<E>"
        _, right = eid.split(".")
        layer = int(eid[1: eid.index(".")])
        expert = int(right[1:])
        tens = mover._resident_tensors[eid]
        pref = f"layers.{layer}.experts.{expert}."
        w = {p: np.asarray(tens[pref + p + ".weight"].detach().cpu().numpy())
             for p in ("up_proj", "gate_proj", "down_proj")}
        row = x[i]
        expected.append(((row @ w["up_proj"].T) * (row @ w["gate_proj"].T)) @ w["down_proj"].T)
    expected = np.stack(expected)

    np.allclose(np.asarray(out), expected, atol=1e-2)
    assert np.asarray(out).shape == (4, 8)


def test_routed_batch_ensures_resident_union(tmp_path):
    _, mover, bank = _bank(tmp_path, gpu_capacity=10_000)
    fwd = _weave(bank, mover)
    x = np.linspace(-1, 1, 16).reshape(2, 8)
    routes = [(["l0.e0"], [1.0]), (["l0.e1"], [1.0])]
    fwd.routed_batch(x, routes)
    assert bank.is_resident("l0.e0") and bank.is_resident("l0.e1")


def test_routed_batch_rejects_wrong_route_count(tmp_path):
    _, mover, bank = _bank(tmp_path, gpu_capacity=10_000)
    fwd = _weave(bank, mover)
    x = np.linspace(-1, 1, 24).reshape(3, 8)
    import pytest as _pytest

    with _pytest.raises(ValueError):
        fwd.routed_batch(x, [(["l0.e0"], [1.0])])  # 1 route for 3 rows



# ---------------------------------------------------------------------------
# route_experts gate primitive
# ---------------------------------------------------------------------------


def test_route_experts_returns_top2_with_normalised_scores():
    ids = ["l0.e0", "l0.e1", "l0.e2"]
    logits = [0.0, 10.0, 5.0]  # e1 >> e2 > e0
    sel, scores = route_experts(logits, ids, top_k=2)
    assert set(sel) == {"l0.e1", "l0.e2"}
    assert abs(scores[0] + scores[1] - 1.0) < 1e-6
    # e1 has the higher logit and must rank first.
    assert sel[0] == "l0.e1"


def test_route_experts_clamps_top_k_to_available():
    ids = ["l0.e0"]
    logits = [1.0]
    sel, scores = route_experts(logits, ids, top_k=5)
    assert sel == ["l0.e0"]
    assert abs(scores[0] - 1.0) < 1e-6


def test_route_experts_empty_when_no_experts():
    sel, scores = route_experts([], [], top_k=2)
    assert sel == [] and scores == []


def test_route_experts_equal_logits_gives_equal_scores():
    ids = ["a", "b", "c", "d"]
    logits = [1.0, 1.0, 1.0, 1.0]
    sel, scores = route_experts(logits, ids, top_k=2)
    # All logits identical → equal probs → top-k subset still equal after
    # renormalisation (each ≈ 0.5).
    for s in scores:
        assert abs(s - 0.5) < 1e-6


def test_route_experts_end_to_end_with_routed(tmp_path):
    """Feed route_experts output directly into MoeForward.routed."""
    _, mover, bank = _bank(tmp_path, gpu_capacity=10_000)
    fwd = _weave(bank, mover)
    expert_ids = ["l0.e0", "l0.e1"]
    logits = [0.0, 10.0]
    sel, scores = route_experts(logits, expert_ids, top_k=2)
    x = np.linspace(-1, 1, 8, dtype=np.float32)
    out = fwd.routed(x, sel, scores)
    assert np.asarray(out).shape == (8,)



# ---------------------------------------------------------------------------
# Torch-path coverage (CPU torch tensors, no GPU needed)
# ---------------------------------------------------------------------------


def _bank_torch(tmp_path):
    """Build a B6 stack with torch tensors (device=cpu) for the torch path."""
    store = SafetensorsExpertStore(_build_model_dir(tmp_path))
    mover = TorchExpertMover(store.expert_blobs(), device="cpu")
    bank = ExpertBank(10_000, strategy=Strategy.offload, mover=mover.move)
    for e in store.experts():
        bank.register(e)
    bank.enter_decode()
    return mover, bank


def test_routed_torch_path_matches_numpy(tmp_path):
    """Routed output with torch tensors matches the numpy path."""
    import torch

    # Numpy reference path.
    _, mover_np, bank_np = _bank(tmp_path, gpu_capacity=10_000)
    fwd_np = _weave(bank_np, mover_np)
    x_np = np.linspace(-1, 1, 8, dtype=np.float32)
    out_np = fwd_np.routed(x_np, ["l0.e0"], [1.0])

    # Torch path: mover has torch CPU tensors; x is torch.
    mover_th, bank_th = _bank_torch(tmp_path)
    fwd_th = _weave(bank_th, mover_th)
    x_th = torch.linspace(-1, 1, 8)
    out_th = fwd_th.routed(x_th, ["l0.e0"], [1.0])

    np.testing.assert_allclose(
        np.asarray(out_np), out_th.detach().cpu().numpy(), atol=1e-2, rtol=1e-2
    )


def test_routed_batch_torch_path(tmp_path):
    """Batched routing with torch tensors produces correct shape."""
    import torch

    mover_th, bank_th = _bank_torch(tmp_path)
    fwd_th = _weave(bank_th, mover_th)
    x = torch.linspace(-1, 1, 16).reshape(2, 8)
    routes = [(["l0.e0"], [1.0]), (["l0.e1"], [1.0])]
    out = fwd_th.routed_batch(x, routes)
    assert out.shape == (2, 8)



# ---------------------------------------------------------------------------
# route_experts_batch
# ---------------------------------------------------------------------------


def test_route_experts_batch_returns_per_position_routes():
    ids = ["l0.e0", "l0.e1", "l0.e2"]
    logits = np.array([
        [0.0, 10.0, 5.0],   # pos 0: e1 >> e2 > e0
        [10.0, 0.0, 0.0],   # pos 1: e0 >> e1 = e2
    ])
    routes = route_experts_batch(logits, ids, top_k=2)
    assert len(routes) == 2
    sel0, sc0 = routes[0]
    assert sel0[0] == "l0.e1"
    sel1, sc1 = routes[1]
    assert sel1[0] == "l0.e0"


def test_route_experts_batch_1d_logit_single_position():
    """A single (n,) logit vector is treated as one position."""
    ids = ["a", "b"]
    logits = np.array([3.0, 1.0])
    routes = route_experts_batch(logits, ids, top_k=1)
    assert len(routes) == 1
    assert routes[0][0] == ["a"]



# ---------------------------------------------------------------------------
# Multi-layer routing
# ---------------------------------------------------------------------------


def test_routed_multi_layer_experts(tmp_path):
    """Experts from different layers route correctly through the bank."""
    store = SafetensorsExpertStore(_build_model_dir(tmp_path, layer_count=3, expert_count=2))
    mover = TorchExpertMover(store.expert_blobs(), device="cpu")
    bank = ExpertBank(10_000, strategy=Strategy.offload, mover=mover.move)
    for e in store.experts():
        bank.register(e)
    bank.enter_decode()
    assert set(bank.experts) == {
        f"l{L}.e{E}" for L in range(3) for E in range(2)
    }

    fwd = MoeForward(bank, mover=mover, hidden_size=8)
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0], dtype=np.float32)
    out = fwd.routed(x, ["l0.e0", "l1.e1", "l2.e0"], [0.5, 0.3, 0.2])
    assert np.asarray(out).shape == (8,)
    assert not np.allclose(out, np.zeros(8))


def test_routed_cross_layer_batch(tmp_path):
    """Batched routing with experts from different layers."""
    store = SafetensorsExpertStore(_build_model_dir(tmp_path, layer_count=2, expert_count=2))
    mover = TorchExpertMover(store.expert_blobs(), device="cpu")
    bank = ExpertBank(10_000, strategy=Strategy.offload, mover=mover.move)
    for e in store.experts():
        bank.register(e)
    bank.enter_decode()

    fwd = MoeForward(bank, mover=mover, hidden_size=8)
    x = np.arange(16, dtype=np.float32).reshape(2, 8)
    routes = [
        (["l0.e0", "l1.e1"], [0.6, 0.4]),
        (["l1.e0", "l0.e1"], [0.7, 0.3]),
    ]
    out = fwd.routed_batch(x, routes)
    assert out.shape == (2, 8)



# ---------------------------------------------------------------------------
# Commutativity and score-sum invariants
# ---------------------------------------------------------------------------


def test_routed_commutative_in_expert_order(tmp_path):
    """Routing {e0, e1} in either order gives the same output (weighted sum)."""
    _, mover, bank = _bank(tmp_path, gpu_capacity=10_000)
    fwd = _weave(bank, mover)
    bank.enter_decode()
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0], dtype=np.float32)

    out_01 = fwd.routed(x, ["l0.e0", "l0.e1"], [0.4, 0.6])
    out_10 = fwd.routed(x, ["l0.e1", "l0.e0"], [0.6, 0.4])

    np.testing.assert_allclose(np.asarray(out_01), np.asarray(out_10), atol=1e-5)


def test_routed_score_sum_invariant(tmp_path):
    """With all-resident experts, output scales with score total."""
    _, mover, bank = _bank(tmp_path, gpu_capacity=10_000)
    fwd = _weave(bank, mover)
    bank.enter_decode()
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0], dtype=np.float32)

    out_half = fwd.routed(x, ["l0.e0"], [0.5])
    out_full = fwd.routed(x, ["l0.e0"], [1.0])

    # Score 1.0 = full expert output; score 0.5 = half that.
    np.testing.assert_allclose(
        np.asarray(out_full), np.asarray(out_half) * 2.0, atol=1e-3
    )



# ---------------------------------------------------------------------------
# Edge cases: empty routing, duplicate experts, malformed input
# ---------------------------------------------------------------------------


def test_routed_empty_expert_ids_returns_zero(tmp_path):
    """Routing zero experts returns a zero tensor of the same shape."""
    _, mover, bank = _bank(tmp_path, gpu_capacity=10_000)
    fwd = _weave(bank, mover)
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0], dtype=np.float32)
    out = fwd.routed(x, [], [])
    np.testing.assert_array_equal(np.asarray(out), np.zeros(8))


def test_routed_duplicate_expert_ids(tmp_path):
    """Routing the same expert twice applies its score twice (weighted sum)."""
    _, mover, bank = _bank(tmp_path, gpu_capacity=10_000)
    fwd = _weave(bank, mover)
    bank.enter_decode()
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0], dtype=np.float32)

    out_dup = fwd.routed(x, ["l0.e0", "l0.e0"], [0.5, 0.5])
    out_one = fwd.routed(x, ["l0.e0"], [1.0])

    np.testing.assert_allclose(np.asarray(out_dup), np.asarray(out_one), atol=1e-5)


def test_route_experts_scores_always_sum_to_one():
    """route_experts normalised scores always sum to 1.0."""
    for logits in [[1.0, 2.0, 3.0], [0.0, 0.0, 0.0], [-100.0, 100.0, -50.0]]:
        _, scores = route_experts(logits, ["a", "b", "c"], top_k=2)
        assert abs(sum(scores) - 1.0) < 1e-6



# ---------------------------------------------------------------------------
# Eviction observability
# ---------------------------------------------------------------------------


def test_eviction_count_increases_with_evictions(tmp_path):
    """A tight GPU budget forces evictions; the counter tracks them."""
    _, mover, bank = _bank(tmp_path, gpu_capacity=192)  # fits one expert
    fwd = _weave(bank, mover)
    bank.enter_decode()

    fwd.routed(np.ones(8), ["l0.e0"], [1.0])
    first_count = fwd.weight_moves
    assert first_count == 0  # first placement is not an eviction

    fwd.routed(np.ones(8), ["l0.e1"], [1.0])
    assert fwd.weight_moves > first_count  # e0 evicted to make room for e1


def test_eviction_count_resets():
    bank = ExpertBank(10_000, strategy=Strategy.offload)
    fwd = MoeForward(bank, hidden_size=8)
    fwd._evictions = 5
    fwd.reset_weight_moves()
    assert fwd.weight_moves == 0



# ---------------------------------------------------------------------------
# route_from_bank (bank-aware routing)
# ---------------------------------------------------------------------------


def test_route_from_bank_uses_bank_topology(tmp_path):
    """route_from_bank maps logits to the bank's sorted expert ids."""
    _, _, bank = _bank(tmp_path, gpu_capacity=10_000)
    expert_ids = sorted(bank.experts)
    assert len(expert_ids) == 2  # l0.e0, l0.e1
    logits = [0.0, 10.0]  # second expert has highest logit
    sel, scores = route_from_bank(logits, bank, top_k=1)
    assert sel == [expert_ids[1]]


def test_route_from_bank_rejects_length_mismatch(tmp_path):
    _, _, bank = _bank(tmp_path, gpu_capacity=10_000)
    import pytest as _pytest

    with _pytest.raises(ValueError):
        route_from_bank([1.0], bank, top_k=1)  # 1 logit != 2 experts



# ---------------------------------------------------------------------------
# Backend lifecycle integration
# ---------------------------------------------------------------------------


def test_backend_lifecycle_load_route_exit(tmp_path):
    """Full cycle: load → enter_decode → routed_forward → exit_decode."""
    from kiln.engine.backends.cuda_native import CUDABackend

    _build_model_dir(tmp_path)
    backend = CUDABackend()
    bank = backend.load_moe_experts(str(tmp_path), strategy="offload")
    bank.enter_decode()

    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0], dtype=np.float32)
    out = backend.routed_forward(x, ["l0.e0"], [1.0])
    assert np.asarray(out).shape == (8,)

    bank.exit_decode()
    assert not bank._decode_phase



# ---------------------------------------------------------------------------
# Multi-budget parity
# ---------------------------------------------------------------------------


def test_routed_identical_across_three_budgets(tmp_path):
    """Same routing decision produces identical output regardless of GPU budget."""
    budgets = [192, 384, 10_000]
    results = []
    for cap in budgets:
        _, mover, bank = _bank(tmp_path, gpu_capacity=cap)
        bank.enter_decode()
        fwd = _weave(bank, mover)
        x = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0], dtype=np.float32)
        out = fwd.routed(x, ["l0.e0", "l0.e1"], [0.4, 0.6])
        results.append(np.asarray(out))

    for i in range(1, len(results)):
        np.testing.assert_allclose(results[0], results[i], atol=1e-2, rtol=1e-2)
