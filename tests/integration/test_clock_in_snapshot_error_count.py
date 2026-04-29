"""Cubic rework cycle 3 — Finding (P2, clock_in.py:477).

RED-first test: when the snapshot try-block raises (whether at the
post-tombstone-id dict comprehension or at ``create_session_snapshot``),
``portable_state.artifact_count`` MUST report the post-tombstone count
authoritatively present in ``projection["artifact_refs"]`` — NOT the
pre-tombstone ``memory_refs`` count.

Cubic finding: the prior cubic #1 fix introduced a fallback
``if not accepted_refs: accepted_refs = tuple(memory_refs)`` which
overwrites the (correctly empty) post-tombstone refs with the
pre-tombstone ``memory_refs`` whenever the dict comprehension raises
(e.g., ``projection["artifact_refs"]`` malformed). This violates R8
(tombstoned artifacts excluded from snapshot/state) and PROD::I4
(STRUCTURED_RETURN_SHAPES — ``artifact_count`` must be a defined-field
post-tombstone value).

Correct fix (Option A): compute ``artifact_count`` from
``projection["artifact_refs"]`` directly, independent of snapshot
success/failure. The post-tombstone count is the projection's authority,
not ``accepted_refs``.

Setup: 3 memory artifacts seeded; 1 tombstoned. The PROJECTION'S
authoritative post-tombstone count is 2. We force the snapshot try-block
to raise via a malformed projection so the dict comprehension at
``clock_in.py:460`` triggers KeyError (and so ``accepted_refs`` stays
empty, exposing the buggy fallback). The test asserts
``artifact_count == 2`` (post-tombstone), NOT 3 (pre-tombstone).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


def _identity_dict() -> dict[str, Any]:
    return {
        "project_id": "proj-A",
        "workspace_id": "wt-build",
        "user_id": "alice",
        "state_schema_version": 1,
        "carrier_namespace": "personal",
    }


def _write_identity_config(working_dir: Path) -> None:
    cfg_path = working_dir / ".hestai" / "state" / "portable" / "identity.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(_identity_dict()))


def _hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _seed_artifact(working_dir: Path, *, artifact_id: str, sequence_id: int) -> None:
    """Seed a portable artifact via LocalFilesystemAdapter so the format is exact."""
    from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter
    from hestai_context_mcp.storage.provenance import build_provenance_or_raise
    from hestai_context_mcp.storage.types import (
        ArtifactKind,
        ArtifactRef,
        IdentityTuple,
        PortableMemoryArtifact,
        WritePrecondition,
    )

    identity = IdentityTuple(**_identity_dict())
    payload = {"id": artifact_id, "seq": sequence_id}
    artifact = PortableMemoryArtifact(
        artifact_id=artifact_id,
        artifact_kind=ArtifactKind.PORTABLE_MEMORY,
        identity=identity,
        schema_version=1,
        producer_version="1",
        minimum_reader_version=1,
        created_at=datetime.now(UTC),
        sequence_id=sequence_id,
        parent_ids=(),
        redaction_provenance=build_provenance_or_raise(
            input_text="i", output_text="o", redacted_credential_categories=()
        ),
        classification_label="PORTABLE_MEMORY",
        payload_hash=_hash_payload(payload),
        payload=payload,
    )
    ref = ArtifactRef(
        artifact_id=artifact.artifact_id,
        identity=artifact.identity,
        artifact_kind=artifact.artifact_kind,
        sequence_id=artifact.sequence_id,
        created_at=artifact.created_at,
        payload_hash=artifact.payload_hash,
        carrier_path="",
    )
    LocalFilesystemAdapter(working_dir=working_dir).write_artifact(
        ref, artifact, WritePrecondition()
    )


def _seed_tombstone(working_dir: Path, *, target_artifact_id: str, sequence_id: int) -> None:
    from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter
    from hestai_context_mcp.storage.types import (
        ArtifactKind,
        ArtifactRef,
        IdentityTuple,
        TombstoneArtifact,
        WritePrecondition,
    )

    identity = IdentityTuple(**_identity_dict())
    tomb = TombstoneArtifact(
        artifact_id=f"tomb-{target_artifact_id}",
        artifact_kind=ArtifactKind.TOMBSTONE,
        identity=identity,
        schema_version=1,
        producer_version="1",
        minimum_reader_version=1,
        created_at=datetime.now(UTC),
        sequence_id=sequence_id,
        parent_ids=(target_artifact_id,),
        target_artifact_id=target_artifact_id,
        reason="user-revoked",
        publisher_identity=identity,
        redaction_provenance=None,
        classification_label="PORTABLE_MEMORY",
        payload_hash=hashlib.sha256(target_artifact_id.encode()).hexdigest(),
    )
    ref = ArtifactRef(
        artifact_id=tomb.artifact_id,
        identity=tomb.identity,
        artifact_kind=tomb.artifact_kind,
        sequence_id=tomb.sequence_id,
        created_at=tomb.created_at,
        payload_hash=tomb.payload_hash,
        carrier_path="",
    )
    LocalFilesystemAdapter(working_dir=working_dir).write_tombstone(ref, tomb, WritePrecondition())


@pytest.mark.integration
class TestClockInArtifactCountPostTombstoneOnSnapshotError:
    """Cubic P2 #2: artifact_count is post-tombstone authoritative regardless
    of snapshot try-block outcome."""

    def test_artifact_count_is_post_tombstone_when_snapshot_block_raises(
        self, tmp_path: Path
    ) -> None:
        """3 memory artifacts, 1 tombstoned -> projection has 2 artifact_refs.

        We force the snapshot try-block to raise inside the dict
        comprehension (via a malformed projection["artifact_refs"]) so
        ``accepted_refs`` remains empty — exposing the buggy fallback. The
        contract: ``portable_state.artifact_count`` MUST be 2 (the
        post-tombstone projection count), NOT 3 (the pre-tombstone
        memory_refs count).
        """
        from hestai_context_mcp.tools.clock_in import clock_in

        _write_identity_config(tmp_path)
        # 3 memory artifacts; tombstone the second so projection has 2.
        _seed_artifact(tmp_path, artifact_id="art-A", sequence_id=1)
        _seed_artifact(tmp_path, artifact_id="art-B", sequence_id=2)
        _seed_artifact(tmp_path, artifact_id="art-C", sequence_id=3)
        _seed_tombstone(tmp_path, target_artifact_id="art-B", sequence_id=4)

        # Real build_projection (we still want the genuine projection to
        # construct correctly) — but we want the dict comprehension at
        # clock_in.py:460 to raise. The comprehension iterates
        # projection["artifact_refs"] and indexes r["artifact_id"]. We
        # therefore wrap build_projection: keep the genuine
        # tombstoned_artifact_ids + identity + length-2 artifact_refs, but
        # replace each element with a dict missing the "artifact_id" key so
        # the comprehension triggers KeyError. ``len(artifact_refs)`` is
        # still 2 — the authoritative post-tombstone count Option A reads.
        from hestai_context_mcp.storage import projection as _projection_mod

        real_build = _projection_mod.build_projection

        def _build_projection_with_malformed_refs(*args: Any, **kwargs: Any) -> dict[str, Any]:
            real = real_build(*args, **kwargs)
            # Same length (post-tombstone count is 2), but each entry lacks
            # "artifact_id" so the dict comprehension raises KeyError.
            real["artifact_refs"] = [
                {"sequence_id": entry["sequence_id"]} for entry in real["artifact_refs"]
            ]
            return real

        with (
            patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main"),
            patch(
                "hestai_context_mcp.storage.projection.build_projection",
                side_effect=_build_projection_with_malformed_refs,
            ),
        ):
            result = clock_in(role="impl", working_dir=str(tmp_path), focus="task")

        portable_state = result["portable_state"]

        # Post-tombstone count is 2 (NOT pre-tombstone 3). This is the
        # core regression assertion for cubic P2 #2.
        assert portable_state["artifact_count"] == 2, (
            "artifact_count must reflect post-tombstone projection count (2), "
            "not pre-tombstone memory_refs count (3); cubic P2 fallback bug"
        )

        # Snapshot write did not succeed (the comprehension raised before
        # snapshot creation), so error is structured and path is None.
        snapshot_error = portable_state["snapshot_error"]
        assert snapshot_error is not None
        assert snapshot_error["code"] == "snapshot_write_failed"
        assert portable_state["snapshot_path"] is None

    def test_artifact_count_is_post_tombstone_when_snapshot_write_raises(
        self, tmp_path: Path
    ) -> None:
        """Companion: when ``create_session_snapshot`` itself raises (after
        the comprehension already populated ``accepted_refs`` correctly),
        the count is still post-tombstone (2). Locks the contract along
        the second branch of the try-block. Per cubic instruction wording.
        """
        from hestai_context_mcp.tools.clock_in import clock_in

        _write_identity_config(tmp_path)
        _seed_artifact(tmp_path, artifact_id="art-A", sequence_id=1)
        _seed_artifact(tmp_path, artifact_id="art-B", sequence_id=2)
        _seed_artifact(tmp_path, artifact_id="art-C", sequence_id=3)
        _seed_tombstone(tmp_path, target_artifact_id="art-B", sequence_id=4)

        def _raise(*args: Any, **kwargs: Any) -> Any:
            raise OSError("simulated disk-full on snapshot write")

        with (
            patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main"),
            patch(
                "hestai_context_mcp.storage.snapshots.create_session_snapshot",
                side_effect=_raise,
            ),
        ):
            result = clock_in(role="impl", working_dir=str(tmp_path), focus="task")

        portable_state = result["portable_state"]
        assert portable_state["artifact_count"] == 2
        snapshot_error = portable_state["snapshot_error"]
        assert snapshot_error is not None
        assert snapshot_error["code"] == "snapshot_write_failed"
        assert portable_state["snapshot_path"] is None
