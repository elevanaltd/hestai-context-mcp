"""
Contract tests for 5-tier review system roles and constants in review_formats.py.

Tests verify TMG, CIV, PE role support including approval pattern matching,
format_review_comment() output, metadata roundtrip, and tier constants
(TIER_3_CRITICAL, TIER_4_STRATEGIC) for the expanded review structure.

Source of truth: review-requirements.oct.md v2.0 (5-tier system)
"""

import pytest


# ---------------------------------------------------------------------------
# A. New roles in VALID_ROLES
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestValidRoles5Tier:
    """VALID_ROLES must include TMG, CIV, PE alongside existing CRS, CE, IL, HO."""

    def test_valid_roles_contains_tmg(self) -> None:
        """TMG (Test Methodology Guardian) must be in VALID_ROLES."""
        from hestai_context_mcp.tools.shared.review_formats import VALID_ROLES

        assert "TMG" in VALID_ROLES, "TMG must be a valid review role"

    def test_valid_roles_contains_civ(self) -> None:
        """CIV (Critical Implementation Validator) must be in VALID_ROLES."""
        from hestai_context_mcp.tools.shared.review_formats import VALID_ROLES

        assert "CIV" in VALID_ROLES, "CIV must be a valid review role"

    def test_valid_roles_contains_pe(self) -> None:
        """PE (Principal Engineer) must be in VALID_ROLES."""
        from hestai_context_mcp.tools.shared.review_formats import VALID_ROLES

        assert "PE" in VALID_ROLES, "PE must be a valid review role"

    def test_valid_roles_preserves_existing_crs(self) -> None:
        """CRS must still be in VALID_ROLES after expansion."""
        from hestai_context_mcp.tools.shared.review_formats import VALID_ROLES

        assert "CRS" in VALID_ROLES

    def test_valid_roles_preserves_existing_ce(self) -> None:
        """CE must still be in VALID_ROLES after expansion."""
        from hestai_context_mcp.tools.shared.review_formats import VALID_ROLES

        assert "CE" in VALID_ROLES

    def test_valid_roles_preserves_existing_il(self) -> None:
        """IL must still be in VALID_ROLES after expansion."""
        from hestai_context_mcp.tools.shared.review_formats import VALID_ROLES

        assert "IL" in VALID_ROLES

    def test_valid_roles_preserves_existing_ho(self) -> None:
        """HO must still be in VALID_ROLES after expansion."""
        from hestai_context_mcp.tools.shared.review_formats import VALID_ROLES

        assert "HO" in VALID_ROLES

    def test_valid_roles_contains_sr(self) -> None:
        """SR (Standards Reviewer) must be in VALID_ROLES."""
        from hestai_context_mcp.tools.shared.review_formats import VALID_ROLES

        assert "SR" in VALID_ROLES, "SR must be a valid review role"

    def test_valid_roles_has_eight_members(self) -> None:
        """VALID_ROLES must have exactly 8 members: CRS, CE, SR, IL, HO, TMG, CIV, PE."""
        from hestai_context_mcp.tools.shared.review_formats import VALID_ROLES

        assert len(VALID_ROLES) == 8, f"Expected 8 roles, got {len(VALID_ROLES)}: {VALID_ROLES}"


# ---------------------------------------------------------------------------
# B. New tier constants
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestTierConstants5Tier:
    """New tier constants for 5-tier system."""

    def test_tier_3_critical_constant_exists(self) -> None:
        """TIER_3_CRITICAL must exist (replaces TIER_3_STRICT)."""
        from hestai_context_mcp.tools.shared.review_formats import TIER_3_CRITICAL

        assert TIER_3_CRITICAL == "TIER_3_CRITICAL"

    def test_tier_4_strategic_constant_exists(self) -> None:
        """TIER_4_STRATEGIC must exist for the new top tier."""
        from hestai_context_mcp.tools.shared.review_formats import TIER_4_STRATEGIC

        assert TIER_4_STRATEGIC == "TIER_4_STRATEGIC"


