"""GROUP_016 — REWORK CYCLE RED tests for RISK_010 fail-closed publish.

Asserts the binding ruling from CE NO-GO + CRS CONDITIONAL on B1 ADR-0013:
when ``RedactionEngine.copy_and_redact`` raises (or otherwise fails), the
clock_out tool MUST fail-closed:

- NO ``PortableMemoryArtifact`` is written to the LocalFilesystemAdapter
  (no on-disk file under ``portable/.../artifacts/``).
- The response carries a structured ``portable_publication.error_code``
  that names the redaction failure class.
- A durable outbox status record is written with the redaction-failure
  reason code, so the skip is auditable on disk (A2 second-order
  concern + PROD::I1 lifecycle integrity).
- The published artifact response MUST NOT carry an ``input_artifact_hash``
  equal to its ``output_artifact_hash`` for non-empty inputs (RISK_010
  provenance integrity: input_text and output_text must be independently
  derived). The fallback "same source" pattern that the original
  implementation used is forbidden.

These tests reproduce the CE-cited scenario that returned NO-GO in
Stage C: patched RedactionEngine.copy_and_redact raises -> clock_out
returned status=published with archive_path=null and an unredacted
"TESTONLY" secret in decisions. After the rework GREEN fix, each test
below MUST pass empirically.
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


def _write_identity_config(working_dir: Path) -> None:
    cfg_path = working_dir / ".hestai" / "state" / "portable" / "identity.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(_identity_dict()))


def _seed_session_with_transcript(working_dir: Path, session_id: str) -> Path:
    """Seed an active session whose session.json points at a real transcript.

    The transcript contains a TESTONLY secret-like marker so any leak in the
    published artifact is unambiguously detectable. This is the CE-cited
    reproducer scenario.
    """

    active = working_dir / ".hestai" / "state" / "sessions" / "active" / session_id
    active.mkdir(parents=True, exist_ok=True)

    transcript = working_dir / "transcript.jsonl"
    # Use a 'TESTONLY' marker plus a sk- shaped string so an unredacted leak
    # is detectable both as a literal substring and via a redaction pattern.
    transcript.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "DECISION: keep TESTONLY-secret-sk-"
                                "AAAAAAAAAAAAAAAAAAAA out of archives"
                            ),
                        }
                    ]
                },
            }
        )
        + "\n"
    )

    session_data = {
        "session_id": session_id,
        "role": "impl",
        "focus": "rework",
        "branch": "main",
        "transcript_path": str(transcript),
        "created_at": "2026-04-26T00:00:00+00:00",
    }
    (active / "session.json").write_text(json.dumps(session_data))
    return active


@pytest.mark.integration
class TestRedactionFailureBlocksPublish:
    """BLOCKER 1 / RISK_010: redaction failure must fail-closed for publish."""

    def test_redaction_engine_raise_blocks_publish_no_artifact_written(
        self, tmp_path: Path
    ) -> None:
        """CE-cited reproducer: patched RedactionEngine raises -> no publish.

        After GREEN: clock_out must NOT publish a PortableMemoryArtifact when
        the redaction engine fails. No JSON file under portable artifacts.
        """

        from hestai_context_mcp.tools.clock_out import clock_out

        _write_identity_config(tmp_path)
        sid = "session-redaction-failure"
        _seed_session_with_transcript(tmp_path, sid)

        def _raise(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("simulated redaction engine failure")

        with patch(
            "hestai_context_mcp.tools.clock_out.RedactionEngine.copy_and_redact",
            side_effect=_raise,
        ):
            result = clock_out(session_id=sid, working_dir=str(tmp_path))

        # The response MUST carry a structured failure for portable_publication.
        publication = result["portable_publication"]
        assert (
            publication["status"] == "failed"
        ), f"redaction failure must fail-closed for publish, got {publication}"
        assert (
            publication["error_code"] == "redaction_failure"
        ), f"expected error_code='redaction_failure', got {publication['error_code']!r}"

        # No PortableMemoryArtifact JSON file written anywhere under portable artifacts.
        portable = tmp_path / ".hestai" / "state" / "portable"
        artifact_files: list[Path] = []
        if portable.exists():
            for p in portable.rglob("*.json"):
                # Outbox entries and identity.json are allowed; reject artifact files only.
                if "/outbox/" in str(p) or p.name == "identity.json":
                    continue
                if "/snapshots/" in str(p):
                    continue
                artifact_files.append(p)
        assert artifact_files == [], (
            "redaction failure must NOT leave a PortableMemoryArtifact on disk; "
            f"found: {artifact_files}"
        )

        # Archive path MUST be null (redaction failed -> no archive).
        assert result["archive_path"] is None

    def test_redaction_engine_raise_writes_outbox_status_record(self, tmp_path: Path) -> None:
        """A2 second-order concern: skip must leave a durable on-disk audit.

        After GREEN: an outbox status entry with reason_code='redaction_failure'
        exists under .hestai/state/portable/outbox/ for the session.
        """

        from hestai_context_mcp.tools.clock_out import clock_out

        _write_identity_config(tmp_path)
        sid = "session-redaction-failure-outbox"
        _seed_session_with_transcript(tmp_path, sid)

        def _raise(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("simulated redaction engine failure")

        with patch(
            "hestai_context_mcp.tools.clock_out.RedactionEngine.copy_and_redact",
            side_effect=_raise,
        ):
            result = clock_out(session_id=sid, working_dir=str(tmp_path))

        outbox = tmp_path / ".hestai" / "state" / "portable" / "outbox"
        assert outbox.exists(), "outbox dir must be created on structured skip"
        entries = list(outbox.glob("*.json"))
        assert entries, "outbox must contain a status record after redaction failure"

        # The outbox entry must name the reason and the session.
        matched = False
        for entry in entries:
            payload = json.loads(entry.read_text(encoding="utf-8"))
            if payload.get("error_code") == "redaction_failure":
                matched = True
                # session-id linkage so operators can correlate.
                assert sid in entry.name or sid in str(
                    payload
                ), f"outbox entry must reference session_id {sid!r}: {payload}"
                break
        assert matched, (
            f"no outbox entry with error_code='redaction_failure' "
            f"in {[e.name for e in entries]}"
        )

        # unpublished_memory_exists reflects the durable skip.
        assert result["unpublished_memory_exists"] is True

    def test_redaction_failure_does_not_leak_unredacted_secret_in_response(
        self, tmp_path: Path
    ) -> None:
        """RISK_010: even on failure, no unredacted secret can appear anywhere.

        After GREEN: response is structured-fail with no transcript content
        carried through; archive_path is null; no published artifact carries
        the TESTONLY marker (the entire publish path is blocked).
        """

        from hestai_context_mcp.tools.clock_out import clock_out

        _write_identity_config(tmp_path)
        sid = "session-no-leak"
        _seed_session_with_transcript(tmp_path, sid)

        def _raise(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("simulated redaction engine failure")

        with patch(
            "hestai_context_mcp.tools.clock_out.RedactionEngine.copy_and_redact",
            side_effect=_raise,
        ):
            result = clock_out(session_id=sid, working_dir=str(tmp_path))

        # The response payload (anywhere) must not contain the TESTONLY marker.
        rendered = json.dumps(result, default=str)
        assert (
            "TESTONLY" not in rendered
        ), "unredacted TESTONLY secret leaked into clock_out response"

        # And no PortableMemoryArtifact JSON written.
        portable = tmp_path / ".hestai" / "state" / "portable"
        if portable.exists():
            for p in portable.rglob("*.json"):
                if "/outbox/" in str(p) or "/snapshots/" in str(p) or p.name == "identity.json":
                    continue
                content = p.read_text(encoding="utf-8")
                assert (
                    "TESTONLY" not in content
                ), f"unredacted secret leaked into on-disk artifact at {p}"


@pytest.mark.integration
class TestProvenanceIntegritySameSourceForbidden:
    """BLOCKER 1 second test gap: input_text == output_text must fail-closed."""

    def test_provenance_with_identical_input_and_output_for_nonempty_payload_is_rejected(
        self, tmp_path: Path
    ) -> None:
        """RISK_010: provenance integrity check.

        After GREEN: when there is no transcript, clock_out must NOT use
        ``payload_canonical`` as both input_text and output_text — that
        produces equal input/output hashes which is a structural forgery
        (no actual redaction was performed). Either skip publish with a
        structured reason, or use a deterministic empty-input constant
        distinct from the output.
        """

        from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter
        from hestai_context_mcp.storage.types import IdentityTuple, PortableNamespace
        from hestai_context_mcp.tools.clock_out import clock_out

        _write_identity_config(tmp_path)
        sid = "session-no-transcript-provenance"
        # Seed session WITHOUT a transcript_path so the no-transcript path
        # is exercised. This is the legitimate "no transcript" case.
        active = tmp_path / ".hestai" / "state" / "sessions" / "active" / sid
        active.mkdir(parents=True, exist_ok=True)
        (active / "session.json").write_text(
            json.dumps(
                {
                    "session_id": sid,
                    "role": "impl",
                    "focus": "rework",
                    "branch": "main",
                    "transcript_path": None,
                    "created_at": "2026-04-26T00:00:00+00:00",
                }
            )
        )

        result = clock_out(session_id=sid, working_dir=str(tmp_path))

        # If publish proceeded, read back any artifact and assert provenance
        # integrity (input_artifact_hash != output_artifact_hash).
        identity = IdentityTuple(**_identity_dict())
        ns = PortableNamespace(
            project_id=identity.project_id,
            workspace_id=identity.workspace_id,
            user_id=identity.user_id,
            state_schema_version=identity.state_schema_version,
            carrier_namespace=identity.carrier_namespace,
        )
        adapter = LocalFilesystemAdapter(working_dir=tmp_path)
        refs = adapter.list_artifacts(ns)
        for ref in refs:
            artifact = adapter.read_artifact(ref)
            # Only PortableMemoryArtifact carries redaction_provenance.
            from hestai_context_mcp.storage.types import PortableMemoryArtifact

            if isinstance(artifact, PortableMemoryArtifact):
                p = artifact.redaction_provenance
                assert p.input_artifact_hash != p.output_artifact_hash, (
                    "RISK_010 provenance integrity: input_artifact_hash MUST NOT "
                    "equal output_artifact_hash for non-empty payloads (the original "
                    "fallback that used payload_canonical for both inputs is forbidden); "
                    f"input={p.input_artifact_hash!r} output={p.output_artifact_hash!r}"
                )
        # Either way, the response must carry a defined structured publication block.
        assert "portable_publication" in result
