"""Tests for kiln.plan (hardware recommendations)."""

from __future__ import annotations

from kiln.plan import PlanResult, build_plan, format_plan


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
