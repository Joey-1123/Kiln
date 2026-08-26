"""Tests for kiln.export (GGUF export module)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from kiln.export import (
    _QUANT_PROFILES,
    GGUFResult,
    _convert_script_exists,
    _llama_quantize_exists,
    export_gguf,
    list_quantizations,
)


class TestQuantizations:
    def test_list_quantizations_returns_list(self):
        result = list_quantizations()
        assert isinstance(result, list)
        assert "Q4_K_M" in result
        assert "Q5_K_M" in result
        assert "Q8_0" in result
        assert "F16" in result

    def test_quant_profiles_are_strings(self):
        for k, v in _QUANT_PROFILES.items():
            assert isinstance(k, str)
            assert isinstance(v, str)


class TestGGUFResult:
    def test_frozen_dataclass(self):
        r = GGUFResult(
            output_path="/tmp/test.gguf",
            quant="Q4_K_M",
            size_bytes=1024,
            llama_cpp_dir="/tmp/llama.cpp",
        )
        assert r.output_path == "/tmp/test.gguf"
        assert r.quant == "Q4_K_M"
        assert r.size_bytes == 1024

        with pytest.raises(AttributeError):
            r.output_path = "/other"


class TestLlamaQuantizeExists:
    def test_false_when_empty_dir(self, tmp_path):
        assert _llama_quantize_exists(tmp_path) is False

    def test_true_when_binary_present(self, tmp_path):
        (tmp_path / "llama-quantize").touch()
        assert _llama_quantize_exists(tmp_path) is True

    def test_true_when_in_build_bin(self, tmp_path):
        build_bin = tmp_path / "build" / "bin"
        build_bin.mkdir(parents=True)
        (build_bin / "llama-quantize").touch()
        assert _llama_quantize_exists(tmp_path) is True


class TestConvertScriptExists:
    def test_false_when_empty(self, tmp_path):
        assert _convert_script_exists(tmp_path) is False

    def test_true_when_present(self, tmp_path):
        (tmp_path / "convert_hf_to_gguf.py").touch()
        assert _convert_script_exists(tmp_path) is True


class TestExportGGUF:
    def test_rejects_unknown_quant(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown quantization"):
            export_gguf(
                model_dir=str(tmp_path),
                output_dir=str(tmp_path / "out"),
                quant="INVALID",
            )

    def test_rejects_missing_model_dir(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Model directory not found"):
            export_gguf(
                model_dir=str(tmp_path / "nonexistent"),
                output_dir=str(tmp_path / "out"),
            )

    def test_rejects_invalid_model_dir(self, tmp_path):
        model_dir = tmp_path / "model"
        model_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="Not a valid HF model"):
            export_gguf(
                model_dir=str(model_dir),
                output_dir=str(tmp_path / "out"),
            )

    def test_rejects_unbuilt_llama_cpp(self, tmp_path):
        model_dir = tmp_path / "model"
        model_dir.mkdir()
        (model_dir / "config.json").write_text("{}")

        with pytest.raises(FileNotFoundError, match="llama-quantize not found"):
            export_gguf(
                model_dir=str(model_dir),
                output_dir=str(tmp_path / "out"),
                llama_cpp_dir=str(tmp_path / "llama"),
            )

    @patch("kiln.export._run_quantize")
    @patch("kiln.export._run_convert_to_f16")
    @patch("kiln.export._llama_quantize_exists", return_value=True)
    def test_success_path(
        self, mock_exists, mock_convert, mock_quantize, tmp_path
    ):
        model_dir = tmp_path / "model"
        model_dir.mkdir()
        (model_dir / "config.json").write_text("{}")

        out_dir = tmp_path / "out"
        out_dir.mkdir()

        def write_output(base, f16_path, output, quant):
            Path(output).touch()

        mock_quantize.side_effect = write_output

        result = export_gguf(
            model_dir=str(model_dir),
            output_dir=str(out_dir),
            quant="Q8_0",
            llama_cpp_dir=str(tmp_path / "llama"),
        )

        assert result.quant == "Q8_0"
        assert result.output_path.endswith("model.Q8_0.gguf")
        assert result.size_bytes == 0
        mock_convert.assert_called_once()
        mock_quantize.assert_called_once()
