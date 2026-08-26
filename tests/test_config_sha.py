"""Tests for config.config_sha — semantic fingerprint."""

import tempfile
from pathlib import Path

import pytest
import yaml

from kiln.config.config_sha import config_sha_from_file, recipe_hash, verify_config_sha
from kiln.config.schema import KilnConfig

_SAMPLE_CONFIG = {
    "recipe": {
        "model": {"base": "meta-llama/Llama-3.1-8B"},
        "training": {
            "epochs": 3,
            "lr": 2e-5,
            "batch_size": 4,
            "lora": {"r": 16, "alpha": 16, "dropout": 0.05},
            "quantization": "4bit",
            "seed": 1234,
        },
        "serve": {"host": "127.0.0.1", "port": 8000, "context_length": 4096},
        "output": {"dir": "./output"},
    },
    "eval": {
        "ship": {"metric_threshold": 0.0},
    },
}


class TestRecipeHash:
    def test_deterministic(self):
        """Same config should produce same hash."""
        cfg = KilnConfig.model_validate(_SAMPLE_CONFIG)
        h1 = recipe_hash(cfg)
        h2 = recipe_hash(cfg)
        assert h1 == h2
        assert len(h1) == 16

    def test_raw_dict_and_validated_same(self):
        """Raw dict and validated model should produce same hash."""
        h_dict = recipe_hash(_SAMPLE_CONFIG)
        cfg = KilnConfig.model_validate(_SAMPLE_CONFIG)
        h_model = recipe_hash(cfg)
        assert h_dict == h_model

    def test_recipe_change_changes_hash(self):
        """Changing recipe fields should change hash."""
        cfg1 = KilnConfig.model_validate(_SAMPLE_CONFIG)
        modified = {
            **_SAMPLE_CONFIG,
            "recipe": {
                **_SAMPLE_CONFIG["recipe"],
                "model": {"base": "other/model"},
            },
        }
        cfg2 = KilnConfig.model_validate(modified)
        assert recipe_hash(cfg1) != recipe_hash(cfg2)

    def test_eval_change_preserves_hash(self):
        """Changing eval policy should NOT change hash."""
        cfg1 = KilnConfig.model_validate(_SAMPLE_CONFIG)
        modified = {**_SAMPLE_CONFIG, "eval": {"ship": {"metric_threshold": 0.5}}}
        cfg2 = KilnConfig.model_validate(modified)
        assert recipe_hash(cfg1) == recipe_hash(cfg2)

    def test_training_change_changes_hash(self):
        """Changing training params should change hash."""
        cfg1 = KilnConfig.model_validate(_SAMPLE_CONFIG)
        modified = {
            **_SAMPLE_CONFIG,
            "recipe": {
                **_SAMPLE_CONFIG["recipe"],
                "training": {
                    **_SAMPLE_CONFIG["recipe"]["training"],
                    "epochs": 10,
                },
            },
        }
        cfg2 = KilnConfig.model_validate(modified)
        assert recipe_hash(cfg1) != recipe_hash(cfg2)


class TestConfigShaFromFile:
    def test_roundtrip(self):
        """Hash from file should match hash from validated config."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.safe_dump(_SAMPLE_CONFIG, f)
            f.flush()
            file_hash = config_sha_from_file(f.name)

        cfg = KilnConfig.model_validate(_SAMPLE_CONFIG)
        assert file_hash == recipe_hash(cfg)
        Path(f.name).unlink()

    def test_nonexistent_file(self):
        """Should raise on missing file."""
        with pytest.raises(FileNotFoundError):
            config_sha_from_file("/nonexistent/path.yaml")


class TestVerifyConfigSha:
    def test_matching(self):
        """Should return True for matching hash."""
        cfg = KilnConfig.model_validate(_SAMPLE_CONFIG)
        h = recipe_hash(cfg)
        assert verify_config_sha(cfg, h) is True

    def test_mismatching(self):
        """Should return False for wrong hash."""
        cfg = KilnConfig.model_validate(_SAMPLE_CONFIG)
        assert verify_config_sha(cfg, "wrong_hash_1234") is False
