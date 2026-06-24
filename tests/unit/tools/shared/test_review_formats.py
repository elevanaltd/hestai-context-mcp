"""Regression tests for review-gate verdict-synonym tolerance.

TDD RED phase: these tests are written BEFORE the matcher widening and
must FAIL against the canonical ``\\bAPPROVED\\b`` matcher.

Regression target — elevana-studio PR #1257 (TIER_3_CRITICAL, reviewers
[CE, CIV, CRS, TMG]): an agent posted a verdict summary table with cells
reading "✅ APPROVE" (no trailing D) for CRS/CIV/TMG and "✅ GO" for CE.
GO cleared (already accepted); APPROVE failed the canonical matcher,
forcing a manual re-post. The table STRUCTURE already parsed
(matches_approval_pattern strips bold/headings and anchors role prefixes
after a "|" pipe); only the verb conjugation broke.

Contract pinned here: APPROVE and APPROVES are accepted as synonyms of
APPROVED wherever APPROVED is, for all approval roles, WITHOUT weakening
anchoring (role prefix at line-start or immediately after a pipe) or word
boundaries. The deliberately-strict anti-spoof path has_crs_model_approval
is intentionally excluded and stays APPROVED|GO only.
"""

import pytest


@pytest.mark.unit
class TestVerdictSynonymTolerance:
    """APPROVE / APPROVES accepted as synonyms of APPROVED (read-side)."""

    # The #1257 verdict summary table (reconstructed structure).
    _PR_1257_TABLE = (
        "## Review Summary\n"
        "\n"
        "| Role | Reviewer | Verdict | Notes |\n"
        "| --- | --- | --- | --- |\n"
        "| **CRS** (code-review-specialist) | Gemini | ✅ APPROVE | clean diff |\n"
        "| **CIV** (critical-implementation-validator) | Codex | ✅ APPROVE | spec ok |\n"
        "| **TMG** (test-methodology-guardian) | Goose | ✅ APPROVE | tests sound |\n"
        "| **CE** (critical-engineer) | Claude | ✅ GO | ship it |\n"
    )

    def test_pr_1257_table_approve_clears_crs(self) -> None:
        """CRS '✅ APPROVE' table cell clears the gate (regression #1257)."""
        from hestai_context_mcp.tools.shared.review_formats import has_crs_approval

        assert has_crs_approval([self._PR_1257_TABLE])

    def test_pr_1257_table_approve_clears_civ(self) -> None:
        """CIV '✅ APPROVE' table cell clears the gate (regression #1257)."""
        from hestai_context_mcp.tools.shared.review_formats import has_civ_approval

        assert has_civ_approval([self._PR_1257_TABLE])

    def test_pr_1257_table_approve_clears_tmg(self) -> None:
        """TMG '✅ APPROVE' table cell clears the gate (regression #1257)."""
        from hestai_context_mcp.tools.shared.review_formats import has_tmg_approval

        assert has_tmg_approval([self._PR_1257_TABLE])

    def test_pr_1257_table_go_still_clears_ce(self) -> None:
        """CE '✅ GO' table cell still clears the gate (unchanged)."""
        from hestai_context_mcp.tools.shared.review_formats import has_ce_approval

        assert has_ce_approval([self._PR_1257_TABLE])

    def test_approve_synonym_matches_via_pattern(self) -> None:
        """matches_approval_pattern accepts APPROVE when keyword is APPROVED."""
        from hestai_context_mcp.tools.shared.review_formats import matches_approval_pattern

        assert matches_approval_pattern("CRS APPROVE: looks good", "CRS", "APPROVED")

    def test_approves_synonym_matches_via_pattern(self) -> None:
        """matches_approval_pattern accepts APPROVES when keyword is APPROVED."""
        from hestai_context_mcp.tools.shared.review_formats import matches_approval_pattern

        assert matches_approval_pattern("CRS APPROVES this change", "CRS", "APPROVED")

    def test_approved_still_matches(self) -> None:
        """Canonical APPROVED still matches after the synonym widening."""
        from hestai_context_mcp.tools.shared.review_formats import matches_approval_pattern

        assert matches_approval_pattern("CRS APPROVED: ok", "CRS", "APPROVED")

    @pytest.mark.parametrize(
        "checker_name",
        [
            "has_crs_approval",
            "has_ce_approval",
            "has_tmg_approval",
            "has_civ_approval",
            "has_pe_approval",
            "has_sr_approval",
            "has_gr_approval",
        ],
    )
    def test_approve_accepted_for_all_roles(self, checker_name: str) -> None:
        """APPROVE clears the gate for every approval role (incl. legacy GR)."""
        import hestai_context_mcp.tools.shared.review_formats as rf

        checker = getattr(rf, checker_name)
        prefix = "GR" if checker_name == "has_gr_approval" else checker_name.split("_")[1].upper()
        assert checker([f"{prefix} APPROVE: looks good"])

    @pytest.mark.parametrize(
        "checker_name",
        [
            "has_crs_approval",
            "has_ce_approval",
            "has_tmg_approval",
            "has_civ_approval",
            "has_pe_approval",
            "has_sr_approval",
            "has_gr_approval",
        ],
    )
    def test_approves_accepted_for_all_roles(self, checker_name: str) -> None:
        """APPROVES clears the gate for every approval role (incl. legacy GR)."""
        import hestai_context_mcp.tools.shared.review_formats as rf

        checker = getattr(rf, checker_name)
        prefix = "GR" if checker_name == "has_gr_approval" else checker_name.split("_")[1].upper()
        assert checker([f"{prefix} APPROVES this change"])

    def test_unanchored_prose_approve_does_not_match(self) -> None:
        """Prose 'I would approve this change.' must NOT satisfy CRS approval.

        No anchored role prefix precedes the verb, so the gate must not clear.
        """
        from hestai_context_mcp.tools.shared.review_formats import has_crs_approval

        assert not has_crs_approval(["I would approve this change."])

    def test_bare_approve_no_role_does_not_match(self) -> None:
        """A bare 'approve' with no anchored role prefix is not an approval."""
        from hestai_context_mcp.tools.shared.review_formats import has_crs_approval

        assert not has_crs_approval(["approve"])

    def test_approve_keyword_does_not_overmatch_longer_word(self) -> None:
        """Word boundaries hold: 'APPROVEMENT' must not satisfy the matcher."""
        from hestai_context_mcp.tools.shared.review_formats import matches_approval_pattern

        assert not matches_approval_pattern("CRS APPROVEMENT pending", "CRS", "APPROVED")

    def test_model_approval_path_unchanged_rejects_bare_approve(self) -> None:
        """has_crs_model_approval stays strict: bare APPROVE (no D) does NOT clear.

        The anti-spoof model-tag path is deliberately excluded from the synonym
        widening; only APPROVED|GO satisfy it.
        """
        from hestai_context_mcp.tools.shared.review_formats import has_crs_model_approval

        assert not has_crs_model_approval(["CRS (Gemini) APPROVE: looks good"], "Gemini")
        # Canonical APPROVED still clears the model path.
        assert has_crs_model_approval(["CRS (Gemini) APPROVED: looks good"], "Gemini")
