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
    TOKEN_BROKEN,
    TOKEN_CYCLE_A,
    TOKEN_MID,
    TOKEN_MISSING,
    TOKEN_NEW,
    TOKEN_OLD,
    TOKEN_RATIFIED,
    snapshot_tree,
    write_broken_chain,
    write_cyclic_pair,
    write_malformed_record,
    write_non_agr_record,
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


class TestResolutionChainStatus:
    """Issue #87 - additive ``resolution_chain_status`` completeness signal.

    Contract (ADR-RFC-ARCH-004 3.2, additive per 3.1.1): when a SUPERSEDED
    record's supersession chain is followed, lookup_decision exposes a
    ``resolution_chain_status`` string so a caller can distinguish a chain that
    reached its terminal from one truncated by a broken link or a cycle. The
    value is derived from the existing ``walk_supersession_chain`` outcome:

      * walk outcome ``"ok"``     -> ``"complete"``
      * walk outcome ``"broken"`` -> ``"broken"``  (chain still returned)
      * walk outcome ``"cycle"``  -> ``"cyclic"``  (chain still returned, no hang)

    The signal is additive: it never removes/renames an existing key, and a
    consumer that ignores it is unaffected (back-compat asserted below).
    """

    _FIELD = "resolution_chain_status"
    _ALLOWED = {"complete", "broken", "cyclic"}

    @pytest.mark.unit
    def test_complete_chain_reports_complete(self, tmp_path: Path) -> None:
        """A SUPERSEDED record whose chain reaches a terminal => 'complete'."""
        lookup_decision = _lookup_decision()
        write_supersession_chain(tmp_path)
        result = lookup_decision(str(tmp_path), TOKEN_OLD)

        assert result["ok"] is True
        assert result["record"]["status"] == "SUPERSEDED"
        chain_tokens = [entry["token"] for entry in result["resolution_chain"]]
        assert chain_tokens == [TOKEN_OLD, TOKEN_MID, TOKEN_NEW]
        assert result[self._FIELD] == "complete"

    @pytest.mark.unit
    def test_broken_chain_reports_broken_and_returns_partial(self, tmp_path: Path) -> None:
        """A missing successor TOKEN => 'broken' + the partial chain still returned."""
        lookup_decision = _lookup_decision()
        write_broken_chain(tmp_path)
        result = lookup_decision(str(tmp_path), TOKEN_BROKEN)

        # The read itself still succeeds (the data is correct, just truncated).
        assert result["ok"] is True
        assert result["record"]["status"] == "SUPERSEDED"
        assert result[self._FIELD] == "broken"
        # The entry gathered so far is surfaced (partial resolution, not empty),
        # and the missing successor is NOT fabricated into the chain.
        chain_tokens = [entry["token"] for entry in result["resolution_chain"]]
        assert chain_tokens == [TOKEN_BROKEN]
        assert TOKEN_MISSING not in chain_tokens

    @pytest.mark.unit
    def test_cyclic_chain_reports_cyclic_without_hanging(self, tmp_path: Path) -> None:
        """A SUPERSEDED_BY cycle => 'cyclic', returns (no unbounded walk/hang)."""
        lookup_decision = _lookup_decision()
        write_cyclic_pair(tmp_path)
        result = lookup_decision(str(tmp_path), TOKEN_CYCLE_A)

        assert result["ok"] is True
        assert result["record"]["status"] == "SUPERSEDED"
        assert result[self._FIELD] == "cyclic"
        # Fail-closed cycle detection still surfaces the gathered partial chain.
        assert result["resolution_chain"]

    @pytest.mark.unit
    def test_non_superseded_record_reports_complete(self, tmp_path: Path) -> None:
        """A non-SUPERSEDED record has an empty (untruncated) chain => 'complete'.

        Chosen contract: the empty chain of a terminal/active record is by
        definition not truncated, so the completeness signal is 'complete'. The
        field is always present (a defined PROD::I4 key), never broken/cyclic
        for a record with no supersession chain.
        """
        lookup_decision = _lookup_decision()
        write_record(tmp_path, token=TOKEN_RATIFIED, status="RATIFIED")
        result = lookup_decision(str(tmp_path), TOKEN_RATIFIED)

        assert result["ok"] is True
        assert result["resolution_chain"] == []
        assert result[self._FIELD] == "complete"

    @pytest.mark.unit
    def test_status_value_is_in_allowed_domain(self, tmp_path: Path) -> None:
        """The value is always a member of the closed enum (PROD::I4 defined field)."""
        lookup_decision = _lookup_decision()
        write_supersession_chain(tmp_path)
        result = lookup_decision(str(tmp_path), TOKEN_OLD)
        assert result[self._FIELD] in self._ALLOWED


