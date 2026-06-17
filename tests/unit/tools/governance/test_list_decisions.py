"""RED suite — ``list_decisions`` MCP tool.

Contract: ADR-RFC-ARCH-004 §3.3 (return shape) + §3.1.1 (error envelope).
Pure read (PROD I5), structured return (PROD I4).

Return::

    {
      "ok": true,
      "records": [{token, status, tier, decision, authored_at, path}, ...],
      "total": <int>
    }

sorted by authored_at DESCENDING. Optional scope/status/tier filters.
FILTER_INVALID for a bad enum, WORKING_DIR_INVALID for a bad path. A record
that IS a DECISION_RECORD but fails to parse is NOT fatal: the parseable
records are still returned and each unparseable one is reported in an explicit
``skipped`` array (§3.3). This satisfies the §3.3 invariant — consumers MUST be
able to detect that the list is incomplete — without one legacy/malformed file
blinding the entire index. (Silent drop remains forbidden.)

RED: ``tools.list_decisions`` does not exist yet — import raises
ModuleNotFoundError.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from ._agr_fixtures import (
    snapshot_tree,
    write_malformed_record,
    write_non_agr_record,
    write_record,
)


def _list_decisions() -> Callable[..., dict]:
    """Lazily import the not-yet-existing tool (RED discipline).

    Import-inside-test keeps COLLECTION green and yields a per-test
    'missing implementation' failure. GREEN creates
    ``tools.list_decisions.list_decisions``.
    """
    from hestai_context_mcp.tools.list_decisions import list_decisions

    return list_decisions


_T1 = "HO-CONTEXT-MCP-LIST-ONE-20260101"
_T2 = "HO-CONTEXT-MCP-LIST-TWO-20260201"
_T3 = "HO-CONTEXT-MCP-LIST-THREE-20260301"


def _seed_three(tmp_path: Path) -> None:
    """Three records spanning statuses/tiers/scopes for filter + sort tests."""
    write_record(
        tmp_path,
        token=_T1,
        status="RATIFIED",
        tier="STRATEGIC",
        authored_at="2026-01-01T00:00:00Z",
        scope="hestai-context-mcp",
    )
    write_record(
        tmp_path,
        token=_T2,
        status="SUPERSEDED",
        tier="TACTICAL",
        authored_at="2026-02-01T00:00:00Z",
        scope="elevana-studio",
        superseded_by=_T3,
    )
    write_record(
        tmp_path,
        token=_T3,
        status="RATIFIED",
        tier="OPERATIONAL",
        authored_at="2026-03-01T00:00:00Z",
        scope="hestai-context-mcp",
    )


class TestHappyPath:
    @pytest.mark.unit
    def test_lists_all_records_sorted_desc(self, tmp_path: Path) -> None:
        """§3.3: records sorted by authored_at DESC, total reflects count."""
        list_decisions = _list_decisions()
        _seed_three(tmp_path)
        result = list_decisions(str(tmp_path))
        assert result["ok"] is True
        assert result["total"] == 3
        tokens = [r["token"] for r in result["records"]]
        # Newest first.
        assert tokens == [_T3, _T2, _T1]

    @pytest.mark.unit
    def test_record_summary_shape(self, tmp_path: Path) -> None:
        """Each entry exposes exactly the §3.3 summary fields."""
        list_decisions = _list_decisions()
        write_record(tmp_path, token=_T1, authored_at="2026-01-01T00:00:00Z")
        result = list_decisions(str(tmp_path))
        entry = result["records"][0]
        assert set(entry.keys()) == {
            "token",
            "status",
            "tier",
            "decision",
            "authored_at",
            "path",
        }
        assert entry["path"] == f".hestai/decisions/{_T1}.oct.md"

    @pytest.mark.unit
    def test_empty_store_returns_empty_list(self, tmp_path: Path) -> None:
        """No records => ok with empty list and total 0 (not an error)."""
        list_decisions = _list_decisions()
        (tmp_path / ".hestai" / "decisions").mkdir(parents=True, exist_ok=True)
        result = list_decisions(str(tmp_path))
        assert result["ok"] is True
        assert result["records"] == []
        assert result["total"] == 0


class TestFilters:
    @pytest.mark.unit
    def test_status_filter(self, tmp_path: Path) -> None:
        """status filter narrows to matching records only."""
        list_decisions = _list_decisions()
        _seed_three(tmp_path)
        result = list_decisions(str(tmp_path), status="RATIFIED")
        assert result["ok"] is True
        assert {r["token"] for r in result["records"]} == {_T1, _T3}
        assert result["total"] == 2

    @pytest.mark.unit
    def test_tier_filter(self, tmp_path: Path) -> None:
        """tier filter narrows by semantic-gravity tier."""
        list_decisions = _list_decisions()
        _seed_three(tmp_path)
        result = list_decisions(str(tmp_path), tier="TACTICAL")
        assert [r["token"] for r in result["records"]] == [_T2]

    @pytest.mark.unit
    def test_scope_filter_exact_match(self, tmp_path: Path) -> None:
        """scope filter matches the SCOPE field exactly (§3.3)."""
        list_decisions = _list_decisions()
        _seed_three(tmp_path)
        result = list_decisions(str(tmp_path), scope="elevana-studio")
        assert [r["token"] for r in result["records"]] == [_T2]

    @pytest.mark.unit
    def test_combined_filters(self, tmp_path: Path) -> None:
        """status + scope filters compose conjunctively."""
        list_decisions = _list_decisions()
        _seed_three(tmp_path)
        result = list_decisions(str(tmp_path), status="RATIFIED", scope="hestai-context-mcp")
        assert {r["token"] for r in result["records"]} == {_T1, _T3}


class TestErrorEnvelope:
    def _assert_envelope(self, result: dict, code: str, category: str) -> None:
        assert result["ok"] is False
        err = result["error"]
        assert err["code"] == code
        assert err["category"] == category
        assert err["tool"] == "list_decisions"
        assert isinstance(err["message"], str) and err["message"]
        assert isinstance(err["context"], dict)
        assert err["contract_ref"].startswith("ADR-RFC-ARCH-004 §3")

    @pytest.mark.unit
    def test_filter_invalid_status(self, tmp_path: Path) -> None:
        """A non-enum status => FILTER_INVALID with field+value context (§3.3)."""
        list_decisions = _list_decisions()
        _seed_three(tmp_path)
        result = list_decisions(str(tmp_path), status="BOGUS")
        self._assert_envelope(result, "FILTER_INVALID", "input_validation")
        assert result["error"]["context"]["field"] == "status"
        assert result["error"]["context"]["value"] == "BOGUS"

    @pytest.mark.unit
    def test_filter_invalid_tier(self, tmp_path: Path) -> None:
        """A non-enum tier => FILTER_INVALID."""
        list_decisions = _list_decisions()
        _seed_three(tmp_path)
        result = list_decisions(str(tmp_path), tier="HUGE")
        self._assert_envelope(result, "FILTER_INVALID", "input_validation")
        assert result["error"]["context"]["field"] == "tier"

    @pytest.mark.unit
    def test_working_dir_invalid(self, tmp_path: Path) -> None:
        """Non-existent working_dir => WORKING_DIR_INVALID."""
        list_decisions = _list_decisions()
        result = list_decisions(str(tmp_path / "nope"))
        self._assert_envelope(result, "WORKING_DIR_INVALID", "io_failure")

    @pytest.mark.unit
    def test_malformed_record_does_not_blind_the_index(self, tmp_path: Path) -> None:
        """§3.3: a single unparseable record is reported in ``skipped`` — NOT fatal.

        The parseable record is still returned, and the malformed one surfaces in
        the explicit ``skipped`` array so the consumer can detect the list is
        incomplete. One legacy/non-conforming file must not blind the whole index.
        """
        list_decisions = _list_decisions()
        write_record(tmp_path, token=_T1, authored_at="2026-01-01T00:00:00Z")
        write_malformed_record(tmp_path)
        result = list_decisions(str(tmp_path))
        # Parseable record is still listed.
        assert result["ok"] is True
        assert [r["token"] for r in result["records"]] == [_T1]
        assert result["total"] == 1
        # The malformed AGR is surfaced, not silently dropped.
        assert len(result["skipped"]) == 1
        skipped = result["skipped"][0]
        assert "MALFORMED" in skipped["path"]
        assert isinstance(skipped["parse_error"], str) and skipped["parse_error"]


class TestCoLocatedNonAgrFiles:
    """F1 (CIV NO-GO regression): ``.hestai/decisions/`` co-hosts non-AGR
    governance artefacts (BUILD_PLAN, SECURITY_DESIGN_REVIEW, arbitration
    records) per ADR-RFC-ARCH-001. They are OUT OF SCOPE and must be skipped
    silently — never RECORD_PARSE_FAILED — while genuinely-malformed AGRs still
    error.
    """

    @pytest.mark.unit
    def test_non_agr_files_excluded_not_errored(self, tmp_path: Path) -> None:
        """Real AGRs are listed; co-located non-AGRs are silently skipped."""
        list_decisions = _list_decisions()
        # Two valid DECISION_RECORDs.
        write_record(tmp_path, token=_T1, authored_at="2026-01-01T00:00:00Z")
        write_record(tmp_path, token=_T3, authored_at="2026-03-01T00:00:00Z")
        # A correctly-placed BUILD_PLAN (DOCUMENT_TYPE convention, no TOKEN).
        write_non_agr_record(
            tmp_path,
            filename="BUILD-PLAN.oct.md",
            sentinel="B1_BUILD_PLAN",
            type_field="BUILD_PLAN",
            type_key="DOCUMENT_TYPE",
            group="phase-pss-b1",
        )
        # A no-TYPE arbitration record (no TYPE line at all).
        write_non_agr_record(
            tmp_path,
            filename="arbitration-1.oct.md",
            sentinel="B1_GATE_ARBITRATION_RECORD",
            type_field=None,
            group="phase-pss-b1",
        )
        # A SECURITY_DESIGN_REVIEW (declares TYPE, but not DECISION_RECORD) in a
        # nested subdir.
        write_non_agr_record(
            tmp_path,
            filename="issue-43-redaction-design.oct.md",
            sentinel="REDACTION_DESIGN_REVIEW",
            type_field="SECURITY_DESIGN_REVIEW",
            group="security",
        )

        result = list_decisions(str(tmp_path))
        assert result["ok"] is True
        # Only the two real AGRs are listed — non-AGRs excluded entirely.
        assert result["total"] == 2
        tokens = [r["token"] for r in result["records"]]
        assert tokens == [_T3, _T1]  # sorted authored_at DESC

    @pytest.mark.unit
    def test_suffixed_type_field_does_not_falsely_qualify(self, tmp_path: Path) -> None:
        """CRS P2 (same class as F1): a non-AGR whose META carries a
        ``*TYPE::DECISION_RECORD`` line (``DOCUMENT_TYPE::`` / ``CONTENT_TYPE::``)
        and NO ``===DECISION_RECORD===`` sentinel must be EXCLUDED, not admitted.

        The pre-fix TYPE detection used an unanchored substring search, so
        ``DOCUMENT_TYPE::DECISION_RECORD`` matched ``TYPE::DECISION_RECORD`` and
        tripped RECORD_PARSE_FAILED. The anchored read-side check rejects it.
        """
        list_decisions = _list_decisions()
        write_record(tmp_path, token=_T1, authored_at="2026-01-01T00:00:00Z")
        # DOCUMENT_TYPE::DECISION_RECORD — substring-leak variant.
        write_non_agr_record(
            tmp_path,
            filename="doc-type-decoy.oct.md",
            sentinel="B1_BUILD_PLAN",
            type_field="DECISION_RECORD",
            type_key="DOCUMENT_TYPE",
        )
        # CONTENT_TYPE::DECISION_RECORD — second substring-leak variant.
        write_non_agr_record(
            tmp_path,
            filename="content-type-decoy.oct.md",
            sentinel="SOME_DOC",
            type_field="DECISION_RECORD",
            type_key="CONTENT_TYPE",
        )

        result = list_decisions(str(tmp_path))
        assert result["ok"] is True  # NOT RECORD_PARSE_FAILED
        assert result["total"] == 1
        assert [r["token"] for r in result["records"]] == [_T1]

    @pytest.mark.unit
    def test_only_non_agr_files_yields_empty_list(self, tmp_path: Path) -> None:
        """A store with ONLY non-AGR artefacts lists nothing (no error)."""
        list_decisions = _list_decisions()
        write_non_agr_record(
            tmp_path,
            filename="BUILD-PLAN.oct.md",
            sentinel="B1_BUILD_PLAN",
            type_field="BUILD_PLAN",
            type_key="DOCUMENT_TYPE",
        )
        result = list_decisions(str(tmp_path))
        assert result["ok"] is True
        assert result["records"] == []
        assert result["total"] == 0

    @pytest.mark.unit
    def test_malformed_agr_skipped_amid_non_agrs(self, tmp_path: Path) -> None:
        """§3.3 distinction intact: a co-located non-AGR is excluded silently
        (out of scope), while an is-an-AGR-but-broken record is reported in
        ``skipped`` (in scope, but unparseable) — not conflated with the non-AGR."""
        list_decisions = _list_decisions()
        write_record(tmp_path, token=_T1, authored_at="2026-01-01T00:00:00Z")
        write_non_agr_record(
            tmp_path,
            filename="BUILD-PLAN.oct.md",
            sentinel="B1_BUILD_PLAN",
            type_field="BUILD_PLAN",
            type_key="DOCUMENT_TYPE",
        )
        write_malformed_record(tmp_path)  # declares DECISION_RECORD, missing fields
        result = list_decisions(str(tmp_path))
        assert result["ok"] is True
        assert [r["token"] for r in result["records"]] == [_T1]
        # Exactly the broken AGR is skipped — the non-AGR is excluded entirely,
        # not reported as a skip.
        assert len(result["skipped"]) == 1
        assert "MALFORMED" in result["skipped"][0]["path"]


class TestGracefulDegradation:
    """§3.3 graceful fallback: a clean store reports an empty ``skipped`` array;
    unparseable records degrade the call to a partial result, never an error."""

    @pytest.mark.unit
    def test_clean_store_has_empty_skipped(self, tmp_path: Path) -> None:
        """When every record parses, ``skipped`` is present and empty — so a
        consumer can unconditionally read it as the incompleteness signal."""
        list_decisions = _list_decisions()
        _seed_three(tmp_path)
        result = list_decisions(str(tmp_path))
        assert result["ok"] is True
        assert result["total"] == 3
        assert result["skipped"] == []

    @pytest.mark.unit
    def test_multiple_malformed_all_reported(self, tmp_path: Path) -> None:
        """Every unparseable record is surfaced; the count is not capped."""
        list_decisions = _list_decisions()
        write_record(tmp_path, token=_T1, authored_at="2026-01-01T00:00:00Z")
        write_malformed_record(tmp_path)
        # A second malformed AGR under a nested decisions subdir.
        nested = tmp_path / ".hestai" / "decisions" / "rfc-arch"
        nested.mkdir(parents=True, exist_ok=True)
        (nested / "HO-CONTEXT-MCP-BROKEN-20260701.oct.md").write_text(
            "===DECISION_RECORD===\n"
            "META:\n"
            "  TYPE::DECISION_RECORD\n"
            '  VERSION::"1.0"\n'
            "  TOKEN::HO-CONTEXT-MCP-BROKEN-20260701\n"
            "===END===\n",
            encoding="utf-8",
        )
        result = list_decisions(str(tmp_path))
        assert result["ok"] is True
        assert [r["token"] for r in result["records"]] == [_T1]
        assert len(result["skipped"]) == 2
        # Each skip entry carries path + parse_error.
        for entry in result["skipped"]:
            assert entry["path"].endswith(".oct.md")
            assert isinstance(entry["parse_error"], str) and entry["parse_error"]


class TestPurity:
    @pytest.mark.unit
    def test_list_is_pure_no_mutation(self, tmp_path: Path) -> None:
        """PROD I5: list_decisions performs zero writes/mutations."""
        list_decisions = _list_decisions()
        _seed_three(tmp_path)
        before = snapshot_tree(tmp_path)
        list_decisions(str(tmp_path))
        list_decisions(str(tmp_path), status="RATIFIED")
        after = snapshot_tree(tmp_path)
        assert before == after
