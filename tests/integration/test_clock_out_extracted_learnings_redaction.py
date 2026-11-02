"""#255 — extracted learnings must be redacted at extraction (PROD::I2).

``clock_out`` redacts the archived transcript, but the DECISION / BLOCKER /
LEARNING values it extracts from the same transcript used to reach three
sinks unredacted:

1. ``.hestai/state/learnings-index.jsonl``
2. ``extracted_learnings`` in the tool response
3. the published Portable Memory Artifact payload (decisions / blockers /
   learnings) written by the identity-configured publish path

These tests drive the real ``clock_out`` entry point against a scripted
transcript in a tmp project. Identity is configured through the real
``.hestai/state/portable/identity.json`` so the artifact is actually built
and written by ``LocalFilesystemAdapter``; assertions read the written bytes.

Fixture credentials are fake and assembled at runtime from parts, so no
contiguous secret-shaped literal exists in this file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from hestai_context_mcp.core.redaction import RedactionEngine

# Fake credentials, built from parts (never a contiguous literal).
FAKE_GITHUB_PAT = "ghp_" + "A" * 36
FAKE_AWS_KEY = "AKIA" + "B" * 16
FAKE_AI_KEY = "sk-" + "C" * 24
FAKE_CREDENTIALS = (FAKE_GITHUB_PAT, FAKE_AWS_KEY, FAKE_AI_KEY)

RAW_DECISION = f"rotate the deploy token {FAKE_GITHUB_PAT} before release"
RAW_BLOCKER = f"CI log printed access key {FAKE_AWS_KEY} in step 4"
RAW_SECRET_LEARNING = f"never echo {FAKE_AI_KEY} into a transcript"
PLAIN_LEARNING = "Keep provider adapters thin: parse, normalise, return (no I/O)."

SESSION_ID = "TESTONLY_session_255"


def _identity_dict() -> dict[str, Any]:
    return {
        "project_id": "proj-255",
        "workspace_id": "wt-fix-255",
        "user_id": "tester",
        "state_schema_version": 1,
        "carrier_namespace": "personal",
    }


def _write_identity_config(working_dir: Path) -> None:
    cfg_path = working_dir / ".hestai" / "state" / "portable" / "identity.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(_identity_dict()), encoding="utf-8")


def _seed_session(working_dir: Path) -> Path:
    """Seed an active session whose transcript carries credentials in learnings.

    Returns the transcript path (it lives outside ``.hestai/state`` so a
    byte scan of the state tree only sees what clock_out wrote).
    """

    transcript = working_dir / "transcript.jsonl"
    records = [
        {
            "type": "human",
            "message": {"role": "user", "content": "Summarise the session."},
            "timestamp": "2026-11-02T10:00:00Z",
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"DECISION: {RAW_DECISION}\n"
                            f"BLOCKER: {RAW_BLOCKER}\n"
                            f"LEARNING: {RAW_SECRET_LEARNING}\n"
                            f"LEARNING: {PLAIN_LEARNING}"
                        ),
                    }
                ],
            },
            "timestamp": "2026-11-02T10:00:01Z",
        },
    ]
    transcript.write_text(
        "".join(json.dumps(r) + "\n" for r in records),
        encoding="utf-8",
    )

    session_dir = working_dir / ".hestai" / "state" / "sessions" / "active" / SESSION_ID
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "session.json").write_text(
        json.dumps(
            {
                "session_id": SESSION_ID,
                "role": "implementation-lead",
                "focus": "issue-255",
                "branch": "main",
                "transcript_path": str(transcript),
                "started_at": "2026-11-02T10:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    return transcript


def _expected_redacted() -> dict[str, list[str]]:
    """What the engine produces for each raw extracted value."""

    return {
        "decisions": [RedactionEngine.redact_content(RAW_DECISION)],
        "blockers": [RedactionEngine.redact_content(RAW_BLOCKER)],
        "learnings": [
            RedactionEngine.redact_content(RAW_SECRET_LEARNING),
            PLAIN_LEARNING,
        ],
    }


def _assert_no_credentials(text: str, where: str) -> None:
    for cred in FAKE_CREDENTIALS:
        assert cred not in text, f"fake credential ({cred[:4]}...) leaked into {where}"


def _state_files(working_dir: Path) -> list[Path]:
    state = working_dir / ".hestai" / "state"
    return [p for p in state.rglob("*") if p.is_file()]


def _published_artifacts(working_dir: Path) -> list[dict[str, Any]]:
    pss = working_dir / ".hestai" / "state" / "portable" / "pss"
    files = sorted(pss.rglob("artifacts/*.json")) if pss.exists() else []
    return [json.loads(p.read_text(encoding="utf-8")) for p in files]


def _index_entries(working_dir: Path) -> list[dict[str, Any]]:
    index = working_dir / ".hestai" / "state" / "learnings-index.jsonl"
    return [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines() if line]


@pytest.fixture
def published(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    """Run clock_out end-to-end with identity configured (real publish path)."""

    from hestai_context_mcp.tools.clock_out import clock_out

    _write_identity_config(tmp_path)
    _seed_session(tmp_path)
    result = clock_out(session_id=SESSION_ID, working_dir=str(tmp_path))
    assert result["status"] == "success"
    return tmp_path, result


def test_fixture_values_are_redactable() -> None:
    """Sanity: each fake credential is one the engine actually redacts."""

    for raw in (RAW_DECISION, RAW_BLOCKER, RAW_SECRET_LEARNING):
        assert RedactionEngine.redact_content(raw) != raw
    assert RedactionEngine.redact_content(PLAIN_LEARNING) == PLAIN_LEARNING


@pytest.mark.integration
class TestExtractedLearningsRedacted:
    """(1)-(3), (5) and archive regression on the identity-configured path."""

    def test_learnings_index_has_no_credentials(
        self, published: tuple[Path, dict[str, Any]]
    ) -> None:
        """(1) learnings-index.jsonl carries redacted values only."""

        working_dir, _ = published
        index = working_dir / ".hestai" / "state" / "learnings-index.jsonl"
        _assert_no_credentials(index.read_text(encoding="utf-8"), "learnings-index.jsonl")

        (entry,) = _index_entries(working_dir)
        expected = _expected_redacted()
        assert entry["decisions"] == expected["decisions"]
        assert entry["blockers"] == expected["blockers"]
        assert entry["learnings"] == expected["learnings"]

    def test_response_extracted_learnings_have_no_credentials(
        self, published: tuple[Path, dict[str, Any]]
    ) -> None:
        """(2) the tool response carries redacted values only."""

        _, result = published
        _assert_no_credentials(json.dumps(result), "clock_out response")
        assert result["extracted_learnings"] == _expected_redacted()

    def test_published_artifact_payload_has_no_credentials(
        self, published: tuple[Path, dict[str, Any]]
    ) -> None:
        """(3) the real publish path writes an artifact whose payload is redacted."""

        working_dir, result = published
        publication = result["portable_publication"]
        assert publication["status"] in {"published", "duplicate"}, publication
        assert publication["artifact_id"]

        artifacts = _published_artifacts(working_dir)
        assert len(artifacts) == 1, "expected exactly one written artifact"
        payload = artifacts[0]["payload"]
        expected = _expected_redacted()
        assert payload["decisions"] == expected["decisions"]
        assert payload["blockers"] == expected["blockers"]
        assert payload["learnings"] == expected["learnings"]

        # Byte-level: nothing clock_out wrote under .hestai/state holds a credential.
        for path in _state_files(working_dir):
            _assert_no_credentials(
                path.read_text(encoding="utf-8", errors="replace"),
                str(path.relative_to(working_dir)),
            )

    def test_non_secret_learning_survives_unchanged(
        self, published: tuple[Path, dict[str, Any]]
    ) -> None:
        """(5) normal learning text is not over-redacted in any sink."""

        working_dir, result = published
        assert PLAIN_LEARNING in result["extracted_learnings"]["learnings"]
        (entry,) = _index_entries(working_dir)
        assert PLAIN_LEARNING in entry["learnings"]
        (artifact,) = _published_artifacts(working_dir)
        assert PLAIN_LEARNING in artifact["payload"]["learnings"]

    def test_archive_remains_redacted(self, published: tuple[Path, dict[str, Any]]) -> None:
        """Regression: the archived transcript copy stays redacted."""

        _, result = published
        archive = Path(result["archive_path"])
        assert archive.exists()
        _assert_no_credentials(archive.read_text(encoding="utf-8"), "archived transcript")


@pytest.mark.integration
class TestExtractedLearningsRedactionFailsClosed:
    """(4) a redaction failure on the extracted values fails closed."""

    def test_redaction_failure_empties_lists_and_blocks_publish(self, tmp_path: Path) -> None:
        """Only the extracted-value redaction fails; the archive redaction succeeds.

        ``copy_and_redact`` also calls ``redact_content`` (on the whole
        transcript), so the patch passes that call through to the real engine
        and raises for every other input. This isolates the extraction path:
        the archive is written, but the extracted values must not surface.
        """

        from hestai_context_mcp.tools.clock_out import clock_out

        _write_identity_config(tmp_path)
        transcript = _seed_session(tmp_path)
        transcript_text = transcript.read_text(encoding="utf-8")
        real_redact = RedactionEngine.redact_content

        def _fail_on_extracted_values(text: str) -> str:
            if text == transcript_text:
                return real_redact(text)
            raise RuntimeError("simulated redaction failure")

        with patch.object(RedactionEngine, "redact_content", side_effect=_fail_on_extracted_values):
            result = clock_out(session_id=SESSION_ID, working_dir=str(tmp_path))

        empty: dict[str, list[str]] = {"decisions": [], "blockers": [], "learnings": []}

        # Response: structured shape, empty lists, nothing raw.
        assert result["status"] == "success"
        assert result["extracted_learnings"] == empty
        _assert_no_credentials(json.dumps(result), "clock_out response")

        # Publish blocked fail-closed: structured failure, no artifact written.
        publication = result["portable_publication"]
        assert publication["status"] == "failed"
        assert publication["error_code"] == "redaction_failure"
        assert publication["artifact_id"] is None
        assert _published_artifacts(tmp_path) == []
        assert result["unpublished_memory_exists"] is True

        # Index: entry written with empty lists.
        (entry,) = _index_entries(tmp_path)
        assert entry["decisions"] == []
        assert entry["blockers"] == []
        assert entry["learnings"] == []

        # Disk: nothing clock_out wrote holds a credential.
        for path in _state_files(tmp_path):
            _assert_no_credentials(
                path.read_text(encoding="utf-8", errors="replace"),
                str(path.relative_to(tmp_path)),
            )
