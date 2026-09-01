"""Tests for kiln.plan (hardware recommendations)."""

from __future__ import annotations

from kiln.config.schema import PlanPolicyConfig
from kiln.plan import PlanResult, Verdict, build_plan, classify_fit, format_plan


class TestPlanResult:
    def test_dataclass(self):
        p = PlanResult(
            backend="cpu",
            quant_recommendation="Q8_0",
            vram_gb=None,
            ram_gb=16.0,
            disk_free_gb=100.0,
            reasoning="No GPU",
        )
        assert p.backend == "cpu"
        assert p.vram_gb is None

    def test_to_dict(self):
        p = PlanResult(
            backend="cpu",
            quant_recommendation="Q8_0",
            vram_gb=None,
            ram_gb=16.0,
            disk_free_gb=100.0,
            reasoning="No GPU",
        )
        d = p.to_dict()
        assert d["backend"] == "cpu"
        assert d["vram_gb"] is None
        assert d["suggested_config"] == {}


class TestBuildPlan:
    def test_returns_plan_result(self):
        result = build_plan()
        assert isinstance(result, PlanResult)
        assert result.backend in ("cuda", "cpu")
        assert result.quant_recommendation in ("Q4_K_M", "Q5_K_M", "Q8_0", "F16")
        assert isinstance(result.reasoning, str)

    def test_has_suggested_config(self):
        result = build_plan()
        assert "serving" in result.suggested_config
        assert "backend" in result.suggested_config["serving"]
        assert "quantization" in result.suggested_config["serving"]

    def test_backend_matches_hardware(self):
        result = build_plan()
        if result.vram_gb and result.vram_gb >= 4.0:
            assert result.backend == "cuda"
        else:
            assert result.backend == "cpu"


class TestFormatPlan:
    def test_format_plan_string(self):
        result = build_plan()
        text = format_plan(result)
        assert isinstance(text, str)
        assert "Backend:" in text
        assert "Quant:" in text
        assert "Reasoning:" in text

    def test_format_plan_with_vram(self):
        result = PlanResult(
            backend="cuda",
            quant_recommendation="Q4_K_M",
            vram_gb=8.0,
            ram_gb=16.0,
            disk_free_gb=100.0,
            reasoning="Test GPU",
        )
        text = format_plan(result)
        assert "8.0 GB" in text

    def test_format_plan_without_vram(self):
        result = PlanResult(
            backend="cpu",
            quant_recommendation="Q8_0",
            vram_gb=None,
            ram_gb=16.0,
            disk_free_gb=100.0,
            reasoning="No GPU",
        )
        text = format_plan(result)
        assert "N/A" in text


class TestClassifyFit:
    """Verdict classification from estimate + configurable policy thresholds."""

    def _policy(self, **over):
        data = dict(PlanPolicyConfig().model_dump())
        data.update(over)
        return PlanPolicyConfig(**data)

    def _classify(self, estimated, available, **over):
        return classify_fit(
            estimated_bytes=estimated,
            available_bytes=available,
            policy=self._policy(**over),
        )

    def test_recommended_when_headroom(self):
        assert self._classify(8_000_000_000, 10_000_000_000) == Verdict.RECOMMENDED

    def test_possible_between_thresholds(self):
        # estimated = 95% of capacity: above recommended (90%) but below possible (100%).
        assert self._classify(9_500_000_000, 10_000_000_000) == Verdict.POSSIBLE_CONSTRAINED

    def test_likely_oom_above_capacity(self):
        assert self._classify(11_000_000_000, 10_000_000_000) == Verdict.LIKELY_OOM

    def test_unsupported_below_minimum_floor(self):
        assert self._classify(
            1_000_000_000, 1_500_000_000, minimum_vram_bytes=2_000_000_000
        ) == Verdict.UNSUPPORTED

    def test_unsupported_no_gpu(self):
        assert self._classify(8_000_000_000, 0) == Verdict.UNSUPPORTED

    def test_defaults_are_conservative(self):
        # Default band: recommended at ≤90% of capacity, possible above that.
        assert self._classify(9_000_000_000, 10_000_000_000) == Verdict.RECOMMENDED
        assert self._classify(9_100_000_000, 10_000_000_000) == Verdict.POSSIBLE_CONSTRAINED

    def test_policy_thresholds_are_configurable(self):
        # Loosen recommended_fraction and re-classify a previously-constrained run.
        assert self._classify(
            9_500_000_000, 10_000_000_000, recommended_fraction=0.95
        ) == Verdict.RECOMMENDED

    def test_to_dict_serializes_verdict(self):
        result = PlanResult(
            backend="cuda",
            quant_recommendation="Q4_K_M",
            vram_gb=8.0,
            ram_gb=16.0,
            disk_free_gb=100.0,
            reasoning="Test GPU",
            training_verdict=Verdict.RECOMMENDED,
        )
        assert result.to_dict()["training_verdict"] == "Recommended"


class TestPlanVerdict:
    def test_build_plan_sets_verdict_when_gpu(self):
        # Hard to force a GPU in CI; at minimum the field must exist and be None
        # on a CPU-only box, and be a Verdict when a GPU is present.
        result = build_plan()
        if result.vram_gb:
            assert result.training_verdict is None or isinstance(result.training_verdict, Verdict)
        else:
            assert result.training_verdict is None

    def test_format_plan_renders_verdict(self):
        result = PlanResult(
            backend="cuda",
            quant_recommendation="Q4_K_M",
            vram_gb=8.0,
            ram_gb=16.0,
            disk_free_gb=100.0,
            reasoning="Test GPU",
            training_verdict=Verdict.POSSIBLE_CONSTRAINED,
        )
        text = format_plan(result)
        assert "Train fit:" in text
        assert "Possible (constrained settings)" in text
