V3 — big-MoE native support: spec + validator (`src/kiln/engine/moe_spec.py`).
`MoESpec` describes expert topology (num_experts / expert_dim / routing / top_k /
layers); `validate_moe_spec` enforces coherence; `build_expert_bank` builds the V2
`ExpertBank` the engine routes experts through. Pure-Python and unit-tested without
a GPU; actual expert weight loading runs in CI on hardware.
