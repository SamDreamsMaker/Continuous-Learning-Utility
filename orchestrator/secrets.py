"""Secret resolution: OS Keyring → environment variable → config value.

Secrets are stored in the OS credential store (Windows Credential Locker,
macOS Keychain, Linux Secret Service) via the `keyring` library. This ensures
credentials are encrypted at rest and never stored as plaintext on disk.

Resolution cascade (first non-empty wins):
1. OS Keyring: keyring.get_password("clu", name)
2. Environment variable: CLU_{NAME} (uppercase)
3. YAML config value (fallback, should be empty for secrets)
"""

import logging
import os

import keyring
import keyring.errors

logger = logging.getLogger(__name__)

SERVICE = "clu"
SECRET_SUFFIXES = ("_key", "_token", "_secret", "_webhook")
ENV_PREFIX = "CLU_"

# Known secret fields for listing (keyring doesn't support enumeration)
KNOWN_SECRETS = [
    "api_key",
    "github_token",
    "whatsapp_access_token",
    "whatsapp_app_secret",
    "whisper_api_key",
    "discord_webhook",
    "slack_webhook",
]


def is_secret_field(name: str) -> bool:
    """Check if a field name looks like a secret (by suffix convention)."""
    return any(name.endswith(s) for s in SECRET_SUFFIXES)


def get_secret(name: str, config_value: str = "") -> str:
    """Resolve a secret: keyring → env var → config value.

    Args:
        name: Secret field name (e.g., "api_key")
        config_value: Fallback value from YAML config

    Returns:
        Resolved secret value, or empty string if not found.
    """
    # 1. OS Keyring (encrypted, preferred)
    try:
        val = keyring.get_password(SERVICE, name)
        if val:
            return val
    except Exception:
        pass

    # 2. Environment variable (CLU_ prefix + uppercase)
    env_name = ENV_PREFIX + name.upper()
    val = os.environ.get(env_name, "")
    if val:
        return val

    # 3. YAML config value (last resort)
    if config_value and not config_value.startswith("${"):
        return config_value

    return ""


def set_secret(name: str, value: str):
    """Store a secret in the OS keyring."""
    keyring.set_password(SERVICE, name, value)
    logger.info("Secret '%s' stored in keyring", name)


def delete_secret(name: str):
    """Remove a secret from the OS keyring."""
    try:
        keyring.delete_password(SERVICE, name)
        logger.info("Secret '%s' removed from keyring", name)
    except keyring.errors.PasswordDeleteError:
        pass


def list_secrets() -> list[str]:
    """List known secret field names that are stored in the keyring.

    Note: keyring doesn't support enumeration, so we check known fields.
    """
    stored = []
    for name in KNOWN_SECRETS:
        try:
            if keyring.get_password(SERVICE, name):
                stored.append(name)
        except Exception:
            pass
    return stored