# ---------------------------------------------------------------------------
# C. TMG approval matching
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestTMGApprovalMatching:
    """has_tmg_approval() must match TMG approval patterns."""

    def test_tmg_approved_basic(self) -> None:
        """'TMG APPROVED: tests cover critical paths' must match."""
        from hestai_context_mcp.tools.shared.review_formats import has_tmg_approval

        assert has_tmg_approval(["TMG APPROVED: tests cover critical paths"])

    def test_tmg_approved_with_model_annotation(self) -> None:
        """'TMG (Goose): APPROVED: coverage verified' must match."""
        from hestai_context_mcp.tools.shared.review_formats import has_tmg_approval

        assert has_tmg_approval(["TMG (Goose): APPROVED: coverage verified"])

    def test_tmg_go_keyword(self) -> None:
        """'TMG GO: sufficient coverage' must match."""
        from hestai_context_mcp.tools.shared.review_formats import has_tmg_approval

        assert has_tmg_approval(["TMG GO: sufficient coverage"])

    def test_tmg_go_with_model(self) -> None:
        """'TMG (Goose): GO: tests look solid' must match."""
        from hestai_context_mcp.tools.shared.review_formats import has_tmg_approval

        assert has_tmg_approval(["TMG (Goose): GO: tests look solid"])

    def test_tmg_no_false_positive_xtmg(self) -> None:
        """'XTMG APPROVED' must NOT match (word boundary)."""
        from hestai_context_mcp.tools.shared.review_formats import has_tmg_approval

        assert not has_tmg_approval(["XTMG APPROVED: fake"])

    def test_tmg_no_false_positive_blocked(self) -> None:
        """'TMG BLOCKED' must NOT match as approval."""
        from hestai_context_mcp.tools.shared.review_formats import has_tmg_approval

        assert not has_tmg_approval(["TMG BLOCKED: tests insufficient"])

    def test_tmg_no_match_empty(self) -> None:
        """Empty list returns False."""
        from hestai_context_mcp.tools.shared.review_formats import has_tmg_approval

        assert not has_tmg_approval([])

    def test_tmg_approved_with_em_dash(self) -> None:
        """'TMG (Goose) \u2014 APPROVED' with em dash must match."""
        from hestai_context_mcp.tools.shared.review_formats import has_tmg_approval

        assert has_tmg_approval(["TMG (Goose) \u2014 APPROVED: edge cases covered"])


# ---------------------------------------------------------------------------
# D. CIV approval matching
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestCIVApprovalMatching:
    """has_civ_approval() must match CIV approval patterns."""

    def test_civ_approved_basic(self) -> None:
        """'CIV APPROVED: implementation matches spec' must match."""
        from hestai_context_mcp.tools.shared.review_formats import has_civ_approval

        assert has_civ_approval(["CIV APPROVED: implementation matches spec"])

    def test_civ_approved_with_model_annotation(self) -> None:
        """'CIV (Goose): APPROVED: DRY verified' must match."""
        from hestai_context_mcp.tools.shared.review_formats import has_civ_approval

        assert has_civ_approval(["CIV (Goose): APPROVED: DRY verified"])

    def test_civ_go_keyword(self) -> None:
        """'CIV GO: abstractions correct' must match."""
        from hestai_context_mcp.tools.shared.review_formats import has_civ_approval

        assert has_civ_approval(["CIV GO: abstractions correct"])

    def test_civ_go_with_model(self) -> None:
        """'CIV (Codex): GO: implementation clean' must match."""
        from hestai_context_mcp.tools.shared.review_formats import has_civ_approval

        assert has_civ_approval(["CIV (Codex): GO: implementation clean"])

    def test_civ_no_false_positive_xciv(self) -> None:
        """'XCIV APPROVED' must NOT match (word boundary)."""
        from hestai_context_mcp.tools.shared.review_formats import has_civ_approval

        assert not has_civ_approval(["XCIV APPROVED: fake"])

    def test_civ_no_false_positive_blocked(self) -> None:
        """'CIV BLOCKED' must NOT match as approval."""
        from hestai_context_mcp.tools.shared.review_formats import has_civ_approval

        assert not has_civ_approval(["CIV BLOCKED: implementation flawed"])

    def test_civ_no_match_empty(self) -> None:
        """Empty list returns False."""
        from hestai_context_mcp.tools.shared.review_formats import has_civ_approval

        assert not has_civ_approval([])

    def test_civ_approved_with_em_dash(self) -> None:
        """'CIV (Goose) \u2014 APPROVED' with em dash must match."""
        from hestai_context_mcp.tools.shared.review_formats import has_civ_approval

        assert has_civ_approval(["CIV (Goose) \u2014 APPROVED: validated"])


