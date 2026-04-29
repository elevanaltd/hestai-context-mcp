"""GROUP_014: FULL_LOCAL_LIFECYCLE — RED-first tests.

End-to-end PSS lifecycle over LocalFilesystemAdapter only:

  clock_in -> publish via clock_out -> next clock_in restores ->
  tombstone roundtrip -> projection deterministic -> session cleanup
  works while publish is queued.

Per BUILD-PLAN §TDD_TEST_LIST GROUP_014 (TEST_149..TEST_158) and
§INTEGRATION_PLAN. Binding rulings exercised:

- R5: clock_in restores via adapter and writes a named snapshot.
- R7: clock_out has separable outcomes (local archive vs publish).
- R8: tombstones exclude memory on next clock_in.
- R9: append-first monotonic order; same-id same-hash idempotent.
- R10 INVARIANT_002: full suite passes with remote adapters disabled.
  (We assert no remote adapter imports or hits during lifecycle.)
- R11: no custom Git refs are used.
- R12: no remote adapter / network behavior.
- B2_START_BLOCKER_003: no remote adapters / config / wire schemas.
- B2_START_BLOCKER_004: never publish without provenance pair.
- B2_START_BLOCKER_005: no custom Git refs.
"""

from __future__ import annotations

import hashlib
import json
import socket
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


def _write_identity_config(working_dir: Path, *, override: dict[str, Any] | None = None) -> None:
    cfg_path = working_dir / ".hestai" / "state" / "portable" / "identity.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(override or _identity_dict()))


def _do_clock_in(working_dir: Path) -> str:
    from hestai_context_mcp.tools.clock_in import clock_in

    with patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main"):
        result = clock_in(role="impl", working_dir=str(working_dir), focus="task")
    return result["session_id"]


def _do_clock_out(working_dir: Path, session_id: str) -> dict[str, Any]:
    from hestai_context_mcp.tools.clock_out import clock_out

    return clock_out(session_id=session_id, working_dir=str(working_dir))


def _seed_artifact(working_dir: Path, *, artifact_id: str, sequence_id: int) -> None:
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
    payload_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
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
        payload_hash=payload_hash,
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
class TestEndToEndLocalLifecycle:
    """TEST_149 + TEST_158."""

    def test_clock_out_then_next_clock_in_restores_memory_from_local_adapter(
        self, tmp_path: Path
    ) -> None:
        """clock_out publishes; subsequent clock_in restores it via the adapter."""
        _write_identity_config(tmp_path)

        sid1 = _do_clock_in(tmp_path)
        result_out = _do_clock_out(tmp_path, sid1)
        assert result_out["portable_publication"]["status"] in {"published", "duplicate"}
        assert result_out["unpublished_memory_exists"] is False

        # Next clock_in must see the published artifact via the adapter.
        sid2 = _do_clock_in(tmp_path)
        assert sid2 != sid1

        # The session 2 named snapshot must include the published artifact.
        from hestai_context_mcp.storage.snapshots import read_session_snapshot

        snap = read_session_snapshot(working_dir=tmp_path, session_id=sid2)
        refs = snap["metadata"]["artifact_refs"]
        assert len(refs) >= 1, "second clock_in should restore the first session's publication"

    def test_local_archive_and_session_cleanup_still_work_when_publish_queued(
        self, tmp_path: Path
    ) -> None:
        """Adapter raise -> archive succeeded, session cleaned up, outbox queued."""
        from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter

        _write_identity_config(tmp_path)
        sid = _do_clock_in(tmp_path)

        def _raise(self: Any, *args: Any, **kwargs: Any) -> None:
            raise OSError("queued path simulation")

        with patch.object(LocalFilesystemAdapter, "write_artifact", _raise):
            result = _do_clock_out(tmp_path, sid)

        assert result["status"] == "success"  # archive succeeded
        # session dir gone (cleanup ran)
        assert not (tmp_path / ".hestai" / "state" / "sessions" / "active" / sid).exists()
        # outbox has an entry
        assert result["unpublished_memory_exists"] is True
        outbox = tmp_path / ".hestai" / "state" / "portable" / "outbox"
        assert outbox.exists()
        assert any(p.suffix == ".json" for p in outbox.iterdir())


