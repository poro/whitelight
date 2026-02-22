"""Environment variable secrets provider (for testing and development)."""

from __future__ import annotations

import json
import os

from whitelight.providers.base import SecretsProvider


class EnvSecretsProvider(SecretsProvider):
    """Retrieves secrets from environment variables.

    Key mapping: 'alpaca/api_key' -> 'WL_ALPACA_API_KEY'
    (slashes become underscores, uppercased, prefixed with WL_)
    """

    def __init__(self, prefix: str = "WL"):
        self._prefix = prefix

    def _env_key(self, key: str) -> str:
        return f"{self._prefix}_{key.replace('/', '_').upper()}"

    def get_secret(self, key: str) -> str:
        env_key = self._env_key(key)
        value = os.environ.get(env_key)
        if value is None:
            raise KeyError(f"Secret not found: {key} (env var: {env_key})")
        return value

    def get_secret_json(self, key: str) -> dict:
        raw = self.get_secret(key)
        return json.loads(raw)
