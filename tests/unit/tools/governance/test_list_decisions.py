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
FILTER_INVALID for a bad enum, WORKING_DIR_INVALID for a bad path,
RECORD_PARSE_FAILED fails the WHOLE call (no silent drop) per §3.3.

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
    def test_record_parse_failed_fails_whole_call(self, tmp_path: Path) -> None:
        """§3.3: a single unparseable record fails the WHOLE call, no silent drop.

        Consumers MUST be able to detect that the list is incomplete; the tool
        therefore returns the error envelope rather than dropping the bad file.
        """
        list_decisions = _list_decisions()
        write_record(tmp_path, token=_T1, authored_at="2026-01-01T00:00:00Z")
        write_malformed_record(tmp_path)
        result = list_decisions(str(tmp_path))
        self._assert_envelope(result, "RECORD_PARSE_FAILED", "schema_violation")


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
    def test_malformed_agr_still_errors_amid_non_agrs(self, tmp_path: Path) -> None:
        """§3.3 protection intact: an is-an-AGR-but-broken record errors even when
        co-located non-AGRs are present (the non-AGRs are not what trips it)."""
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
        assert result["ok"] is False
        assert result["error"]["code"] == "RECORD_PARSE_FAILED"
        # The failing path is the broken AGR, not the legitimately-typed non-AGR.
        assert "MALFORMED" in result["error"]["context"]["path"]


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