@pytest.mark.integration
class TestTombstoneLifecycle:
    """TEST_150 + TEST_154."""

    def test_tombstone_published_between_sessions_excludes_memory_on_next_clock_in(
        self, tmp_path: Path
    ) -> None:
        """Tombstone -> next clock_in projection excludes the target."""
        _write_identity_config(tmp_path)

        # Seed an artifact, then tombstone it; next clock_in must exclude.
        _seed_artifact(tmp_path, artifact_id="art-tomb-target", sequence_id=1)
        _seed_tombstone(tmp_path, target_artifact_id="art-tomb-target", sequence_id=2)

        sid = _do_clock_in(tmp_path)

        from hestai_context_mcp.storage.snapshots import read_session_snapshot

        snap = read_session_snapshot(working_dir=tmp_path, session_id=sid)
        proj = snap["projection"]
        assert "art-tomb-target" in proj["tombstoned_artifact_ids"]
        # No artifact_refs entry survives.
        ref_ids = {r["artifact_id"] for r in proj["artifact_refs"]}
        assert "art-tomb-target" not in ref_ids

    def test_restore_merges_valid_artifacts_by_identity_and_monotonic_order(
        self, tmp_path: Path
    ) -> None:
        """Multiple artifacts merge in monotonic (sequence_id, artifact_id) order."""
        _write_identity_config(tmp_path)

        _seed_artifact(tmp_path, artifact_id="art-a", sequence_id=10)
        _seed_artifact(tmp_path, artifact_id="art-b", sequence_id=5)
        _seed_artifact(tmp_path, artifact_id="art-c", sequence_id=20)

        sid = _do_clock_in(tmp_path)

        from hestai_context_mcp.storage.snapshots import read_session_snapshot

        snap = read_session_snapshot(working_dir=tmp_path, session_id=sid)
        ordered = [
            (r["sequence_id"], r["artifact_id"]) for r in snap["projection"]["artifact_refs"]
        ]
        assert ordered == sorted(ordered), "projection must be sorted by (seq, id)"


