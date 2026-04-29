"""GROUP_018 — REWORK CYCLE RED tests for ADDITIONAL CONCERN 1.

Asserts the binding A2 second-order concern from CE Stage C: when
clock_out hits a fail-closed identity skip path (per RISK_001), a
durable outbox status record MUST be written to disk so the skip is
auditable, not just surfaced in the response.

Per the rework directive::

    when clock_out skips publish for any structured reason
    (no_identity_configured, redaction_failure, provenance_incomplete),
    write an outbox status record with reason_code field at
    .hestai/state/portable/outbox/{session_id}-{reason_code}.json

This test asserts the file exists after the no_identity_configured skip.
The redaction_failure case is covered by the BLOCKER 1 paired tests in
``test_clock_out_rework_redaction_failclose.py``; this file focuses on
the identity-skip case so the audit trail is observable independently
in commit history (ADDITIONAL CONCERN 1 has its own RED+GREEN pair per
the rework COMMIT POLICY).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


def _write_session(working_dir: Path, session_id: str) -> Path:
    """Seed an active session directory for clock_out without identity."""

    active = working_dir / ".hestai" / "state" / "sessions" / "active" / session_id
    active.mkdir(parents=True, exist_ok=True)
    (active / "session.json").write_text(
        json.dumps(
            {
                "session_id": session_id,
                "role": "impl",
                "focus": "rework",
                "branch": "main",
                "transcript_path": None,
                "created_at": "2026-04-26T00:00:00+00:00",
            }
        )
    )
    return active


@pytest.mark.integration
class TestNoIdentityConfiguredOutboxStatusRecord:
    """ADDITIONAL CONCERN 1: skip must leave durable on-disk audit."""

    def test_no_identity_configured_skip_writes_outbox_status_record(self, tmp_path: Path) -> None:
        """A2 + PROD::I1: identity-skip writes durable outbox record.

        After GREEN: a file exists at
        ``.hestai/state/portable/outbox/{session_id}-no_identity_configured.json``
        when clock_out skips publish because identity is unconfigured.
        """

        from hestai_context_mcp.tools.clock_out import clock_out

        sid = "session-no-identity-skip"
        _write_session(tmp_path, sid)

        result = clock_out(session_id=sid, working_dir=str(tmp_path))

        # Response surface confirms the structured skip reason.
        publication = result["portable_publication"]
        assert publication["status"] == "failed"
        assert publication["error_code"] == "no_identity_configured"

        # Durable on-disk audit: skip-status record under the outbox.
        outbox = tmp_path / ".hestai" / "state" / "portable" / "outbox"
        assert outbox.exists(), "outbox directory must be created on structured skip"
        expected = outbox / f"{sid}-no_identity_configured.json"
        assert expected.exists(), (
            f"expected skip-status file at {expected} (ADDITIONAL CONCERN 1: "
            "every structured skip must leave a durable on-disk record); "
            f"actual entries: {[p.name for p in outbox.iterdir()]}"
        )
        record = json.loads(expected.read_text(encoding="utf-8"))
        assert record["session_id"] == sid
        assert record["error_code"] == "no_identity_configured"
        assert record["kind"] == "skip_status"
        assert "recorded_at" in record

        # And unpublished_memory_exists reflects the durable skip.
        assert result["unpublished_memory_exists"] is True

    def test_no_identity_configured_skip_outbox_record_is_idempotent_on_repeated_clock_out(
        self, tmp_path: Path
    ) -> None:
        """Repeated skip with same session+reason must not corrupt the record."""

        from hestai_context_mcp.tools.clock_out import clock_out

        sid = "session-no-identity-idempotent"
        _write_session(tmp_path, sid)
        clock_out(session_id=sid, working_dir=str(tmp_path))

        # Second call (re-create session because clock_out removed it).
        _write_session(tmp_path, sid)
        result = clock_out(session_id=sid, working_dir=str(tmp_path))

        outbox = tmp_path / ".hestai" / "state" / "portable" / "outbox"
        expected = outbox / f"{sid}-no_identity_configured.json"
        assert expected.exists()

        # Record is well-formed JSON (overwriting, not corrupting).
        record = json.loads(expected.read_text(encoding="utf-8"))
        assert record["session_id"] == sid
        assert record["error_code"] == "no_identity_configured"

        # Response is consistent.
        publication = result["portable_publication"]
        assert publication["status"] == "failed"
        assert publication["error_code"] == "no_identity_configured"


@pytest.mark.integration
class TestSkipReasonCodeFileNamingConvention:
    """Naming convention guard: {session_id}-{reason_code}.json under outbox/."""

    def test_skip_status_file_name_is_session_id_dash_reason_code(self, tmp_path: Path) -> None:
        """The on-disk filename follows {session_id}-{reason_code}.json (CE rework)."""

        from hestai_context_mcp.tools.clock_out import clock_out

        sid = "session-naming-convention"
        _write_session(tmp_path, sid)
        clock_out(session_id=sid, working_dir=str(tmp_path))

        outbox = tmp_path / ".hestai" / "state" / "portable" / "outbox"
        skip_records: list[Any] = list(outbox.glob(f"{sid}-*.json"))
        assert skip_records, f"no skip-status records for session {sid} under {outbox}"
        for path in skip_records:
            stem = path.stem  # e.g. "session-naming-convention-no_identity_configured"
            assert stem.startswith(f"{sid}-"), (
                f"skip-status filename {path.name!r} must start with "
                f"'{sid}-' for operator correlation"
            )
            reason_code = stem[len(sid) + 1 :]
            assert reason_code, "reason_code segment must be non-empty"
            # The on-disk record echoes the reason_code in its 'error_code' field.
            record = json.loads(path.read_text(encoding="utf-8"))
            assert record["error_code"] == reason_code, (
                f"filename reason_code {reason_code!r} must match record "
                f"error_code {record['error_code']!r}"
            )
