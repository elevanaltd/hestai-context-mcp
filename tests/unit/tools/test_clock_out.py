"""Tests for clock_out tool.

RED phase: These tests define the expected behavior of the clock_out tool
including session archival, credential redaction, learnings extraction,
learnings index management, and active session cleanup.
"""

import json
from pathlib import Path

from hestai_context_mcp.tools.clock_out import clock_out


def _setup_active_session(
    working_dir: Path,
    session_id: str = "TESTONLY_session_abc123",
    role: str = "implementation-lead",
    focus: str = "test-focus",
    transcript_path: str | None = None,
) -> Path:
    """Helper: create an active session directory with session.json."""
    active_dir = working_dir / ".hestai" / "state" / "sessions" / "active"
    active_dir.mkdir(parents=True, exist_ok=True)
    archive_dir = working_dir / ".hestai" / "state" / "sessions" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    session_dir = active_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    session_data = {
        "session_id": session_id,
        "role": role,
        "working_dir": str(working_dir),
        "focus": focus,
        "started_at": "2026-04-17T10:00:00+00:00",
        "branch": "main",
    }
    if transcript_path:
        session_data["transcript_path"] = transcript_path

    (session_dir / "session.json").write_text(json.dumps(session_data))
    return session_dir


def _create_transcript(path: Path, records: list[dict] | None = None) -> Path:
    """Helper: create a transcript JSONL file."""
    if records is None:
        records = [
            {
                "type": "human",
                "message": {"role": "user", "content": "What should we do?"},
                "timestamp": "2026-04-17T10:00:00Z",
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "DECISION_1: Use provider adapter pattern.\n"
                                "BLOCKER_1: Legacy parser crashes on new format.\n"
                                "LEARNING_1: Always handle unknown record types gracefully."
                            ),
                        }
                    ],
                },
                "timestamp": "2026-04-17T10:00:01Z",
            },
        ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")
    return path


class TestClockOutReturnShape:
    """Tests for the clock_out return shape matching interface contract."""

    def test_success_return_has_required_fields(self, tmp_path):
        """Successful clock_out returns all required fields."""
        transcript_path = tmp_path / "transcript.jsonl"
        _create_transcript(transcript_path)
        _setup_active_session(
            tmp_path,
            transcript_path=str(transcript_path),
        )

        result = clock_out(
            session_id="TESTONLY_session_abc123",
            working_dir=str(tmp_path),
        )

        assert result["status"] == "success"
        assert result["session_id"] == "TESTONLY_session_abc123"
        assert "archive_path" in result
        assert "octave_path" in result
        assert isinstance(result["message_count"], int)
        assert "compression_status" in result
        assert "extracted_learnings" in result

    def test_success_extracted_learnings_shape(self, tmp_path):
        """Extracted learnings has decisions, blockers, and learnings lists."""
        transcript_path = tmp_path / "transcript.jsonl"
        _create_transcript(transcript_path)
        _setup_active_session(
            tmp_path,
            transcript_path=str(transcript_path),
        )

        result = clock_out(
            session_id="TESTONLY_session_abc123",
            working_dir=str(tmp_path),
        )

        learnings = result["extracted_learnings"]
        assert isinstance(learnings["decisions"], list)
        assert isinstance(learnings["blockers"], list)
        assert isinstance(learnings["learnings"], list)


class TestClockOutSessionValidation:
    """Tests for session validation behavior."""

    def test_invalid_session_id_returns_error(self, tmp_path):
        """clock_out returns error for non-existent session."""
        # Create the directory structure but no session
        (tmp_path / ".hestai" / "state" / "sessions" / "active").mkdir(parents=True, exist_ok=True)

        result = clock_out(
            session_id="TESTONLY_nonexistent_session",
            working_dir=str(tmp_path),
        )

        assert result["status"] == "error"

    def test_path_traversal_rejected(self, tmp_path):
        """Session IDs with path traversal sequences are rejected."""
        (tmp_path / ".hestai" / "state" / "sessions" / "active").mkdir(parents=True, exist_ok=True)

        result = clock_out(
            session_id="../../../etc/passwd",
            working_dir=str(tmp_path),
        )

        assert result["status"] == "error"

    def test_empty_session_id_returns_error(self, tmp_path):
        """Empty session ID returns error."""
        (tmp_path / ".hestai" / "state" / "sessions" / "active").mkdir(parents=True, exist_ok=True)

        result = clock_out(session_id="", working_dir=str(tmp_path))
        assert result["status"] == "error"