# ---------------------------------------------------------------------------
# E. PE approval matching
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestPEApprovalMatching:
    """has_pe_approval() must match PE approval patterns."""

    def test_pe_approved_basic(self) -> None:
        """'PE APPROVED: architecture sound for 6 months' must match."""
        from hestai_context_mcp.tools.shared.review_formats import has_pe_approval

        assert has_pe_approval(["PE APPROVED: architecture sound for 6 months"])

    def test_pe_approved_with_model_annotation(self) -> None:
        """'PE (Goose): APPROVED: no temporal coupling' must match."""
        from hestai_context_mcp.tools.shared.review_formats import has_pe_approval

        assert has_pe_approval(["PE (Goose): APPROVED: no temporal coupling"])

    def test_pe_go_keyword(self) -> None:
        """'PE GO: sustainable patterns' must match."""
        from hestai_context_mcp.tools.shared.review_formats import has_pe_approval

        assert has_pe_approval(["PE GO: sustainable patterns"])

    def test_pe_go_with_model(self) -> None:
        """'PE (Codex): GO: long-term viable' must match."""
        from hestai_context_mcp.tools.shared.review_formats import has_pe_approval

        assert has_pe_approval(["PE (Codex): GO: long-term viable"])

    def test_pe_no_false_positive_xpe(self) -> None:
        """'XPE APPROVED' must NOT match (word boundary)."""
        from hestai_context_mcp.tools.shared.review_formats import has_pe_approval

        assert not has_pe_approval(["XPE APPROVED: fake"])

    def test_pe_no_false_positive_blocked(self) -> None:
        """'PE BLOCKED' must NOT match as approval."""
        from hestai_context_mcp.tools.shared.review_formats import has_pe_approval

        assert not has_pe_approval(["PE BLOCKED: architecture unsound"])

    def test_pe_no_match_empty(self) -> None:
        """Empty list returns False."""
        from hestai_context_mcp.tools.shared.review_formats import has_pe_approval

        assert not has_pe_approval([])

    def test_pe_approved_with_em_dash(self) -> None:
        """'PE (Goose) \u2014 APPROVED' with em dash must match."""
        from hestai_context_mcp.tools.shared.review_formats import has_pe_approval

        assert has_pe_approval(["PE (Goose) \u2014 APPROVED: strategic review passed"])


