"""AWS Secrets Manager secrets provider for cloud deployment."""

from __future__ import annotations

import json

import boto3

from whitelight.providers.base import SecretsProvider


class AWSSecretsProvider(SecretsProvider):
    """Retrieves secrets from AWS Secrets Manager.

    Expects secrets stored as JSON objects. The key parameter maps to
    a field within the JSON secret.
    """

    def __init__(self, region: str = "us-east-1", secret_name: str = "whitelight/credentials"):
        self._client = boto3.client("secretsmanager", region_name=region)
        self._secret_name = secret_name
        self._cache: dict | None = None

    def _load_secret(self) -> dict:
        if self._cache is None:
            response = self._client.get_secret_value(SecretId=self._secret_name)
            self._cache = json.loads(response["SecretString"])
        return self._cache

    def get_secret(self, key: str) -> str:
        secrets = self._load_secret()
        flat_key = key.replace("/", "_")
        if flat_key not in secrets:
            raise KeyError(f"Secret key not found: {key} (looked for '{flat_key}')")
        return str(secrets[flat_key])

    def get_secret_json(self, key: str) -> dict:
        return self._load_secret()
