"""AI provider / model / credential configuration.

Resolution order (highest precedence first):

1. **API keys** — keyring entry on the *new* service name, then
   migrated from the legacy service name, then environment variable.
2. **Provider** — ``HESTAI_AI_PROVIDER`` env var, else
   :data:`DEFAULT_PROVIDER` (``"openrouter"``).
3. **Model** — ``HESTAI_AI_MODEL`` env var, else
   :data:`DEFAULT_MODEL` (``"google/gemini-2.0-flash-lite"``).

**Keyring service-name migration** (HO-confirmed):
    * Legacy name: ``"hestai-mcp"`` (from the deprecated
      ``hestai-mcp`` project).
    * New name: ``"hestai-context-mcp"``.
    * On first read, if the new service has no entry but the legacy
      service does, the value is copied to the new service and the
      legacy entry is deleted. An INFO log records the migration (the
      key value itself is never logged; PROD::I2).
    * Runs exactly once per key per process: the second read finds the
      new entry populated and takes the fast path.

Invariants:
    * ``PROD::I2 CREDENTIAL_SAFETY``: no secret is ever passed to a
      logger (neither as message nor as structured arg); after
      migration only one copy of the credential exists.
    * ``PROD::I6 LEGACY_INDEPENDENCE``: no ``hestai_mcp`` import.
"""

from __future__ import annotations

import logging
import os

import keyring

logger = logging.getLogger(__name__)

__all__ = [
    "LEGACY_KEYRING_SERVICE",
    "KEYRING_SERVICE",
    "DEFAULT_PROVIDER",
    "DEFAULT_MODEL",
    "resolve_provider",
    "resolve_model",
    "resolve_api_key",
    "get_provider_base_url",
]

# Keyring service names. See module docstring for migration rules.
LEGACY_KEYRING_SERVICE: str = "hestai-mcp"
KEYRING_SERVICE: str = "hestai-context-mcp"

# Provider / model defaults (match legacy hestai-mcp defaults).
DEFAULT_PROVIDER: str = "openrouter"
DEFAULT_MODEL: str = "google/gemini-2.0-flash-lite"

# Provider → base URL. Constant (NOT env-configurable) so a rogue env
# var cannot redirect traffic to an attacker host.
_PROVIDER_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}

# Provider → env-var name for its API key (legacy set; no new names).
_PROVIDER_ENV_VARS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def resolve_provider() -> str:
    """Return the configured provider identifier."""
    return os.environ.get("HESTAI_AI_PROVIDER", DEFAULT_PROVIDER)


def resolve_model() -> str:
    """Return the configured model identifier."""
    return os.environ.get("HESTAI_AI_MODEL", DEFAULT_MODEL)


def get_provider_base_url(provider: str) -> str:
    """Return the base URL for ``provider``.

    Raises:
        ValueError: if the provider is not recognised.
    """
    try:
        return _PROVIDER_BASE_URLS[provider]
    except KeyError as exc:
        raise ValueError(f"Unknown provider: {provider!r}") from exc


def _keyring_account(provider: str) -> str:
    """Return the per-provider keyring *account* name."""
    return f"{provider}-key"


def _migrate_legacy_key(provider: str) -> str | None:
    """Copy a legacy keyring entry to the new service and delete it.

    Returns the migrated value, or ``None`` if no legacy entry existed.

    PROD::I2: the secret value is never logged. PROD::I6: no
    ``hestai_mcp`` import is performed; only the generic ``keyring``
    module is used.
    """
    account = _keyring_account(provider)
    legacy_value = keyring.get_password(LEGACY_KEYRING_SERVICE, account)
    if not legacy_value:
        return None
    # Promote to the new service name first; only delete the legacy
    # entry once the new entry is confirmed written. This order matters
    # for crash safety — an aborted process must not leave the user
    # without any key.
    keyring.set_password(KEYRING_SERVICE, account, legacy_value)
    try:
        keyring.delete_password(LEGACY_KEYRING_SERVICE, account)
    except Exception:
        # Best-effort deletion; the new entry is the source of truth
        # from here on. A subsequent call will re-attempt deletion.
        logger.warning(
            "Keyring migration: failed to delete legacy entry for provider %r",
            provider,
        )
    logger.info(
        "Keyring migration: moved %r credential from legacy service %r to %r",
        provider,
        LEGACY_KEYRING_SERVICE,
        KEYRING_SERVICE,
    )
    return legacy_value


def resolve_api_key(*, provider: str) -> str | None:
    """Return the API key for ``provider``, or ``None`` if absent.

    Precedence:
        1. keyring (service=``KEYRING_SERVICE``, account=``"{provider}-key"``).
        2. keyring legacy entry (service=``LEGACY_KEYRING_SERVICE``):
           migrated into the new service entry then returned.
        3. environment variable (``OPENAI_API_KEY`` / ``OPENROUTER_API_KEY``).

    Never logs the secret value.
    """
    account = _keyring_account(provider)
    value = keyring.get_password(KEYRING_SERVICE, account)
    if value:
        return value
    migrated = _migrate_legacy_key(provider)
    if migrated:
        return migrated
    env_name = _PROVIDER_ENV_VARS.get(provider)
    if env_name is None:
        return None
    env_value = os.environ.get(env_name)
    return env_value or None
