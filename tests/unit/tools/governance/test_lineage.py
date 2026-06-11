"""Lineage edge-resolution guard (ADR-RFC-ARCH-004 §4.1 #8).

AMENDS / EXTENDS / SUPERSEDED_BY references MUST resolve to TOKENs present in
the SAME repository. A dangling same-repo edge is reported as a STRUCTURED
finding (PROD I4) — never a crash. Cross-repo edges (repo:<id>:... / pin:...)
are advisory / out of scope per §2.4 and are NEVER flagged as dangling.

Cohort-isolation nuance: a dangling AMENDS whose target exists in the full
corpus but not in a test subset (e.g. HO-PRODUCTION-TYPE-VARIANCE-PRICING-…)
is an EXPECTED isolation case, not a defect. Callers mark such targets via
``expected_isolated_tokens``; the guard separates them from genuine defects in
the structured output.
"""

from pathlib import Path

import pytest

from hestai_context_mcp.tools.governance.lineage import resolve_lineage_edges

# Non-secret governance identifiers (constants keep secret scanners quiet).
_SELF = "HO-CONTEXT-MCP-SELF-20260610"
_LIVE_TARGET = "HO-CONTEXT-MCP-LIVE-TARGET-20260610"
_OTHER_TARGET = "HO-CONTEXT-MCP-OTHER-TARGET-20260610"
_DANGLING = "HO-CONTEXT-MCP-MISSING-TARGET-20260610"
# Cohort-isolation target: exists in the full corpus, absent from a test subset.
_COHORT_ISOLATED = "HO-PRODUCTION-TYPE-VARIANCE-PRICING-20260513"


def _seed_record(working_dir: Path, token: str) -> None:
    """Write a minimal in-repo DECISION_RECORD so ``token`` resolves."""
    decisions = working_dir / ".hestai" / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    (decisions / f"{token}.oct.md").write_text(
        "===DECISION_RECORD===\n"
        "META:\n"
        "  TYPE::DECISION_RECORD\n"
        f"  TOKEN::{token}\n"
        "===END===\n"
    )


def _record_with_edges(
    *,
    token: str,
    amends: list[str] | None = None,
    extends: list[str] | None = None,
    superseded_by: str | None = None,
) -> str:
    """Build raw OCTAVE content carrying bare-TOKEN lineage edges."""
    lines = [
        "===DECISION_RECORD===",
        "META:",
        "  TYPE::DECISION_RECORD",
        f"  TOKEN::{token}",
    ]
    if amends is not None:
        lines.append(f"  AMENDS::[{', '.join(amends)}]")
    if extends is not None:
        lines.append(f"  EXTENDS::[{', '.join(extends)}]")
    if superseded_by is not None:
        lines.append(f"  SUPERSEDED_BY::{superseded_by}")
    lines.append("===END===")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Happy path + no-edge
# ---------------------------------------------------------------------------


class TestResolvedEdges:
    @pytest.mark.unit
    def test_no_edges_is_ok(self, tmp_path: Path) -> None:
        """A record with no lineage edges resolves cleanly."""
        finding = resolve_lineage_edges(tmp_path, _record_with_edges(token=_SELF))
        assert finding["ok"] is True
        assert finding["dangling"] == []
        assert finding["expected_isolated"] == []

    @pytest.mark.unit
    def test_all_edges_resolve_in_repo(self, tmp_path: Path) -> None:
        """When every AMENDS/EXTENDS target exists in-repo, ok=True."""
        _seed_record(tmp_path, _LIVE_TARGET)
        _seed_record(tmp_path, _OTHER_TARGET)
        content = _record_with_edges(token=_SELF, amends=[_LIVE_TARGET], extends=[_OTHER_TARGET])
        finding = resolve_lineage_edges(tmp_path, content)
        assert finding["ok"] is True
        assert finding["dangling"] == []

    @pytest.mark.unit
    def test_quoted_and_bare_targets_both_resolve(self, tmp_path: Path) -> None:
        """Edge list entries resolve whether the stored TOKEN is bare or quoted."""
        # Stored bare:
        _seed_record(tmp_path, _LIVE_TARGET)
        # Stored quoted:
        decisions = tmp_path / ".hestai" / "decisions"
        (decisions / f"{_OTHER_TARGET}.oct.md").write_text(
            f'===DECISION_RECORD===\nMETA:\n  TOKEN::"{_OTHER_TARGET}"\n===END===\n'
        )
        content = _record_with_edges(token=_SELF, amends=[_LIVE_TARGET, _OTHER_TARGET])
        finding = resolve_lineage_edges(tmp_path, content)
        assert finding["ok"] is True
        assert finding["dangling"] == []


# ---------------------------------------------------------------------------
# Dangling same-repo edges -> structured finding (NOT a crash)
# ---------------------------------------------------------------------------


