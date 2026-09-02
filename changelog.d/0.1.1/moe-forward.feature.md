B6 forward — the decode-phase MoE compute block (`MoeForward`). Closes the
deferred *forward* half of B6: given hidden states and a top-k routing decision,
`MoeForward.routed()` guarantees each routed expert is resident in the
`ExpertBank` (decode phase) and computes the standard up/gate/down projections
from the mover's live weight registry, aggregated by routing score:
`out = sum_i s_i ((x @ up_i.T) * (x @ gate_i.T)) @ down_i.T`. Weights follow
`nn.Linear` `(out, in)` layout and are coerced into the input's library/device
so CPU-parity runs (numpy) and GPU runs (torch) share one code path without
mixing operands; torch/safetensors stay lazily imported. A parity test in
`tests/test_moe_forward.py` routes the same two experts under an all-resident
budget and a one-expert budget (forcing real evict-reload) and asserts
bit-identical output — proving eviction is weight-transparent. Identity
projections make the block unit-testable without a full sharded model.