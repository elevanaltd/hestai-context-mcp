"""GROUP_012: CLOCK_OUT_INTEGRATION — RED-first tests.

Asserts the PSS publish + outbox integration in ``tools.clock_out`` per
BUILD-PLAN §INTEGRATION_PLAN CLOCK_OUT_EDIT_PLAN and §TDD_TEST_LIST
GROUP_012 (TEST_129..TEST_138).

Binding rulings exercised here:

- A2 (CIV) skip-publish must write outbox status record with reason
  code (no silent skip).
- CE RISK_010 fail-closed publish: no publish without redacted
  input/output provenance pair.
- CE RISK_005 v1 payload keys = {session_id, role, focus, archive_path,
  decisions, blockers, learnings, description}.
- R7: clock_out has two separable outcomes (local archive vs portable
  publish); local must succeed independently from publish.
- R9: duplicate publish is idempotent (same payload_hash).
- B2_START_BLOCKER_004: never publish without complete provenance.
"""

from __future__ import annotations

import json
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


def _write_session(working_dir: Path, session_id: str, *, role: str, focus: str) -> Path:
    """Seed an active session directory for clock_out to consume."""
    active = working_dir / ".hestai" / "state" / "sessions" / "active" / session_id
    active.mkdir(parents=True, exist_ok=True)
    session_data = {
        "session_id": session_id,
        "role": role,
        "focus": focus,
        "branch": "main",
        "transcript_path": None,
        "created_at": "2026-04-26T00:00:00+00:00",
    }
    (active / "session.json").write_text(json.dumps(session_data))
    return active


def _clock_in_then_session(
    working_dir: Path, *, role: str = "impl", focus: str | None = "task"
) -> str:
    """Run clock_in (with identity configured) so that a snapshot exists.

    Returns the created session_id so clock_out can target it.
    """
    from hestai_context_mcp.tools.clock_in import clock_in

    with patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main"):
        result = clock_in(role=role, working_dir=str(working_dir), focus=focus)
    return result["session_id"]


@pytest.mark.integration
class TestClockOutLocalArchiveSeparable:
    """TEST_129 + TEST_158."""

    def test_clock_out_local_archive_success_independent_from_portable_publish(
        self, tmp_path: Path
    ) -> None:
        """Local archive completes regardless of publish outcome."""
        from hestai_context_mcp.tools.clock_out import clock_out

        # No identity configured -> publish is skipped, but archive flow runs.
        sid = "session-localonly"
        _write_session(tmp_path, sid, role="impl", focus="task")

        result = clock_out(session_id=sid, working_dir=str(tmp_path))

        assert result["status"] == "success"
        # Portable publication block exists and is structured even without identity.
        assert "portable_publication" in result
        assert "unpublished_memory_exists" in result
        assert isinstance(result["unpublished_memory_exists"], bool)


