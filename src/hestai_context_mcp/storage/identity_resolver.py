"""ADR-0013 PSS identity resolver — RISK_001 + B2_START_BLOCKER_001.

Resolves the PSS IdentityTuple from on-disk project configuration.
Per the BUILD-PLAN B2_START_BLOCKER_001, B1 must NOT invent auth or
first-run UX. The resolver looks for a single configuration file at::

    .hestai/state/portable/identity.json

If the file is absent, the resolver returns ``None``. Callers (clock_in
restore path, clock_out publish path) treat ``None`` as a fail-closed
"no identity configured" state — no exception, no fallback identity.
This preserves PROD::I6 (local-first, optional remote) and avoids
breaching B2_START_BLOCKER_001.

The configuration file shape is one JSON object containing exactly the
five IdentityTuple fields. Schema version negotiation is handled by
storage.identity.validate_identity_tuple.
"""

from __future__ import annotations

import json
from pathlib import Path

from hestai_context_mcp.storage.identity import (
    IdentityValidationError,
    validate_identity_tuple,
)
from hestai_context_mcp.storage.types import IdentityTuple


def _identity_config_path(working_dir: Path) -> Path:
    return working_dir / ".hestai" / "state" / "portable" / "identity.json"


def resolve_identity(working_dir: str | Path) -> IdentityTuple | None:
    """Return the configured PSS IdentityTuple or ``None`` if absent.

    Args:
        working_dir: Project root.

    Returns:
        Validated ``IdentityTuple`` when configuration exists; ``None``
        when the configuration file is missing.

    Raises:
        IdentityValidationError: when the configuration file exists but
            its contents fail R3 validation.
    """

    cfg_path = _identity_config_path(Path(working_dir))
    if not cfg_path.exists():
        return None
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise IdentityValidationError(
            code="identity_config_unreadable",
            message=f"failed to read PSS identity config at {cfg_path}: {e}",
        ) from e
    if not isinstance(raw, dict):
        raise IdentityValidationError(
            code="identity_config_shape",
            message=f"PSS identity config at {cfg_path} must be a JSON object",
        )

    # Cubic P2 #6: do NOT silently coerce non-string identity fields via
    # str(...). Per RISK_001 fail-closed default and PROD::I2 fail-closed
    # identity safety, a malformed identity.json (string fields that are
    # actually int/list/dict) must surface as "no identity configured"
    # rather than a fabricated IdentityTuple. Return None so callers
    # (clock_in restore path, clock_out publish path) treat the situation
    # exactly as if the file were missing.
    for string_field in ("project_id", "workspace_id", "user_id", "carrier_namespace"):
        value = raw.get(string_field)
        if not isinstance(value, str):
            return None
    if not isinstance(raw.get("state_schema_version"), int) or isinstance(
        raw.get("state_schema_version"), bool
    ):
        return None

    try:
        identity = IdentityTuple(
            project_id=raw["project_id"],
            workspace_id=raw["workspace_id"],
            user_id=raw["user_id"],
            state_schema_version=raw["state_schema_version"],
            carrier_namespace=raw["carrier_namespace"],
        )
    except (KeyError, TypeError, ValueError) as e:
        raise IdentityValidationError(
            code="identity_config_fields",
            message=f"PSS identity config at {cfg_path} is missing required fields: {e}",
        ) from e
    return validate_identity_tuple(identity)


__all__ = ["resolve_identity"]
