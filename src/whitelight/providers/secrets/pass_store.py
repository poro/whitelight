"""GNU pass (GPG-encrypted) secrets provider for local deployment."""

from __future__ import annotations

import json
import subprocess

from whitelight.providers.base import SecretsProvider


class PassSecretsProvider(SecretsProvider):
    """Retrieves secrets from `pass` (the standard Unix password manager).

    Each secret is stored as a GPG-encrypted file under the configured prefix.
    Example: key='alpaca/api_key' -> `pass show whitelight/alpaca/api_key`
    """

    def __init__(self, prefix: str = "whitelight"):
        self._prefix = prefix

    def _pass_path(self, key: str) -> str:
        return f"{self._prefix}/{key}"

    def get_secret(self, key: str) -> str:
        path = self._pass_path(key)
        try:
            result = subprocess.run(
                ["pass", "show", path],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise KeyError(f"Secret not found in pass: {path}") from e
        except FileNotFoundError:
            raise RuntimeError("`pass` command not found. Install it: apt install pass")

    def get_secret_json(self, key: str) -> dict:
        raw = self.get_secret(key)
        return json.loads(raw)
