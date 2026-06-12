"""RED suite — ``lookup_decision`` MCP tool.

Contract: ADR-RFC-ARCH-004 §3.2 (return shape) + §3.1.1 (common error
envelope). Pure read (PROD I5), structured return (PROD I4).

Happy path returns::

    {
      "ok": true,
      "record": {token, type, version, status, tier, decision, because,
                 authored_at, path, fields{}},
      "resolution_chain": [ ... ]   # populated when STATUS == SUPERSEDED
    }

Error envelope (§3.1.1) for TOKEN_NOT_FOUND, TOKEN_MALFORMED,
RECORD_PARSE_FAILED, WORKING_DIR_INVALID.

RED: ``tools.lookup_decision`` does not exist yet — import raises
ModuleNotFoundError (right-reason failure, not a collection error).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from ._agr_fixtures import (
    TOKEN_MID,
    TOKEN_NEW,
    TOKEN_OLD,
    TOKEN_RATIFIED,
    snapshot_tree,
    write_malformed_record,
    write_record,
    write_supersession_chain,
)


def _lookup_decision() -> Callable[..., dict]:
    """Lazily import the not-yet-existing tool (RED discipline).

    The import lives inside each test so COLLECTION succeeds and every test
    FAILS individually with a 'missing implementation' reason rather than a
    module-level collection error masking the file. GREEN creates
    ``tools.lookup_decision.lookup_decision``.
    """
    from hestai_context_mcp.tools.lookup_decision import lookup_decision

    return lookup_decision


class TestHappyPath:
    @pytest.mark.unit
    def test_returns_full_record_shape(self, tmp_path: Path) -> None:
        """§3.2 return shape: ok + record with every defined field + chain."""
        lookup_decision = _lookup_decision()
        write_record(
            tmp_path,
            token=TOKEN_RATIFIED,
            status="RATIFIED",
            tier="STRATEGIC",
            authored_at="2026-06-01T00:00:00Z",
            decision="A binding decision sentence.",
            because="A one-sentence rationale.",
            scope="hestai-context-mcp",
        )
        result = lookup_decision(str(tmp_path), TOKEN_RATIFIED)

        assert result["ok"] is True
        rec = result["record"]
        assert rec["token"] == TOKEN_RATIFIED
        assert rec["type"] == "DECISION_RECORD"
        assert rec["version"] == "1.0"
        assert rec["status"] == "RATIFIED"
        assert rec["tier"] == "STRATEGIC"
        assert rec["decision"] == "A binding decision sentence."
        assert rec["because"] == "A one-sentence rationale."
        assert rec["authored_at"] == "2026-06-01T00:00:00Z"
        # path is repo-relative (§3.2).
        assert rec["path"] == f".hestai/decisions/{TOKEN_RATIFIED}.oct.md"
        assert isinstance(rec["fields"], dict)
        assert rec["fields"].get("SCOPE") == "hestai-context-mcp"
        # Non-superseded record => empty resolution_chain.
        assert result["resolution_chain"] == []

    @pytest.mark.unit
    def test_audience_defaults_to_agent(self, tmp_path: Path) -> None:
        """``audience`` is optional and defaults to 'agent' (§3.2).

        Omitting audience must succeed and yield the agent-shape record;
        passing audience='agent' explicitly yields the identical record.
        """
        lookup_decision = _lookup_decision()
        write_record(tmp_path, token=TOKEN_RATIFIED)
        default = lookup_decision(str(tmp_path), TOKEN_RATIFIED)
        explicit = lookup_decision(str(tmp_path), TOKEN_RATIFIED, audience="agent")
        assert default["record"] == explicit["record"]

    @pytest.mark.unit
    def test_resolves_record_under_subgroup(self, tmp_path: Path) -> None:
        """§1.1: a token under .hestai/decisions/<group>/ resolves identically."""
        lookup_decision = _lookup_decision()
        write_record(tmp_path, token=TOKEN_RATIFIED, group="rfc-arch")
        result = lookup_decision(str(tmp_path), TOKEN_RATIFIED)
        assert result["ok"] is True
        assert result["record"]["path"] == (f".hestai/decisions/rfc-arch/{TOKEN_RATIFIED}.oct.md")


class TestResolutionChain:
    @pytest.mark.unit
    def test_chain_populated_when_superseded(self, tmp_path: Path) -> None:
        """STATUS==SUPERSEDED populates resolution_chain (§3.2)."""
        lookup_decision = _lookup_decision()
        write_supersession_chain(tmp_path)
        result = lookup_decision(str(tmp_path), TOKEN_OLD)
        assert result["ok"] is True
        assert result["record"]["status"] == "SUPERSEDED"
        chain_tokens = [entry["token"] for entry in result["resolution_chain"]]
        # Chain starts at the requested token and walks to the terminal.
        assert chain_tokens == [TOKEN_OLD, TOKEN_MID, TOKEN_NEW]


class TestErrorEnvelope:
    def _assert_envelope(self, result: dict, code: str, category: str) -> None:
        """§3.1.1 envelope assertions shared across error cases."""
        assert result["ok"] is False
        err = result["error"]
        assert err["code"] == code
        assert err["category"] == category
        assert err["tool"] == "lookup_decision"
        assert isinstance(err["message"], str) and err["message"]
        assert isinstance(err["context"], dict)
        assert err["contract_ref"].startswith("ADR-RFC-ARCH-004 §3")

    @pytest.mark.unit
    def test_token_not_found(self, tmp_path: Path) -> None:
        """Well-formed token with no record => TOKEN_NOT_FOUND."""
        lookup_decision = _lookup_decision()
        decisions = tmp_path / ".hestai" / "decisions"
        decisions.mkdir(parents=True, exist_ok=True)
        result = lookup_decision(str(tmp_path), "HO-CONTEXT-MCP-ABSENT-20260101")
        self._assert_envelope(result, "TOKEN_NOT_FOUND", "input_validation")
        assert result["error"]["context"]["token"] == "HO-CONTEXT-MCP-ABSENT-20260101"

    @pytest.mark.unit
    def test_token_malformed(self, tmp_path: Path) -> None:
        """A token failing the §1.3 regex => TOKEN_MALFORMED (not NOT_FOUND)."""
        lookup_decision = _lookup_decision()
        result = lookup_decision(str(tmp_path), "not a valid token")
        self._assert_envelope(result, "TOKEN_MALFORMED", "input_validation")

    @pytest.mark.unit
    def test_record_parse_failed_is_fatal_not_skipped(self, tmp_path: Path) -> None:
        """A discoverable-but-unparseable record => RECORD_PARSE_FAILED (§3.2).

        Implementation choice in the ADR: treat as fatal for the read; do NOT
        silently skip. context.path is populated.
        """
        lookup_decision = _lookup_decision()
        path = write_malformed_record(tmp_path)
        # Look it up by its (valid-format) filename token.
        token = path.stem.replace(".oct", "")
        result = lookup_decision(str(tmp_path), token)
        self._assert_envelope(result, "RECORD_PARSE_FAILED", "schema_violation")
        assert "path" in result["error"]["context"]

    @pytest.mark.unit
    def test_working_dir_invalid(self, tmp_path: Path) -> None:
        """A non-existent working_dir => WORKING_DIR_INVALID (io_failure)."""
        lookup_decision = _lookup_decision()
        missing = tmp_path / "does-not-exist"
        result = lookup_decision(str(missing), TOKEN_RATIFIED)
        self._assert_envelope(result, "WORKING_DIR_INVALID", "io_failure")


class TestPurity:
    @pytest.mark.unit
    def test_lookup_is_pure_no_mutation(self, tmp_path: Path) -> None:
        """PROD I5: lookup_decision performs zero writes/mutations.

        Snapshot every file's (mtime_ns, size) before and after the call; the
        tree must be byte-identical. A MANIFEST side-write or any mutation
        fails the suite.
        """
        lookup_decision = _lookup_decision()
        write_record(tmp_path, token=TOKEN_RATIFIED)
        write_supersession_chain(tmp_path)
        before = snapshot_tree(tmp_path)
        lookup_decision(str(tmp_path), TOKEN_RATIFIED)
        lookup_decision(str(tmp_path), TOKEN_OLD)
        after = snapshot_tree(tmp_path)
        assert before == after
