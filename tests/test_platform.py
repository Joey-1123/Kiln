"""Hermetic tests for the centralized accelerator probe (ROCm A1).

The probe functions lazy-import torch via ``platform._import_torch``, so we
exercise every branch by patching that helper with a fake torch — no real
torch / CUDA / HIP required, and no sys.modules surgery that would fight a
real torch already loaded in the test session.
"""


from kiln.utils import platform


def _fake_torch(*, cuda_available=False, cuda_ver=None, hip_ver=None, has_cuda=True):
    """Build a bare fake torch module object for the probe to inspect.

    ``cuda_available`` may be a bool or a callable used as ``is_available``.
    """
    import types

    fake = types.SimpleNamespace()
    fake.version = types.SimpleNamespace(cuda=cuda_ver, hip=hip_ver)
    if has_cuda:
        is_available = cuda_available if callable(cuda_available) else lambda: cuda_available
        fake.cuda = types.SimpleNamespace(is_available=is_available)
    return fake


class TestAccelerator:
    def test_no_torch_returns_none(self, monkeypatch):
        def boom():
            raise ImportError("no torch")

        monkeypatch.setattr(platform, "_import_torch", boom)
        assert platform.accelerator() == "none"

    def test_torch_without_cuda_attr_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            platform, "_import_torch", lambda: _fake_torch(has_cuda=False)
        )
        assert platform.accelerator() == "none"

    def test_cuda_not_available_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            platform, "_import_torch", lambda: _fake_torch(cuda_available=False)
        )
        assert platform.accelerator() == "none"

    def test_cuda_available_returns_nvidia(self, monkeypatch):
        monkeypatch.setattr(
            platform,
            "_import_torch",
            lambda: _fake_torch(cuda_available=True, cuda_ver="12.1"),
        )
        assert platform.accelerator() == "nvidia"

    def test_hip_build_returns_amd(self, monkeypatch):
        monkeypatch.setattr(
            platform, "_import_torch", lambda: _fake_torch(cuda_available=True, hip_ver="6.0")
        )
        assert platform.accelerator() == "amd"

    def test_raise_returns_none(self, monkeypatch):
        def raise_err():
            raise RuntimeError("driver error")

        monkeypatch.setattr(
            platform, "_import_torch", lambda: _fake_torch(cuda_available=raise_err)
        )
        assert platform.accelerator() == "none"


class TestTorchGpuAvailable:
    def test_no_torch_false(self, monkeypatch):
        def boom():
            raise ImportError("no torch")

        monkeypatch.setattr(platform, "_import_torch", boom)
        assert platform.torch_gpu_available() is False

    def test_cuda_true(self, monkeypatch):
        monkeypatch.setattr(
            platform, "_import_torch", lambda: _fake_torch(cuda_available=True)
        )
        assert platform.torch_gpu_available() is True

    def test_cuda_false(self, monkeypatch):
        monkeypatch.setattr(
            platform, "_import_torch", lambda: _fake_torch(cuda_available=False)
        )
        assert platform.torch_gpu_available() is False

    def test_is_available_raises_returns_false(self, monkeypatch):
        def raise_err():
            raise RuntimeError("driver error")

        monkeypatch.setattr(
            platform, "_import_torch", lambda: _fake_torch(cuda_available=raise_err)
        )
        assert platform.torch_gpu_available() is False


class TestTorchAccelVersion:
    def test_no_torch_none(self, monkeypatch):
        def boom():
            raise ImportError("no torch")

        monkeypatch.setattr(platform, "_import_torch", boom)
        assert platform.torch_accel_version() is None

    def test_cuda_banner(self, monkeypatch):
        monkeypatch.setattr(
            platform,
            "_import_torch",
            lambda: _fake_torch(cuda_available=True, cuda_ver="12.1"),
        )
        assert platform.torch_accel_version() == "cuda 12.1"

    def test_hip_banner(self, monkeypatch):
        monkeypatch.setattr(
            platform,
            "_import_torch",
            lambda: _fake_torch(cuda_available=True, hip_ver="6.0"),
        )
        assert platform.torch_accel_version() == "hip 6.0"

    def test_no_toolkit_none(self, monkeypatch):
        monkeypatch.setattr(
            platform,
            "_import_torch",
            lambda: _fake_torch(cuda_available=True, cuda_ver=None, hip_ver=None),
        )
        assert platform.torch_accel_version() is None


class TestGpuDiscoveryParsers:
    def test_parse_nvidia_smi_single(self):
        out = platform.parse_nvidia_smi(
            "NVIDIA GeForce RTX 4090, 24564, GPU-abc123\n"
        )
        assert out == [
            {"family": "nvidia", "name": "NVIDIA GeForce RTX 4090",
             "vram_mib": 24564, "uuid": "GPU-abc123"}
        ]

    def test_parse_nvidia_smi_multi_and_blanklines(self):
        out = platform.parse_nvidia_smi(
            "RTX 4090, 24564, GPU-1\n\nGTX 1080, 8192, GPU-2\n"
        )
        assert len(out) == 2
        assert out[1]["uuid"] == "GPU-2"

    def test_parse_nvidia_smi_bad_vram_defaults_zero(self):
        out = platform.parse_nvidia_smi("Unknown GPU, n/a, GPU-x")
        assert out[0]["vram_mib"] == 0

    def test_parse_rocm_smi_json(self):
        raw = (
            '{"card0": {"Card series": "AMD Radeon RX 7900 XTX", '
            '"VRAM Total Memory (B)": "26843545600", "Unique ID": "0x1234"}}'
        )
        out = platform.parse_rocm_smi_json(raw)
        assert out == [
            {"family": "amd", "name": "AMD Radeon RX 7900 XTX",
             "vram_mib": 25600, "uuid": "0x1234"}
        ]

    def test_parse_rocm_smi_json_system_wrapper(self):
        raw = (
            '{"system": {"card1": {"Card series": "AMD Instinct MI300X", '
            '"VRAM Total Memory (B)": "107374182400"}}}'
        )
        out = platform.parse_rocm_smi_json(raw)
        assert out[0]["family"] == "amd"
        assert out[0]["name"] == "AMD Instinct MI300X"
        assert out[0]["vram_mib"] == 102400

    def test_parse_rocm_smi_bad_json_falls_back_to_plain(self):
        out = platform.parse_rocm_smi_json("not json at all")
        assert isinstance(out, list)

    def test_parse_rocm_smi_empty(self):
        assert platform.parse_rocm_smi_json("") == []
