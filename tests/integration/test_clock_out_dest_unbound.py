"""Cubic rework cycle 2 — Finding #3 (P1, clock_out.py:288).

RED-first test: when ``dest`` would not yet be assigned (e.g., focus is
None and ``focus.replace("/", "-")`` raises AttributeError before the
``dest = archive_dir / archive_filename`` line executes), the cleanup
handler must NOT leak ``UnboundLocalError``. The expected behaviour is
a structured response (PROD::I1 SESSION_LIFECYCLE_INTEGRITY +
PROD::I4 STRUCTURED_RETURN_SHAPES) where redaction_failed records the
underlying error and clock_out continues to the publish path without
crashing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


def _write_session_with_focus_none(working_dir: Path, session_id: str) -> Path:
    """Seed an active session whose session_data['focus'] is None.

    A real transcript file is also created so the redaction branch is
    entered (the bug only triggers when transcript_path exists).
    """

    active = working_dir / ".hestai" / "state" / "sessions" / "active" / session_id
    active.mkdir(parents=True, exist_ok=True)

    # Seed a tiny transcript file so the redaction branch is taken.
    transcript = working_dir / "transcript.jsonl"
    transcript.write_text(
        json.dumps({"role": "user", "content": "hi"}) + "\n",
        encoding="utf-8",
    )

    session_data: dict[str, Any] = {
        "session_id": session_id,
        "role": "impl",
        # focus=None is the trigger: focus.replace("/", "-") raises
        # AttributeError before ``dest`` is bound.
        "focus": None,
        "branch": "main",
        "transcript_path": str(transcript),
        "created_at": "2026-04-26T00:00:00+00:00",
    }
    (active / "session.json").write_text(json.dumps(session_data))
    return active


@pytest.mark.integration
class TestClockOutDestUnboundCleanup:
    """Cubic P1 #3: cleanup handler must not leak UnboundLocalError."""

    def test_clock_out_focus_none_does_not_leak_unbound_local_error(self, tmp_path: Path) -> None:
        """focus=None must not cause UnboundLocalError when dest is referenced
        in the cleanup handler. A structured response is required."""

        from hestai_context_mcp.tools.clock_out import clock_out

        sid = "session-focus-none"
        _write_session_with_focus_none(tmp_path, sid)

        # MUST NOT raise UnboundLocalError (or any unstructured error).
        result = clock_out(session_id=sid, working_dir=str(tmp_path))

        # Top-level shape preserved.
        assert isinstance(result, dict)
        assert "status" in result
        assert "portable_publication" in result
        # archive_path is None because the redaction branch failed before
        # dest could be assigned.
        assert result["archive_path"] is None
