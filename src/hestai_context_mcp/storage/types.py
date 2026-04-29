"""ADR-0013 PSS storage type contract — verbatim from BUILD-PLAN §PROTOCOL_SIGNATURES.

This module contains pure type definitions for Portable Session State (PSS)
artifacts, identity, refs, capabilities, and acks. It performs:
- NO filesystem I/O.
- NO environment reads.
- NO adapter imports.
- NO remote-carrier fields.

CRS C1 (B1→B2 arbitration): signatures MUST be implemented verbatim.
CRS C3: frozen+slots dataclasses preserve effective immutability of leaf
fields; nested JSON payload immutability is enforced at the *construction
site* (e.g., clock_out artifact build) — see provenance/clock_out groups.

R-trace: R1 (classification), R2 (capabilities/refs), R3 (identity),
R4 (schema), R6 (redaction provenance), R7 (publish ack),
R8 (tombstone), R9 (sequence + precondition).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = Mapping[str, JsonValue]


class StateClassification(StrEnum):
    LOCAL_MUTABLE = "LOCAL_MUTABLE"
    PORTABLE_MEMORY = "PORTABLE_MEMORY"
    DERIVED_PROJECTION = "DERIVED_PROJECTION"


class ArtifactKind(StrEnum):
    PORTABLE_MEMORY = "portable_memory"
    TOMBSTONE = "tombstone"


class PublishStatus(StrEnum):
    PUBLISHED = "published"
    QUEUED = "queued"
    DUPLICATE = "duplicate"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class StorageCapabilities:
    strong_list_consistency: bool
    atomic_compare_and_swap: bool
    conditional_writes: bool
    advisory_locking: bool
    streaming_writes: bool
    encryption_at_rest: bool
    encryption_in_transit: bool
    hard_delete: bool
    read_only: bool


@dataclass(frozen=True, slots=True)
class IdentityTuple:
    project_id: str
    workspace_id: str
    user_id: str
    state_schema_version: int
    carrier_namespace: str


@dataclass(frozen=True, slots=True)
class PortableNamespace:
    project_id: str
    workspace_id: str
    user_id: str
    state_schema_version: int
    carrier_namespace: str


@dataclass(frozen=True, slots=True)
class RedactionProvenance:
    engine_name: str
    engine_version: str
    ruleset_hash: str
    input_artifact_hash: str
    output_artifact_hash: str
    redacted_at: datetime
    classification_label: Literal["PORTABLE_MEMORY"]
    redacted_credential_categories: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    artifact_id: str
    identity: IdentityTuple
    artifact_kind: ArtifactKind
    sequence_id: int
    created_at: datetime
    payload_hash: str
    carrier_path: str


@dataclass(frozen=True, slots=True)
class PortableMemoryArtifact:
    artifact_id: str
    artifact_kind: Literal[ArtifactKind.PORTABLE_MEMORY]
    identity: IdentityTuple
    schema_version: int
    producer_version: str
    minimum_reader_version: int
    created_at: datetime
    sequence_id: int
    parent_ids: tuple[str, ...]
    redaction_provenance: RedactionProvenance
    classification_label: Literal["PORTABLE_MEMORY"]
    payload_hash: str
    payload: JsonObject


@dataclass(frozen=True, slots=True)
class TombstoneArtifact:
    artifact_id: str
    artifact_kind: Literal[ArtifactKind.TOMBSTONE]
    identity: IdentityTuple
    schema_version: int
    producer_version: str
    minimum_reader_version: int
    created_at: datetime
    sequence_id: int
    parent_ids: tuple[str, ...]
    target_artifact_id: str
    reason: str
    publisher_identity: IdentityTuple
    redaction_provenance: RedactionProvenance | None
    classification_label: Literal["PORTABLE_MEMORY"]
    payload_hash: str


@dataclass(frozen=True, slots=True)
class WritePrecondition:
    if_absent: bool = True
    expected_current_hash: str | None = None
    expected_parent_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PublishAck:
    artifact_id: str
    identity: IdentityTuple
    carrier_namespace: str
    sequence_id: int
    status: PublishStatus
    durable_carrier_receipt: str | None
    queued_path: str | None
    published_at: datetime | None
    error_code: str | None
    error_message: str | None


PortableArtifact: TypeAlias = PortableMemoryArtifact | TombstoneArtifact


def is_portable_memory(artifact: PortableArtifact) -> bool:
    """Discriminator helper for PortableArtifact union (G5).

    Returns True when the artifact is a PortableMemoryArtifact. Together
    with :func:`is_tombstone` this provides predicate access for callers
    that prefer not to use match/case (e.g., older Python compatibility
    in tests). The canonical narrowing path is match-statement on
    ``artifact_kind`` Literal narrowing — see RISK_002 / G5.
    """

    return isinstance(artifact, PortableMemoryArtifact)


def is_tombstone(artifact: PortableArtifact) -> bool:
    """Discriminator helper for PortableArtifact union (G5).

    Returns True when the artifact is a TombstoneArtifact. See
    :func:`is_portable_memory` for the paired predicate.
    """

    return isinstance(artifact, TombstoneArtifact)


__all__ = [
    "ArtifactKind",
    "ArtifactRef",
    "IdentityTuple",
    "JsonObject",
    "JsonScalar",
    "JsonValue",
    "PortableArtifact",
    "PortableMemoryArtifact",
    "PortableNamespace",
    "PublishAck",
    "PublishStatus",
    "RedactionProvenance",
    "StateClassification",
    "StorageCapabilities",
    "TombstoneArtifact",
    "WritePrecondition",
    "is_portable_memory",
    "is_tombstone",
]
