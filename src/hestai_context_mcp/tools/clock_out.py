"""Clock-out tool: Archive session transcript and extract learnings.

Archives an agent session by:
1. Validating the session exists
2. Parsing the transcript using the provider adapter pattern
3. Redacting credentials via RedactionEngine
4. Archiving the redacted transcript
5. Extracting learnings (DECISION/BLOCKER/LEARNING patterns)
6. Appending to learnings index
7. Cleaning up the active session directory

Part of ADR-0353 Phase 1 harvest.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hestai_context_mcp.core.redaction import RedactionEngine
from hestai_context_mcp.core.transcript.base import TranscriptMessage
from hestai_context_mcp.core.transcript.registry import detect_parser

logger = logging.getLogger(__name__)

# Patterns for extracting learnings from assistant messages
_DECISION_PATTERN = re.compile(r"DECISION(?:_\d+)?:\s*(.+?)(?:\n|$)")
_BLOCKER_PATTERN = re.compile(r"BLOCKER(?:_\d+)?:\s*(.+?)(?:\n|$)")
_LEARNING_PATTERN = re.compile(r"LEARNING(?:_\d+)?:\s*(.+?)(?:\n|$)")


def _validate_session_id(session_id: str) -> str | None:
    """Validate session_id to prevent path traversal attacks.

    Args:
        session_id: Session ID to validate.

    Returns:
        Stripped session_id if valid, None if invalid.
    """
    if not session_id or not session_id.strip():
        return None

    session_id = session_id.strip()

    # Path traversal prevention
    if ".." in session_id or "/" in session_id or "\\" in session_id:
        return None

    return session_id


def _extract_learnings(
    messages: list[TranscriptMessage],
) -> dict[str, list[str]]:
    """Extract DECISION/BLOCKER/LEARNING patterns from assistant messages.

    Scans assistant messages for structured learning patterns commonly
    used by agents to mark important session outcomes.

    Args:
        messages: List of transcript messages to scan.

    Returns:
        Dict with 'decisions', 'blockers', and 'learnings' string lists.
    """
    decisions: list[str] = []
    blockers: list[str] = []
    learnings: list[str] = []

    for msg in messages:
        if msg.role != "assistant":
            continue

        for match in _DECISION_PATTERN.finditer(msg.content):
            text = match.group(1).strip()
            if text:
                decisions.append(text)

        for match in _BLOCKER_PATTERN.finditer(msg.content):
            text = match.group(1).strip()
            if text:
                blockers.append(text)

        for match in _LEARNING_PATTERN.finditer(msg.content):
            text = match.group(1).strip()
            if text:
                learnings.append(text)

    return {
        "decisions": decisions,
        "blockers": blockers,
        "learnings": learnings,
    }


def _append_to_learnings_index(
    working_dir: Path,
    session_id: str,
    session_data: dict[str, Any],
    extracted_learnings: dict[str, list[str]],
    archive_path: str | None,
) -> None:
    """Append session learnings to the learnings index.

    Creates or appends to .hestai/state/learnings-index.jsonl.

    Args:
        working_dir: Project working directory.
        session_id: Session identifier.
        session_data: Session metadata from session.json.
        extracted_learnings: Extracted DECISION/BLOCKER/LEARNING data.
        archive_path: Path to the archived transcript.
    """
    index_path = working_dir / ".hestai" / "state" / "learnings-index.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "session_id": session_id,
        "role": session_data.get("role", "unknown"),
        "focus": session_data.get("focus", "unknown"),
        "archived_at": datetime.now(UTC).isoformat(),
        "decisions": extracted_learnings["decisions"],
        "blockers": extracted_learnings["blockers"],
        "learnings": extracted_learnings["learnings"],
        "archive_path": archive_path,
    }

    with open(index_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def clock_out(
    session_id: str,
    working_dir: str = "",
    description: str = "",
) -> dict[str, Any]:
    """Archive agent session transcript and extract learnings.

    Compresses session transcript and archives it. Extracts learnings
    for future session context. Cleans up active session directory.

    Args:
        session_id: Session ID from clock_in.
        working_dir: Project working directory (recommended).
        description: Optional session summary/description.

    Returns:
        Dictionary with archive status, paths, message count,
        compression status, and extracted learnings.
    """
    # Validate session_id
    valid_id = _validate_session_id(session_id)
    if valid_id is None:
        return {
            "status": "error",
            "session_id": session_id,
            "archive_path": None,
            "octave_path": None,
            "message_count": 0,
            "compression_status": "skipped",
            "extracted_learnings": {"decisions": [], "blockers": [], "learnings": []},
            "message": f"Invalid session_id: {session_id!r}",
        }

    session_id = valid_id
    wd = Path(working_dir).resolve() if working_dir else Path.cwd()

    # Verify session exists
    active_dir = wd / ".hestai" / "state" / "sessions" / "active"
    session_dir = active_dir / session_id

    if not session_dir.exists():
        return {
            "status": "error",
            "session_id": session_id,
            "archive_path": None,
            "octave_path": None,
            "message_count": 0,
            "compression_status": "skipped",
            "extracted_learnings": {"decisions": [], "blockers": [], "learnings": []},
            "message": f"Session {session_id} not found in active sessions",
        }

    # Load session metadata
    session_file = session_dir / "session.json"
    if not session_file.exists():
        return {
            "status": "error",
            "session_id": session_id,
            "archive_path": None,
            "octave_path": None,
            "message_count": 0,
            "compression_status": "skipped",
            "extracted_learnings": {"decisions": [], "blockers": [], "learnings": []},
            "message": f"Session metadata not found: {session_file}",
        }

    try:
        session_data = json.loads(session_file.read_text())
    except (json.JSONDecodeError, OSError) as e:
        return {
            "status": "error",
            "session_id": session_id,
            "archive_path": None,
            "octave_path": None,
            "message_count": 0,
            "compression_status": "skipped",
            "extracted_learnings": {"decisions": [], "blockers": [], "learnings": []},
            "message": f"Could not read session metadata: {e}",
        }

    # Find transcript file
    transcript_path = _resolve_transcript_path(session_data)
    messages: list[TranscriptMessage] = []

    if transcript_path and transcript_path.exists():
        # Parse transcript using provider adapter
        parser = detect_parser(transcript_path)
        if parser:
            messages = parser.parse(transcript_path)
            logger.info("Parsed %d messages from %s", len(messages), transcript_path)
        else:
            logger.warning("No parser detected for transcript: %s", transcript_path)

    # Extract learnings from assistant messages
    extracted_learnings = _extract_learnings(messages)

    # Archive: redact and save transcript
    archive_path: str | None = None
    archive_dir = wd / ".hestai" / "state" / "sessions" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    if transcript_path and transcript_path.exists():
        try:
            timestamp = datetime.now(UTC).strftime("%Y-%m-%d")
            focus = session_data.get("focus", "general")
            safe_focus = focus.replace("/", "-").replace("\\", "-").replace("\n", "-").strip("-")
            archive_filename = f"{timestamp}-{safe_focus}-{session_id}-redacted.jsonl"
            dest = archive_dir / archive_filename

            # Apply RedactionEngine for credential safety (fail-closed)
            RedactionEngine.copy_and_redact(transcript_path, dest)
            archive_path = str(dest)
            logger.info("Archived redacted transcript to %s", dest)
        except Exception as e:
            logger.error("Redaction/archival failed: %s", e)
            # Continue without archive -- session cleanup still needed

    # OCTAVE compression (Phase 1 simplification: skipped)
    octave_path: str | None = None
    compression_status = "skipped"

    # Append to learnings index
    _append_to_learnings_index(
        wd,
        session_id,
        session_data,
        extracted_learnings,
        archive_path,
    )

    # Remove active session directory
    try:
        shutil.rmtree(session_dir)
        logger.info("Removed active session: %s", session_dir)
    except OSError as e:
        logger.warning("Could not remove active session directory: %s", e)

    return {
        "status": "success",
        "session_id": session_id,
        "archive_path": archive_path,
        "octave_path": octave_path,
        "message_count": len(messages),
        "compression_status": compression_status,
        "extracted_learnings": extracted_learnings,
    }


def _resolve_transcript_path(session_data: dict[str, Any]) -> Path | None:
    """Resolve the transcript file path from session data.

    Phase 1 simplification: Looks for an explicit transcript_path in
    session.json. Full Claude path discovery heuristic is future work.

    Args:
        session_data: Session metadata dict.

    Returns:
        Path to transcript file, or None if not specified/found.
    """
    transcript_path_str = session_data.get("transcript_path")
    if transcript_path_str:
        path = Path(transcript_path_str)
        if path.exists():
            return path
        logger.warning("Transcript path from session.json not found: %s", path)
    return None