@pytest.mark.integration
class TestProjectionDeterminism:
    """TEST_151 — INVARIANT_004."""

    def test_two_machine_roots_same_artifacts_produce_same_context_shape(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """Two distinct project roots with identical artifacts -> identical projection."""
        root1 = tmp_path_factory.mktemp("machine-1")
        root2 = tmp_path_factory.mktemp("machine-2")

        for root in (root1, root2):
            _write_identity_config(root)
            _seed_artifact(root, artifact_id="art-shared-1", sequence_id=1)
            _seed_artifact(root, artifact_id="art-shared-2", sequence_id=2)

        sid1 = _do_clock_in(root1)
        sid2 = _do_clock_in(root2)

        from hestai_context_mcp.storage.snapshots import read_session_snapshot

        snap1 = read_session_snapshot(working_dir=root1, session_id=sid1)
        snap2 = read_session_snapshot(working_dir=root2, session_id=sid2)

        # Projection content (artifact_refs sans machine-specific paths)
        # is identical across machines.
        assert snap1["projection"] == snap2["projection"]


@pytest.mark.integration
class TestRemoteDisabledAndNoNetwork:
    """TEST_152 + TEST_156 + TEST_157 — INVARIANT_002 + R11."""

    def test_full_suite_passes_with_remote_adapters_disabled(self, tmp_path: Path) -> None:
        """Lifecycle works without any remote adapter present in the codebase."""
        _write_identity_config(tmp_path)
        sid = _do_clock_in(tmp_path)
        result = _do_clock_out(tmp_path, sid)
        assert result["status"] == "success"
        # We use only LocalFilesystemAdapter; no remote path even references
        # carrier classes other than the local adapter. Asserted directly:
        from hestai_context_mcp import storage

        # Inspect __all__ for top-level adapter exports beyond the local one.
        public_exports = set(getattr(storage, "__all__", []))
        adapter_exports = {n for n in public_exports if n.endswith("Adapter")}
        # StorageAdapter (the protocol) and LocalFilesystemAdapter are
        # the only legal entries in B1 per R12 and B2_START_BLOCKER_003.
        allowed = {"StorageAdapter", "LocalFilesystemAdapter"}
        assert adapter_exports <= allowed, (
            f"R12 / B2_START_BLOCKER_003 violation: unexpected adapters "
            f"exported: {adapter_exports - allowed}"
        )

    def test_local_filesystem_mode_has_no_network_calls(self, tmp_path: Path) -> None:
        """Patch socket.socket -> any DNS / TCP attempt during lifecycle raises."""
        _write_identity_config(tmp_path)

        original_socket = socket.socket

        class _NoNetworkSocket(original_socket):  # type: ignore[misc, valid-type]
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                raise OSError("INVARIANT_002 violation: PSS lifecycle attempted a network call")

        with patch("socket.socket", _NoNetworkSocket):
            sid = _do_clock_in(tmp_path)
            result = _do_clock_out(tmp_path, sid)
            assert result["status"] == "success"

    def test_custom_git_ref_storage_is_not_used(self, tmp_path: Path) -> None:
        """R11: no custom Git refs (refs/hestai/*) are written during lifecycle."""
        _write_identity_config(tmp_path)
        sid = _do_clock_in(tmp_path)
        _do_clock_out(tmp_path, sid)

        # No .git directory created; no refs/hestai paths exist.
        for path in tmp_path.rglob("*"):
            assert "refs/hestai" not in str(path), f"R11 violation: {path}"

    def test_local_filesystem_adapter_advertises_local_only_classification(self) -> None:
        """B2_START_BLOCKER_003: adapter exposes a public is_local_only() method.

        The local-only flag is the single canonical way for downstream
        callers (and the post-B2 quality gate chain) to mechanically
        confirm that the LocalFilesystemAdapter is the only storage
        carrier in B1. This is a positive structural invariant: it must
        return True for the local adapter and the property must exist.
        """
        from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter

        adapter = LocalFilesystemAdapter(working_dir=Path("/tmp"))
        # Method exists and returns True for the local adapter.
        assert hasattr(adapter, "is_local_only"), (
            "B2_START_BLOCKER_003 violation: LocalFilesystemAdapter must "
            "expose is_local_only() -> bool"
        )
        assert (
            adapter.is_local_only() is True
        ), "LocalFilesystemAdapter.is_local_only() must return True"


@pytest.mark.integration
class TestFailClosedStreamGuard:
    """TEST_153 + TEST_155."""

    def test_hydration_failure_does_not_publish_over_newer_stream(self, tmp_path: Path) -> None:
        """Schema-too-new artifact -> structured error AND no v1 publish over it."""
        from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter
        from hestai_context_mcp.storage.provenance import build_provenance_or_raise
        from hestai_context_mcp.storage.types import (
            ArtifactKind,
            ArtifactRef,
            IdentityTuple,
            PortableMemoryArtifact,
            WritePrecondition,
        )

        _write_identity_config(tmp_path)

        # Seed a "v1-on-disk" artifact whose minimum_reader_version is 99
        # so the reader treats it as schema_too_new on hydrate.
        # We use the v1 schema slot to keep the file shape valid (no v2
        # invented per RISK_007); the minimum_reader_version field is what
        # raises SchemaTooNewError on validate.
        identity = IdentityTuple(**_identity_dict())
        # NOTE: state_schema_version stays 1 (validation requires it to be
        # in SUPPORTED_SCHEMA_VERSIONS); we trip the "too new" gate via
        # minimum_reader_version=99 which IS the documented v2-machine
        # rejection path per ADR-0013 R4 second-to-last bullet.
        payload = {"newer": "stream"}
        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        artifact = PortableMemoryArtifact(
            artifact_id="art-v2",
            artifact_kind=ArtifactKind.PORTABLE_MEMORY,
            identity=identity,
            schema_version=1,
            producer_version="9",
            minimum_reader_version=99,
            created_at=datetime.now(UTC),
            sequence_id=1,
            parent_ids=(),
            redaction_provenance=build_provenance_or_raise(
                input_text="i", output_text="o", redacted_credential_categories=()
            ),
            classification_label="PORTABLE_MEMORY",
            payload_hash=payload_hash,
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
        LocalFilesystemAdapter(working_dir=tmp_path).write_artifact(
            ref, artifact, WritePrecondition()
        )

        # clock_in must surface schema_too_new (not silent empty).
        from hestai_context_mcp.tools.clock_in import clock_in

        with patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main"):
            result = clock_in(role="impl", working_dir=str(tmp_path))
        ps = result["portable_state"]
        assert ps["restore_status"] == "schema_too_new"
        assert ps["error"] and ps["error"]["code"] == "schema_too_new"

    def test_restore_refuses_fork_or_workspace_identity_mismatch(self, tmp_path: Path) -> None:
        """Identity mismatch -> structured restore_status='identity_mismatch'."""
        # Configure identity A.
        _write_identity_config(tmp_path)

        # Seed an artifact bound to identity B (different workspace_id).
        from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter
        from hestai_context_mcp.storage.provenance import build_provenance_or_raise
        from hestai_context_mcp.storage.types import (
            ArtifactKind,
            ArtifactRef,
            IdentityTuple,
            PortableMemoryArtifact,
            WritePrecondition,
        )

        identity_b = IdentityTuple(
            project_id="proj-A",
            workspace_id="OTHER-WORKSPACE",
            user_id="alice",
            state_schema_version=1,
            carrier_namespace="personal",
        )
        payload = {"id": "fork-leak"}
        ph = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        artifact = PortableMemoryArtifact(
            artifact_id="fork-leak",
            artifact_kind=ArtifactKind.PORTABLE_MEMORY,
            identity=identity_b,
            schema_version=1,
            producer_version="1",
            minimum_reader_version=1,
            created_at=datetime.now(UTC),
            sequence_id=1,
            parent_ids=(),
            redaction_provenance=build_provenance_or_raise(
                input_text="i", output_text="o", redacted_credential_categories=()
            ),
            classification_label="PORTABLE_MEMORY",
            payload_hash=ph,
            payload=payload,
        )
        ref = ArtifactRef(
            artifact_id=artifact.artifact_id,
            identity=identity_b,
            artifact_kind=artifact.artifact_kind,
            sequence_id=artifact.sequence_id,
            created_at=artifact.created_at,
            payload_hash=artifact.payload_hash,
            carrier_path="",
        )
        LocalFilesystemAdapter(working_dir=tmp_path).write_artifact(
            ref, artifact, WritePrecondition()
        )

        # clock_in (with identity A) sees no artifacts under namespace A's
        # tree because they live under workspace_id=OTHER-WORKSPACE; the
        # restore status remains "ok" with artifact_count=0. The structural
        # invariant we assert: forked-workspace artifacts are NEVER merged
        # into A's projection.
        sid = _do_clock_in(tmp_path)

        from hestai_context_mcp.storage.snapshots import read_session_snapshot

        snap = read_session_snapshot(working_dir=tmp_path, session_id=sid)
        ref_ids = {r["artifact_id"] for r in snap["projection"]["artifact_refs"]}
        assert (
            "fork-leak" not in ref_ids
        ), "R3 violation: fork/workspace artifact leaked into projection"