class TestClockOutTranscriptParsing:
    """Tests for transcript parsing via provider adapter."""

    def test_parses_claude_transcript_correctly(self, tmp_path):
        """clock_out parses Claude JSONL and counts messages."""
        transcript_path = tmp_path / "transcript.jsonl"
        _create_transcript(transcript_path)
        _setup_active_session(
            tmp_path,
            transcript_path=str(transcript_path),
        )

        result = clock_out(
            session_id="TESTONLY_session_abc123",
            working_dir=str(tmp_path),
        )

        assert result["status"] == "success"
        assert result["message_count"] == 2

    def test_handles_missing_transcript_gracefully(self, tmp_path):
        """clock_out returns success with 0 messages when transcript not found."""
        _setup_active_session(tmp_path)

        result = clock_out(
            session_id="TESTONLY_session_abc123",
            working_dir=str(tmp_path),
        )

        # Should succeed but with 0 messages
        assert result["status"] == "success"
        assert result["message_count"] == 0

    def test_skips_unknown_record_types(self, tmp_path):
        """clock_out handles transcripts with unknown record types."""
        transcript_path = tmp_path / "transcript.jsonl"
        records = [
            {"type": "queue-operation", "data": {}},
            {
                "type": "human",
                "message": {"role": "user", "content": "test"},
            },
            {"type": "progress", "data": {"percent": 50}},
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "response"}],
                },
            },
            {"type": "pr-link", "data": {}},
        ]
        _create_transcript(transcript_path, records)
        _setup_active_session(
            tmp_path,
            transcript_path=str(transcript_path),
        )

        result = clock_out(
            session_id="TESTONLY_session_abc123",
            working_dir=str(tmp_path),
        )

        assert result["status"] == "success"
        assert result["message_count"] == 2


class TestClockOutRedaction:
    """Tests for credential redaction in archived transcripts."""

    def test_credentials_redacted_in_archive(self, tmp_path):
        """Archived transcript has credentials redacted."""
        # nosec: TESTONLY_ prefix - not real credentials
        transcript_path = tmp_path / "transcript.jsonl"
        records = [
            {
                "type": "human",
                "message": {
                    "role": "user",
                    "content": "My API key is sk-TESTONLYabcdefghijklmnopqrstuvwxyz",  # nosec
                },
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "I see your key."}],
                },
            },
        ]
        _create_transcript(transcript_path, records)
        _setup_active_session(
            tmp_path,
            transcript_path=str(transcript_path),
        )

        result = clock_out(
            session_id="TESTONLY_session_abc123",
            working_dir=str(tmp_path),
        )

        assert result["status"] == "success"
        assert result["archive_path"] is not None

        # Read the archived file and verify redaction
        archive_content = Path(result["archive_path"]).read_text()
        assert "sk-TESTONLYabcdefghijklmnopqrstuvwxyz" not in archive_content  # nosec
        assert "[REDACTED_API_KEY]" in archive_content


