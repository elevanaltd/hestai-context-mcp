"""ADR-0013 PSS portable artifact schema versioning + migration framework.

Implements R4 (versioning + migration) and R10 (fail-closed hydration):

- ``CURRENT_SCHEMA_VERSION`` and ``SUPPORTED_SCHEMA_VERSIONS`` define the
  reader's compatibility envelope. B1 ships only v1 to honor R12 (no
  invented v2 content) and the B1 scope discipline (RISK_007 NO compaction).
- ``MIGRATION_REGISTRY`` is keyed by source schema version. Each entry is a
  callable that takes a PortableMemoryArtifact and returns a v-current
  projection artifact. Migration NEVER rewrites the source on disk
  (CONTEXT_PROJECTION_EDIT_PLAN EDIT_004).
- ``parse_artifact_dict`` deserializes a dict into a PortableMemoryArtifact,
  silently dropping forward-compatible fields when the reader can support
  the artifact (R4 last bullet).
- ``validate_artifact`` enforces structural integrity (identity/schema
  alignment, payload_hash present, sequence_id >= 0, classification ==
  PORTABLE_MEMORY). Failures raise SchemaValidationError with a stable
  ``code`` field.
- ``SchemaTooNewError`` is the structured error raised when an artifact's
  minimum_reader_version exceeds the reader's support envelope. This is
  the wire shape that lands in clock_in restore_error / clock_out
  publish-skip status (RISK_001 + A1).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from hestai_context_mcp.storage.types import (
    ArtifactKind,
    IdentityTuple,
    PortableMemoryArtifact,
    RedactionProvenance,
)

CURRENT_SCHEMA_VERSION: int = 1
SUPPORTED_SCHEMA_VERSIONS: frozenset[int] = frozenset({1})


@dataclass(frozen=True, slots=True)
class SchemaValidationError(Exception):
    """Structural validation failure for a portable artifact."""

    code: str
    message: str

    def __post_init__(self) -> None:  # pragma: no cover — Exception side-effect
        Exception.__init__(self, self.message)


@dataclass(frozen=True, slots=True)
class SchemaTooNewError(Exception):
    """Reader cannot hydrate an artifact whose minimum_reader_version is too high."""

    code: str
    message: str
    minimum_reader_version: int

    def __post_init__(self) -> None:  # pragma: no cover — Exception side-effect
        Exception.__init__(self, self.message)


def is_artifact_supported(artifact: PortableMemoryArtifact) -> bool:
    """True iff the reader can hydrate this artifact (R4)."""

    return (
        artifact.minimum_reader_version <= CURRENT_SCHEMA_VERSION
        and artifact.schema_version in SUPPORTED_SCHEMA_VERSIONS
    )


def validate_artifact(artifact: PortableMemoryArtifact) -> PortableMemoryArtifact:
    """Validate structural integrity of a portable memory artifact (R4 + R10).

    Returns the artifact unchanged on success so callers can chain.

    Raises:
        SchemaTooNewError: when minimum_reader_version exceeds support.
        SchemaValidationError: with a stable ``code`` for any other
            structural issue.
    """

    if not is_artifact_supported(artifact):
        raise SchemaTooNewError(
            code="schema_too_new",
            message=(
                f"artifact minimum_reader_version={artifact.minimum_reader_version} "
                f"exceeds reader CURRENT_SCHEMA_VERSION={CURRENT_SCHEMA_VERSION}"
            ),
            minimum_reader_version=artifact.minimum_reader_version,
        )

    if artifact.identity.state_schema_version != artifact.schema_version:
        raise SchemaValidationError(
            code="identity_schema_mismatch",
            message=(
                f"identity.state_schema_version={artifact.identity.state_schema_version} "
                f"!= artifact.schema_version={artifact.schema_version}"
            ),
        )

    if not artifact.payload_hash:
        raise SchemaValidationError(
            code="missing_payload_hash",
            message="artifact.payload_hash must be a non-empty string",
        )

    if artifact.sequence_id < 0:
        raise SchemaValidationError(
            code="non_monotonic_sequence_id",
            message=f"sequence_id must be >= 0, got {artifact.sequence_id}",
        )

    if artifact.classification_label != "PORTABLE_MEMORY":
        raise SchemaValidationError(
            code="non_portable_classification",
            message=(
                "classification_label must be 'PORTABLE_MEMORY', got "
                f"{artifact.classification_label!r}"
            ),
        )

    return artifact


def _identity_migration(artifact: PortableMemoryArtifact) -> PortableMemoryArtifact:
    """v1 identity migration — returns the artifact unchanged.

    R4: migration produces a projection artifact and never rewrites the
    source on disk; the v1 identity migration is the simplest case.
    """

    return artifact


MIGRATION_REGISTRY: Mapping[int, Callable[[PortableMemoryArtifact], PortableMemoryArtifact]] = {
    1: _identity_migration,
}


def migrate_into_projection(artifact: PortableMemoryArtifact) -> PortableMemoryArtifact:
    """Apply the registered migration for ``artifact.schema_version``.

    Used by the projection builder (storage.projection) and clock_in
    restore. Source is never mutated on disk; this returns a (possibly
    new) PortableMemoryArtifact instance suitable for projection input.

    Raises:
        SchemaTooNewError: when the artifact is forward-incompatible.
        SchemaValidationError: when no migration is registered.
    """

    validate_artifact(artifact)
    migrator = MIGRATION_REGISTRY.get(artifact.schema_version)
    if migrator is None:
        raise SchemaValidationError(
            code="no_migration_registered",
            message=f"no migration registered for schema_version={artifact.schema_version}",
        )
    return migrator(artifact)


def _parse_identity(raw: Mapping[str, Any]) -> IdentityTuple:
    return IdentityTuple(
        project_id=str(raw["project_id"]),
        workspace_id=str(raw["workspace_id"]),
        user_id=str(raw["user_id"]),
        state_schema_version=int(raw["state_schema_version"]),
        carrier_namespace=str(raw["carrier_namespace"]),
    )


def _parse_provenance(raw: Mapping[str, Any]) -> RedactionProvenance:
    redacted_at = raw["redacted_at"]
    if isinstance(redacted_at, str):
        redacted_at = datetime.fromisoformat(redacted_at)
    return RedactionProvenance(
        engine_name=str(raw["engine_name"]),
        engine_version=str(raw["engine_version"]),
        ruleset_hash=str(raw["ruleset_hash"]),
        input_artifact_hash=str(raw["input_artifact_hash"]),
        output_artifact_hash=str(raw["output_artifact_hash"]),
        redacted_at=redacted_at,
        classification_label="PORTABLE_MEMORY",
        redacted_credential_categories=tuple(raw.get("redacted_credential_categories", ())),
    )


def parse_artifact_dict(raw: Mapping[str, Any]) -> PortableMemoryArtifact:
    """Deserialize a dict into PortableMemoryArtifact.

    Forward-compatible: silently drops keys outside the v-current schema
    when ``minimum_reader_version <= CURRENT_SCHEMA_VERSION`` (R4 last
    bullet). For too-new artifacts, ``validate_artifact`` raises
    ``SchemaTooNewError`` after construction.
    """

    created_at = raw["created_at"]
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)

    artifact = PortableMemoryArtifact(
        artifact_id=str(raw["artifact_id"]),
        artifact_kind=ArtifactKind.PORTABLE_MEMORY,
        identity=_parse_identity(raw["identity"]),
        schema_version=int(raw["schema_version"]),
        producer_version=str(raw["producer_version"]),
        minimum_reader_version=int(raw["minimum_reader_version"]),
        created_at=created_at,
        sequence_id=int(raw["sequence_id"]),
        parent_ids=tuple(raw.get("parent_ids", ())),
        redaction_provenance=_parse_provenance(raw["redaction_provenance"]),
        classification_label="PORTABLE_MEMORY",
        payload_hash=str(raw["payload_hash"]),
        payload=dict(raw["payload"]),
    )
    # Note: forward-compat unknown fields (e.g., 'future_only_field') are
    # not consumed above and are silently ignored when supported.
    if not is_artifact_supported(artifact):
        # Keep the structured fail-closed path even when constructed via
        # parse_artifact_dict — caller relies on this to distinguish
        # too-new artifacts from structurally-invalid ones.
        return artifact  # validate_artifact will raise downstream
    return replace(artifact)


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "MIGRATION_REGISTRY",
    "SUPPORTED_SCHEMA_VERSIONS",
    "SchemaTooNewError",
    "SchemaValidationError",
    "is_artifact_supported",
    "migrate_into_projection",
    "parse_artifact_dict",
    "validate_artifact",
]
