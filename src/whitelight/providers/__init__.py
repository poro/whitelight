"""Provider factory functions for config-driven wiring."""

from __future__ import annotations

from whitelight.config import AlertsConfig, BrokeragesConfig, SecretsConfig
from whitelight.providers.base import AlertProvider, BrokerageClient, SecretsProvider


def create_secrets_provider(config: SecretsConfig) -> SecretsProvider:
    match config.provider:
        case "aws_secrets_manager":
            from .secrets.aws import AWSSecretsProvider
            return AWSSecretsProvider(
                region=config.aws_region, secret_name=config.aws_secret_name
            )
        case "pass":
            from .secrets.pass_store import PassSecretsProvider
            return PassSecretsProvider(prefix=config.pass_prefix)
        case "env":
            from .secrets.env import EnvSecretsProvider
            return EnvSecretsProvider()
        case _:
            raise ValueError(f"Unknown secrets provider: {config.provider}")


def create_alert_provider(config: AlertsConfig, secrets: SecretsProvider) -> AlertProvider:
    match config.provider:
        case "telegram":
            from .alerts.telegram import TelegramAlertProvider
            return TelegramAlertProvider(
                bot_token=secrets.get_secret("telegram/bot_token"),
                chat_id=secrets.get_secret("telegram/chat_id"),
            )
        case "pushover":
            from .alerts.pushover import PushoverAlertProvider
            return PushoverAlertProvider(
                api_token=secrets.get_secret("pushover/api_token"),
                user_key=secrets.get_secret("pushover/user_key"),
            )
        case "sns":
            from .alerts.sns import SNSAlertProvider
            return SNSAlertProvider(
                topic_arn=secrets.get_secret("sns/topic_arn"),
            )
        case "ntfy":
            from .alerts.ntfy import NtfyAlertProvider
            return NtfyAlertProvider(
                topic=secrets.get_secret("ntfy/topic"),
            )
        case "noop" | "none":
            from .alerts.noop import NoopAlertProvider
            return NoopAlertProvider()
        case "composite":
            from .alerts.composite import CompositeAlertProvider
            providers = [
                create_alert_provider(AlertsConfig(provider=p), secrets)
                for p in config.composite_providers
            ]
            return CompositeAlertProvider(providers)
        case _:
            raise ValueError(f"Unknown alert provider: {config.provider}")


def create_brokerage_client(
    config: BrokeragesConfig,
    secrets: SecretsProvider,
    alert_provider: AlertProvider,
) -> BrokerageClient:
    """Build the brokerage client stack based on config."""
    primary = _build_single_client(config.primary, config, secrets)

    if config.failover_enabled and config.secondary:
        secondary = _build_single_client(config.secondary, config, secrets)
        from .brokerages.failover import FailoverBrokerageClient
        return FailoverBrokerageClient(
            primary=primary,
            secondary=secondary,
            alert_provider=alert_provider,
        )

    return primary


def _build_single_client(
    name: str,
    config: BrokeragesConfig,
    secrets: SecretsProvider,
) -> BrokerageClient:
    match name:
        case "alpaca":
            from .brokerages.alpaca import AlpacaClient
            return AlpacaClient(
                api_key=secrets.get_secret("alpaca/api_key"),
                secret_key=secrets.get_secret("alpaca/api_secret"),
                paper=config.alpaca.paper,
            )
        case "ibkr":
            from .brokerages.ibkr import IBKRClient
            return IBKRClient(
                host=config.ibkr.gateway_host,
                port=config.ibkr.gateway_port,
                client_id=config.ibkr.client_id,
                paper=config.ibkr.gateway_port == 7497,
            )
        case "paper":
            from .brokerages.paper import PaperBrokerageClient
            return PaperBrokerageClient()
        case _:
            raise ValueError(f"Unknown brokerage: {name}")
