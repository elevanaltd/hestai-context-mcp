"""Clock-out tool: Archive session transcript and extract learnings.

Archives an agent session by:
1. Validating the session exists
2. Parsing the transcript using the provider adapter pattern
3. Redacting credentials via RedactionEngine
4. Archiving the redacted transcript
5. Extracting learnings (DECISION/BLOCKER/LEARNING patterns)
6. Appending to learnings index
7. Cleaning up the active session directory

ADR-0013 PSS extension: after archive succeeds, clock_out builds a
``PortableMemoryArtifact`` with v1 payload keys (RISK_005), validates
redaction provenance fail-closed (RISK_010 / G4), and publishes via
``LocalFilesystemAdapter``. Publish failures enqueue a status-only
record in the durable outbox (R7 + A2 + G7). The response is extended
with a ``portable_publication`` block and a ``unpublished_memory_exists``
flag. All existing top-level fields are preserved (G2 backward-compat).

Part of ADR-0353 Phase 1 harvest.
"""

from __future__ import annotations

import hashlib
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
from hestai_context_mcp.storage.provenance import (
    ProvenanceIncompleteError,
    build_provenance_or_raise,
)

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
            "portable_publication": _skipped_publication("invalid_session_id"),
            "unpublished_memory_exists": False,
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
            "portable_publication": _skipped_publication("session_not_found"),
            "unpublished_memory_exists": _outbox_has_entries(wd),
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
            "portable_publication": _skipped_publication("session_metadata_missing"),
            "unpublished_memory_exists": _outbox_has_entries(wd),
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
            "portable_publication": _skipped_publication("session_metadata_unreadable"),
            "unpublished_memory_exists": _outbox_has_entries(wd),
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

    # Archive: redact and save transcript.
    # RISK_010 fail-closed (CE rework): redaction failure is structurally
    # distinct from "no transcript" — the former MUST block publish; the
    # latter is a legitimate skip. We track the two outcomes separately so
    # the publish path can decide deterministically.
    archive_path: str | None = None
    redaction_failed: bool = False
    redaction_failure_reason: str = ""
    archive_dir = wd / ".hestai" / "state" / "sessions" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    if transcript_path and transcript_path.exists():
        # Cubic P1 #3: ``dest`` must be initialised BEFORE the try block so
        # the cleanup handler does not raise UnboundLocalError when an
        # earlier statement (e.g., focus.replace on a None focus) raises
        # before the assignment ``dest = archive_dir / archive_filename``
        # is reached. PROD::I1 SESSION_LIFECYCLE_INTEGRITY + PROD::I4
        # STRUCTURED_RETURN_SHAPES require a structured response, not an
        # unstructured UnboundLocalError leak.
        dest: Path | None = None
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
            # CE rework RISK_010: do NOT silently fall through to publish.
            # The transcript existed but redaction failed — this is a
            # structural credential-safety failure (PROD::I2 fail-closed).
            redaction_failed = True
            redaction_failure_reason = str(e)
            # Best-effort cleanup of any partial dest file so no
            # half-redacted content lingers on disk.
            try:
                if dest is not None and dest.exists():
                    dest.unlink()
            except OSError:  # pragma: no cover — defensive
                pass

    # OCTAVE compression (Phase 1 simplification: skipped)
    octave_path: str | None = None
    compression_status = "skipped"

    # CE rework RISK_010: when redaction fails, the in-memory
    # extracted_learnings may carry unredacted credentials from the parsed
    # transcript. PROD::I2 fail-closed forbids surfacing them in the
    # response or the learnings index. Replace with empty lists so the
    # caller gets the structured shape (PROD::I4 STRUCTURED_RETURN_SHAPES)
    # without any credential exposure.
    if redaction_failed:
        extracted_learnings = {"decisions": [], "blockers": [], "learnings": []}

    # Append to learnings index
    _append_to_learnings_index(
        wd,
        session_id,
        session_data,
        extracted_learnings,
        archive_path,
    )

    # ADR-0013 PSS: build + publish the Portable Memory Artifact, then
    # decide outbox enqueue vs success. The publication block is ALWAYS
    # present (G2 backward-compat + PROD::I4 STRUCTURED_RETURN_SHAPES).
    # Publication NEVER raises — every error path is captured into the
    # structured publication block.
    portable_publication, unpublished_memory_exists = _publish_portable_memory(
        working_dir_path=wd,
        session_id=session_id,
        session_data=session_data,
        archive_path=archive_path,
        extracted_learnings=extracted_learnings,
        description=description,
        redaction_failed=redaction_failed,
        redaction_failure_reason=redaction_failure_reason,
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
        "portable_publication": portable_publication,
        "unpublished_memory_exists": unpublished_memory_exists,
    }


