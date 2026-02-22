"""Unit tests for whitelight.config."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from whitelight.config import (
    StrategyConfig,
    WhiteLightConfig,
    _deep_merge,
    _load_yaml,
)


# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------


class TestDeepMerge:
    def test_flat_merge(self):
        base = {"a": 1, "b": 2}
        overlay = {"b": 3, "c": 4}
        result = _deep_merge(base, overlay)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"top": {"a": 1, "b": 2}, "other": 10}
        overlay = {"top": {"b": 3, "c": 4}}
        result = _deep_merge(base, overlay)
        assert result == {"top": {"a": 1, "b": 3, "c": 4}, "other": 10}

    def test_overlay_replaces_non_dict_with_dict(self):
        base = {"key": "string_value"}
        overlay = {"key": {"nested": True}}
        result = _deep_merge(base, overlay)
        assert result == {"key": {"nested": True}}

    def test_overlay_replaces_dict_with_non_dict(self):
        base = {"key": {"nested": True}}
        overlay = {"key": "string_value"}
        result = _deep_merge(base, overlay)
        assert result == {"key": "string_value"}

    def test_empty_overlay(self):
        base = {"a": 1, "b": 2}
        result = _deep_merge(base, {})
        assert result == {"a": 1, "b": 2}

    def test_empty_base(self):
        overlay = {"a": 1, "b": 2}
        result = _deep_merge({}, overlay)
        assert result == {"a": 1, "b": 2}

    def test_deeply_nested_merge(self):
        base = {"l1": {"l2": {"l3": {"a": 1, "b": 2}}}}
        overlay = {"l1": {"l2": {"l3": {"b": 99, "c": 3}}}}
        result = _deep_merge(base, overlay)
        assert result == {"l1": {"l2": {"l3": {"a": 1, "b": 99, "c": 3}}}}

    def test_does_not_mutate_base(self):
        base = {"a": 1, "nested": {"x": 10}}
        overlay = {"a": 2, "nested": {"y": 20}}
        _deep_merge(base, overlay)
        # base should be unchanged
        assert base == {"a": 1, "nested": {"x": 10}}


# ---------------------------------------------------------------------------
# _load_yaml
# ---------------------------------------------------------------------------


class TestLoadYaml:
    def test_returns_empty_dict_for_missing_file(self, tmp_path: Path):
        result = _load_yaml(tmp_path / "nonexistent.yaml")
        assert result == {}

    def test_loads_yaml_file(self, tmp_path: Path):
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("key: value\nnested:\n  a: 1\n")
        result = _load_yaml(yaml_file)
        assert result == {"key": "value", "nested": {"a": 1}}

    def test_returns_empty_dict_for_empty_file(self, tmp_path: Path):
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text("")
        result = _load_yaml(yaml_file)
        assert result == {}


# ---------------------------------------------------------------------------
# WhiteLightConfig.load
# ---------------------------------------------------------------------------


class TestWhiteLightConfigLoad:
    def test_default_config_loads_from_project(self):
        """The default.yaml in the repo should load without error."""
        config_dir = Path(__file__).parent.parent.parent / "config"
        if not (config_dir / "default.yaml").exists():
            pytest.skip("config/default.yaml not found (CI may not have it)")
        cfg = WhiteLightConfig.load(config_dir=config_dir)
        assert cfg.deployment.mode == "local"
        assert cfg.brokerages.primary == "alpaca"

    def test_loads_from_custom_config_dir(self, tmp_path: Path):
        default = {
            "deployment": {"mode": "test", "log_level": "DEBUG"},
            "strategy": {
                "substrategy_weights": {
                    "s1": 0.25, "s2": 0.15, "s3": 0.10,
                    "s4": 0.10, "s5": 0.15, "s6": 0.15, "s7": 0.10,
                },
            },
        }
        (tmp_path / "default.yaml").write_text(yaml.dump(default))
        (tmp_path / "test.yaml").write_text("")

        cfg = WhiteLightConfig.load(deployment_mode="test", config_dir=tmp_path)
        assert cfg.deployment.mode == "test"
        assert cfg.deployment.log_level == "DEBUG"

    def test_overlay_merges_on_top_of_default(self, tmp_path: Path):
        default = {
            "deployment": {"mode": "local", "log_level": "INFO"},
        }
        overlay = {
            "deployment": {"log_level": "DEBUG"},
        }
        (tmp_path / "default.yaml").write_text(yaml.dump(default))
        (tmp_path / "local.yaml").write_text(yaml.dump(overlay))

        cfg = WhiteLightConfig.load(deployment_mode="local", config_dir=tmp_path)
        assert cfg.deployment.mode == "local"
        assert cfg.deployment.log_level == "DEBUG"


# ---------------------------------------------------------------------------
# Weights validation
# ---------------------------------------------------------------------------


class TestWeightsValidation:
    def test_weights_sum_to_one(self):
        """Production default weights should sum to 1.0."""
        config_dir = Path(__file__).parent.parent.parent / "config"
        if not (config_dir / "default.yaml").exists():
            pytest.skip("config/default.yaml not found")
        cfg = WhiteLightConfig.load(config_dir=config_dir)
        total = sum(cfg.strategy.substrategy_weights.values())
        assert abs(total - 1.0) <= 0.01

    def test_invalid_weights_raise_error(self):
        """Weights that don't sum to 1.0 should raise a ValidationError."""
        with pytest.raises(Exception) as exc_info:
            StrategyConfig(
                substrategy_weights={
                    "s1": 0.5,
                    "s2": 0.5,
                    "s3": 0.5,  # total = 1.5
                }
            )
        assert "sum to 1.0" in str(exc_info.value)

    def test_empty_weights_are_valid(self):
        """An empty weights dict should not raise (it's the default)."""
        cfg = StrategyConfig(substrategy_weights={})
        assert cfg.substrategy_weights == {}

    def test_valid_weights_accepted(self):
        cfg = StrategyConfig(
            substrategy_weights={
                "s1": 0.25,
                "s2": 0.15,
                "s3": 0.10,
                "s4": 0.10,
                "s5": 0.15,
                "s6": 0.15,
                "s7": 0.10,
            }
        )
        assert sum(cfg.substrategy_weights.values()) == pytest.approx(1.0)

    def test_weights_near_one_accepted(self):
        """Weights that sum to 0.995 (within tolerance 0.01) should be OK."""
        cfg = StrategyConfig(
            substrategy_weights={"a": 0.5, "b": 0.495}
        )
        assert sum(cfg.substrategy_weights.values()) == pytest.approx(0.995)


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_default_execution_config(self):
        cfg = WhiteLightConfig()
        assert cfg.execution.order_type == "market"
        assert cfg.execution.max_retry_attempts == 5

    def test_default_data_config(self):
        cfg = WhiteLightConfig()
        assert "NDX" in cfg.data.tickers
        assert "TQQQ" in cfg.data.tickers
        assert "SQQQ" in cfg.data.tickers