@pytest.mark.integration
class TestClockOutArtifactBuild:
    """TEST_130 + TEST_136 + TEST_137."""

    def test_clock_out_builds_artifact_after_redaction_success(self, tmp_path: Path) -> None:
        """When identity is set + provenance is complete, clock_out publishes."""
        from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter
        from hestai_context_mcp.storage.types import IdentityTuple, PortableNamespace
        from hestai_context_mcp.tools.clock_out import clock_out

        _write_identity_config(tmp_path)
        sid = _clock_in_then_session(tmp_path)
        # clock_in creates an active session via SessionManager; reuse sid.

        result = clock_out(session_id=sid, working_dir=str(tmp_path))

        assert result["status"] == "success"
        publication = result["portable_publication"]
        assert publication["status"] in {"published", "duplicate"}
        assert publication["artifact_id"]
        assert publication["sequence_id"] is not None

        # Artifact is on disk via the adapter's namespace path.
        identity = IdentityTuple(**_identity_dict())
        ns = PortableNamespace(
            project_id=identity.project_id,
            workspace_id=identity.workspace_id,
            user_id=identity.user_id,
            state_schema_version=identity.state_schema_version,
            carrier_namespace=identity.carrier_namespace,
        )
        refs = LocalFilesystemAdapter(working_dir=tmp_path).list_artifacts(ns)
        assert len(refs) >= 1

    def test_clock_out_missing_redaction_provenance_fails_publication_not_archive(
        self, tmp_path: Path
    ) -> None:
        """Provenance gate fails publication only; archive flow still runs."""
        from hestai_context_mcp.tools.clock_out import clock_out

        _write_identity_config(tmp_path)
        sid = _clock_in_then_session(tmp_path)

        # Patch build_provenance_or_raise to simulate provenance failure.
        from hestai_context_mcp.storage.provenance import ProvenanceIncompleteError

        def _broken(**kwargs: Any) -> Any:
            raise ProvenanceIncompleteError(
                code="provenance_incomplete",
                missing_field="engine_version",
                message="simulated incomplete provenance",
            )

        with patch(
            "hestai_context_mcp.tools.clock_out.build_provenance_or_raise",
            side_effect=_broken,
        ):
            result = clock_out(session_id=sid, working_dir=str(tmp_path))

        assert result["status"] == "success"  # archive still succeeded
        publication = result["portable_publication"]
        assert publication["status"] == "failed"
        assert publication["error_code"] == "provenance_incomplete"
        # Skip path writes outbox status record (A2): unpublished memory exists.
        assert result["unpublished_memory_exists"] is True

    def test_clock_out_artifact_parent_ids_include_prior_snapshot_refs(
        self, tmp_path: Path
    ) -> None:
        """Published artifact parent_ids reference the snapshot's prior artifact ids."""
        import hashlib
        from datetime import UTC, datetime

        from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter
        from hestai_context_mcp.storage.provenance import build_provenance_or_raise
        from hestai_context_mcp.storage.types import (
            ArtifactKind,
            ArtifactRef,
            IdentityTuple,
            PortableMemoryArtifact,
            PortableNamespace,
            WritePrecondition,
        )
        from hestai_context_mcp.tools.clock_out import clock_out

        _write_identity_config(tmp_path)

        # Seed a prior artifact so clock_in's snapshot has a non-empty refs list.
        identity = IdentityTuple(**_identity_dict())
        prior_payload = {"id": "art-prior", "seq": 1}
        prior = PortableMemoryArtifact(
            artifact_id="art-prior",
            artifact_kind=ArtifactKind.PORTABLE_MEMORY,
            identity=identity,
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
            payload_hash=hashlib.sha256(
                json.dumps(prior_payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            payload=prior_payload,
        )
        ref = ArtifactRef(
            artifact_id=prior.artifact_id,
            identity=prior.identity,
            artifact_kind=prior.artifact_kind,
            sequence_id=prior.sequence_id,
            created_at=prior.created_at,
            payload_hash=prior.payload_hash,
            carrier_path="",
        )
        LocalFilesystemAdapter(working_dir=tmp_path).write_artifact(ref, prior, WritePrecondition())

        sid = _clock_in_then_session(tmp_path)
        result = clock_out(session_id=sid, working_dir=str(tmp_path))

        publication = result["portable_publication"]
        assert publication["status"] in {"published", "duplicate"}

        # Read back via adapter and confirm parent_ids include prior id.
        adapter = LocalFilesystemAdapter(working_dir=tmp_path)
        ns = PortableNamespace(
            project_id=identity.project_id,
            workspace_id=identity.workspace_id,
            user_id=identity.user_id,
            state_schema_version=identity.state_schema_version,
            carrier_namespace=identity.carrier_namespace,
        )
        refs = adapter.list_artifacts(ns)
        new_refs = [r for r in refs if r.artifact_id != "art-prior"]
        assert new_refs, "clock_out should have written at least one new artifact"
        new_artifact = adapter.read_artifact(new_refs[0])

        assert isinstance(new_artifact, PortableMemoryArtifact)
        assert "art-prior" in new_artifact.parent_ids


@pytest.mark.integration
class TestClockOutPublishIntegration:
    """TEST_131 + TEST_132 + TEST_133."""

    def test_clock_out_publishes_artifact_to_local_filesystem_adapter(self, tmp_path: Path) -> None:
        """Adapter gets exactly one publish call (no remote, no Git refs)."""
        from hestai_context_mcp.tools.clock_out import clock_out

        _write_identity_config(tmp_path)
        sid = _clock_in_then_session(tmp_path)

        result = clock_out(session_id=sid, working_dir=str(tmp_path))

        publication = result["portable_publication"]
        assert publication["carrier_namespace"] == _identity_dict()["carrier_namespace"]
        # carrier_path is local; absolute path under working_dir.
        receipt = publication.get("durable_carrier_receipt") or ""
        assert ".hestai" in receipt and "portable" in receipt and "artifacts" in receipt

    def test_clock_out_return_includes_portable_publication_status(self, tmp_path: Path) -> None:
        """portable_publication is always present, even when skipped."""
        from hestai_context_mcp.tools.clock_out import clock_out

        sid = "session-without-identity"
        _write_session(tmp_path, sid, role="impl", focus="task")
        result = clock_out(session_id=sid, working_dir=str(tmp_path))

        assert "portable_publication" in result
        publication = result["portable_publication"]
        for key in ("status", "artifact_id", "sequence_id", "carrier_namespace", "queued_path"):
            assert key in publication

    def test_clock_out_return_includes_unpublished_memory_exists_false_when_empty(
        self, tmp_path: Path
    ) -> None:
        """When publish succeeds, unpublished_memory_exists is False."""
        from hestai_context_mcp.tools.clock_out import clock_out

        _write_identity_config(tmp_path)
        sid = _clock_in_then_session(tmp_path)

        result = clock_out(session_id=sid, working_dir=str(tmp_path))

        publication = result["portable_publication"]
        assert publication["status"] in {"published", "duplicate"}
        assert result["unpublished_memory_exists"] is False


@pytest.mark.integration
class TestClockOutPublishFailure:
    """TEST_134 + TEST_135."""

    def test_clock_out_publish_failure_queues_outbox_and_reports_local_success(
        self, tmp_path: Path
    ) -> None:
        """Adapter raise -> outbox status record exists; archive succeeded."""
        from hestai_context_mcp.tools.clock_out import clock_out

        _write_identity_config(tmp_path)
        sid = _clock_in_then_session(tmp_path)

        # Force the adapter publish call to raise an OSError after archive.
        from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter

        def _raise(self: Any, *args: Any, **kwargs: Any) -> None:
            raise OSError("simulated adapter failure")

        with patch.object(LocalFilesystemAdapter, "write_artifact", _raise):
            result = clock_out(session_id=sid, working_dir=str(tmp_path))

        assert result["status"] == "success"  # archive succeeded
        publication = result["portable_publication"]
        assert publication["status"] == "failed"
        # Outbox queued path is recorded.
        assert publication["queued_path"]
        # The outbox file exists.
        assert Path(publication["queued_path"]).exists()

    def test_clock_out_publish_failure_sets_unpublished_memory_exists_true(
        self, tmp_path: Path
    ) -> None:
        """When publish fails, unpublished_memory_exists is True."""
        from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter
        from hestai_context_mcp.tools.clock_out import clock_out

        _write_identity_config(tmp_path)
        sid = _clock_in_then_session(tmp_path)

        def _raise(self: Any, *args: Any, **kwargs: Any) -> None:
            raise OSError("simulated adapter failure")

        with patch.object(LocalFilesystemAdapter, "write_artifact", _raise):
            result = clock_out(session_id=sid, working_dir=str(tmp_path))

        assert result["unpublished_memory_exists"] is True


@pytest.mark.integration
class TestClockOutDuplicateIdempotent:
    """TEST_138."""

    def test_clock_out_duplicate_publish_is_idempotent_same_hash(self, tmp_path: Path) -> None:
        """Re-publishing the same payload hash returns DUPLICATE not FAILED.

        Cubic P2 #8 fix: the artifact_id seed is content-addressed on
        ``session_id|identity|payload_hash`` (clock_out.py:673). Calling
        ``_clock_in_then_session`` twice generated DIFFERENT sids, so the
        second publish derived a different artifact_id and never hit
        duplicate detection — the original test was vacuous. We must
        REUSE the same session_id (and same role/focus, so v1 payload
        is identical) across both publish calls.
        """

        from hestai_context_mcp.tools.clock_out import clock_out

        _write_identity_config(tmp_path)
        sid = _clock_in_then_session(tmp_path, role="impl", focus="task")

        # First publish.
        result1 = clock_out(session_id=sid, working_dir=str(tmp_path))
        assert result1["portable_publication"]["status"] in {"published", "duplicate"}
        first_artifact_id = result1["portable_publication"]["artifact_id"]
        assert first_artifact_id  # sanity: non-empty

        # clock_out removes the active session dir; recreate it with the
        # SAME sid + same role + same focus so v1 payload hash and
        # artifact_id seed are identical to the first call.
        _write_session(tmp_path, sid, role="impl", focus="task")

        # Second publish — content-addressed artifact_id matches the
        # already-on-disk artifact, so the adapter returns DUPLICATE.
        result2 = clock_out(session_id=sid, working_dir=str(tmp_path))
        publication2 = result2["portable_publication"]
        assert publication2["artifact_id"] == first_artifact_id, (
            "duplicate test requires identical artifact_ids; "
            f"got {publication2['artifact_id']!r} != {first_artifact_id!r}"
        )
        # The §INTEGRATION_PLAN R9 idempotent-on-same-hash contract:
        # the second publish MUST report status="duplicate".
        assert publication2["status"] == "duplicate"
