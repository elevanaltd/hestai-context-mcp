"""GROUP_004: SCHEMA_AND_MIGRATION — RED-first tests for storage/schema.py.

Asserts the portable artifact schema versioning + migration framework per
ADR-0013 R4 + R10:
- ``CURRENT_SCHEMA_VERSION = 1``.
- ``SUPPORTED_SCHEMA_VERSIONS`` contains 1 (and only 1 for B1).
- A migration registry exists (with at least the v1 identity migration).
- Artifacts whose ``minimum_reader_version`` exceeds support fail closed
  with a structured ``SchemaTooNewError`` (R10 / fail-closed restore).
- Validators reject identity/schema mismatch, missing payload_hash,
  negative sequence_id, and non-PORTABLE_MEMORY classification.
- Hydration failure produces a structured error, never silent empty
  fallback (INVARIANT_005).

R-trace: see BUILD-PLAN §TDD_TEST_LIST GROUP_004_SCHEMA_AND_MIGRATION.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hestai_context_mcp.storage.types import (
    ArtifactKind,
    IdentityTuple,
    PortableMemoryArtifact,
    RedactionProvenance,
)


def _identity() -> IdentityTuple:
    return IdentityTuple(
        project_id="hestai-context-mcp",
        workspace_id="build-adr-13",
        user_id="shaun",
        state_schema_version=1,
        carrier_namespace="personal",
    )


def _provenance() -> RedactionProvenance:
    return RedactionProvenance(
        engine_name="hestai-context-mcp.redaction",
        engine_version="1",
        ruleset_hash="rh-v1",
        input_artifact_hash="ih",
        output_artifact_hash="oh",
        redacted_at=datetime.now(UTC),
        classification_label="PORTABLE_MEMORY",
        redacted_credential_categories=(),
    )


def _make_artifact(
    *,
    schema_version: int = 1,
    minimum_reader_version: int = 1,
    sequence_id: int = 1,
    payload_hash: str = "ph",
    classification_label: str = "PORTABLE_MEMORY",
) -> PortableMemoryArtifact:
    return PortableMemoryArtifact(
        artifact_id="a1",
        artifact_kind=ArtifactKind.PORTABLE_MEMORY,
        identity=_identity(),
        schema_version=schema_version,
        producer_version="0.1.0",
        minimum_reader_version=minimum_reader_version,
        created_at=datetime.now(UTC),
        sequence_id=sequence_id,
        parent_ids=(),
        redaction_provenance=_provenance(),
        classification_label=classification_label,  # type: ignore[arg-type]
        payload_hash=payload_hash,
        payload={"k": "v"},
    )


@pytest.mark.unit
class TestCurrentSchemaVersion:
    """TEST_033: CURRENT_SCHEMA_VERSION = 1."""

    def test_current_schema_version_is_one(self) -> None:
        from hestai_context_mcp.storage.schema import CURRENT_SCHEMA_VERSION

        assert CURRENT_SCHEMA_VERSION == 1


@pytest.mark.unit
class TestSchemaSupport:
    """TEST_034: v1 artifacts are supported by reader."""

    def test_v1_artifact_supported_by_reader(self) -> None:
        from hestai_context_mcp.storage.schema import is_artifact_supported

        artifact = _make_artifact(schema_version=1, minimum_reader_version=1)
        assert is_artifact_supported(artifact) is True


@pytest.mark.unit
class TestMinimumReaderVersionFailClosed:
    """TEST_035 + TEST_036: minimum_reader_version above CURRENT fails closed."""

    def test_minimum_reader_version_above_supported_fails_closed(self) -> None:
        from hestai_context_mcp.storage.schema import is_artifact_supported

        artifact = _make_artifact(schema_version=2, minimum_reader_version=2)
        assert is_artifact_supported(artifact) is False

    def test_schema_too_new_error_is_structured(self) -> None:
        from hestai_context_mcp.storage.schema import SchemaTooNewError, validate_artifact

        artifact = _make_artifact(schema_version=2, minimum_reader_version=2)
        with pytest.raises(SchemaTooNewError) as excinfo:
            validate_artifact(artifact)
        assert excinfo.value.code == "schema_too_new"
        assert excinfo.value.minimum_reader_version == 2


@pytest.mark.unit
class TestUnknownOptionalFieldsIgnored:
    """TEST_037: optional fields ignored when minimum_reader_version allows."""

    def test_unknown_optional_fields_ignored_when_min_reader_allows(self) -> None:
        from hestai_context_mcp.storage.schema import parse_artifact_dict

        # An artifact dict with an unknown forward-compatible field should
        # parse successfully when minimum_reader_version <= CURRENT.
        raw = {
            "artifact_id": "a1",
            "artifact_kind": ArtifactKind.PORTABLE_MEMORY.value,
            "identity": {
                "project_id": "p",
                "workspace_id": "w",
                "user_id": "u",
                "state_schema_version": 1,
                "carrier_namespace": "personal",
            },
            "schema_version": 1,
            "producer_version": "0.1.0",
            "minimum_reader_version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "sequence_id": 1,
            "parent_ids": [],
            "redaction_provenance": {
                "engine_name": "e",
                "engine_version": "1",
                "ruleset_hash": "r",
                "input_artifact_hash": "i",
                "output_artifact_hash": "o",
                "redacted_at": datetime.now(UTC).isoformat(),
                "classification_label": "PORTABLE_MEMORY",
                "redacted_credential_categories": [],
            },
            "classification_label": "PORTABLE_MEMORY",
            "payload_hash": "ph",
            "payload": {"k": "v"},
            # Unknown forward-compat field:
            "future_only_field": "should-be-ignored",
        }
        artifact = parse_artifact_dict(raw)
        assert isinstance(artifact, PortableMemoryArtifact)
        assert artifact.artifact_id == "a1"


@pytest.mark.unit
class TestMigrationRegistry:
    """TEST_038/TEST_039: registry exists with at least the v1 identity migration."""

    def test_v1_migration_returns_projection_artifact_without_rewriting_source(self) -> None:
        from hestai_context_mcp.storage.schema import migrate_into_projection

        artifact = _make_artifact()
        projection = migrate_into_projection(artifact)
        # v1 migration: returns artifact unchanged (identity migration).
        assert projection.artifact_id == artifact.artifact_id
        assert projection.schema_version == artifact.schema_version

    def test_migration_registry_has_entry_for_v1(self) -> None:
        from hestai_context_mcp.storage.schema import MIGRATION_REGISTRY

        assert 1 in MIGRATION_REGISTRY
        # Identity migration is callable.
        assert callable(MIGRATION_REGISTRY[1])


@pytest.mark.unit
class TestSchemaValidation:
    """TEST_040..TEST_043: validators reject inconsistent artifacts."""

    def test_schema_validation_rejects_identity_schema_mismatch(self) -> None:
        from hestai_context_mcp.storage.schema import (
            SchemaValidationError,
            validate_artifact,
        )
        from hestai_context_mcp.storage.types import IdentityTuple

        identity = IdentityTuple(
            project_id="p",
            workspace_id="w",
            user_id="u",
            state_schema_version=99,  # mismatch vs schema_version=1
            carrier_namespace="personal",
        )
        artifact = _make_artifact()
        # Replace identity via dataclasses.replace to keep frozen contract.
        import dataclasses

        artifact = dataclasses.replace(artifact, identity=identity, schema_version=1)
        with pytest.raises(SchemaValidationError) as excinfo:
            validate_artifact(artifact)
        assert excinfo.value.code == "identity_schema_mismatch"

    def test_schema_validation_rejects_missing_payload_hash(self) -> None:
        from hestai_context_mcp.storage.schema import (
            SchemaValidationError,
            validate_artifact,
        )

        artifact = _make_artifact(payload_hash="")
        with pytest.raises(SchemaValidationError) as excinfo:
            validate_artifact(artifact)
        assert excinfo.value.code == "missing_payload_hash"

    def test_schema_validation_rejects_negative_sequence_id(self) -> None:
        from hestai_context_mcp.storage.schema import (
            SchemaValidationError,
            validate_artifact,
        )

        artifact = _make_artifact(sequence_id=-1)
        with pytest.raises(SchemaValidationError) as excinfo:
            validate_artifact(artifact)
        assert excinfo.value.code == "non_monotonic_sequence_id"

    def test_schema_validation_rejects_non_portable_classification(self) -> None:
        from hestai_context_mcp.storage.schema import (
            SchemaValidationError,
            validate_artifact,
        )

        artifact = _make_artifact(classification_label="LOCAL_MUTABLE")
        with pytest.raises(SchemaValidationError) as excinfo:
            validate_artifact(artifact)
        assert excinfo.value.code == "non_portable_classification"


@pytest.mark.unit
class TestRestoreFailureNotSilent:
    """TEST_044 + INVARIANT_005: hydration failure is structured, not empty."""

    def test_restore_failure_is_not_silent_empty_projection(self) -> None:
        from hestai_context_mcp.storage.schema import SchemaTooNewError, validate_artifact

        artifact = _make_artifact(schema_version=99, minimum_reader_version=99)
        with pytest.raises(SchemaTooNewError):
            validate_artifact(artifact)
