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
    "resolve_provider_payload",
]

# Keyring service names. See module docstring for migration rules.
LEGACY_KEYRING_SERVICE: str = "hestai-mcp"
KEYRING_SERVICE: str = "hestai-context-mcp"

# Provider / model defaults (match legacy hestai-mcp defaults).
DEFAULT_PROVIDER: str = "openrouter"
DEFAULT_MODEL: str = "google/gemini-2.0-flash-lite"

# Tier -> env-var name for that tier's model. The ``default`` tier reads the
# base ``HESTAI_AI_MODEL``; richer tiers read their own var and fall back to
# the base var, then ``DEFAULT_MODEL`` (see :func:`resolve_model`). Tiers are
# orthogonal to provider: a tier only changes *which model identifier* is sent
# to whatever provider is configured (PROD::I3 — no vendor coupling).
_TIER_ENV_VARS: dict[str, str] = {
    "default": "HESTAI_AI_MODEL",
    "analysis": "HESTAI_AI_MODEL_ANALYSIS",
    "critical": "HESTAI_AI_MODEL_CRITICAL",
}

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

# Issue #96 — provider upstream-routing pin (OpenRouter only).
#
# OpenRouter load-balances a model across multiple upstream providers per
# request; for a reasoning model that non-determinism causes intermittent
# output-cap truncation on the worse-fitted upstream. Pinning a *preferred*
# upstream order removes the lottery while keeping ``allow_fallbacks`` True so a
# preferred-upstream outage degrades gracefully (prefer, not require).
#
# The default order is intentionally minimal and fully env-overridable
# (``HESTAI_AI_PROVIDER_ORDER``, comma-separated) so the upstream slug names can
# be corrected without a code change. Routing can be disabled entirely via
# ``HESTAI_AI_PROVIDER_ROUTING=off`` or by supplying an empty order list. Only
# OpenRouter consumes a routing payload; other providers receive ``None``.
_PROVIDER_ROUTING_DEFAULT_ORDER: dict[str, tuple[str, ...]] = {
    "openrouter": ("MiniMax",),
}
_ROUTING_DISABLED_VALUES: frozenset[str] = frozenset({"off", "0", "false", "none", "disabled"})


def resolve_provider() -> str:
    """Return the configured provider identifier."""
    return os.environ.get("HESTAI_AI_PROVIDER", DEFAULT_PROVIDER)


def resolve_model(tier: str = "default") -> str:
    """Return the configured model identifier for ``tier``.

    Tiers (issue #77):
        * ``"default"``  -> ``HESTAI_AI_MODEL``
        * ``"analysis"`` -> ``HESTAI_AI_MODEL_ANALYSIS``
        * ``"critical"`` -> ``HESTAI_AI_MODEL_CRITICAL``

    Resolution for a tier is a fallback chain: the tier's own env var, then
    the base ``HESTAI_AI_MODEL``, then :data:`DEFAULT_MODEL`. For the
    ``"default"`` tier this collapses to the pre-#77 behaviour exactly
    (``HESTAI_AI_MODEL`` else :data:`DEFAULT_MODEL`), so the zero-arg call
    remains back-compatible.

    Args:
        tier: One of ``"default"``, ``"analysis"``, ``"critical"``.

    Raises:
        ValueError: if ``tier`` is not a recognised tier.
    """
    try:
        tier_var = _TIER_ENV_VARS[tier]
    except KeyError as exc:
        raise ValueError(
            f"Unknown model tier: {tier!r} (expected one of {sorted(_TIER_ENV_VARS)})"
        ) from exc
    # Tier var first; fall back to the base model var, then the hard default.
    tier_value = os.environ.get(tier_var)
    if tier_value:
        return tier_value
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


def resolve_provider_payload(provider: str) -> dict[str, object] | None:
    """Return the generic routing payload to merge into the request body.

    The returned shape is the OpenRouter ``{"provider": {...}}`` envelope the
    adapter merges verbatim into ``/chat/completions``. It is *config-sourced*
    (there is no model-name branch here): the preferred upstream order comes
    from :data:`_PROVIDER_ROUTING_DEFAULT_ORDER`, overridable via
    ``HESTAI_AI_PROVIDER_ORDER`` (comma-separated upstream slugs).

    ``allow_fallbacks`` is held True (prefer, not require) so a preferred
    upstream outage degrades gracefully rather than hard-failing.

    Returns ``None`` (no routing preference sent) when:
        * the provider is not OpenRouter,
        * ``HESTAI_AI_PROVIDER_ROUTING`` is set to a disabling value, or
        * the resolved order list is empty.

    Args:
        provider: The configured provider identifier.
    """
    if provider != "openrouter":
        return None

    routing_flag = os.environ.get("HESTAI_AI_PROVIDER_ROUTING", "").strip().lower()
    if routing_flag in _ROUTING_DISABLED_VALUES:
        return None

    order_override = os.environ.get("HESTAI_AI_PROVIDER_ORDER")
    if order_override is not None:
        order = [slug.strip() for slug in order_override.split(",") if slug.strip()]
    else:
        order = list(_PROVIDER_ROUTING_DEFAULT_ORDER.get(provider, ()))

    if not order:
        return None

    return {"provider": {"order": order, "allow_fallbacks": True}}


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


def _self_heal_legacy_entry(provider: str) -> None:
    """Delete any lingering legacy keyring entry for ``provider`` (best-effort).

    Closes the crash-window leak identified by CE review:
    ``_migrate_legacy_key`` writes to the new service and then deletes
    the legacy entry; if the process dies between those two operations
    the legacy secret persists forever because subsequent reads take
    the fast path and never revisit the legacy entry. This helper is
    invoked on every successful fast-path read of the new entry so the
    duplicate is eventually cleaned up. No secret value is logged.
    """
    account = _keyring_account(provider)
    legacy_value = keyring.get_password(LEGACY_KEYRING_SERVICE, account)
    if not legacy_value:
        return
    try:
        keyring.delete_password(LEGACY_KEYRING_SERVICE, account)
    except Exception:
        logger.warning(
            "Keyring self-heal: failed to delete lingering legacy entry " "for provider %r",
            provider,
        )
        return
    logger.info(
        "Keyring self-heal: removed lingering legacy credential for " "provider %r from service %r",
        provider,
        LEGACY_KEYRING_SERVICE,
    )


def resolve_api_key(*, provider: str) -> str | None:
    """Return the API key for ``provider``, or ``None`` if absent.

    Precedence:
        1. keyring (service=``KEYRING_SERVICE``, account=``"{provider}-key"``).
        2. keyring legacy entry (service=``LEGACY_KEYRING_SERVICE``):
           migrated into the new service entry then returned.
        3. environment variable (``OPENAI_API_KEY`` / ``OPENROUTER_API_KEY``).

    When the new-service entry is present the function also performs a
    best-effort *self-heal* deletion of any lingering legacy entry for
    the same account. This closes the crash-window duplicate-leak
    otherwise possible between ``set_password`` and ``delete_password``
    inside :func:`_migrate_legacy_key`.

    Never logs the secret value.
    """
    account = _keyring_account(provider)
    value = keyring.get_password(KEYRING_SERVICE, account)
    if value:
        # Self-heal: if the new entry exists, the legacy entry must NOT
        # exist. If a prior migration crashed before its final delete,
        # clean up here.
        _self_heal_legacy_entry(provider)
        return value
    migrated = _migrate_legacy_key(provider)
    if migrated:
        return migrated
    env_name = _PROVIDER_ENV_VARS.get(provider)
    if env_name is None:
        return None
    env_value = os.environ.get(env_name)
    return env_value or None
