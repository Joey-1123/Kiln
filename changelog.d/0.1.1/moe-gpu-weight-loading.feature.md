B6 — MoE GPU weight loading: a real safetensors-backed expert store + torch
mover wired into the CUDA backend. `SafetensorsExpertStore` (B6-1) is a
torch-free resolver that reads either a single `*.safetensors` file or a HF
sharded `*.safetensors.index.json` (via `weight_map`) and derives the full
expert topology: `expert_blobs()` maps each `expert_id -> {tensor_key:
[(shard, key)]}`, `experts()` reports real `size_bytes`/`dims` from each
tensor's shape and dtype, and `populate()`/`build_mover()` hand the descriptors
and a weight-movement factory to an `ExpertBank`. `TorchExpertMover` (B6-2)
implements the bank's `Mover` seam with real CPU±disk moves (numpy loads from
the shards) and a lazy GPU `.to(device)` path; both modules import torch /
safetensors only inside functions so the torch-free control plane stays light.
`CUDABackend.load_moe_experts()` (B6-3) wires the three together: it resolves a
model dir, binds a mover to the model's device, and returns a populated
`ExpertBank` the engine trims during decode. The GPU-only gate
(`@pytest.mark.gpu`) proves expert tensors land on the CUDA device and
self-skips off-GPU; the CPU path (store + mover + backend wiring) is covered by
`tests/test_safetensors_store.py`.