class TestClockOutLearningsExtraction:
    """Tests for DECISION/BLOCKER/LEARNING pattern extraction."""

    def test_extracts_decisions(self, tmp_path):
        """clock_out extracts DECISION patterns from assistant messages."""
        transcript_path = tmp_path / "transcript.jsonl"
        records = [
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": "DECISION_1: Use adapter pattern for extensibility.",
                        }
                    ],
                },
            },
        ]
        _create_transcript(transcript_path, records)
        _setup_active_session(
            tmp_path,
            transcript_path=str(transcript_path),
        )

        result = clock_out(
            session_id="TESTONLY_session_abc123",
            working_dir=str(tmp_path),
        )

        assert (
            "Use adapter pattern for extensibility." in result["extracted_learnings"]["decisions"]
        )

    def test_extracts_blockers(self, tmp_path):
        """clock_out extracts BLOCKER patterns from assistant messages."""
        transcript_path = tmp_path / "transcript.jsonl"
        records = [
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": "BLOCKER_1: Legacy parser crashes on new format.",
                        }
                    ],
                },
            },
        ]
        _create_transcript(transcript_path, records)
        _setup_active_session(
            tmp_path,
            transcript_path=str(transcript_path),
        )

        result = clock_out(
            session_id="TESTONLY_session_abc123",
            working_dir=str(tmp_path),
        )

        assert "Legacy parser crashes on new format." in result["extracted_learnings"]["blockers"]

    def test_extracts_learnings(self, tmp_path):
        """clock_out extracts LEARNING patterns from assistant messages."""
        transcript_path = tmp_path / "transcript.jsonl"
        records = [
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": "LEARNING_1: Always handle unknown record types gracefully.",
                        }
                    ],
                },
            },
        ]
        _create_transcript(transcript_path, records)
        _setup_active_session(
            tmp_path,
            transcript_path=str(transcript_path),
        )

        result = clock_out(
            session_id="TESTONLY_session_abc123",
            working_dir=str(tmp_path),
        )

        assert (
            "Always handle unknown record types gracefully."
            in result["extracted_learnings"]["learnings"]
        )

    def test_extracts_unnumbered_patterns(self, tmp_path):
        """clock_out extracts DECISION:/BLOCKER:/LEARNING: without numbers."""
        transcript_path = tmp_path / "transcript.jsonl"
        records = [
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "DECISION: Go with simple approach.\n"
                                "BLOCKER: Missing dependency.\n"
                                "LEARNING: Keep it minimal."
                            ),
                        }
                    ],
                },
            },
        ]
        _create_transcript(transcript_path, records)
        _setup_active_session(
            tmp_path,
            transcript_path=str(transcript_path),
        )

        result = clock_out(
            session_id="TESTONLY_session_abc123",
            working_dir=str(tmp_path),
        )

        learnings = result["extracted_learnings"]
        assert "Go with simple approach." in learnings["decisions"]
        assert "Missing dependency." in learnings["blockers"]
        assert "Keep it minimal." in learnings["learnings"]


class TestClockOutArchival:
    """Tests for session archival behavior."""

    def test_archive_created_in_correct_path(self, tmp_path):
        """Archived transcript is saved under sessions/archive/."""
        transcript_path = tmp_path / "transcript.jsonl"
        _create_transcript(transcript_path)
        _setup_active_session(
            tmp_path,
            transcript_path=str(transcript_path),
        )

        result = clock_out(
            session_id="TESTONLY_session_abc123",
            working_dir=str(tmp_path),
        )

        archive_path = Path(result["archive_path"])
        assert archive_path.exists()
        assert "archive" in str(archive_path)
        assert "TESTONLY_session_abc123" in archive_path.name

    def test_active_session_removed_after_archival(self, tmp_path):
        """Active session directory is removed after successful archival."""
        transcript_path = tmp_path / "transcript.jsonl"
        _create_transcript(transcript_path)
        session_dir = _setup_active_session(
            tmp_path,
            transcript_path=str(transcript_path),
        )

        assert session_dir.exists()

        result = clock_out(
            session_id="TESTONLY_session_abc123",
            working_dir=str(tmp_path),
        )

        assert result["status"] == "success"
        assert not session_dir.exists()


class TestClockOutLearningsIndex:
    """Tests for learnings index management."""

    def test_learnings_appended_to_index(self, tmp_path):
        """clock_out appends learnings to learnings-index.jsonl."""
        transcript_path = tmp_path / "transcript.jsonl"
        _create_transcript(transcript_path)
        _setup_active_session(
            tmp_path,
            transcript_path=str(transcript_path),
        )

        clock_out(
            session_id="TESTONLY_session_abc123",
            working_dir=str(tmp_path),
        )

        index_path = tmp_path / ".hestai" / "state" / "learnings-index.jsonl"
        assert index_path.exists()

        # Read and verify index entry
        entries = [json.loads(line) for line in index_path.read_text().strip().split("\n") if line]
        assert len(entries) >= 1

        entry = entries[0]
        assert entry["session_id"] == "TESTONLY_session_abc123"
        assert "decisions" in entry
        assert "blockers" in entry
        assert "learnings" in entry

    def test_multiple_sessions_append_to_same_index(self, tmp_path):
        """Multiple clock_out calls append to the same index file."""
        for i in range(2):
            sid = f"TESTONLY_session_{i}"
            transcript_path = tmp_path / f"transcript_{i}.jsonl"
            _create_transcript(transcript_path)
            _setup_active_session(
                tmp_path,
                session_id=sid,
                transcript_path=str(transcript_path),
            )
            clock_out(session_id=sid, working_dir=str(tmp_path))

        index_path = tmp_path / ".hestai" / "state" / "learnings-index.jsonl"
        entries = [json.loads(line) for line in index_path.read_text().strip().split("\n") if line]
        assert len(entries) == 2
