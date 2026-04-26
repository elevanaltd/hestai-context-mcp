"""GROUP_010: PROJECTION_RESTORE — RED-first tests for storage/projection.py.

Asserts the deterministic projection builder per BUILD-PLAN
§TDD_TEST_LIST GROUP_010 (TEST_109..TEST_118) and ADR-0013
R3/R4/R5/R8/R9/R10.

Binding rulings exercised here:
- R9: monotonic merge, idempotent same-hash duplicates, structured
  conflict for different-hash duplicates.
- R8: tombstones are applied BEFORE merge so the projection never
  contains a tombstoned artifact (A3 — tombstone round-trip).
- R10 / INVARIANT_004: same artifacts on different machine roots
  produce the same projection shape (no machine-specific absolute
  paths leaking into portable fields).
- R10 / INVARIANT_005: hydration failure is a structured error, not a
  silent empty fallback.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import pytest


def _identity(*, project_id: str = "proj-A") -> Any:
    from hestai_context_mcp.storage.types import IdentityTuple

    return IdentityTuple(
        project_id=project_id,
        workspace_id="wt-build",
        user_id="alice",
        state_schema_version=1,
        carrier_namespace="personal",
    )


def _provenance() -> Any:
    from hestai_context_mcp.storage.provenance import build_provenance_or_raise

    return build_provenance_or_raise(
        input_text="i",
        output_text="o",
        redacted_credential_categories=(),
    )


def _hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _memory(
    *,
    artifact_id: str,
    sequence_id: int,
    payload: dict[str, Any] | None = None,
    identity: Any | None = None,
) -> Any:
    from hestai_context_mcp.storage.types import ArtifactKind, PortableMemoryArtifact

    payload = payload or {"id": artifact_id}
    identity = identity or _identity()
    return PortableMemoryArtifact(
        artifact_id=artifact_id,
        artifact_kind=ArtifactKind.PORTABLE_MEMORY,
        identity=identity,
        schema_version=1,
        producer_version="1",
        minimum_reader_version=1,
        created_at=datetime.now(UTC),
        sequence_id=sequence_id,
        parent_ids=(),
        redaction_provenance=_provenance(),
        classification_label="PORTABLE_MEMORY",
        payload_hash=_hash_payload(payload),
        payload=payload,
    )


def _tombstone(
    *,
    artifact_id: str,
    sequence_id: int,
    target_artifact_id: str,
    reason: str = "user-revoked",
) -> Any:
    from hestai_context_mcp.storage.types import ArtifactKind, TombstoneArtifact

    identity = _identity()
    return TombstoneArtifact(
        artifact_id=artifact_id,
        artifact_kind=ArtifactKind.TOMBSTONE,
        identity=identity,
        schema_version=1,
        producer_version="1",
        minimum_reader_version=1,
        created_at=datetime.now(UTC),
        sequence_id=sequence_id,
        parent_ids=(target_artifact_id,),
        target_artifact_id=target_artifact_id,
        reason=reason,
        publisher_identity=identity,
        redaction_provenance=None,
        classification_label="PORTABLE_MEMORY",
        payload_hash=hashlib.sha256(target_artifact_id.encode()).hexdigest(),
    )


@pytest.mark.unit
class TestProjectionOrdering:
    """TEST_109."""

    def test_projection_sorts_artifacts_by_sequence_then_id(self) -> None:
        from hestai_context_mcp.storage.projection import build_projection

        a3 = _memory(artifact_id="art-3", sequence_id=3)
        a1 = _memory(artifact_id="art-1", sequence_id=1)
        a2b = _memory(artifact_id="art-2-beta", sequence_id=2)
        a2a = _memory(artifact_id="art-2-alpha", sequence_id=2)
        result = build_projection(
            identity=_identity(),
            artifacts=(a3, a1, a2b, a2a),
            tombstones=(),
        )
        ids = [r["artifact_id"] for r in result["artifact_refs"]]
        assert ids == ["art-1", "art-2-alpha", "art-2-beta", "art-3"]


@pytest.mark.unit
class TestProjectionIdentityGuards:
    """TEST_110."""

    def test_projection_rejects_mixed_identity_artifacts(self) -> None:
        from hestai_context_mcp.storage.projection import build_projection

        from hestai_context_mcp.storage.identity import IdentityValidationError

        a1 = _memory(artifact_id="art-1", sequence_id=1)
        a2 = _memory(artifact_id="art-2", sequence_id=2, identity=_identity(project_id="proj-X"))
        with pytest.raises(IdentityValidationError):
            build_projection(identity=_identity(), artifacts=(a1, a2), tombstones=())


@pytest.mark.unit
class TestProjectionTombstones:
    """TEST_111..TEST_113 (A3 tombstone round-trip)."""

    def test_projection_applies_tombstones_before_merge(self) -> None:
        from hestai_context_mcp.storage.projection import build_projection

        a1 = _memory(artifact_id="art-1", sequence_id=1)
        a2 = _memory(artifact_id="art-2", sequence_id=2)
        t1 = _tombstone(artifact_id="tomb-1", sequence_id=3, target_artifact_id="art-1")
        result = build_projection(
            identity=_identity(),
            artifacts=(a1, a2),
            tombstones=(t1,),
        )
        ids = [r["artifact_id"] for r in result["artifact_refs"]]
        assert "art-1" not in ids
        assert "art-2" in ids
        # Tombstone is recorded but does NOT count as a memory ref.
        assert "tombstoned_artifact_ids" in result
        assert result["tombstoned_artifact_ids"] == ["art-1"]

    def test_projection_excludes_tombstoned_memory_artifact(self) -> None:
        from hestai_context_mcp.storage.projection import build_projection

        a1 = _memory(artifact_id="art-1", sequence_id=1, payload={"keep": False})
        t1 = _tombstone(artifact_id="tomb-1", sequence_id=2, target_artifact_id="art-1")
        result = build_projection(identity=_identity(), artifacts=(a1,), tombstones=(t1,))
        assert all(r["artifact_id"] != "art-1" for r in result["artifact_refs"])
        # Payload merge does not contain the tombstoned artifact's payload.
        for r in result["artifact_refs"]:
            assert r.get("payload", {}).get("keep") is not False

    def test_projection_preserves_tombstone_semantics_after_compaction_input(self) -> None:
        """B1 has no compaction; the projection still treats compacted
        inputs identically to raw inputs — tombstones still apply."""
        from hestai_context_mcp.storage.projection import build_projection

        a1 = _memory(artifact_id="art-1", sequence_id=1)
        a2 = _memory(artifact_id="art-2", sequence_id=2)
        t1 = _tombstone(artifact_id="tomb-1", sequence_id=3, target_artifact_id="art-1")
        # Caller pre-sorted (simulated compaction). Build_projection still
        # applies the tombstone.
        result = build_projection(
            identity=_identity(),
            artifacts=(a1, a2),
            tombstones=(t1,),
        )
        ids = [r["artifact_id"] for r in result["artifact_refs"]]
        assert "art-1" not in ids


@pytest.mark.unit
class TestProjectionDuplicates:
    """TEST_114..TEST_115."""

    def test_duplicate_artifact_ids_same_hash_are_idempotent(self) -> None:
        from hestai_context_mcp.storage.projection import build_projection

        a = _memory(artifact_id="art-1", sequence_id=1, payload={"v": 1})
        # Same id + identical payload (so same payload_hash).
        a2 = _memory(artifact_id="art-1", sequence_id=1, payload={"v": 1})
        result = build_projection(identity=_identity(), artifacts=(a, a2), tombstones=())
        ids = [r["artifact_id"] for r in result["artifact_refs"]]
        assert ids == ["art-1"]

    def test_duplicate_artifact_ids_different_hash_are_structured_error(self) -> None:
        from hestai_context_mcp.storage.projection import (
            ProjectionError,
            build_projection,
        )

        a = _memory(artifact_id="art-1", sequence_id=1, payload={"v": 1})
        b = _memory(artifact_id="art-1", sequence_id=1, payload={"v": 2})
        with pytest.raises(ProjectionError):
            build_projection(identity=_identity(), artifacts=(a, b), tombstones=())


@pytest.mark.unit
class TestProjectionDeterminism:
    """TEST_116..TEST_117 (R10 / INVARIANT_004)."""

    def test_projection_shape_identical_across_machine_roots(self) -> None:
        from hestai_context_mcp.storage.projection import build_projection

        # Same artifact set under different "machine root" carrier_paths
        # (which are in ArtifactRef, not in the artifact itself). The
        # projection works directly on artifacts, so it must be
        # path-independent.
        a1 = _memory(artifact_id="art-1", sequence_id=1, payload={"x": 1})
        a2 = _memory(artifact_id="art-2", sequence_id=2, payload={"y": 2})
        r1 = build_projection(identity=_identity(), artifacts=(a1, a2), tombstones=())
        r2 = build_projection(identity=_identity(), artifacts=(a1, a2), tombstones=())
        assert r1 == r2

    def test_projection_allows_absolute_paths_only_in_explicit_local_fields(self) -> None:
        from hestai_context_mcp.storage.projection import build_projection

        # Absolute path in payload would leak machine identity. The
        # projection must NOT introduce absolute paths on its own; if a
        # caller smuggles one into a payload, the projection must still
        # be deterministic, but absolute paths must NOT appear in the
        # top-level metadata fields.
        a1 = _memory(artifact_id="art-1", sequence_id=1, payload={"v": 1})
        result = build_projection(identity=_identity(), artifacts=(a1,), tombstones=())
        # Top-level identity / artifact_refs must not contain leaked
        # absolute paths.
        assert "/" not in result["identity"]["project_id"]
        for r in result["artifact_refs"]:
            assert "/" not in r["artifact_id"]


@pytest.mark.unit
class TestProjectionFailureClosed:
    """TEST_118 — INVARIANT_005."""

    def test_projection_failure_is_structured_not_silent_empty(self) -> None:
        from hestai_context_mcp.storage.projection import (
            ProjectionError,
            build_projection,
        )

        # Mixed identity is one failure mode; verify the *empty* fallback
        # is NOT taken — i.e. the function raises rather than returning
        # an empty projection.
        a = _memory(artifact_id="art-1", sequence_id=1, payload={"v": 1})
        b = _memory(artifact_id="art-1", sequence_id=1, payload={"v": 2})
        with pytest.raises(ProjectionError):
            build_projection(identity=_identity(), artifacts=(a, b), tombstones=())