class TestDanglingEdges:
    @pytest.mark.unit
    def test_dangling_amends_reported_as_structured_finding(self, tmp_path: Path) -> None:
        """A dangling same-repo AMENDS is a structured finding, not an exception."""
        content = _record_with_edges(token=_SELF, amends=[_DANGLING])
        finding = resolve_lineage_edges(tmp_path, content)
        assert finding["ok"] is False
        assert len(finding["dangling"]) == 1
        edge = finding["dangling"][0]
        assert edge["edge_type"] == "AMENDS"
        assert edge["source"] == _SELF
        assert edge["target"] == _DANGLING
        assert edge["scope"] == "same-repo"

    @pytest.mark.unit
    def test_dangling_superseded_by_reported(self, tmp_path: Path) -> None:
        """A dangling SUPERSEDED_BY is reported as a same-repo dangling edge."""
        content = _record_with_edges(token=_SELF, superseded_by=_DANGLING)
        finding = resolve_lineage_edges(tmp_path, content)
        assert finding["ok"] is False
        types = {e["edge_type"] for e in finding["dangling"]}
        assert types == {"SUPERSEDED_BY"}

    @pytest.mark.unit
    def test_mixed_extends_partial_dangle(self, tmp_path: Path) -> None:
        """One resolvable + one dangling EXTENDS target -> exactly one dangle."""
        _seed_record(tmp_path, _LIVE_TARGET)
        content = _record_with_edges(token=_SELF, extends=[_LIVE_TARGET, _DANGLING])
        finding = resolve_lineage_edges(tmp_path, content)
        assert finding["ok"] is False
        dangling_targets = [e["target"] for e in finding["dangling"]]
        assert dangling_targets == [_DANGLING]

    @pytest.mark.unit
    def test_never_raises_on_malformed_content(self, tmp_path: Path) -> None:
        """Garbage content yields a structured finding, never an exception."""
        finding = resolve_lineage_edges(tmp_path, "not octave at all :: %%%")
        assert finding["ok"] is True
        assert finding["dangling"] == []

    @pytest.mark.unit
    def test_internal_failure_is_caught_and_structured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unexpected exception inside resolution is caught (fail-safe).

        If the deterministic lookup raises (e.g. a transient FS fault), the
        guard must NOT propagate — it returns a structured finding with the
        edges gathered so far rather than crashing the caller (PROD I4).
        """

        def boom(*_args: object, **_kwargs: object) -> bool:
            raise RuntimeError("simulated lookup fault")

        monkeypatch.setattr(
            "hestai_context_mcp.tools.governance.lineage.lookup_token_deterministic",
            boom,
        )
        content = _record_with_edges(token=_SELF, amends=[_DANGLING])
        finding = resolve_lineage_edges(tmp_path, content)
        # No exception escaped; the structure is intact. The fault aborted
        # resolution before the dangle was recorded, so ok stays True.
        assert finding["ok"] is True
        assert finding["dangling"] == []
        assert finding["source"] == _SELF


# ---------------------------------------------------------------------------
# Cross-repo edges -> advisory / out of scope (§2.4)
# ---------------------------------------------------------------------------


class TestCrossRepoEdges:
    @pytest.mark.unit
    def test_repo_prefixed_edge_is_out_of_scope(self, tmp_path: Path) -> None:
        """A repo:<id>:... cross-repo edge is never flagged as dangling."""
        content = _record_with_edges(
            token=_SELF,
            amends=["repo:elevanaltd/hestai-workbench:.hestai/decisions/x.oct.md@main"],
        )
        finding = resolve_lineage_edges(tmp_path, content)
        assert finding["ok"] is True
        assert finding["dangling"] == []
        assert len(finding["cross_repo"]) == 1
        assert finding["cross_repo"][0]["scope"] == "cross-repo"

    @pytest.mark.unit
    def test_pin_prefixed_edge_is_out_of_scope(self, tmp_path: Path) -> None:
        """A pin:<url>... external pin is advisory and not dangling."""
        content = _record_with_edges(
            token=_SELF,
            extends=["pin:https://github.com/elevanaltd/x/blob/abc/d.md@abc"],
        )
        finding = resolve_lineage_edges(tmp_path, content)
        assert finding["ok"] is True
        assert finding["dangling"] == []
        assert len(finding["cross_repo"]) == 1


# ---------------------------------------------------------------------------
# Cohort-isolation expected case (NOT a defect)
# ---------------------------------------------------------------------------


class TestCohortIsolation:
    @pytest.mark.unit
    def test_expected_isolated_target_is_not_a_defect(self, tmp_path: Path) -> None:
        """A dangling target marked expected-isolated is handled, not a defect.

        The target exists in the full corpus but is absent from this test
        subset (cohort isolation). It is reported in ``expected_isolated``,
        kept OUT of ``dangling``, and does NOT set ok=False.
        """
        content = _record_with_edges(token=_SELF, amends=[_COHORT_ISOLATED])
        finding = resolve_lineage_edges(
            tmp_path, content, expected_isolated_tokens={_COHORT_ISOLATED}
        )
        assert finding["ok"] is True
        assert finding["dangling"] == []
        assert len(finding["expected_isolated"]) == 1
        iso = finding["expected_isolated"][0]
        assert iso["target"] == _COHORT_ISOLATED
        assert iso["edge_type"] == "AMENDS"

    @pytest.mark.unit
    def test_expected_isolation_does_not_mask_real_dangle(self, tmp_path: Path) -> None:
        """A genuine dangle alongside an expected-isolated target is still caught.

        Cohort isolation must not become a blanket suppression: only the
        explicitly-listed isolated target is excused; any OTHER unresolved
        same-repo target remains a defect.
        """
        content = _record_with_edges(token=_SELF, amends=[_COHORT_ISOLATED, _DANGLING])
        finding = resolve_lineage_edges(
            tmp_path, content, expected_isolated_tokens={_COHORT_ISOLATED}
        )
        assert finding["ok"] is False
        assert [e["target"] for e in finding["dangling"]] == [_DANGLING]
        assert [e["target"] for e in finding["expected_isolated"]] == [_COHORT_ISOLATED]
