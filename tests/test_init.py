"""Tests for the `kiln init` command (config-from-template writer)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from kiln.cli import app
from kiln.config.schema import KilnConfig, load_config

runner = CliRunner()


def test_init_chat_default(tmp_path: Path) -> None:
    cfg = tmp_path / "kiln.yaml"
    result = runner.invoke(
        app,
        ["init", "--model", "Qwen/Qwen2.5-0.5B", "--config", str(cfg), "--force"],
    )
    assert result.exit_code == 0, result.output
    assert cfg.is_file()
    loaded = load_config(cfg)
    assert isinstance(loaded, KilnConfig)
    assert loaded.recipe.model.base == "Qwen/Qwen2.5-0.5B"
    assert loaded.recipe.data is None  # chat template has no training data


def test_init_train_requires_data_default(tmp_path: Path) -> None:
    cfg = tmp_path / "kiln.yaml"
    result = runner.invoke(
        app,
        ["init", "-t", "train", "--model", "Qwen/Qwen2.5-0.5B", "--config", str(cfg)],
    )
    assert result.exit_code == 0, result.output
    loaded = load_config(cfg)
    # train template writes a default data path even if not supplied
    assert loaded.recipe.data is not None
    assert loaded.recipe.training is not None


def test_init_existing_refuses_without_force(tmp_path: Path) -> None:
    cfg = tmp_path / "kiln.yaml"
    cfg.write_text("recipe:\n  model:\n    base: existing\n", encoding="utf-8")
    result = runner.invoke(
        app, ["init", "--model", "Qwen/Qwen2.5-0.5B", "--config", str(cfg)]
    )
    assert result.exit_code != 0
    assert "overwrite" in result.output


def test_init_force_overwrites(tmp_path: Path) -> None:
    cfg = tmp_path / "kiln.yaml"
    cfg.write_text("recipe:\n  model:\n    base: existing\n", encoding="utf-8")
    result = runner.invoke(
        app,
        ["init", "--model", "Qwen/Qwen2.5-0.5B", "--config", str(cfg), "--force"],
    )
    assert result.exit_code == 0, result.output
    assert load_config(cfg).recipe.model.base == "Qwen/Qwen2.5-0.5B"


def test_init_rejects_unknown_template(tmp_path: Path) -> None:
    cfg = tmp_path / "kiln.yaml"
    result = runner.invoke(
        app, ["init", "-t", "bogus", "--model", "m", "--config", str(cfg)]
    )
    assert result.exit_code != 0


def test_init_noninteractive_without_model_fails(tmp_path: Path) -> None:
    cfg = tmp_path / "kiln.yaml"
    # No --model and stdin is not a tty under CliRunner -> USAGE error, no prompt.
    result = runner.invoke(app, ["init", "--config", str(cfg)])
    assert result.exit_code != 0
    assert "--model is required" in result.output or "not implemented" not in result.output
