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
from pathlib import Path

import keyring

logger = logging.getLogger(__name__)

__all__ = [
    "LEGACY_KEYRING_SERVICE",
    "KEYRING_SERVICE",
    "DEFAULT_PROVIDER",
    "DEFAULT_MODEL",
    "resolve_provider",
    "resolve_model",
    "resolve_require_real_validation",
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

# Issue #106 — per-repo model opt-in flag (HO-INTAKE-MODEL-RESOLUTION-CENTRALIZED).
# Model selection is centralized-by-default (the process env wins, so every
# caller repo gets the same model). A caller repo opts in to its OWN model only
# by setting this key truthy in its ``working_dir/.env``.
_PER_REPO_OVERRIDE_KEY: str = "PER_REPO_OVERRIDE"
_TRUTHY_VALUES: frozenset[str] = frozenset({"1", "true", "yes", "on"})

# Issue #108.4 — opt-in fail-closed flag for Gate-B real OCTAVE validation.
# Default OFF: Gate B is fail-soft-but-loud (a missing ``validation`` extra
# degrades to regex-only with an explicit signal). A deployment opts INTO strict
# fail-closed validation by setting this key truthy. Resolved per-repo from
# ``working_dir/.env`` in isolation (parse this key only, never load_dotenv), with
# process-env as the launcher fallback — mirroring ``resolve_model`` per-repo
# isolation (HO-INTAKE-MODEL-RESOLUTION-PER-REPO). A boolean is not a secret.
_REQUIRE_REAL_VALIDATION_KEY: str = "HESTAI_GOVERNANCE_REQUIRE_REAL_VALIDATION"

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


def _read_caller_env_keys(working_dir: str, keys: tuple[str, ...]) -> dict[str, str]:
    """Parse ``{working_dir}/.env`` and return ONLY the requested keys.

    Issue #106 / PROD::I2: this is a *read-only parse*, NOT ``load_dotenv`` —
    the caller's ``.env`` is never merged into ``os.environ``, so no caller
    secret enters the shared process. Only the keys in ``keys`` are returned;
    everything else in the file is ignored. A missing or unreadable file
    yields an empty mapping (the caller falls back to centralized resolution).
    """
    try:
        text = (Path(working_dir) / ".env").read_text(encoding="utf-8")
    except (OSError, ValueError):
        return {}
    wanted = set(keys)
    found: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        if name.startswith("export "):
            name = name[len("export ") :].strip()
        if name in wanted:
            found[name] = value.strip().strip('"').strip("'")
    return found


def resolve_model(tier: str = "default", working_dir: str | None = None) -> str:
    """Return the configured model identifier for ``tier``.

    Tiers (issue #77):
        * ``"default"``  -> ``HESTAI_AI_MODEL``
        * ``"analysis"`` -> ``HESTAI_AI_MODEL_ANALYSIS``
        * ``"critical"`` -> ``HESTAI_AI_MODEL_CRITICAL``

    Resolution is centralized-by-default (issue #106,
    HO-INTAKE-MODEL-RESOLUTION-CENTRALIZED): the process environment is the
    source, so every caller repo gets the same model regardless of
    ``working_dir``. The chain is the tier's own env var, then the base
    ``HESTAI_AI_MODEL``, then :data:`DEFAULT_MODEL`. The zero-arg call keeps
    pre-#77 behaviour exactly (back-compatible).

    Per-repo opt-in: when ``working_dir`` is supplied AND that repo's
    ``.env`` sets ``PER_REPO_OVERRIDE`` truthy, the repo's OWN
    ``HESTAI_AI_MODEL[_TIER]`` (read from its ``.env``) wins — with the same
    tier -> base fallback. If the override is on but the repo declares no
    model, resolution falls through to the centralized chain. The caller
    ``.env`` is parsed for the flag + model keys ONLY; it is never
    ``load_dotenv``'d, so no caller secret enters the process (PROD::I2).

    Args:
        tier: One of ``"default"``, ``"analysis"``, ``"critical"``.
        working_dir: Optional caller project root. When ``None`` (the
            default), resolution is purely centralized — identical to the
            pre-#106 behaviour.

    Raises:
        ValueError: if ``tier`` is not a recognised tier.
    """
    try:
        tier_var = _TIER_ENV_VARS[tier]
    except KeyError as exc:
        raise ValueError(
            f"Unknown model tier: {tier!r} (expected one of {sorted(_TIER_ENV_VARS)})"
        ) from exc

    # Per-repo opt-in: only when the caller's .env explicitly enables it.
    if working_dir is not None:
        caller = _read_caller_env_keys(
            working_dir, (_PER_REPO_OVERRIDE_KEY, tier_var, "HESTAI_AI_MODEL")
        )
        if caller.get(_PER_REPO_OVERRIDE_KEY, "").strip().lower() in _TRUTHY_VALUES:
            repo_tier_value = caller.get(tier_var)
            if repo_tier_value:
                return repo_tier_value
            repo_base = caller.get("HESTAI_AI_MODEL")
            if repo_base:
                return repo_base
            # Override on but no model declared in the repo .env -> fall
            # through to the centralized chain below.

    # Centralized default: tier var first, then base var, then hard default.
    tier_value = os.environ.get(tier_var)
    if tier_value:
        return tier_value
    return os.environ.get("HESTAI_AI_MODEL", DEFAULT_MODEL)


def resolve_require_real_validation(working_dir: str | None = None) -> bool:
    """Return whether Gate-B real OCTAVE validation is REQUIRED (fail-closed).

    Issue #108.4 (Option C). Default is ``False`` — Gate B is fail-soft-but-loud
    (a missing ``validation`` extra degrades to regex-only with an explicit
    top-level signal). When this returns ``True`` the caller turns an
    ``available=False`` Gate-B result into a HARD block (no linker / no PR).

    Resolution, mirroring :func:`resolve_model` per-repo isolation
    (HO-INTAKE-MODEL-RESOLUTION-PER-REPO):

        1. ``working_dir/.env`` — parsed for THIS key ONLY (never ``load_dotenv``,
           so no caller secret enters the process; PROD::I2). If present, it is
           the per-call source of truth (a governance repo can demand strict
           validation regardless of the launcher).
        2. process env (launcher fallback) — ``HESTAI_GOVERNANCE_REQUIRE_REAL_VALIDATION``.
        3. default ``False``.

    Args:
        working_dir: Optional caller project root. When ``None`` only the process
            env / default are consulted (no ``.env`` is read).
    """
    if working_dir is not None:
        caller = _read_caller_env_keys(working_dir, (_REQUIRE_REAL_VALIDATION_KEY,))
        repo_value = caller.get(_REQUIRE_REAL_VALIDATION_KEY)
        if repo_value is not None:
            return repo_value.strip().lower() in _TRUTHY_VALUES

    return os.environ.get(_REQUIRE_REAL_VALIDATION_KEY, "").strip().lower() in _TRUTHY_VALUES


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

    # Issue #99: include OpenRouter real-usage accounting alongside the routing
    # pin. Both are OpenRouter-specific knobs that belong in the config layer
    # (PROD::I3 — keep vendor knowledge in adapters/config, not in the generic
    # wire-protocol adapter). ``usage.include=True`` tells OpenRouter to return
    # the provider's real token counts and real USD cost in the response body.
    return {"provider": {"order": order, "allow_fallbacks": True}, "usage": {"include": True}}


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