def _skipped_publication(reason_code: str) -> dict[str, Any]:
    """Build a structured 'skipped' portable_publication block (A2)."""

    return {
        "status": "failed",
        "artifact_id": None,
        "sequence_id": None,
        "carrier_namespace": None,
        "queued_path": None,
        "durable_carrier_receipt": None,
        "error_code": reason_code,
        "error_message": f"clock_out skipped portable publication: {reason_code}",
    }


def _record_skip_status(
    working_dir: Path,
    *,
    session_id: str,
    reason_code: str,
    reason_message: str,
) -> Path | None:
    """Write a durable on-disk skip-status record under portable/outbox/.

    CE rework ADDITIONAL CONCERN 1: any structured publish skip
    (no_identity_configured, redaction_failure, provenance_incomplete,
    archive_unreadable, identity_invalid) MUST leave an auditable on-disk
    trace so PROD::I1 lifecycle integrity holds (no orphaned sessions).

    The file shape is intentionally simple JSON keyed by
    ``{session_id}-{reason_code}.json`` so operators can locate the
    record directly without parsing the broader outbox queue. The
    contents include the reason message and a UTC timestamp.

    Returns:
        The on-disk Path of the written record, or ``None`` if the write
        failed (defensive: skip-status is best-effort and must never
        propagate an exception out of clock_out).
    """

    target_dir = working_dir / ".hestai" / "state" / "portable" / "outbox"
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        # session_id is already validated upstream (no path traversal).
        # reason_code is internal-controlled.
        target = target_dir / f"{session_id}-{reason_code}.json"
        record = {
            "session_id": session_id,
            "error_code": reason_code,
            "error_message": reason_message,
            "recorded_at": datetime.now(UTC).isoformat(),
            "kind": "skip_status",
        }
        target.write_text(
            json.dumps(record, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        return target
    except OSError as e:  # pragma: no cover - defensive
        logger.warning("skip-status record write failed: %s", e)
        return None


def _outbox_has_entries(working_dir: Path) -> bool:
    """Pure read: True iff the durable outbox has any pending entries.

    Imported lazily so the early-return paths don't drag in storage code
    when there's nothing to publish.
    """

    try:
        from hestai_context_mcp.storage.outbox import OutboxStore

        return OutboxStore(working_dir=working_dir).unpublished_memory_exists()
    except Exception:  # pragma: no cover - defensive: never raise from clock_out
        return False


def _build_v1_payload(
    *,
    session_id: str,
    role: str,
    focus: str,
    archive_path: str | None,
    extracted_learnings: dict[str, list[str]],
    description: str,
) -> dict[str, Any]:
    """Build the RISK_005 v1 portable artifact payload.

    Keys are exactly: ``session_id, role, focus, archive_path, decisions,
    blockers, learnings, description``.
    """

    return {
        "session_id": session_id,
        "role": role,
        "focus": focus,
        "archive_path": archive_path,
        "decisions": list(extracted_learnings.get("decisions", [])),
        "blockers": list(extracted_learnings.get("blockers", [])),
        "learnings": list(extracted_learnings.get("learnings", [])),
        "description": description,
    }


def _payload_hash(payload: dict[str, Any]) -> str:
    """Deterministic SHA-256 over a canonical JSON encoding."""

    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _ack_to_publication(ack: Any) -> dict[str, Any]:
    """Convert a PublishAck to the public portable_publication shape."""

    return {
        "status": ack.status.value,
        "artifact_id": ack.artifact_id,
        "sequence_id": ack.sequence_id,
        "carrier_namespace": ack.carrier_namespace,
        "queued_path": ack.queued_path,
        "durable_carrier_receipt": ack.durable_carrier_receipt,
        "error_code": ack.error_code,
        "error_message": ack.error_message,
    }


#: Sentinel input used when there is *no* transcript content to hash.
#: Distinct from any payload_canonical so input_artifact_hash and
#: output_artifact_hash are never equal for non-empty payloads (RISK_010
#: provenance integrity, CE rework).
_EMPTY_TRANSCRIPT_SENTINEL: str = "<no_transcript_input>"


def _publish_portable_memory(
    *,
    working_dir_path: Path,
    session_id: str,
    session_data: dict[str, Any],
    archive_path: str | None,
    extracted_learnings: dict[str, list[str]],
    description: str,
    redaction_failed: bool = False,
    redaction_failure_reason: str = "",
) -> tuple[dict[str, Any], bool]:
    """Build, publish, and (on failure) enqueue the Portable Memory Artifact.

    Returns a tuple of (portable_publication block, unpublished_memory_exists).
    Never raises: every failure path is captured into the structured
    publication block. Lazy imports keep storage coupling out of
    module-load time.

    Args:
        redaction_failed: When True, the upstream redaction step raised; we
            MUST fail-closed (RISK_010, CE rework) and never publish — even
            if identity is configured and provenance can be re-computed.
        redaction_failure_reason: Human-readable reason; surfaced in the
            outbox status record so operators can correlate.
    """

    # Lazy imports: keep storage subtree off clock_out's import-time
    # surface. PROD::I5 — clock_out is the publish boundary, not get_context.
    from hestai_context_mcp.storage.identity import IdentityValidationError
    from hestai_context_mcp.storage.identity_resolver import resolve_identity
    from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter
    from hestai_context_mcp.storage.outbox import OutboxStore
    from hestai_context_mcp.storage.snapshots import (
        SnapshotNotFoundError,
        read_session_snapshot,
    )
    from hestai_context_mcp.storage.types import (
        ArtifactKind,
        ArtifactRef,
        IdentityTuple,
        PortableMemoryArtifact,
        PublishAck,
        PublishStatus,
        WritePrecondition,
    )

    outbox = OutboxStore(working_dir=working_dir_path)

    # CE rework BLOCKER 1 (RISK_010): if redaction failed upstream, the
    # publish path is fail-closed regardless of identity / provenance.
    # PROD::I2 forbids any publish that does not preserve fail-closed
    # redaction. Emit a structured failure + durable outbox status record
    # so the skip is auditable (A2 second-order concern).
    if redaction_failed:
        publication = _skipped_publication("redaction_failure")
        publication["error_message"] = (
            redaction_failure_reason or "redaction failed; publish blocked fail-closed"
        )
        _record_skip_status(
            working_dir_path,
            session_id=session_id,
            reason_code="redaction_failure",
            reason_message=publication["error_message"],
        )
        return publication, True

    # Identity gate: B2_START_BLOCKER_001 — do not invent identity. If the
    # config is absent, the publish path is a structured skip with an
    # outbox status record (A2 + CE rework ADDITIONAL CONCERN 1). Every
    # structured skip leaves a durable on-disk trace so PROD::I1 lifecycle
    # integrity is preserved (no orphaned sessions).
    try:
        identity = resolve_identity(working_dir_path)
    except IdentityValidationError as e:
        publication = _skipped_publication("identity_invalid")
        publication["error_message"] = e.message
        _record_skip_status(
            working_dir_path,
            session_id=session_id,
            reason_code="identity_invalid",
            reason_message=e.message,
        )
        return publication, True

    if identity is None:
        publication = _skipped_publication("no_identity_configured")
        _record_skip_status(
            working_dir_path,
            session_id=session_id,
            reason_code="no_identity_configured",
            reason_message="no identity configured; publish skipped",
        )
        return publication, True

    # Provenance gate: G4 atomic guard. Build provenance from the redacted
    # archive if available; else use a deterministic empty-input sentinel
    # distinct from the canonical payload so input_artifact_hash and
    # output_artifact_hash are independently derived (RISK_010 provenance
    # integrity — CE rework: same-source fallback is forbidden).
    payload_role = str(session_data.get("role", "unknown"))
    payload_focus = str(session_data.get("focus", "unknown"))
    payload = _build_v1_payload(
        session_id=session_id,
        role=payload_role,
        focus=payload_focus,
        archive_path=archive_path,
        extracted_learnings=extracted_learnings,
        description=description,
    )
    payload_canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))

    if archive_path is not None and Path(archive_path).exists():
        try:
            input_text = Path(archive_path).read_text(encoding="utf-8")
        except OSError as e:
            publication = _skipped_publication("archive_unreadable")
            publication["error_message"] = str(e)
            _record_skip_status(
                working_dir_path,
                session_id=session_id,
                reason_code="archive_unreadable",
                reason_message=str(e),
            )
            return publication, True
    else:
        # No transcript archived (legitimate "no transcript" case). Use a
        # constant sentinel as input_text so input_artifact_hash !=
        # output_artifact_hash for any non-empty payload. This keeps
        # provenance integrity structurally distinguishable from the
        # forbidden "same source" pattern (CE rework RISK_010).
        input_text = _EMPTY_TRANSCRIPT_SENTINEL

    try:
        provenance = build_provenance_or_raise(
            input_text=input_text,
            output_text=payload_canonical,
            redacted_credential_categories=(),
        )
    except ProvenanceIncompleteError as e:
        publication = _skipped_publication(e.code)
        publication["error_message"] = e.message
        # A2 + CE rework: the skip is observable on disk via the outbox
        # entry AND a status record keyed by session+reason for operators.
        try:
            synthetic_id = f"skip-{session_id}"
            ack = PublishAck(
                artifact_id=synthetic_id,
                identity=identity,
                carrier_namespace=identity.carrier_namespace,
                sequence_id=0,
                status=PublishStatus.FAILED,
                durable_carrier_receipt=None,
                queued_path=None,
                published_at=None,
                error_code=e.code,
                error_message=e.message,
            )
            queued = outbox.enqueue(ack=ack, error_code=e.code, error_message=e.message)
            publication["queued_path"] = str(queued)
        except Exception as enqueue_err:  # pragma: no cover - defensive
            logger.warning("outbox enqueue for provenance skip failed: %s", enqueue_err)
        _record_skip_status(
            working_dir_path,
            session_id=session_id,
            reason_code=e.code,
            reason_message=e.message,
        )
        return publication, outbox.unpublished_memory_exists()

    # Build the artifact. parent_ids reference the session snapshot's
    # known artifact_refs (R5 + R9 monotonic chain).
    parent_ids: tuple[str, ...] = ()
    try:
        snapshot = read_session_snapshot(
            working_dir=working_dir_path,
            session_id=session_id,
        )
        snapshot_refs = snapshot.get("metadata", {}).get("artifact_refs", [])
        parent_ids = tuple(str(r["artifact_id"]) for r in snapshot_refs)
    except SnapshotNotFoundError:
        parent_ids = ()
    except (OSError, KeyError, ValueError, TypeError):  # pragma: no cover - defensive
        parent_ids = ()

    # Stable artifact_id derived from session+payload so duplicate publish
    # is idempotent (R9). The id is content-addressed on the canonical
    # payload + identity, so identical sessions reproduce identical ids.
    artifact_id_seed = (
        f"{session_id}|{identity.project_id}|{identity.workspace_id}|"
        f"{identity.user_id}|{identity.state_schema_version}|{identity.carrier_namespace}|"
        f"{_payload_hash(payload)}"
    )
    artifact_id = "pss-" + hashlib.sha256(artifact_id_seed.encode("utf-8")).hexdigest()[:32]
    sequence_id = int(datetime.now(UTC).timestamp() * 1000)
    payload_hash = _payload_hash(payload)

    artifact = PortableMemoryArtifact(
        artifact_id=artifact_id,
        artifact_kind=ArtifactKind.PORTABLE_MEMORY,
        identity=IdentityTuple(
            project_id=identity.project_id,
            workspace_id=identity.workspace_id,
            user_id=identity.user_id,
            state_schema_version=identity.state_schema_version,
            carrier_namespace=identity.carrier_namespace,
        ),
        schema_version=1,
        producer_version="1",
        minimum_reader_version=1,
        created_at=datetime.now(UTC),
        sequence_id=sequence_id,
        parent_ids=parent_ids,
        redaction_provenance=provenance,
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

    adapter = LocalFilesystemAdapter(working_dir=working_dir_path)
    try:
        ack = adapter.write_artifact(ref, artifact, WritePrecondition())
    except Exception as e:  # noqa: BLE001 — adapter contract is broad; we
        # capture every failure into the structured publication shape and
        # enqueue an outbox entry so unpublished_memory_exists flips True.
        logger.warning("LocalFilesystemAdapter publish failed: %s", e)
        publication = _skipped_publication("adapter_write_failed")
        publication["error_message"] = str(e)
        try:
            failed_ack = PublishAck(
                artifact_id=artifact.artifact_id,
                identity=artifact.identity,
                carrier_namespace=artifact.identity.carrier_namespace,
                sequence_id=artifact.sequence_id,
                status=PublishStatus.FAILED,
                durable_carrier_receipt=None,
                queued_path=None,
                published_at=None,
                error_code="adapter_write_failed",
                error_message=str(e),
            )
            queued = outbox.enqueue(
                ack=failed_ack,
                error_code="adapter_write_failed",
                error_message=str(e),
            )
            publication["queued_path"] = str(queued)
        except Exception as enqueue_err:  # pragma: no cover - defensive
            logger.warning("outbox enqueue after adapter failure failed: %s", enqueue_err)
        return publication, outbox.unpublished_memory_exists()

    publication = _ack_to_publication(ack)
    if ack.status == PublishStatus.FAILED:
        # Adapter returned a structured failure (e.g. precondition
        # conflicting payload). Enqueue and report unpublished memory.
        try:
            queued = outbox.enqueue(
                ack=ack,
                error_code=ack.error_code or "publish_failed",
                error_message=ack.error_message or "publish failed",
            )
            publication["queued_path"] = str(queued)
        except Exception as enqueue_err:  # pragma: no cover - defensive
            logger.warning("outbox enqueue after FAILED ack failed: %s", enqueue_err)

    return publication, outbox.unpublished_memory_exists()


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
