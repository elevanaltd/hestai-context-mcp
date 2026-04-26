"""GROUP_008: SNAPSHOTS — RED-first tests for storage/snapshots.py.

Asserts the named-session snapshot contract per BUILD-PLAN
§TDD_TEST_LIST GROUP_008 (TEST_089..TEST_098) and ADR-0013 R5.

Binding rulings exercised here:
- R5: snapshot path is .hestai/state/portable/snapshots/{session_id}/
  context-projection.json. Snapshots are written by clock_in only;
  reads are pure (no mutation, no directory creation).
- R3: identity tuple is recorded in snapshot metadata; mismatched
  identities are refused at write time.
- R10: snapshot does not drift mid-session — a new artifact published
  after creation must not be reflected in the existing snapshot.
- TEST_094: session_id is path-traversal-safe (rejects .., / etc.).
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest


def _identity() -> Any:
    from hestai_context_mcp.storage.types import IdentityTuple

    return IdentityTuple(
        project_id="proj-A",
        workspace_id="wt-build",
        user_id="alice",
        state_schema_version=1,
        carrier_namespace="personal",
    )


def _ref(artifact_id: str = "art-1", sequence_id: int = 1) -> Any:
    from hestai_context_mcp.storage.types import ArtifactKind, ArtifactRef

    return ArtifactRef(
        artifact_id=artifact_id,
        identity=_identity(),
        artifact_kind=ArtifactKind.PORTABLE_MEMORY,
        sequence_id=sequence_id,
        created_at=datetime.now(UTC),
        payload_hash="0" * 64,
        carrier_path=f"/tmp/{artifact_id}.json",
    )


@pytest.mark.unit
class TestCreateSnapshot:
    """TEST_089..TEST_092."""

    def test_create_session_snapshot_writes_under_session_id(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.snapshots import create_session_snapshot

        sid = "11111111-1111-1111-1111-111111111111"
        path = create_session_snapshot(
            working_dir=tmp_path,
            session_id=sid,
            identity=_identity(),
            artifact_refs=(_ref("art-1", 1),),
            projection_payload={"hello": "world"},
        )
        expected = (
            tmp_path
            / ".hestai"
            / "state"
            / "portable"
            / "snapshots"
            / sid
            / "context-projection.json"
        )
        assert path == expected
        assert expected.exists()

    def test_snapshot_metadata_records_identity_tuple(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.snapshots import create_session_snapshot

        sid = "22222222-2222-2222-2222-222222222222"
        identity = _identity()
        create_session_snapshot(
            working_dir=tmp_path,
            session_id=sid,
            identity=identity,
            artifact_refs=(_ref(),),
            projection_payload={},
        )
        metadata_path = (
            tmp_path / ".hestai" / "state" / "portable" / "snapshots" / sid / "metadata.json"
        )
        assert metadata_path.exists()
        meta = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert meta["identity"]["project_id"] == identity.project_id
        assert meta["identity"]["workspace_id"] == identity.workspace_id
        assert meta["identity"]["user_id"] == identity.user_id
        assert meta["identity"]["state_schema_version"] == identity.state_schema_version
        assert meta["identity"]["carrier_namespace"] == identity.carrier_namespace

    def test_snapshot_metadata_records_artifact_refs(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.snapshots import create_session_snapshot

        sid = "33333333-3333-3333-3333-333333333333"
        refs = (_ref("art-1", 1), _ref("art-2", 2))
        create_session_snapshot(
            working_dir=tmp_path,
            session_id=sid,
            identity=_identity(),
            artifact_refs=refs,
            projection_payload={},
        )
        meta = json.loads(
            (
                tmp_path / ".hestai" / "state" / "portable" / "snapshots" / sid / "metadata.json"
            ).read_text(encoding="utf-8")
        )
        ids = [r["artifact_id"] for r in meta["artifact_refs"]]
        assert ids == ["art-1", "art-2"]

    def test_snapshot_metadata_records_created_at(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.snapshots import create_session_snapshot

        sid = "44444444-4444-4444-4444-444444444444"
        create_session_snapshot(
            working_dir=tmp_path,
            session_id=sid,
            identity=_identity(),
            artifact_refs=(),
            projection_payload={},
        )
        meta = json.loads(
            (
                tmp_path / ".hestai" / "state" / "portable" / "snapshots" / sid / "metadata.json"
            ).read_text(encoding="utf-8")
        )
        assert "created_at" in meta
        # Parses as a timezone-aware ISO string.
        dt = datetime.fromisoformat(meta["created_at"])
        assert dt.tzinfo is not None


@pytest.mark.unit
class TestReadSnapshot:
    """TEST_093 + TEST_094."""

    def test_read_session_snapshot_is_pure_read(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.snapshots import (
            create_session_snapshot,
            read_session_snapshot,
        )

        sid = "55555555-5555-5555-5555-555555555555"
        create_session_snapshot(
            working_dir=tmp_path,
            session_id=sid,
            identity=_identity(),
            artifact_refs=(),
            projection_payload={"k": "v"},
        )
        snap_dir = tmp_path / ".hestai" / "state" / "portable" / "snapshots" / sid
        before = {p: p.stat().st_mtime_ns for p in snap_dir.rglob("*")}
        time.sleep(0.005)
        result = read_session_snapshot(working_dir=tmp_path, session_id=sid)
        assert result["projection"] == {"k": "v"}
        after = {p: p.stat().st_mtime_ns for p in snap_dir.rglob("*")}
        for p in snap_dir.rglob("*"):
            assert before[p] == after[p], f"snapshot read modified {p}"

    def test_snapshot_read_rejects_path_traversal_session_id(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.snapshots import (
            SnapshotIdValidationError,
            read_session_snapshot,
        )

        for bad in ("../escape", "..", "/abs", "a/b", "a\\b", ""):
            with pytest.raises(SnapshotIdValidationError):
                read_session_snapshot(working_dir=tmp_path, session_id=bad)


@pytest.mark.unit
class TestSnapshotConstraints:
    """TEST_095..TEST_098."""

    def test_snapshot_creation_rejects_identity_mismatch(self, tmp_path: Path) -> None:
        """Artifact refs whose identity differs from the snapshot identity
        are refused — prevents cross-identity contamination."""
        from hestai_context_mcp.storage.snapshots import create_session_snapshot

        from hestai_context_mcp.storage.identity import IdentityValidationError
        from hestai_context_mcp.storage.types import (
            ArtifactKind,
            ArtifactRef,
            IdentityTuple,
        )

        bad_identity = IdentityTuple(
            project_id="proj-OTHER",
            workspace_id="wt-build",
            user_id="alice",
            state_schema_version=1,
            carrier_namespace="personal",
        )
        bad_ref = ArtifactRef(
            artifact_id="art-x",
            identity=bad_identity,
            artifact_kind=ArtifactKind.PORTABLE_MEMORY,
            sequence_id=1,
            created_at=datetime.now(UTC),
            payload_hash="0" * 64,
            carrier_path="/tmp/x.json",
        )
        with pytest.raises(IdentityValidationError):
            create_session_snapshot(
                working_dir=tmp_path,
                session_id="66666666-6666-6666-6666-666666666666",
                identity=_identity(),
                artifact_refs=(bad_ref,),
                projection_payload={},
            )

    def test_snapshot_classified_derived_projection(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.snapshots import SNAPSHOT_CLASSIFICATION

        from hestai_context_mcp.storage.types import StateClassification

        assert SNAPSHOT_CLASSIFICATION is StateClassification.DERIVED_PROJECTION

    def test_snapshot_does_not_change_when_new_artifact_is_published_after_creation(
        self, tmp_path: Path
    ) -> None:
        from hestai_context_mcp.storage.snapshots import (
            create_session_snapshot,
            read_session_snapshot,
        )

        sid = "77777777-7777-7777-7777-777777777777"
        create_session_snapshot(
            working_dir=tmp_path,
            session_id=sid,
            identity=_identity(),
            artifact_refs=(_ref("art-1", 1),),
            projection_payload={"only_artifact": "art-1"},
        )
        # Simulate a later publish — write an unrelated artifact under
        # portable/artifacts/. The snapshot must not pick it up.
        artifacts_dir = tmp_path / ".hestai" / "state" / "portable" / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        (artifacts_dir / "art-2.json").write_text(json.dumps({"artifact_id": "art-2"}))
        result = read_session_snapshot(working_dir=tmp_path, session_id=sid)
        assert result["projection"] == {"only_artifact": "art-1"}
        assert [r["artifact_id"] for r in result["metadata"]["artifact_refs"]] == ["art-1"]

    def test_snapshot_missing_returns_structured_not_found(self, tmp_path: Path) -> None:
        from hestai_context_mcp.storage.snapshots import (
            SnapshotNotFoundError,
            read_session_snapshot,
        )

        with pytest.raises(SnapshotNotFoundError):
            read_session_snapshot(
                working_dir=tmp_path,
                session_id="00000000-0000-0000-0000-000000000000",
            )
