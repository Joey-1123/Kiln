AMD ROCm support (slice A1–A4): all accelerator probing now flows through a
single torch-free control-plane API in `utils/platform.py` — `torch_gpu_available()`,
`torch_accel_version()`, `accelerator()` (nvidia/amd/none), and `gpu_devices()` which
parses `nvidia-smi` or `rocm-smi --json` via hermetic pure functions. Since HIP
surfaces AMD GPUs through the `torch.cuda.*` namespace, the device name stays
`"cuda"`, but the backend registry now records a `device_family` (nvidia/amd/any) and
registers a `roc` alias for `CUDABackend`; the engine dispatches on GPU capability
rather than hardcoded name. `kiln doctor` and `kiln plan` report AMD as "AMD (ROCm)"
and recommend the `roc` backend on AMD hardware. Detection call-sites across the
engine (expert mover, decode/triton kernels), the tune measurement cache and
bandwidth probe, and the SFT/DPO trainers' `fp16` gate all route through the probe,
and `quant.available()` offers the GPU schemes for the `roc` tag. Real-hardware
validation is deferred to CI/user runs — the parsing and routing layers are covered
by hermetic unit tests.
