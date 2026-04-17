"""Tests for the shared review_formats module.

Verifies the formatting and pattern-matching utilities that underpin
the submit_review tool's gate-compliance behavior.
"""

import pytest


@pytest.mark.unit
class TestValidConstants:
    """Verify the role and verdict constants."""

    def test_valid_roles_contains_all_eight(self):
        """VALID_ROLES must contain exactly the 8 defined roles."""
        from hestai_context_mcp.tools.shared.review_formats import VALID_ROLES

        expected = {"CE", "CIV", "CRS", "HO", "IL", "PE", "SR", "TMG"}
        assert expected == VALID_ROLES

    def test_valid_verdicts_contains_all_three(self):
        """VALID_VERDICTS must contain exactly the 3 defined verdicts."""
        from hestai_context_mcp.tools.shared.review_formats import VALID_VERDICTS

        expected = {"APPROVED", "BLOCKED", "CONDITIONAL"}
        assert expected == VALID_VERDICTS


@pytest.mark.unit
class TestFormatReviewComment:
    """Verify comment formatting produces gate-compliant output."""

    def test_basic_approved_format(self):
        """Basic APPROVED comment should have role, keyword, and assessment."""
        from hestai_context_mcp.tools.shared.review_formats import format_review_comment

        comment = format_review_comment(role="CE", verdict="APPROVED", assessment="LGTM")
        assert "CE APPROVED: LGTM" in comment

    def test_il_approved_maps_to_self_reviewed(self):
        """IL + APPROVED must produce SELF-REVIEWED keyword."""
        from hestai_context_mcp.tools.shared.review_formats import format_review_comment

        comment = format_review_comment(role="IL", verdict="APPROVED", assessment="Fixed")
        assert "SELF-REVIEWED" in comment

    def test_ho_approved_maps_to_reviewed(self):
        """HO + APPROVED must produce REVIEWED keyword."""
        from hestai_context_mcp.tools.shared.review_formats import format_review_comment

        comment = format_review_comment(role="HO", verdict="APPROVED", assessment="Verified")
        assert "HO" in comment
        assert "REVIEWED" in comment

    def test_model_annotation_format(self):
        """Model annotation should appear in parentheses."""
        from hestai_context_mcp.tools.shared.review_formats import format_review_comment

        comment = format_review_comment(
            role="CRS",
            verdict="APPROVED",
            assessment="Good",
            model_annotation="Gemini",
        )
        assert "CRS (Gemini)" in comment

    def test_metadata_html_comment(self):
        """Formatted comment should include metadata HTML comment."""
        from hestai_context_mcp.tools.shared.review_formats import format_review_comment

        comment = format_review_comment(role="TMG", verdict="APPROVED", assessment="Tests OK")
        assert "<!-- review:" in comment
        assert "-->" in comment

    def test_commit_sha_in_metadata(self):
        """Valid commit SHA should appear in metadata (truncated to 7)."""
        from hestai_context_mcp.tools.shared.review_formats import format_review_comment

        comment = format_review_comment(
            role="CE",
            verdict="APPROVED",
            assessment="OK",
            commit_sha="abc1234def5678",
        )
        assert "abc1234" in comment

    def test_invalid_sha_dropped(self):
        """Invalid SHA should be silently dropped."""
        from hestai_context_mcp.tools.shared.review_formats import format_review_comment

        comment = format_review_comment(
            role="CE",
            verdict="APPROVED",
            assessment="OK",
            commit_sha="not-valid!",
        )
        assert "not-valid!" not in comment


@pytest.mark.unit
class TestApprovalPatternMatching:
    """Verify the pattern matching for gate clearing."""

    def test_crs_approval_detected(self):
        """CRS APPROVED pattern should be detected."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            has_crs_approval,
        )

        comment = format_review_comment(role="CRS", verdict="APPROVED", assessment="Good")
        assert has_crs_approval([comment]) is True

    def test_ce_approval_detected(self):
        """CE APPROVED pattern should be detected."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            has_ce_approval,
        )

        comment = format_review_comment(role="CE", verdict="APPROVED", assessment="Good")
        assert has_ce_approval([comment]) is True

    def test_self_review_detected(self):
        """IL SELF-REVIEWED pattern should be detected."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            has_self_review,
        )

        comment = format_review_comment(role="IL", verdict="APPROVED", assessment="Quick fix")
        assert has_self_review([comment]) is True

    def test_ho_review_detected(self):
        """HO REVIEWED pattern should be detected."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            has_ho_review,
        )

        comment = format_review_comment(role="HO", verdict="APPROVED", assessment="Verified")
        assert has_ho_review([comment]) is True

    def test_blocked_does_not_match_approval(self):
        """BLOCKED comments should NOT match approval patterns."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            has_crs_approval,
        )

        comment = format_review_comment(role="CRS", verdict="BLOCKED", assessment="Issues")
        assert has_crs_approval([comment]) is False
