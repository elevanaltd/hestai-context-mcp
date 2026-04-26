"""ADR-0013 PSS redaction provenance — R6 + R10 fail-closed publication gate.

This module is the publication-gate enforcer:

- ``compute_ruleset_hash`` derives a deterministic SHA-256 over the named
  RedactionEngine.PATTERNS regex set so readers can detect stale
  provenance after rules change (PROD::I2).
- ``build_provenance`` constructs a complete RedactionProvenance, hashing
  input/output text and stamping the engine name + version constants from
  ``core.redaction``. ``build_provenance_from_result`` accepts the
  RedactionEngine.redact() result so callers don't need to redact twice.
- ``validate_provenance_complete`` rejects partial provenance with stable
  ``ProvenanceIncompleteError(code='provenance_incomplete',
  missing_field=...)`` codes for clock_out / adapter integration.
- ``assert_ruleset_hash_current`` rejects stale provenance whose ruleset
  hash no longer matches the live PATTERNS digest.
- ``build_provenance_or_raise`` is the **G4 atomic guard**: it raises
  BEFORE any side-effecting work begins. Storage adapters and clock_out
  MUST call this *before* opening a target file so a partial-state write
  cannot occur.

CRS C3 (B1→B2 arbitration): JSON payloads are mutable nested types; the
redaction provenance contract here treats input_text/output_text as bytes
inputs to a hash function and never persists them, which preserves
effective immutability for the provenance record itself (frozen+slots
RedactionProvenance dataclass).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from hestai_context_mcp.core.redaction import (
    REDACTION_ENGINE_NAME,
    REDACTION_ENGINE_VERSION,
    RedactionEngine,
    RedactionResult,
)
from hestai_context_mcp.storage.types import RedactionProvenance


@dataclass(frozen=True, slots=True)
class ProvenanceIncompleteError(Exception):
    """Provenance metadata missing a required field for publication (R6 + RISK_010)."""

    code: str
    missing_field: str
    message: str

    def __post_init__(self) -> None:  # pragma: no cover — Exception side-effect
        Exception.__init__(self, self.message)


@dataclass(frozen=True, slots=True)
class ProvenanceStaleError(Exception):
    """Ruleset hash on the provenance record no longer matches live PATTERNS."""

    code: str
    message: str

    def __post_init__(self) -> None:  # pragma: no cover — Exception side-effect
        Exception.__init__(self, self.message)


def compute_ruleset_hash() -> str:
    """Deterministic digest over RedactionEngine.PATTERNS (R6).

    Combines pattern names + compiled regex source + replacement strings
    in sorted order so the hash is stable across runs and changes
    deterministically when PATTERNS changes (A4 contract test).
    """

    parts: list[str] = []
    for name in sorted(RedactionEngine.PATTERNS):
        pattern, replacement = RedactionEngine.PATTERNS[name]
        parts.append(f"{name}|{pattern.pattern}|{replacement}")
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return digest


def _hash_text(text: str) -> str:
    """SHA-256 of text content for provenance input/output_artifact_hash."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_provenance(
    *,
    input_text: str,
    output_text: str,
    redacted_credential_categories: tuple[str, ...],
    engine_name_override: str | None = None,
    engine_version_override: str | None = None,
    redacted_at: datetime | None = None,
) -> RedactionProvenance:
    """Construct a complete RedactionProvenance for a redacted artifact (R6).

    Args:
        input_text: Pre-redaction text content.
        output_text: Post-redaction text content.
        redacted_credential_categories: Categories detected by the engine
            (may be empty per NOTE_009; never None).
        engine_name_override: Test-only seam to inject a different engine
            identifier; production code uses REDACTION_ENGINE_NAME.
        engine_version_override: Test-only seam to inject a different
            version (used by the G4 atomic-guard test to simulate a
            mis-configured caller).
        redacted_at: Optional timezone-aware datetime; defaults to now(UTC).
    """

    return RedactionProvenance(
        engine_name=(
            engine_name_override if engine_name_override is not None else REDACTION_ENGINE_NAME
        ),
        engine_version=(
            engine_version_override
            if engine_version_override is not None
            else REDACTION_ENGINE_VERSION
        ),
        ruleset_hash=compute_ruleset_hash(),
        input_artifact_hash=_hash_text(input_text),
        output_artifact_hash=_hash_text(output_text),
        redacted_at=redacted_at if redacted_at is not None else datetime.now(UTC),
        classification_label="PORTABLE_MEMORY",
        redacted_credential_categories=tuple(redacted_credential_categories),
    )