# ---------------------------------------------------------------------------
# F. format_review_comment for new roles
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestFormatReviewCommentNewRoles:
    """format_review_comment() must work with TMG, CIV, PE roles."""

    def test_format_tmg_approved(self) -> None:
        """Format TMG APPROVED comment."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            matches_approval_pattern,
        )

        comment = format_review_comment(
            role="TMG", verdict="APPROVED", assessment="Tests cover critical paths"
        )
        assert matches_approval_pattern(comment, "TMG", "APPROVED")
        assert "Tests cover critical paths" in comment

    def test_format_tmg_with_model(self) -> None:
        """Format TMG APPROVED with model annotation."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            matches_approval_pattern,
        )

        comment = format_review_comment(
            role="TMG",
            verdict="APPROVED",
            assessment="Edge cases covered",
            model_annotation="Goose",
        )
        assert matches_approval_pattern(comment, "TMG", "APPROVED")
        assert "Goose" in comment

    def test_format_civ_approved(self) -> None:
        """Format CIV APPROVED comment."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            matches_approval_pattern,
        )

        comment = format_review_comment(
            role="CIV", verdict="APPROVED", assessment="Implementation matches spec"
        )
        assert matches_approval_pattern(comment, "CIV", "APPROVED")
        assert "Implementation matches spec" in comment

    def test_format_civ_with_model(self) -> None:
        """Format CIV APPROVED with model annotation."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            matches_approval_pattern,
        )

        comment = format_review_comment(
            role="CIV",
            verdict="APPROVED",
            assessment="DRY verified",
            model_annotation="Goose",
        )
        assert matches_approval_pattern(comment, "CIV", "APPROVED")
        assert "Goose" in comment

    def test_format_pe_approved(self) -> None:
        """Format PE APPROVED comment."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            matches_approval_pattern,
        )

        comment = format_review_comment(
            role="PE", verdict="APPROVED", assessment="Architecture sound for 6 months"
        )
        assert matches_approval_pattern(comment, "PE", "APPROVED")
        assert "Architecture sound for 6 months" in comment

    def test_format_pe_with_model(self) -> None:
        """Format PE APPROVED with model annotation."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            matches_approval_pattern,
        )

        comment = format_review_comment(
            role="PE",
            verdict="APPROVED",
            assessment="No temporal coupling",
            model_annotation="Goose",
        )
        assert matches_approval_pattern(comment, "PE", "APPROVED")
        assert "Goose" in comment

    def test_format_tmg_blocked(self) -> None:
        """Format TMG BLOCKED comment with correct prefix and metadata."""
        from hestai_context_mcp.tools.shared.review_formats import format_review_comment

        comment = format_review_comment(
            role="TMG", verdict="BLOCKED", assessment="Tests insufficient"
        )
        assert comment.startswith(
            "TMG BLOCKED:"
        ), f"TMG BLOCKED comment must start with 'TMG BLOCKED:', got: {comment[:30]}"
        assert "Tests insufficient" in comment
        assert "<!-- review:" in comment, "BLOCKED comment must contain metadata line"

    def test_format_civ_blocked(self) -> None:
        """Format CIV BLOCKED comment with correct prefix and metadata."""
        from hestai_context_mcp.tools.shared.review_formats import format_review_comment

        comment = format_review_comment(
            role="CIV", verdict="BLOCKED", assessment="Implementation flawed"
        )
        assert comment.startswith(
            "CIV BLOCKED:"
        ), f"CIV BLOCKED comment must start with 'CIV BLOCKED:', got: {comment[:30]}"
        assert "Implementation flawed" in comment
        assert "<!-- review:" in comment, "BLOCKED comment must contain metadata line"

    def test_format_pe_blocked(self) -> None:
        """Format PE BLOCKED comment with correct prefix and metadata."""
        from hestai_context_mcp.tools.shared.review_formats import format_review_comment

        comment = format_review_comment(
            role="PE", verdict="BLOCKED", assessment="Architecture unsound"
        )
        assert comment.startswith(
            "PE BLOCKED:"
        ), f"PE BLOCKED comment must start with 'PE BLOCKED:', got: {comment[:30]}"
        assert "Architecture unsound" in comment
        assert "<!-- review:" in comment, "BLOCKED comment must contain metadata line"


