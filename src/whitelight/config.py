"""Configuration management with layered YAML + environment variable overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, field_validator


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge overlay into base. Overlay values win."""
    result = base.copy()
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_yaml(path: Path) -> dict:
    """Load a YAML file, returning empty dict if file doesn't exist."""
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


class DeploymentConfig(BaseModel):
    mode: str = "local"
    log_level: str = "INFO"
    log_format: str = "json"
    log_dir: str = "/var/log/whitelight"


class SecretsConfig(BaseModel):
    provider: str = "env"
    aws_region: str = "us-east-1"
    aws_secret_name: str = "whitelight/credentials"
    pass_prefix: str = "whitelight"


class AlertsConfig(BaseModel):
    provider: str = "telegram"
    composite_providers: list[str] = []


class DataConfig(BaseModel):
    polygon_base_url: str = "https://api.polygon.io"
    cache_dir: str = "./data"
    cache_format: str = "parquet"
    tickers: list[str] = ["NDX", "TQQQ", "SQQQ"]
    history_start_date: str = "1985-01-01"
    sync_timeout_seconds: int = 120


class AlpacaConfig(BaseModel):
    paper: bool = True
    timeout_seconds: int = 30


class IBKRConfig(BaseModel):
    gateway_host: str = "127.0.0.1"
    gateway_port: int = 7497
    client_id: int = 1
    timeout_seconds: int = 30


class BrokeragesConfig(BaseModel):
    primary: str = "alpaca"
    secondary: Optional[str] = "ibkr"
    failover_enabled: bool = True
    alpaca: AlpacaConfig = AlpacaConfig()
    ibkr: IBKRConfig = IBKRConfig()


class StrategyConfig(BaseModel):
    substrategy_weights: dict[str, float] = {}
    allocation_tiers: list[dict[str, Any]] = []
    min_rebalance_threshold: float = 0.05
    params: dict[str, dict[str, Any]] = {}
    combiner_version: int = 1          # 1 = original, 2 = vol-adaptive with ATR stops
    position_sizing: bool = False       # scale position by volatility percentile

    @field_validator("substrategy_weights")
    @classmethod
    def weights_sum_to_one(cls, v: dict[str, float]) -> dict[str, float]:
        if v:
            total = sum(v.values())
            if abs(total - 1.0) > 0.01:
                raise ValueError(f"Sub-strategy weights must sum to 1.0, got {total}")
        return v


class ExecutionConfig(BaseModel):
    window_start_minutes_before_close: int = 15
    window_end_minutes_before_close: int = 1
    max_retry_attempts: int = 5
    retry_backoff_base_seconds: float = 2.0
    retry_backoff_max_seconds: float = 60.0
    market_close_buffer_seconds: int = 60
    order_type: str = "market"
    min_order_value_usd: float = 10.0


class WhiteLightConfig(BaseModel):
    deployment: DeploymentConfig = DeploymentConfig()
    secrets: SecretsConfig = SecretsConfig()
    alerts: AlertsConfig = AlertsConfig()
    data: DataConfig = DataConfig()
    brokerages: BrokeragesConfig = BrokeragesConfig()
    strategy: StrategyConfig = StrategyConfig()
    execution: ExecutionConfig = ExecutionConfig()

    @classmethod
    def load(
        cls,
        deployment_mode: Optional[str] = None,
        config_dir: Optional[Path] = None,
    ) -> WhiteLightConfig:
        """Load config from default.yaml, overlaid with deployment-specific YAML.

        Priority (lowest to highest):
        1. config/default.yaml
        2. config/{mode}.yaml
        3. Environment variables (WL_DEPLOYMENT_MODE, etc.)
        """
        if config_dir is None:
            config_dir = Path(__file__).parent.parent.parent / "config"

        base = _load_yaml(config_dir / "default.yaml")
        mode = deployment_mode or os.environ.get(
            "WL_DEPLOYMENT_MODE",
            base.get("deployment", {}).get("mode", "local"),
        )
        overlay = _load_yaml(config_dir / f"{mode}.yaml")
        merged = _deep_merge(base, overlay)

        return cls(**merged)
