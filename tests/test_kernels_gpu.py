"""GPU tests for the CUDA-graph decode kernels (plan B4). CUDA only.

Torch is imported lazily inside each test so this module is safe to collect on a
torch-free / CPU box — it simply skips. Run on a CUDA runner with `pytest -m gpu`.
ROCm/AMD support is deferred.
"""

import pytest

pytestmark = pytest.mark.gpu


def _require_cuda():
    try:
        import torch
    except ImportError:
        pytest.skip("torch not installed")
    if not torch.cuda.is_available():
        pytest.skip("CUDA not available")
    return torch


def test_captured_graph_matches_eager():
    torch = _require_cuda()
    from kiln.engine.kernels.decode import CudaGraphDecode, make_demo_steps

    dim = 64
    steps = make_demo_steps(dim)
    sched = CudaGraphDecode(steps)

    x = torch.randn(dim, device="cuda")
    eager = sched.run_eager(x.clone(), n_iterations=1)
    sched.capture(x.clone())
    captured = sched.run_captured(x.clone())

    assert sched.captured
    assert torch.allclose(eager, captured, atol=1e-5)


def test_run_captured_requires_capture():
    torch = _require_cuda()
    from kiln.engine.kernels.decode import CudaGraphDecode, make_demo_steps

    sched = CudaGraphDecode(make_demo_steps(16))
    with pytest.raises(RuntimeError):
        sched.run_captured(torch.randn(16, device="cuda"))