# ---------------------------------------------------------------------------
# G. Metadata parsing for new roles
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestMetadataParsingNewRoles:
    """parse_review_metadata() must handle TMG, CIV, PE metadata correctly."""

    def test_tmg_metadata_roundtrip(self) -> None:
        """TMG formatted comment has parseable metadata with correct role."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            parse_review_metadata,
        )

        comment = format_review_comment(
            role="TMG",
            verdict="APPROVED",
            assessment="Tests cover paths",
            model_annotation="Goose",
            commit_sha="abc1234",
        )
        meta = parse_review_metadata(comment)
        assert meta is not None
        assert meta["role"] == "TMG"
        assert meta["provider"] == "goose"
        assert meta["verdict"] == "APPROVED"
        assert meta["sha"] == "abc1234"

    def test_civ_metadata_roundtrip(self) -> None:
        """CIV formatted comment has parseable metadata with correct role."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            parse_review_metadata,
        )

        comment = format_review_comment(
            role="CIV",
            verdict="APPROVED",
            assessment="Spec match verified",
            model_annotation="Goose",
            commit_sha="def5678",
        )
        meta = parse_review_metadata(comment)
        assert meta is not None
        assert meta["role"] == "CIV"
        assert meta["provider"] == "goose"
        assert meta["verdict"] == "APPROVED"

    def test_pe_metadata_roundtrip(self) -> None:
        """PE formatted comment has parseable metadata with correct role."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            parse_review_metadata,
        )

        comment = format_review_comment(
            role="PE",
            verdict="APPROVED",
            assessment="Sustainable patterns",
            model_annotation="Goose",
            commit_sha="ghi9012",
        )
        meta = parse_review_metadata(comment)
        assert meta is not None
        assert meta["role"] == "PE"
        assert meta["provider"] == "goose"
        assert meta["verdict"] == "APPROVED"

    def test_tmg_blocked_metadata(self) -> None:
        """TMG BLOCKED has correct metadata verdict."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            parse_review_metadata,
        )

        comment = format_review_comment(
            role="TMG",
            verdict="BLOCKED",
            assessment="Tests insufficient",
        )
        meta = parse_review_metadata(comment)
        assert meta is not None
        assert meta["role"] == "TMG"
        assert meta["verdict"] == "BLOCKED"


# ---------------------------------------------------------------------------
# H. Role-agnostic self-review matching
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestGenericSelfReview:
    """has_self_review() must match any word/identifier followed by SELF-REVIEWED."""

    def test_has_self_review_with_il(self) -> None:
        """IL SELF-REVIEWED must match (backward compat)."""
        from hestai_context_mcp.tools.shared.review_formats import has_self_review

        assert has_self_review(["IL SELF-REVIEWED: fixed typo"])

    def test_has_self_review_with_skills_expert(self) -> None:
        """skills-expert SELF-REVIEWED must match (hyphenated role name)."""
        from hestai_context_mcp.tools.shared.review_formats import has_self_review

        assert has_self_review(["skills-expert SELF-REVIEWED: updated GATES"])

    def test_has_self_review_with_human_name(self) -> None:
        """Human name like Shaun SELF-REVIEWED must match."""
        from hestai_context_mcp.tools.shared.review_formats import has_self_review

        assert has_self_review(["Shaun SELF-REVIEWED: quick config change"])

    def test_has_self_review_with_agent_expert(self) -> None:
        """agent-expert SELF-REVIEWED must match."""
        from hestai_context_mcp.tools.shared.review_formats import has_self_review

        assert has_self_review(["agent-expert SELF-REVIEWED: new agent definition"])

    def test_has_self_review_negative(self) -> None:
        """Comment without SELF-REVIEWED must not match."""
        from hestai_context_mcp.tools.shared.review_formats import has_self_review

        assert not has_self_review(["NOT-A-REVIEW: just a comment"])

    def test_has_self_review_partial_match(self) -> None:
        """SELF-REVIEWED alone without role prefix must not match."""
        from hestai_context_mcp.tools.shared.review_formats import has_self_review

        assert not has_self_review(["SELF-REVIEWED"])

    def test_has_il_self_review_backward_compat(self) -> None:
        """has_il_self_review() must still work as deprecated wrapper."""
        from hestai_context_mcp.tools.shared.review_formats import has_il_self_review

        assert has_il_self_review(["IL SELF-REVIEWED: backward compat test"])

    def test_has_self_review_empty_list(self) -> None:
        """Empty list returns False."""
        from hestai_context_mcp.tools.shared.review_formats import has_self_review

        assert not has_self_review([])

    def test_has_self_review_with_model_annotation(self) -> None:
        """IL (Claude) SELF-REVIEWED must match via flexible pattern."""
        from hestai_context_mcp.tools.shared.review_formats import has_self_review

        assert has_self_review(["IL (Claude): SELF-REVIEWED: quick fix"])

    def test_has_self_review_not_matched_in_prose(self) -> None:
        """SELF-REVIEWED in mid-line prose must not match (line-start anchoring)."""
        from hestai_context_mcp.tools.shared.review_formats import has_self_review

        assert not has_self_review(["The author submits a SELF-REVIEWED marker for the change"])


