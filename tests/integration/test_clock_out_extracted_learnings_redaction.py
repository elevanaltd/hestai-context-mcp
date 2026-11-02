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
import logging
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


def _default_assistant_text() -> str:
    return (
        f"DECISION: {RAW_DECISION}\n"
        f"BLOCKER: {RAW_BLOCKER}\n"
        f"LEARNING: {RAW_SECRET_LEARNING}\n"
        f"LEARNING: {PLAIN_LEARNING}"
    )


def _seed_session(working_dir: Path, assistant_text: str | None = None) -> Path:
    """Seed an active session whose transcript carries credentials in learnings.

    Returns the transcript path (it lives outside ``.hestai/state`` so a
    byte scan of the state tree only sees what clock_out wrote).
    """

    if assistant_text is None:
        assistant_text = _default_assistant_text()
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
                        "text": assistant_text,
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

        # Archive: the whole-transcript redaction still succeeded and is clean.
        archive = Path(result["archive_path"])
        assert archive.exists()
        _assert_no_credentials(archive.read_text(encoding="utf-8"), "archived transcript")

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

    def test_both_redactions_fail_with_credential_in_message_reason_is_type_only(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Extraction AND archive redaction raise with a credential in the message.

        The failure reason reaches the response and the on-disk skip record, so
        it must name only the exception type; the archive handler must not
        replace the sanitized extraction reason with ``str(e)``.
        """

        from hestai_context_mcp.tools.clock_out import clock_out

        _write_identity_config(tmp_path)
        _seed_session(tmp_path)

        def _raise_echoing_input(text: str) -> str:
            raise RuntimeError(f"cannot redact input near {FAKE_GITHUB_PAT}")

        with (
            caplog.at_level(logging.DEBUG),
            patch.object(RedactionEngine, "redact_content", side_effect=_raise_echoing_input),
        ):
            result = clock_out(session_id=SESSION_ID, working_dir=str(tmp_path))

        publication = result["portable_publication"]
        assert publication["error_code"] == "redaction_failure"
        assert "RuntimeError" in publication["error_message"]
        assert "cannot redact input" not in publication["error_message"]
        assert result["archive_path"] is None
        _assert_no_credentials(json.dumps(result), "clock_out response")
        _assert_no_credentials(caplog.text, "clock_out log output")
        for path in _state_files(tmp_path):
            _assert_no_credentials(
                path.read_text(encoding="utf-8", errors="replace"),
                str(path.relative_to(tmp_path)),
            )

    def test_archive_redaction_failure_with_credential_in_message_reason_is_type_only(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Only the archive redaction raises; its message must not leak either."""

        from hestai_context_mcp.tools.clock_out import clock_out

        _write_identity_config(tmp_path)
        _seed_session(tmp_path)

        def _raise_echoing_input(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError(f"cannot redact input near {FAKE_GITHUB_PAT}")

        with (
            caplog.at_level(logging.DEBUG),
            patch.object(RedactionEngine, "copy_and_redact", side_effect=_raise_echoing_input),
        ):
            result = clock_out(session_id=SESSION_ID, working_dir=str(tmp_path))

        publication = result["portable_publication"]
        assert publication["error_code"] == "redaction_failure"
        assert "RuntimeError" in publication["error_message"]
        assert "cannot redact input" not in publication["error_message"]
        _assert_no_credentials(json.dumps(result), "clock_out response")
        _assert_no_credentials(caplog.text, "clock_out log output")
        for path in _state_files(tmp_path):
            _assert_no_credentials(
                path.read_text(encoding="utf-8", errors="replace"),
                str(path.relative_to(tmp_path)),
            )


# Fake multi-line private key and DB password, built from parts at runtime.
FAKE_PEM_BODY = "MII" + "Q" * 40
FAKE_PEM = (
    "-----BEGIN "
    + "RSA PRIVATE KEY-----\n"
    + FAKE_PEM_BODY
    + "\n"
    + "Q" * 40
    + "\n-----END "
    + "RSA PRIVATE KEY-----"
)
FAKE_DB_PASSWORD = "Fake" + "Pass" + "word" + "123"
FAKE_DB_URI = "postgres://admin:" + FAKE_DB_PASSWORD + "@db.local:5432/app"


def _clock_out_with(
    working_dir: Path, assistant_text: str, description: str = ""
) -> dict[str, Any]:
    from hestai_context_mcp.tools.clock_out import clock_out

    _write_identity_config(working_dir)
    _seed_session(working_dir, assistant_text)
    result = clock_out(session_id=SESSION_ID, working_dir=str(working_dir), description=description)
    assert result["status"] == "success"
    assert result["portable_publication"]["status"] in {"published", "duplicate"}
    return result


def _assert_absent_everywhere(
    working_dir: Path, result: dict[str, Any], needles: tuple[str, ...]
) -> None:
    """No needle in the response or in any file clock_out wrote under .hestai/state."""

    response = json.dumps(result)
    for needle in needles:
        assert needle not in response, "fake secret material leaked into clock_out response"
    for path in _state_files(working_dir):
        text = path.read_text(encoding="utf-8", errors="replace")
        for needle in needles:
            assert (
                needle not in text
            ), f"fake secret material leaked into {path.relative_to(working_dir)}"


@pytest.mark.integration
class TestRedactionScopeAtExtraction:
    """Code-review findings on the first GREEN: what per-value redaction alone misses."""

    def test_multiline_private_key_in_learning_line_is_redacted(self, tmp_path: Path) -> None:
        """A key that starts on a LEARNING line and ends lines later must not leak.

        The extraction regex stops at the newline, so redacting only the
        extracted value never shows the engine the BEGIN...END span.
        """

        text = f"LEARNING: the deploy key was {FAKE_PEM}\nDECISION: rotate the deploy key"
        result = _clock_out_with(tmp_path, text)

        _assert_absent_everywhere(tmp_path, result, (FAKE_PEM_BODY, "PRIVATE KEY-----"))
        (artifact,) = _published_artifacts(tmp_path)
        assert artifact["payload"]["learnings"] == ["the deploy key was [REDACTED_PRIVATE_KEY]"]
        assert artifact["payload"]["decisions"] == ["rotate the deploy key"]

    def test_db_password_redacted_when_a_later_line_has_an_at_sign(self, tmp_path: Path) -> None:
        """Guard: whole-message redaction alone misses this; the extracted value must not.

        The db_password pattern only fires when no ``@`` follows it in the
        string, so a later ``@reviewer`` line defeats it on the whole message.
        """

        text = f"DECISION: use {FAKE_DB_URI} for staging\nLEARNING: ping @reviewer before merge"
        result = _clock_out_with(tmp_path, text)

        _assert_absent_everywhere(tmp_path, result, (FAKE_DB_PASSWORD,))
        (artifact,) = _published_artifacts(tmp_path)
        assert artifact["payload"]["learnings"] == ["ping @reviewer before merge"]

    def test_description_credential_absent_from_published_payload(self, tmp_path: Path) -> None:
        """The caller-supplied description is written into the same portable payload."""

        description = f"rotated access key {FAKE_AWS_KEY} after the leak"
        result = _clock_out_with(tmp_path, f"LEARNING: {PLAIN_LEARNING}", description)

        _assert_absent_everywhere(tmp_path, result, (FAKE_AWS_KEY,))
        (artifact,) = _published_artifacts(tmp_path)
        assert artifact["payload"]["description"] == RedactionEngine.redact_content(description)
        assert artifact["payload"]["learnings"] == [PLAIN_LEARNING]

    def test_url_line_does_not_redact_a_later_learning_with_an_at_sign(
        self, tmp_path: Path
    ) -> None:
        """(5) No over-redaction: a URL on one line must not wipe a later learning.

        The engine's db_password pattern can span lines (its user part is a
        negated class), so running every pattern over the whole message turns
        'email ops@example.com' into a fake password marker. Only the
        multi-line private-key handling needs the whole message.
        """

        email_learning = "email ops@example.com for access"
        text = (
            "See https://docs.example.com/guide for the setup steps\n"
            f"LEARNING: {email_learning}\n"
            f"LEARNING: the deploy key was {FAKE_PEM}"
        )
        result = _clock_out_with(tmp_path, text)

        expected = [email_learning, "the deploy key was [REDACTED_PRIVATE_KEY]"]
        assert result["extracted_learnings"]["learnings"] == expected
        (entry,) = _index_entries(tmp_path)
        assert entry["learnings"] == expected
        (artifact,) = _published_artifacts(tmp_path)
        assert artifact["payload"]["learnings"] == expected
        _assert_absent_everywhere(tmp_path, result, (FAKE_PEM_BODY, "PRIVATE KEY-----"))

    def test_multiline_description_db_password_with_later_at_line_is_redacted(
        self, tmp_path: Path
    ) -> None:
        """A db password in a multi-line description must not reach the payload.

        One engine pass over the whole description misses it when a later line
        contains '@' (the db_password lookahead), so the description needs the
        same line-bounded treatment as the transcript messages.
        """

        description = f"Used {FAKE_DB_URI} for staging\nping @reviewer before merge"
        result = _clock_out_with(tmp_path, f"LEARNING: {PLAIN_LEARNING}", description)

        _assert_absent_everywhere(tmp_path, result, (FAKE_DB_PASSWORD,))
        (artifact,) = _published_artifacts(tmp_path)
        assert artifact["payload"]["description"].endswith("\nping @reviewer before merge")

    def test_multiline_description_url_line_does_not_redact_a_later_email(
        self, tmp_path: Path
    ) -> None:
        """(5) No over-redaction of a non-secret multi-line description."""

        description = "See https://docs.example.com/guide for setup\nNote: email ops@example.com"
        _clock_out_with(tmp_path, f"LEARNING: {PLAIN_LEARNING}", description)

        (artifact,) = _published_artifacts(tmp_path)
        assert artifact["payload"]["description"] == description


@pytest.mark.integration
def test_description_redaction_failure_fails_closed(tmp_path: Path) -> None:
    """(4) A failure redacting only the description also fails closed."""

    from hestai_context_mcp.tools.clock_out import clock_out

    marker = "DESCRIPTION-ONLY-MARKER"
    description = f"{marker} rotated access key {FAKE_AWS_KEY}"
    _write_identity_config(tmp_path)
    _seed_session(tmp_path)
    real_redact = RedactionEngine.redact_content

    def _fail_on_description(text: str) -> str:
        if marker in text:
            raise RuntimeError("simulated redaction failure")
        return real_redact(text)

    with patch.object(RedactionEngine, "redact_content", side_effect=_fail_on_description):
        result = clock_out(
            session_id=SESSION_ID, working_dir=str(tmp_path), description=description
        )

    assert result["status"] == "success"
    assert result["extracted_learnings"] == {"decisions": [], "blockers": [], "learnings": []}
    publication = result["portable_publication"]
    assert publication["status"] == "failed"
    assert publication["error_code"] == "redaction_failure"
    assert _published_artifacts(tmp_path) == []
    _assert_absent_everywhere(tmp_path, result, (FAKE_AWS_KEY, marker) + FAKE_CREDENTIALS)


# ---------------------------------------------------------------------------
# CE round 1 on PR #257: session metadata and exception text reach the sinks.
# ---------------------------------------------------------------------------


def _assert_tree_and_logs_clean(working_dir: Path, result: dict[str, Any], log_text: str) -> None:
    """No fake credential in the response, the logs, or any path or file under .hestai/state."""

    _assert_no_credentials(json.dumps(result), "clock_out response")
    _assert_no_credentials(log_text, "clock_out log output")
    for path in _state_files(working_dir):
        rel = str(path.relative_to(working_dir))
        _assert_no_credentials(rel, f"file name {rel[:40]}...")
        _assert_no_credentials(path.read_text(encoding="utf-8", errors="replace"), rel)


def _seed_session_metadata(working_dir: Path, *, role: str, focus: str) -> None:
    """Overwrite role/focus in the seeded session.json."""

    session_file = (
        working_dir / ".hestai" / "state" / "sessions" / "active" / SESSION_ID / "session.json"
    )
    data = json.loads(session_file.read_text(encoding="utf-8"))
    data["role"] = role
    data["focus"] = focus
    session_file.write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.integration
class TestSessionMetadataRedacted:
    """role and focus from session.json reach every sink; they must be redacted."""

    def test_credential_in_role_and_focus_absent_from_every_sink(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from hestai_context_mcp.tools.clock_out import clock_out

        role = f"implementation-lead {FAKE_GITHUB_PAT}"
        focus = f"issue-255 {FAKE_AWS_KEY}"
        _write_identity_config(tmp_path)
        _seed_session(tmp_path)
        _seed_session_metadata(tmp_path, role=role, focus=focus)

        with caplog.at_level(logging.DEBUG):
            result = clock_out(session_id=SESSION_ID, working_dir=str(tmp_path))

        assert result["status"] == "success"
        assert result["portable_publication"]["status"] in {"published", "duplicate"}
        _assert_tree_and_logs_clean(tmp_path, result, caplog.text)

        (entry,) = _index_entries(tmp_path)
        assert entry["role"] == RedactionEngine.redact_content(role)
        assert entry["focus"] == RedactionEngine.redact_content(focus)
        (artifact,) = _published_artifacts(tmp_path)
        assert artifact["payload"]["role"] == RedactionEngine.redact_content(role)
        assert artifact["payload"]["focus"] == RedactionEngine.redact_content(focus)
        assert Path(result["archive_path"]).exists()

    def test_metadata_redaction_failure_fails_closed(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A failure redacting only role/focus empties the lists and blocks publish."""

        from hestai_context_mcp.tools.clock_out import clock_out

        marker = "METADATA-ONLY-MARKER"
        _write_identity_config(tmp_path)
        _seed_session(tmp_path)
        _seed_session_metadata(tmp_path, role=f"{marker} {FAKE_GITHUB_PAT}", focus="issue-255")
        real_redact = RedactionEngine.redact_content

        def _fail_on_metadata(text: str) -> str:
            if marker in text:
                raise RuntimeError("simulated redaction failure")
            return real_redact(text)

        with (
            caplog.at_level(logging.DEBUG),
            patch.object(RedactionEngine, "redact_content", side_effect=_fail_on_metadata),
        ):
            result = clock_out(session_id=SESSION_ID, working_dir=str(tmp_path))

        assert result["extracted_learnings"] == {"decisions": [], "blockers": [], "learnings": []}
        assert result["portable_publication"]["error_code"] == "redaction_failure"
        assert _published_artifacts(tmp_path) == []
        _assert_tree_and_logs_clean(tmp_path, result, caplog.text)
        assert marker not in json.dumps(result)
        (entry,) = _index_entries(tmp_path)
        assert marker not in json.dumps(entry)


@pytest.mark.integration
class TestExceptionTextNeverReachesSinks:
    """Exception messages may echo input: every failure reason names the type only."""

    def test_adapter_write_failure_reason_is_type_only(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from hestai_context_mcp.storage.local_filesystem import LocalFilesystemAdapter
        from hestai_context_mcp.tools.clock_out import clock_out

        _write_identity_config(tmp_path)
        _seed_session(tmp_path)

        def _raise(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError(f"carrier write failed near {FAKE_GITHUB_PAT}")

        with (
            caplog.at_level(logging.DEBUG),
            patch.object(LocalFilesystemAdapter, "write_artifact", side_effect=_raise),
        ):
            result = clock_out(session_id=SESSION_ID, working_dir=str(tmp_path))

        publication = result["portable_publication"]
        assert publication["error_code"] == "adapter_write_failed"
        assert "RuntimeError" in publication["error_message"]
        assert "carrier write failed" not in publication["error_message"]
        outbox = tmp_path / ".hestai" / "state" / "portable" / "outbox"
        assert any(outbox.iterdir()), "adapter failure must still enqueue an outbox entry"
        _assert_tree_and_logs_clean(tmp_path, result, caplog.text)

    def test_archive_unreadable_reason_is_type_only(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from hestai_context_mcp.tools.clock_out import clock_out

        _write_identity_config(tmp_path)
        _seed_session(tmp_path)
        real_read_text = Path.read_text

        def _read_text(self: Path, *args: Any, **kwargs: Any) -> str:
            if self.name.endswith("-redacted.jsonl"):
                raise OSError(f"cannot read archive near {FAKE_GITHUB_PAT}")
            return real_read_text(self, *args, **kwargs)

        with (
            caplog.at_level(logging.DEBUG),
            patch.object(Path, "read_text", _read_text),
        ):
            result = clock_out(session_id=SESSION_ID, working_dir=str(tmp_path))

        publication = result["portable_publication"]
        assert publication["error_code"] == "archive_unreadable"
        assert "OSError" in publication["error_message"]
        assert "cannot read archive" not in publication["error_message"]
        _assert_tree_and_logs_clean(tmp_path, result, caplog.text)

    def test_session_metadata_unreadable_message_is_type_only(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from hestai_context_mcp.tools.clock_out import clock_out

        _seed_session(tmp_path)
        real_read_text = Path.read_text

        def _read_text(self: Path, *args: Any, **kwargs: Any) -> str:
            if self.name == "session.json":
                raise OSError(f"cannot read session near {FAKE_GITHUB_PAT}")
            return real_read_text(self, *args, **kwargs)

        with (
            caplog.at_level(logging.DEBUG),
            patch.object(Path, "read_text", _read_text),
        ):
            result = clock_out(session_id=SESSION_ID, working_dir=str(tmp_path))

        assert result["status"] == "error"
        assert "OSError" in result["message"]
        assert "cannot read session" not in result["message"]
        _assert_tree_and_logs_clean(tmp_path, result, caplog.text)

    def test_active_session_removal_failure_log_is_type_only(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from hestai_context_mcp.tools.clock_out import clock_out

        _seed_session(tmp_path)

        def _raise(*_args: Any, **_kwargs: Any) -> None:
            raise OSError(f"cannot remove near {FAKE_GITHUB_PAT}")

        with (
            caplog.at_level(logging.DEBUG),
            patch("hestai_context_mcp.tools.clock_out.shutil.rmtree", side_effect=_raise),
        ):
            result = clock_out(session_id=SESSION_ID, working_dir=str(tmp_path))

        assert result["status"] == "success"
        assert "cannot remove" not in caplog.text
        _assert_tree_and_logs_clean(tmp_path, result, caplog.text)


@pytest.mark.integration
def test_transcript_path_is_not_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """transcript_path comes from session.json, not from clock_in: keep it out of logs."""

    from hestai_context_mcp.tools.clock_out import clock_out

    secret_dir = tmp_path / f"t-{FAKE_GITHUB_PAT}"
    secret_dir.mkdir()
    transcript = _seed_session(tmp_path)
    moved = secret_dir / transcript.name
    transcript.rename(moved)
    session_file = (
        tmp_path / ".hestai" / "state" / "sessions" / "active" / SESSION_ID / "session.json"
    )
    data = json.loads(session_file.read_text(encoding="utf-8"))
    data["transcript_path"] = str(moved)
    session_file.write_text(json.dumps(data), encoding="utf-8")

    with caplog.at_level(logging.DEBUG):
        result = clock_out(session_id=SESSION_ID, working_dir=str(tmp_path))

    assert result["status"] == "success"
    _assert_no_credentials(caplog.text, "clock_out log output")
