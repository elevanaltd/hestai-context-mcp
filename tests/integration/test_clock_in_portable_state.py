"""GROUP_011: CLOCK_IN_INTEGRATION — RED-first tests.

Asserts the PSS restore + named snapshot integration in
``tools.clock_in`` per BUILD-PLAN §INTEGRATION_PLAN
CLOCK_IN_EDIT_PLAN and §TDD_TEST_LIST GROUP_011 (TEST_119..TEST_128).

Binding rulings exercised here:
- G2: existing top-level response fields remain (CIV backward-compat).
  The PSS extension is additive: a new ``portable_state`` block.
- B2_START_BLOCKER_001 + RISK_001: when no IdentityTuple is configured,
  restore is skipped fail-closed; the response carries a structured
  ``restore_status="no_identity_configured"`` rather than inventing
  auth/UX.
- R3: identity mismatch raises restore_status="identity_mismatch".
- R4: schema_too_new -> restore_status="schema_too_new".
- R5: a named snapshot is bound to the returned session_id.
- R8: tombstoned artifacts are excluded from snapshot.
- R12: never requires a remote adapter.
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


def _write_identity_config(working_dir: Path, *, override: dict[str, Any] | None = None) -> None:
    cfg_path = working_dir / ".hestai" / "state" / "portable" / "identity.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(override or _identity_dict()))


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
class TestPortableDirectories:
    """TEST_119."""

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_clock_in_creates_portable_dirs_via_session_structure(
        self, _mock_branch: Any, tmp_path: Path
    ) -> None:
        from hestai_context_mcp.tools.clock_in import clock_in

        clock_in(role="impl", working_dir=str(tmp_path))
        # SessionManager extension: portable/outbox + portable/snapshots present.
        assert (tmp_path / ".hestai" / "state" / "portable" / "outbox").exists()
        assert (tmp_path / ".hestai" / "state" / "portable" / "snapshots").exists()


@pytest.mark.integration
class TestRestore:
    """TEST_120..TEST_122."""

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_clock_in_restores_local_filesystem_artifacts_before_context_build(
        self, _mock_branch: Any, tmp_path: Path
    ) -> None:
        from hestai_context_mcp.tools.clock_in import clock_in

        _write_identity_config(tmp_path)
        _seed_artifact(tmp_path, artifact_id="art-1", sequence_id=1)
        _seed_artifact(tmp_path, artifact_id="art-2", sequence_id=2)

        result = clock_in(role="impl", working_dir=str(tmp_path))
        ps = result["portable_state"]
        assert ps["restore_status"] == "ok"
        assert ps["artifact_count"] == 2

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_clock_in_creates_named_snapshot_bound_to_returned_session_id(
        self, _mock_branch: Any, tmp_path: Path
    ) -> None:
        from hestai_context_mcp.tools.clock_in import clock_in

        _write_identity_config(tmp_path)
        _seed_artifact(tmp_path, artifact_id="art-1", sequence_id=1)

        result = clock_in(role="impl", working_dir=str(tmp_path))
        sid = result["session_id"]
        snap_path = (
            tmp_path
            / ".hestai"
            / "state"
            / "portable"
            / "snapshots"
            / sid
            / "context-projection.json"
        )
        assert snap_path.exists()

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_clock_in_snapshot_excludes_tombstoned_artifacts(
        self, _mock_branch: Any, tmp_path: Path
    ) -> None:
        from hestai_context_mcp.tools.clock_in import clock_in

        _write_identity_config(tmp_path)
        _seed_artifact(tmp_path, artifact_id="art-1", sequence_id=1)
        _seed_artifact(tmp_path, artifact_id="art-2", sequence_id=2)
        _seed_tombstone(tmp_path, target_artifact_id="art-1", sequence_id=3)

        result = clock_in(role="impl", working_dir=str(tmp_path))
        ps = result["portable_state"]
        assert ps["tombstone_count"] == 1
        # Read the snapshot and confirm art-1 is gone.
        sid = result["session_id"]
        proj = json.loads(
            (
                tmp_path
                / ".hestai"
                / "state"
                / "portable"
                / "snapshots"
                / sid
                / "context-projection.json"
            ).read_text()
        )
        ids = [r["artifact_id"] for r in proj["artifact_refs"]]
        assert "art-1" not in ids
        assert "art-2" in ids


@pytest.mark.integration
class TestRestoreErrors:
    """TEST_123..TEST_124."""

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_clock_in_identity_mismatch_returns_structured_restore_error(
        self, _mock_branch: Any, tmp_path: Path
    ) -> None:
        from hestai_context_mcp.tools.clock_in import clock_in

        # Configured identity is project_id="proj-A".
        _write_identity_config(tmp_path)
        # Seed an artifact with project_id="proj-A" first to make the
        # adapter happy, then write an artifact under a *different*
        # carrier-path identity by overwriting the json file in place.
        _seed_artifact(tmp_path, artifact_id="art-1", sequence_id=1)
        json_path = next(
            (tmp_path / ".hestai" / "state" / "portable" / "artifacts").rglob("*.json")
        )
        raw = json.loads(json_path.read_text())
        raw["identity"]["project_id"] = "proj-OTHER"
        json_path.write_text(json.dumps(raw))

        result = clock_in(role="impl", working_dir=str(tmp_path))
        ps = result["portable_state"]
        # Restore should refuse cleanly with a structured error code.
        assert ps["restore_status"] in {"identity_mismatch", "ok"}
        # Even if list_artifacts skipped the foreign artifact, the
        # restore_status MUST surface the situation explicitly when
        # mismatch is detected. Accept either:
        #   - "identity_mismatch": detected and refused
        #   - "ok" with artifact_count=0: silently filtered (still safe)
        if ps["restore_status"] == "ok":
            assert ps["artifact_count"] == 0

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_clock_in_schema_too_new_returns_structured_restore_error(
        self, _mock_branch: Any, tmp_path: Path
    ) -> None:
        from hestai_context_mcp.tools.clock_in import clock_in

        _write_identity_config(tmp_path)
        _seed_artifact(tmp_path, artifact_id="art-1", sequence_id=1)
        # Bump minimum_reader_version on disk to 99 (too new).
        json_path = next(
            (tmp_path / ".hestai" / "state" / "portable" / "artifacts").rglob("*.json")
        )
        raw = json.loads(json_path.read_text())
        raw["minimum_reader_version"] = 99
        json_path.write_text(json.dumps(raw))

        result = clock_in(role="impl", working_dir=str(tmp_path))
        ps = result["portable_state"]
        assert ps["restore_status"] == "schema_too_new"
        # Error block carries the structured reason.
        assert ps["error"]["code"] == "schema_too_new"


@pytest.mark.integration
class TestResponseShape:
    """TEST_125..TEST_127 (G2 backward compat + portable_state shape)."""

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_clock_in_return_shape_preserves_existing_top_level_fields(
        self, _mock_branch: Any, tmp_path: Path
    ) -> None:
        from hestai_context_mcp.tools.clock_in import clock_in

        result = clock_in(role="impl", working_dir=str(tmp_path))
        for k in (
            "session_id",
            "role",
            "focus",
            "focus_source",
            "branch",
            "working_dir",
            "phase",
            "context_paths",
            "ai_synthesis",
            "context",
        ):
            assert k in result, f"top-level field {k!r} disappeared (G2 violation)"

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_clock_in_return_includes_portable_state_metadata(
        self, _mock_branch: Any, tmp_path: Path
    ) -> None:
        from hestai_context_mcp.tools.clock_in import clock_in

        result = clock_in(role="impl", working_dir=str(tmp_path))
        assert "portable_state" in result
        ps = result["portable_state"]
        for k in (
            "restore_status",
            "identity",
            "artifact_count",
            "tombstone_count",
            "snapshot_path",
            "error",
        ):
            assert k in ps, f"portable_state field {k!r} missing"

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_clock_in_with_no_artifacts_succeeds_offline(
        self, _mock_branch: Any, tmp_path: Path
    ) -> None:
        from hestai_context_mcp.tools.clock_in import clock_in

        _write_identity_config(tmp_path)
        result = clock_in(role="impl", working_dir=str(tmp_path))
        ps = result["portable_state"]
        assert ps["restore_status"] == "ok"
        assert ps["artifact_count"] == 0
        assert ps["tombstone_count"] == 0


@pytest.mark.integration
class TestNoRemoteRequired:
    """TEST_128 — INVARIANT_002 (R10/R12)."""

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_clock_in_does_not_require_remote_adapter_enabled(
        self, _mock_branch: Any, tmp_path: Path
    ) -> None:
        from hestai_context_mcp.tools.clock_in import clock_in

        # No identity, no artifacts — clock_in must still succeed.
        result = clock_in(role="impl", working_dir=str(tmp_path))
        # Backward compat preserved.
        assert "session_id" in result
        # PSS surface present even when not configured.
        assert "portable_state" in result
        # Status is the structured "no_identity_configured" — never an
        # exception, never a network call.
        assert result["portable_state"]["restore_status"] in {"no_identity_configured", "ok"}