class TestResolutionChainStatusBackCompat:
    """Back-compat: the additive field must not disturb any existing key.

    ADR-RFC-ARCH-004 3.1.1 permits added fields but forbids removing/renaming
    existing ones; consumers reading only the old keys MUST be unaffected.
    """

    _EXISTING_TOP_KEYS = {"ok", "record", "resolution_chain"}
    _EXISTING_RECORD_KEYS = {
        "token",
        "type",
        "version",
        "status",
        "tier",
        "decision",
        "because",
        "authored_at",
        "path",
        "fields",
    }

    @pytest.mark.unit
    def test_existing_keys_unchanged_for_superseded(self, tmp_path: Path) -> None:
        """Every pre-#87 key is still present with its prior value/shape."""
        lookup_decision = _lookup_decision()
        write_supersession_chain(tmp_path)
        result = lookup_decision(str(tmp_path), TOKEN_OLD)

        # No existing key removed/renamed (additive-only: superset is allowed).
        assert set(result) >= self._EXISTING_TOP_KEYS
        assert set(result["record"]) >= self._EXISTING_RECORD_KEYS
        # Existing values are byte-stable.
        assert result["ok"] is True
        assert result["record"]["token"] == TOKEN_OLD
        assert result["record"]["status"] == "SUPERSEDED"
        assert [e["token"] for e in result["resolution_chain"]] == [
            TOKEN_OLD,
            TOKEN_MID,
            TOKEN_NEW,
        ]
        # The only new top-level key is the additive completeness signal.
        assert set(result) - self._EXISTING_TOP_KEYS == {"resolution_chain_status"}

    @pytest.mark.unit
    def test_existing_keys_unchanged_for_non_superseded(self, tmp_path: Path) -> None:
        """The non-superseded happy path keeps its exact pre-#87 key set."""
        lookup_decision = _lookup_decision()
        write_record(tmp_path, token=TOKEN_RATIFIED, scope="hestai-context-mcp")
        result = lookup_decision(str(tmp_path), TOKEN_RATIFIED)

        assert set(result) >= self._EXISTING_TOP_KEYS
        assert set(result["record"]) >= self._EXISTING_RECORD_KEYS
        assert result["resolution_chain"] == []
        assert set(result) - self._EXISTING_TOP_KEYS == {"resolution_chain_status"}


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


class TestCoLocatedNonAgrFiles:
    """F1 (CIV NO-GO regression): a co-located non-AGR must never resolve as a
    record. A token that only matches a non-AGR is TOKEN_NOT_FOUND, not a hit.
    """

    @pytest.mark.unit
    def test_token_matching_only_a_non_agr_is_not_found(self, tmp_path: Path) -> None:
        """A non-AGR whose filename embeds a valid-format token does not resolve.

        We name a BUILD_PLAN with a DECISION_RECORD-looking filename token; since
        the file is not a DECISION_RECORD (wrong sentinel/type, no TOKEN field),
        discover_record must reject it and lookup must return TOKEN_NOT_FOUND.
        """
        lookup_decision = _lookup_decision()
        decoy_token = "HO-CONTEXT-MCP-DECOY-NONAGR-20260601"
        write_non_agr_record(
            tmp_path,
            filename=f"{decoy_token}.oct.md",
            sentinel="B1_BUILD_PLAN",
            type_field="BUILD_PLAN",
            type_key="DOCUMENT_TYPE",
        )
        result = lookup_decision(str(tmp_path), decoy_token)
        assert result["ok"] is False
        assert result["error"]["code"] == "TOKEN_NOT_FOUND"


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
