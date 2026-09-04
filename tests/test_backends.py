"""Tests for engine.backends — capability matrix and registry."""

from kiln.engine.backends import (
    BackendInfo,
    clear_registry,
    get_backend,
    list_backends,
    register_backend,
    select_backend,
)


class TestRegistry:
    def setup_method(self):
        clear_registry()

    def test_register_and_get(self):
        """Should register and retrieve a backend."""
        info = BackendInfo(name="test", supports_gpu=True)
        register_backend(info)
        assert get_backend("test") is info

    def test_list_backends(self):
        """Should list all registered backends."""
        register_backend(BackendInfo(name="a"))
        register_backend(BackendInfo(name="b"))
        backends = list_backends()
        assert len(backends) == 2
        names = {b.name for b in backends}
        assert names == {"a", "b"}

    def test_get_unknown_returns_none(self):
        """Should return None for unknown backend."""
        assert get_backend("nonexistent") is None

    def test_register_idempotent(self):
        """Last write wins for same name."""
        b1 = BackendInfo(name="x", description="first")
        b2 = BackendInfo(name="x", description="second")
        register_backend(b1)
        register_backend(b2)
        assert get_backend("x") is b2

    def test_clear_registry(self):
        """Should clear all backends."""
        register_backend(BackendInfo(name="a"))
        clear_registry()
        assert list_backends() == []


class TestSelectBackend:
    def setup_method(self):
        clear_registry()

    def test_prefer_specific(self):
        """Should return preferred backend when available."""
        register_backend(BackendInfo(name="cpu"))
        register_backend(BackendInfo(name="cuda", supports_gpu=True))
        result = select_backend(prefer="cuda")
        assert result is not None
        assert result.name == "cuda"

    def test_prefer_unknown_falls_through(self):
        """Unknown prefer should fall through to auto-selection."""
        register_backend(BackendInfo(name="cpu"))
        result = select_backend(prefer="nonexistent")
        assert result is not None
        assert result.name == "cpu"

    def test_require_gpu(self):
        """Should filter to GPU backends only."""
        register_backend(BackendInfo(name="cpu", supports_gpu=False))
        register_backend(BackendInfo(name="cuda", supports_gpu=True))
        result = select_backend(require_gpu=True)
        assert result is not None
        assert result.name == "cuda"

    def test_require_nf4(self):
        """Should filter to NF4 backends only."""
        register_backend(BackendInfo(name="cpu", supports_nf4=False))
        register_backend(BackendInfo(name="cuda", supports_nf4=True))
        result = select_backend(require_nf4=True)
        assert result is not None
        assert result.name == "cuda"

    def test_no_match_returns_none(self):
        """Should return None if no backend matches."""
        register_backend(BackendInfo(name="cpu", supports_gpu=False))
        result = select_backend(require_gpu=True)
        assert result is None

    def test_empty_registry(self):
        """Should return None with empty registry."""
        result = select_backend()
        assert result is None

    def test_prefers_gpu_capable(self):
        """Should prefer GPU-capable backends in auto-selection."""
        register_backend(BackendInfo(name="cpu", supports_gpu=False))
        register_backend(BackendInfo(name="cuda", supports_gpu=True))
        result = select_backend()
        assert result is not None
        assert result.name == "cuda"


class TestBackendInfo:
    def test_frozen(self):
        """BackendInfo should be frozen."""
        info = BackendInfo(name="test")
        # Frozen dataclass — can't set attributes
        # (this would raise in __init__ if not frozen)
        assert info.name == "test"

    def test_defaults(self):
        """Should have sensible defaults."""
        info = BackendInfo(name="test")
        assert info.supports_gpu is False
        assert info.supports_cpu is True
        assert info.device_family == "any"
        assert info.supports_streaming is True
        assert info.supports_nf4 is False
        assert info.supports_grammar is False
        assert info.requires_cuda is False


class TestRequireAccel:
    def setup_method(self):
        clear_registry()

    def _reg(self):
        register_backend(BackendInfo(name="cuda", device_family="nvidia", supports_gpu=True))
        register_backend(BackendInfo(name="roc", device_family="amd", supports_gpu=True))
        register_backend(BackendInfo(name="cpu"))

    def test_nvidia_family_only_selects_cuda(self):
        self._reg()
        result = select_backend(require_gpu=True, require_accel="nvidia")
        assert result is not None
        assert result.name == "cuda"

    def test_amd_family_only_selects_roc(self):
        self._reg()
        result = select_backend(require_gpu=True, require_accel="amd")
        assert result is not None
        assert result.name == "roc"

    def test_no_accel_prefers_first_gpu(self):
        self._reg()
        result = select_backend(require_gpu=True)
        assert result is not None
        assert result.name == "cuda"

    def test_prefer_respects_family(self):
        self._reg()
        result = select_backend(prefer="roc", require_accel="amd")
        assert result is not None
        assert result.name == "roc"

    def test_prefer_rejected_when_family_mismatch(self):
        self._reg()
        result = select_backend(prefer="cuda", require_accel="amd")
        # cuda is nvidia-family; should not match when amd required -> falls
        # through to candidates with amd family => roc
        assert result is not None
        assert result.name == "roc"

    def test_unknown_accel_returns_none(self):
        self._reg()
        result = select_backend(require_gpu=True, require_accel="intel")
        assert result is None


class TestRocRegistration:
    def setup_method(self):
        clear_registry()
        from kiln.engine.backends.cuda_native import register as reg

        reg()

    def test_roc_registered_alongside_cuda(self):
        roc = get_backend("roc")
        assert roc is not None
        assert roc.device_family == "amd"
        assert roc.supports_gpu is True

    def test_cuda_registered_as_nvidia(self):
        cuda = get_backend("cuda")
        assert cuda is not None
        assert cuda.device_family == "nvidia"

    def test_amd_auto_selects_roc(self):
        result = select_backend(require_gpu=True, require_accel="amd")
        assert result is not None
        assert result.name == "roc"
