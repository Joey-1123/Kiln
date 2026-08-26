"""Contract: config YAML -> model -> dump -> reload must be lossless."""

from __future__ import annotations

import textwrap

import pytest
from pydantic import ValidationError

from kiln.config.schema import KilnConfig, config_to_yaml, load_config


def _minimal_yaml() -> str:
    return textwrap.dedent(
        """
        recipe:
          model:
            base: meta-llama/Llama-3.1-8B-Instruct
          data:
            train: ./data/train.jsonl
            format: alpaca
            val_split: 0.1
        eval:
          ship:
            metric_threshold: 0.05
        """
    ).strip()


def test_minimal_config_loads(tmp_path) -> None:
    p = tmp_path / "kiln.yaml"
    p.write_text(_minimal_yaml(), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.recipe.model.base == "meta-llama/Llama-3.1-8B-Instruct"
    assert cfg.recipe.training.lora.r == 16  # defaults applied
    assert cfg.eval.ship.metric_threshold == 0.05


def test_roundtrip_identity(tmp_path) -> None:
    p = tmp_path / "kiln.yaml"
    p.write_text(_minimal_yaml(), encoding="utf-8")
    cfg = load_config(p)
    dumped = config_to_yaml(cfg)
    reloaded = KilnConfig.model_validate(__import__("yaml").safe_load(dumped))
    assert reloaded == cfg


def test_unknown_fields_rejected(tmp_path) -> None:
    bad = _minimal_yaml() + "\n  surprise_field: true\n"
    # inject at wrong nesting to trip extra=forbid on the recipe level
    bad = bad.replace("recipe:\n", "recipe:\n  surprise_top: 1\n")
    p = tmp_path / "bad.yaml"
    p.write_text(bad, encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(p)


def test_invalid_format_rejected_with_clear_message(tmp_path) -> None:
    bad = _minimal_yaml().replace("format: alpaca", "format: yaml-ish")
    p = tmp_path / "bad.yaml"
    p.write_text(bad, encoding="utf-8")
    with pytest.raises(ValidationError, match="alpaca"):
        load_config(p)


def test_recipe_and_eval_are_top_level_separate() -> None:
    fields = set(KilnConfig.model_fields)
    assert {"recipe", "eval"} <= fields
