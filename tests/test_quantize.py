"""Torch-free tests for `kiln quantize` job validation (no CUDA needed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from kiln.quant.quantize import QuantJob, _read_calibration_texts
from kiln.utils.errors import KilnError
from kiln.utils.exitcodes import USAGE


def _make_model_dir(tmp_path: Path) -> Path:
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text("{}")
    return model


def _make_calib(tmp_path: Path, lines: list[str]) -> Path:
    p = tmp_path / "calib.jsonl"
    p.write_text("\n".join(lines) + "\n")
    return p


def test_valid_gptq_job(tmp_path: Path) -> None:
    model = _make_model_dir(tmp_path)
    calib = _make_calib(tmp_path, ['{"text": "hello world"}', "raw line text"])
    job = QuantJob(
        scheme="gptq",
        model_dir=str(model),
        output_dir=str(tmp_path / "out"),
        calibration_data=str(calib),
    )
    assert job.scheme == "gptq"
    assert job.bits == 4


def test_invalid_scheme_rejected(tmp_path: Path) -> None:
    model = _make_model_dir(tmp_path)
    calib = _make_calib(tmp_path, ['{"text": "x"}'])
    with pytest.raises(KilnError) as exc:
        QuantJob(
            scheme="4bit",
            model_dir=str(model),
            output_dir=str(tmp_path / "out"),
            calibration_data=str(calib),
        )
    assert exc.value.exit_code == USAGE
    assert "quantize" in (exc.value.hint or "").lower()


def test_missing_model_dir_rejected(tmp_path: Path) -> None:
    calib = _make_calib(tmp_path, ['{"text": "x"}'])
    with pytest.raises(KilnError) as exc:
        QuantJob(
            scheme="awq",
            model_dir=str(tmp_path / "nope"),
            output_dir=str(tmp_path / "out"),
            calibration_data=str(calib),
        )
    assert exc.value.exit_code == USAGE


def test_missing_calibration_rejected(tmp_path: Path) -> None:
    model = _make_model_dir(tmp_path)
    with pytest.raises(KilnError) as exc:
        QuantJob(
            scheme="awq",
            model_dir=str(model),
            output_dir=str(tmp_path / "out"),
            calibration_data=str(tmp_path / "missing.jsonl"),
        )
    assert exc.value.exit_code == USAGE


def test_read_calibration_mixed_formats(tmp_path: Path) -> None:
    calib = _make_calib(
        tmp_path,
        ['{"text": "a"}', '{"content": "b"}', "raw c", "", "   "],
    )
    texts = _read_calibration_texts(str(calib))
    assert texts == ["a", "b", "raw c"]


def test_read_calibration_empty_errors(tmp_path: Path) -> None:
    calib = _make_calib(tmp_path, ["", "  "])
    with pytest.raises(KilnError) as exc:
        _read_calibration_texts(str(calib))
    assert exc.value.exit_code == USAGE
