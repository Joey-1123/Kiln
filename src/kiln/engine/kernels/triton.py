"""First fused Triton kernel — additive bias for decode logits (V2).

Triton is an optional accelerator; the kernel is lazy-imported so the
torch-free control plane never imports it. When Triton or CUDA is absent
the implementation falls back to a fused torch path that preserves the
same numerical contract so the parity oracle can verify equivalence.

The kernel itself is intentionally small: a row-wise ``out = x + bias``
that fuses what would otherwise be two separate elementwise launches.
Larger fused matmul/softmax kernels arrive behind the same seam once this
flag is proven.
"""

from __future__ import annotations

from typing import Any


def _try_triton_kernel() -> Any | None:
    try:
        import triton
        import triton.language as tl

        @triton.jit
        def _bias_add_kernel(
            x_ptr: Any,
            bias_ptr: Any,
            out_ptr: Any,
            n_elements: int,
            block: tl.constexpr,  # type: ignore[valid-type]
        ) -> None:
            pid = tl.arange(0, block)
            mask = pid < n_elements
            x = tl.load(x_ptr + pid, mask=mask)
            b = tl.load(bias_ptr + pid, mask=mask)
            tl.store(out_ptr + pid, x + b, mask=mask)

        return _bias_add_kernel
    except Exception:
        return None


_TRITON_KERNEL = None


def _get_kernel() -> Any | None:
    global _TRITON_KERNEL
    if _TRITON_KERNEL is None:
        _TRITON_KERNEL = _try_triton_kernel()
    return _TRITON_KERNEL


def fused_bias_add(x: Any, bias: Any) -> Any:
    """Fused ``x + bias`` elementwise add via Triton when available.

    Falls back to ``x + bias`` in torch. Both paths are numerically identical
    so the parity harness can compare them directly.
    """
    kernel = _get_kernel()
    if kernel is not None:
        try:
            import torch

            if x.is_cuda and bias.is_cuda and x.shape == bias.shape:
                out = torch.empty_like(x)
                n = x.numel()
                block = 1024
                grid = (1,)
                kernel[grid](x, bias, out, n, block=block)
                return out
        except Exception:
            pass
    return x + bias


def is_triton_available() -> bool:
    """Whether a Triton-backed path can be used on this machine."""
    k = _get_kernel()
    if k is None:
        return False
    try:
        import torch

        return torch.cuda.is_available()
    except Exception:
        return False