# ---------------------------------------------------------------------------
# I. Approval matcher line-start enforcement
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestApprovalMatcherLineStartEnforcement:
    """matches_approval_pattern() must require role at line-start position.

    Prevents false positives from prose like 'TMG+CRS+CE+CIV+PE by tier), GO aliases'
    where CE and GO appear on the same line but CE is not at the line start.
    """

    def test_ce_go_in_prose_not_matched(self) -> None:
        """CE and GO in prose must NOT match as CE approval.

        Reproduction case from PR #338: TMG review comment contains
        'TMG+CRS+CE+CIV+PE by tier), GO aliases' which falsely satisfies
        has_ce_approval() because CE and GO are on the same line.
        """
        from hestai_context_mcp.tools.shared.review_formats import has_ce_approval

        assert not has_ce_approval(
            ["TMG+CRS+CE+CIV+PE by tier), GO aliases"]
        ), "CE in prose must NOT satisfy approval gate"

    def test_ce_approved_in_prose_not_matched(self) -> None:
        """'The CE review found APPROVED patterns' must NOT match."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert not matches_approval_pattern(
            "The CE review found APPROVED patterns", "CE", "APPROVED"
        )

    def test_tmg_in_prose_not_matched(self) -> None:
        """TMG in compound expression must NOT satisfy approval."""
        from hestai_context_mcp.tools.shared.review_formats import has_tmg_approval

        assert not has_tmg_approval(["Required: TMG+CRS+CE, with GO keyword support"])

    def test_crs_in_prose_not_matched(self) -> None:
        """CRS in compound expression must NOT satisfy approval."""
        from hestai_context_mcp.tools.shared.review_formats import has_crs_approval

        assert not has_crs_approval(["Required: TMG+CRS+CE, then APPROVED by reviewers"])

    def test_approval_at_line_start_still_matches(self) -> None:
        """CE APPROVED at actual line start must still match."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert matches_approval_pattern("CE APPROVED: looks good", "CE", "APPROVED")

    def test_approval_after_pipe_still_matches(self) -> None:
        """CE in markdown table (after pipe) must still match."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert matches_approval_pattern("| CE | APPROVED | assessment |", "CE", "APPROVED")

    def test_approval_with_leading_whitespace_matches(self) -> None:
        """CE APPROVED with leading whitespace must still match."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert matches_approval_pattern("  CE APPROVED: looks good", "CE", "APPROVED")

    def test_multiline_prose_then_approval(self) -> None:
        """Role in prose on line 1 must NOT match, but role at line start on line 2 must."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        text = "Need CE and CRS reviews\nCE APPROVED: assessment here"
        assert matches_approval_pattern(text, "CE", "APPROVED")


# ---------------------------------------------------------------------------
# J. SR (Standards Reviewer) approval matching
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestSRApprovalMatching:
    """has_sr_approval() must match SR approval patterns."""

    def test_sr_approved_basic(self) -> None:
        """'SR APPROVED: standards aligned with North Star' must match."""
        from hestai_context_mcp.tools.shared.review_formats import has_sr_approval

        assert has_sr_approval(["SR APPROVED: standards aligned with North Star"])

    def test_sr_approved_with_model_annotation(self) -> None:
        """'SR (Gemini): APPROVED: no contradictions detected' must match."""
        from hestai_context_mcp.tools.shared.review_formats import has_sr_approval

        assert has_sr_approval(["SR (Gemini): APPROVED: no contradictions detected"])

    def test_sr_go_keyword(self) -> None:
        """'SR GO: standards artifacts complete' must match."""
        from hestai_context_mcp.tools.shared.review_formats import has_sr_approval

        assert has_sr_approval(["SR GO: standards artifacts complete"])

    def test_sr_go_with_model(self) -> None:
        """'SR (Codex): GO: alignment verified' must match."""
        from hestai_context_mcp.tools.shared.review_formats import has_sr_approval

        assert has_sr_approval(["SR (Codex): GO: alignment verified"])

    def test_sr_no_false_positive_xsr(self) -> None:
        """'XSR APPROVED' must NOT match (word boundary)."""
        from hestai_context_mcp.tools.shared.review_formats import has_sr_approval

        assert not has_sr_approval(["XSR APPROVED: fake"])

    def test_sr_no_false_positive_blocked(self) -> None:
        """'SR BLOCKED' must NOT match as approval."""
        from hestai_context_mcp.tools.shared.review_formats import has_sr_approval

        assert not has_sr_approval(["SR BLOCKED: North Star contradiction detected"])

    def test_sr_no_match_empty(self) -> None:
        """Empty list returns False."""
        from hestai_context_mcp.tools.shared.review_formats import has_sr_approval

        assert not has_sr_approval([])

    def test_sr_approved_with_em_dash(self) -> None:
        """'SR (Gemini) \u2014 APPROVED' with em dash must match."""
        from hestai_context_mcp.tools.shared.review_formats import has_sr_approval

        assert has_sr_approval(["SR (Gemini) \u2014 APPROVED: standards review passed"])

    def test_has_gr_approval_matches_legacy_gr(self) -> None:
        """has_gr_approval() must still match legacy 'GR APPROVED' comments."""
        from hestai_context_mcp.tools.shared.review_formats import has_gr_approval

        assert has_gr_approval(["GR APPROVED: legacy governance review"])

    def test_has_gr_approval_also_matches_sr(self) -> None:
        """has_gr_approval() must also match new 'SR APPROVED' comments."""
        from hestai_context_mcp.tools.shared.review_formats import has_gr_approval

        assert has_gr_approval(["SR APPROVED: standards review"])


# ---------------------------------------------------------------------------
# K. format_review_comment and metadata for SR role
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestFormatReviewCommentSR:
    """format_review_comment() must work with SR role."""

    def test_format_sr_approved(self) -> None:
        """Format SR APPROVED comment."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            matches_approval_pattern,
        )

        comment = format_review_comment(
            role="SR", verdict="APPROVED", assessment="Standards aligned with North Star"
        )
        assert matches_approval_pattern(comment, "SR", "APPROVED")
        assert "Standards aligned with North Star" in comment

    def test_format_sr_with_model(self) -> None:
        """Format SR APPROVED with model annotation."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            matches_approval_pattern,
        )

        comment = format_review_comment(
            role="SR",
            verdict="APPROVED",
            assessment="No contradictions detected",
            model_annotation="Gemini",
        )
        assert matches_approval_pattern(comment, "SR", "APPROVED")
        assert "Gemini" in comment

    def test_format_sr_blocked(self) -> None:
        """Format SR BLOCKED comment with correct prefix and metadata."""
        from hestai_context_mcp.tools.shared.review_formats import format_review_comment

        comment = format_review_comment(
            role="SR", verdict="BLOCKED", assessment="North Star contradiction detected"
        )
        assert comment.startswith(
            "SR BLOCKED:"
        ), f"SR BLOCKED comment must start with 'SR BLOCKED:', got: {comment[:30]}"
        assert "North Star contradiction detected" in comment
        assert "<!-- review:" in comment, "BLOCKED comment must contain metadata line"

    def test_sr_metadata_roundtrip(self) -> None:
        """SR formatted comment has parseable metadata with correct role."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            parse_review_metadata,
        )

        comment = format_review_comment(
            role="SR",
            verdict="APPROVED",
            assessment="Standards aligned",
            model_annotation="Gemini",
            commit_sha="abc1234",
        )
        meta = parse_review_metadata(comment)
        assert meta is not None
        assert meta["role"] == "SR"
        assert meta["provider"] == "gemini"
        assert meta["verdict"] == "APPROVED"
        assert meta["sha"] == "abc1234"

    def test_sr_blocked_metadata(self) -> None:
        """SR BLOCKED has correct metadata verdict."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            parse_review_metadata,
        )

        comment = format_review_comment(
            role="SR",
            verdict="BLOCKED",
            assessment="Precedence hierarchy violation",
        )
        meta = parse_review_metadata(comment)
        assert meta is not None
        assert meta["role"] == "SR"
        assert meta["verdict"] == "BLOCKED"
