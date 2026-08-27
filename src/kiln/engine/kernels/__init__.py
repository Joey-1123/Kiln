"""V2 custom kernels (plan B4) — CUDA graph-capturable decode.

This package holds the torch-backed decode kernels. Everything torch-specific is
lazy-imported inside functions so importing the package on a CPU-only or
torch-free box is safe (the fast suite and startup-light probe never pull torch).
ROCm/AMD support is deferred; these paths target CUDA.
"""
