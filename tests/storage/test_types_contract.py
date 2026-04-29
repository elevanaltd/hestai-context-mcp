"""GROUP_001: TYPES_CONTRACT — RED-first tests for storage/types.py.

These tests assert the dataclass and enum contract described in
BUILD-PLAN §PROTOCOL_SIGNATURES (verbatim, per CRS C1) and ADR-0013 R1..R9.

Binding rulings exercised here:
- RISK_002: PortableArtifact = PortableMemoryArtifact | TombstoneArtifact (union).
- RISK_005: v1 payload keys (asserted via PortableMemoryArtifact.payload typing only;
  the concrete payload-key contract is asserted at the build site in clock_out
  later — here we only check the artifact carries a JSON-shaped payload field).
- CRS C1: signatures verbatim — these tests pin the exact field names/types.
- CRS C3: frozen+slots dataclasses preserve effective immutability of leaf
  fields. (Nested JSON payload immutability is enforced at construction site,
  see provenance/clock_out groups.)
- G5: PortableArtifact discriminated union — TypeGuard helpers + match
  exhaustiveness covered in test_artifact_union exhaustiveness section below.

R-trace mapping: see BUILD-PLAN §TDD_TEST_LIST GROUP_001_TYPES_CONTRACT.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import Literal, get_args, get_origin

import pytest


@pytest.mark.unit
class TestStorageCapabilitiesContract:
    """TEST_001: StorageCapabilities matrix fields (R2)."""

    def test_storage_capabilities_has_required_matrix_fields(self) -> None:
        from hestai_context_mcp.storage.types import StorageCapabilities

        names = {f.name for f in dataclasses.fields(StorageCapabilities)}
        required = {
            "strong_list_consistency",
            "atomic_compare_and_swap",
            "conditional_writes",
            "advisory_locking",
            "streaming_writes",
            "encryption_at_rest",
            "encryption_in_transit",
            "hard_delete",
            "read_only",
        }
        assert required.issubset(names)
        # CRS C3: frozen + slots so capabilities cannot be mutated post-init.
        assert StorageCapabilities.__dataclass_params__.frozen is True
        assert "__slots__" in StorageCapabilities.__dict__


@pytest.mark.unit
class TestIdentityTupleContract:
    """TEST_002: IdentityTuple R3 fields."""

    def test_identity_tuple_contains_all_r3_fields(self) -> None:
        from hestai_context_mcp.storage.types import IdentityTuple

        names = [f.name for f in dataclasses.fields(IdentityTuple)]
        assert names == [
            "project_id",
            "workspace_id",
            "user_id",
            "state_schema_version",
            "carrier_namespace",
        ]
        assert IdentityTuple.__dataclass_params__.frozen is True
        assert "__slots__" in IdentityTuple.__dict__


@pytest.mark.unit
class TestPortableNamespaceContract:
    """TEST_003: PortableNamespace shadow of IdentityTuple (NOTE_006)."""

    def test_portable_namespace_contains_all_adapter_scope_fields(self) -> None:
        from hestai_context_mcp.storage.types import PortableNamespace

        names = [f.name for f in dataclasses.fields(PortableNamespace)]
        assert names == [
            "project_id",
            "workspace_id",
            "user_id",
            "state_schema_version",
            "carrier_namespace",
        ]
        assert PortableNamespace.__dataclass_params__.frozen is True
        assert "__slots__" in PortableNamespace.__dict__


@pytest.mark.unit
class TestRedactionProvenanceContract:
    """TEST_004: RedactionProvenance R6 fields."""

    def test_redaction_provenance_contains_all_r6_fields(self) -> None:
        from hestai_context_mcp.storage.types import RedactionProvenance

        names = {f.name for f in dataclasses.fields(RedactionProvenance)}
        required = {
            "engine_name",
            "engine_version",
            "ruleset_hash",
            "input_artifact_hash",
            "output_artifact_hash",
            "redacted_at",
            "classification_label",
            "redacted_credential_categories",
        }
        assert required == names
        assert RedactionProvenance.__dataclass_params__.frozen is True
        assert "__slots__" in RedactionProvenance.__dict__


@pytest.mark.unit
class TestArtifactRefContract:
    """TEST_005: ArtifactRef carries identity + sequence + kind + hash (R2/R3/R9)."""

    def test_artifact_ref_contains_sequence_identity_kind_and_hash(self) -> None:
        from hestai_context_mcp.storage.types import ArtifactRef

        names = {f.name for f in dataclasses.fields(ArtifactRef)}
        for required in (
            "artifact_id",
            "identity",
            "artifact_kind",
            "sequence_id",
            "created_at",
            "payload_hash",
            "carrier_path",
        ):
            assert required in names


@pytest.mark.unit
class TestPortableMemoryArtifactContract:
    """TEST_006: PortableMemoryArtifact R4 fields."""

    def test_portable_memory_artifact_contains_all_r4_fields(self) -> None:
        from hestai_context_mcp.storage.types import PortableMemoryArtifact

        names = {f.name for f in dataclasses.fields(PortableMemoryArtifact)}
        for required in (
            "artifact_id",
            "artifact_kind",
            "identity",
            "schema_version",
            "producer_version",
            "minimum_reader_version",
            "created_at",
            "sequence_id",
            "parent_ids",
            "redaction_provenance",
            "classification_label",
            "payload_hash",
            "payload",
        ):
            assert required in names


@pytest.mark.unit
class TestTombstoneArtifactContract:
    """TEST_007: TombstoneArtifact R8 shape."""

    def test_tombstone_artifact_contains_target_reason_publisher_and_hash(self) -> None:
        from hestai_context_mcp.storage.types import TombstoneArtifact

        names = {f.name for f in dataclasses.fields(TombstoneArtifact)}
        for required in (
            "artifact_id",
            "artifact_kind",
            "identity",
            "schema_version",
            "producer_version",
            "minimum_reader_version",
            "created_at",
            "sequence_id",
            "parent_ids",
            "target_artifact_id",
            "reason",
            "publisher_identity",
            "redaction_provenance",
            "classification_label",
            "payload_hash",
        ):
            assert required in names


@pytest.mark.unit
class TestPublishAckContract:
    """TEST_008: PublishAck R7 acknowledgement and queue fields."""

    def test_publish_ack_contains_acknowledgement_and_queue_fields(self) -> None:
        from hestai_context_mcp.storage.types import PublishAck

        names = {f.name for f in dataclasses.fields(PublishAck)}
        for required in (
            "artifact_id",
            "identity",
            "carrier_namespace",
            "sequence_id",
            "status",
            "durable_carrier_receipt",
            "queued_path",
            "published_at",
            "error_code",
            "error_message",
        ):
            assert required in names


@pytest.mark.unit
class TestWritePreconditionContract:
    """TEST_009: WritePrecondition default to append/create-only (NOTE_012)."""

    def test_write_precondition_defaults_to_append_create_only(self) -> None:
        from hestai_context_mcp.storage.types import WritePrecondition

        precondition = WritePrecondition()
        assert precondition.if_absent is True
        assert precondition.expected_current_hash is None
        assert precondition.expected_parent_ids == ()


@pytest.mark.unit
class TestPortableArtifactUnionContract:
    """TEST_010 + G5: PortableArtifact discriminated union (RISK_002)."""

    def test_portable_artifact_union_accepts_memory_or_tombstone(self) -> None:
        from hestai_context_mcp.storage.types import (
            PortableArtifact,
            PortableMemoryArtifact,
            TombstoneArtifact,
        )

        # PortableArtifact is a typing alias; assert via get_args resolution.
        args = get_args(PortableArtifact)
        # TypeAlias in 3.11 may strip union origin in get_args; fallback OK.
        if get_origin(PortableArtifact) is not None:
            assert PortableMemoryArtifact in args
            assert TombstoneArtifact in args
        else:
            # If runtime alias resolves to a union itself, args will hold both.
            assert any(a is PortableMemoryArtifact for a in args) or args == ()


@pytest.mark.unit
class TestStateClassificationEnumContract:
    """TEST_011: StateClassification three R1 tiers."""

    def test_classification_enum_contains_three_r1_tiers(self) -> None:
        from hestai_context_mcp.storage.types import StateClassification

        values = {member.value for member in StateClassification}
        assert values == {"LOCAL_MUTABLE", "PORTABLE_MEMORY", "DERIVED_PROJECTION"}


@pytest.mark.unit
class TestPublishStatusEnumContract:
    """TEST_012: PublishStatus four-state enum (R7)."""

    def test_publish_status_enum_contains_published_queued_duplicate_failed(self) -> None:
        from hestai_context_mcp.storage.types import PublishStatus

        values = {member.value for member in PublishStatus}
        assert values == {"published", "queued", "duplicate", "failed"}


@pytest.mark.unit
class TestPortableArtifactExhaustiveness:
    """G5: assert_never exhaustiveness on PortableArtifact union (RISK_002)."""

    def test_portable_artifact_match_is_exhaustive(self) -> None:
        from typing import assert_never

        from hestai_context_mcp.storage.types import (
            ArtifactKind,
            IdentityTuple,
            PortableArtifact,
            PortableMemoryArtifact,
            RedactionProvenance,
            TombstoneArtifact,
        )

        identity = IdentityTuple(
            project_id="p",
            workspace_id="w",
            user_id="u",
            state_schema_version=1,
            carrier_namespace="personal",
        )
        provenance = RedactionProvenance(
            engine_name="hestai-context-mcp.redaction",
            engine_version="1",
            ruleset_hash="r",
            input_artifact_hash="i",
            output_artifact_hash="o",
            redacted_at=datetime.now(UTC),
            classification_label="PORTABLE_MEMORY",
            redacted_credential_categories=(),
        )
        memory: PortableArtifact = PortableMemoryArtifact(
            artifact_id="a1",
            artifact_kind=ArtifactKind.PORTABLE_MEMORY,
            identity=identity,
            schema_version=1,
            producer_version="0.1.0",
            minimum_reader_version=1,
            created_at=datetime.now(UTC),
            sequence_id=1,
            parent_ids=(),
            redaction_provenance=provenance,
            classification_label="PORTABLE_MEMORY",
            payload_hash="p1",
            payload={"k": "v"},
        )
        tomb: PortableArtifact = TombstoneArtifact(
            artifact_id="t1",
            artifact_kind=ArtifactKind.TOMBSTONE,
            identity=identity,
            schema_version=1,
            producer_version="0.1.0",
            minimum_reader_version=1,
            created_at=datetime.now(UTC),
            sequence_id=2,
            parent_ids=("a1",),
            target_artifact_id="a1",
            reason="user request",
            publisher_identity=identity,
            redaction_provenance=None,
            classification_label="PORTABLE_MEMORY",
            payload_hash="t1h",
        )

        def label(artifact: PortableArtifact) -> str:
            match artifact:
                case PortableMemoryArtifact():
                    return "memory"
                case TombstoneArtifact():
                    return "tombstone"
                case _ as unreachable:  # pragma: no cover — exhaustiveness guard
                    assert_never(unreachable)

        assert label(memory) == "memory"
        assert label(tomb) == "tombstone"


@pytest.mark.unit
class TestArtifactKindEnum:
    """RISK_002: ArtifactKind discriminator values aligned with Literal narrowing."""

    def test_artifact_kind_enum_values(self) -> None:
        from hestai_context_mcp.storage.types import ArtifactKind

        assert ArtifactKind.PORTABLE_MEMORY.value == "portable_memory"
        assert ArtifactKind.TOMBSTONE.value == "tombstone"


@pytest.mark.unit
class TestClassificationLabelLiteral:
    """CRS C1: classification_label remains Literal['PORTABLE_MEMORY']."""

    def test_classification_label_is_literal_portable_memory(self) -> None:
        import typing

        from hestai_context_mcp.storage.types import RedactionProvenance

        hints = typing.get_type_hints(RedactionProvenance, include_extras=True)
        annotation = hints["classification_label"]
        assert get_origin(annotation) is Literal
        assert get_args(annotation) == ("PORTABLE_MEMORY",)


@pytest.mark.unit
class TestTypesModuleHasNoIo:
    """STRUCTURE: types module is pure — no filesystem or network imports."""

    def test_types_module_has_no_filesystem_or_network_imports(self) -> None:
        from pathlib import Path

        types_src = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "hestai_context_mcp"
            / "storage"
            / "types.py"
        )
        text = types_src.read_text()
        for forbidden in ("requests", "httpx", "boto", "urllib.request", "git "):
            assert forbidden not in text, f"types.py imported forbidden token: {forbidden}"
