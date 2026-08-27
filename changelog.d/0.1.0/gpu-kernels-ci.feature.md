V2 kernels (B4) + CI (B7) — CUDA decode graph. `src/kiln/engine/kernels/decode.py`
adds `CudaGraphDecode`, which captures a fixed step sequence into a `torch.cuda.Graph`
and replays it (parity-checked against eager). Torch is lazy-imported so the fast
suite stays green; the GPU tests are `@pytest.mark.gpu` and skip without CUDA.
CI gained a `gpu` job (self-hosted CUDA runner label) that runs the `-m gpu` suite.
ROCm/AMD support is deferred.