def build_provenance_from_result(
    *,
    input_text: str,
    result: RedactionResult,
    redacted_at: datetime | None = None,
) -> RedactionProvenance:
    """Construct provenance directly from a RedactionEngine.redact() result.

    Avoids re-redacting in callers and keeps the redacted_credential_categories
    aligned with the engine's actual detection output (TEST_056).
    """

    return build_provenance(
        input_text=input_text,
        output_text=result.redacted_text,
        redacted_credential_categories=tuple(result.redacted_types),
        redacted_at=redacted_at,
    )


_REQUIRED_PROVENANCE_FIELDS: tuple[str, ...] = (
    "engine_name",
    "engine_version",
    "ruleset_hash",
    "input_artifact_hash",
    "output_artifact_hash",
)


def validate_provenance_complete(provenance: RedactionProvenance) -> RedactionProvenance:
    """Reject incomplete provenance with a stable error code (R6 + RISK_010).

    Raises:
        ProvenanceIncompleteError: with ``missing_field`` indicating which
            required string field is empty/blank.
    """

    for field in _REQUIRED_PROVENANCE_FIELDS:
        value = getattr(provenance, field)
        if not isinstance(value, str) or not value:
            raise ProvenanceIncompleteError(
                code="provenance_incomplete",
                missing_field=field,
                message=f"RedactionProvenance.{field} must be a non-empty string",
            )
    if provenance.classification_label != "PORTABLE_MEMORY":
        raise ProvenanceIncompleteError(
            code="provenance_incomplete",
            missing_field="classification_label",
            message=(
                "classification_label must be 'PORTABLE_MEMORY'; "
                "any other value violates R1 + R6"
            ),
        )
    if provenance.redacted_at.tzinfo is None:
        raise ProvenanceIncompleteError(
            code="provenance_incomplete",
            missing_field="redacted_at",
            message="redacted_at must be timezone-aware",
        )
    return provenance


def assert_ruleset_hash_current(provenance: RedactionProvenance) -> None:
    """Refuse provenance whose ruleset_hash does not match live PATTERNS (TEST_055).

    Used at publish time to prevent treating older redactor output as safe
    after rules change (PROD::I2 fail-closed).
    """

    current = compute_ruleset_hash()
    if provenance.ruleset_hash != current:
        raise ProvenanceStaleError(
            code="ruleset_hash_stale",
            message=(
                "RedactionProvenance.ruleset_hash does not match current "
                "RedactionEngine.PATTERNS digest — bump REDACTION_ENGINE_VERSION "
                "or re-redact before publishing"
            ),
        )


def build_provenance_or_raise(
    *,
    input_text: str,
    output_text: str,
    redacted_credential_categories: tuple[str, ...],
    engine_name_override: str | None = None,
    engine_version_override: str | None = None,
    redacted_at: datetime | None = None,
) -> RedactionProvenance:
    """G4 atomic guard: build + validate provenance in a single non-side-effecting call.

    Storage adapters and clock_out MUST call this BEFORE opening a target
    file so partial-state writes cannot occur. The function raises
    ``ProvenanceIncompleteError`` synchronously when any required field is
    empty (e.g., ``engine_version_override=''``), preserving R10 + RISK_010
    fail-closed publication semantics.
    """

    provenance = build_provenance(
        input_text=input_text,
        output_text=output_text,
        redacted_credential_categories=redacted_credential_categories,
        engine_name_override=engine_name_override,
        engine_version_override=engine_version_override,
        redacted_at=redacted_at,
    )
    return validate_provenance_complete(provenance)


__all__ = [
    "ProvenanceIncompleteError",
    "ProvenanceStaleError",
    "assert_ruleset_hash_current",
    "build_provenance",
    "build_provenance_from_result",
    "build_provenance_or_raise",
    "compute_ruleset_hash",
    "validate_provenance_complete",
]
