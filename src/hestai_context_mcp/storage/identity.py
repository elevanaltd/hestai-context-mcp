"""ADR-0013 PSS identity validation — R3 + RISK_001 fail-closed observability.

Pure validation helpers for IdentityTuple and PortableNamespace. Performs
no filesystem I/O. Returns structured errors so callers (clock_in restore
path, clock_out publish path) can route them into observable
``portable_state.error`` payloads without inventing auth or first-run UX
(B2_START_BLOCKER_001).

Binding rulings:
- R3: project_id/workspace_id/user_id/carrier_namespace must be non-blank
  strings free of path separators, traversal sequences, and control chars.
  state_schema_version must be a positive int in SUPPORTED_SCHEMA_VERSIONS.
- R10: namespace/identity mismatch is a structured ValidationError, not a
  silent empty-restore fallback.
- RISK_001 + A1: ``RestoreError`` carries a code + optional cause for
  fail-closed observability when identity/schema/IO problems occur during
  the restore lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass

from hestai_context_mcp.storage.types import IdentityTuple, PortableNamespace

#: Supported state-schema-version set. Currently single-version (R4 + B1
#: scope: NO compaction, NO v2 content). Expanding this set requires CE
#: re-consult per the B1→B2 arbitration record.
SUPPORTED_SCHEMA_VERSIONS: frozenset[int] = frozenset({1})

_PATH_SEPARATORS: tuple[str, ...] = ("/", "\\")
_TRAVERSAL_TOKENS: tuple[str, ...] = ("..",)
_CONTROL_CHARS: tuple[str, ...] = ("\n", "\r", "\t", "\x00")


class IdentityValidationError(ValueError):
    """Structured validation error for identity inputs.

    Attributes:
        code: Stable error code (machine-readable; safe for logging).
        field: Identity field that failed validation, when applicable.
        message: Human-readable description.
    """

    def __init__(self, code: str, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.field = field
        self.message = message


@dataclass(frozen=True, slots=True)
class RestoreError(Exception):
    """Structured restore error (RISK_001 + A1).

    Used by the clock_in restore pipeline to surface identity-mismatch,
    schema_too_new, or local-adapter IO failures in a machine-readable
    shape. Inherits from Exception so callers can ``raise`` and ``catch``
    normally; the attributes (code, message, cause) form the wire shape
    that lands in ``clock_in`` response ``portable_state.error``.
    """

    code: str
    message: str
    cause: BaseException | None = None

    def __post_init__(self) -> None:  # pragma: no cover — Exception side-effect
        Exception.__init__(self, self.message)


def _check_string_component(value: object, *, field: str) -> None:
    """Validate a single identity string component (R3).

    Cubic P1 #2: explicitly reject non-string types BEFORE any string
    method is called. Without this gate, a non-string truthy value
    (e.g., int, list, dict) would reach ``value.strip()`` and raise
    an unstructured ``AttributeError``. Per PROD::I2 fail-closed
    identity validation and RISK_001, the structured error code is
    ``invalid_identity_component_type``.
    """

    if not isinstance(value, str):
        raise IdentityValidationError(
            code="invalid_identity_component_type",
            message=(
                f"identity component {field!r} must be a string, "
                f"got {type(value).__name__}"
            ),
            field=field,
        )

    if not value or not value.strip():
        raise IdentityValidationError(
            code="blank_identity_component",
            message=f"identity component {field!r} must be a non-blank string",
            field=field,
        )

    for sep in _PATH_SEPARATORS:
        if sep in value:
            raise IdentityValidationError(
                code="path_separator",
                message=f"identity component {field!r} must not contain path separator {sep!r}",
                field=field,
            )

    for token in _TRAVERSAL_TOKENS:
        if token in value:
            raise IdentityValidationError(
                code="path_traversal",
                message=f"identity component {field!r} must not contain traversal token {token!r}",
                field=field,
            )

    for ctrl in _CONTROL_CHARS:
        if ctrl in value:
            raise IdentityValidationError(
                code="control_character",
                message=f"identity component {field!r} must not contain control characters",
                field=field,
            )


def validate_identity_tuple(identity: IdentityTuple) -> IdentityTuple:
    """Validate an IdentityTuple before any path construction or adapter call.

    Returns the same identity unchanged on success so callers can chain
    e.g. ``adapter.list_artifacts(validate_identity_tuple(identity))``.

    Raises:
        IdentityValidationError: with a stable ``code`` field on failure.
    """

    for field in ("project_id", "workspace_id", "user_id", "carrier_namespace"):
        _check_string_component(getattr(identity, field), field=field)

    # Cubic P1 #5: bool subclasses int, so ``isinstance(int)`` would
    # silently accept True/False (True → 1 passes the supported-version
    # membership check). Reject bool explicitly before the int check so
    # PROD::I2 fail-closed identity validation rejects all non-int types.
    if (
        isinstance(identity.state_schema_version, bool)
        or not isinstance(identity.state_schema_version, int)
        or identity.state_schema_version <= 0
        or identity.state_schema_version not in SUPPORTED_SCHEMA_VERSIONS
    ):
        raise IdentityValidationError(
            code="unsupported_schema_version",
            message=(
                f"state_schema_version={identity.state_schema_version!r} not in "
                f"supported set {sorted(SUPPORTED_SCHEMA_VERSIONS)!r}"
            ),
            field="state_schema_version",
        )

    return identity


def validate_namespace_matches_identity(
    *, namespace: PortableNamespace, identity: IdentityTuple
) -> None:
    """Assert PortableNamespace == IdentityTuple component-wise (NOTE_007 / R3)."""

    mismatches: list[str] = []
    for field in (
        "project_id",
        "workspace_id",
        "user_id",
        "state_schema_version",
        "carrier_namespace",
    ):
        if getattr(namespace, field) != getattr(identity, field):
            mismatches.append(field)

    if mismatches:
        raise IdentityValidationError(
            code="namespace_identity_mismatch",
            message=(
                "PortableNamespace does not match IdentityTuple in fields: " + ", ".join(mismatches)
            ),
        )


__all__ = [
    "IdentityValidationError",
    "RestoreError",
    "SUPPORTED_SCHEMA_VERSIONS",
    "validate_identity_tuple",
    "validate_namespace_matches_identity",
]
