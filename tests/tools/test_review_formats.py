"""
Tests for shared review format constants and pattern matching.

TDD RED phase: These tests define the contract for review_formats module.
Tests written FIRST before implementation exists.

Coverage:
- Review tier constants
- matches_approval_pattern() with all supported formats
- Format generation produces valid patterns
- Edge cases: markdown bold, extra whitespace, model annotations
- Helper functions: has_crs_approval, has_ce_approval, has_il_self_review
"""

import pytest


@pytest.mark.unit
class TestReviewTierConstants:
    """Test that tier constants are defined correctly."""

    def test_tier_0_exempt_value(self) -> None:
        """TIER_0_EXEMPT constant exists and has correct value."""
        from hestai_context_mcp.tools.shared.review_formats import TIER_0_EXEMPT

        assert TIER_0_EXEMPT == "TIER_0_EXEMPT"

    def test_tier_1_self_value(self) -> None:
        """TIER_1_SELF constant exists and has correct value."""
        from hestai_context_mcp.tools.shared.review_formats import TIER_1_SELF

        assert TIER_1_SELF == "TIER_1_SELF"

    def test_tier_2_crs_value(self) -> None:
        """TIER_2_STANDARD constant exists and has correct value."""
        from hestai_context_mcp.tools.shared.review_formats import TIER_2_STANDARD

        assert TIER_2_STANDARD == "TIER_2_STANDARD"

    def test_tier_3_full_value(self) -> None:
        """TIER_3_STRICT constant exists and has correct value."""
        from hestai_context_mcp.tools.shared.review_formats import TIER_3_STRICT

        assert TIER_3_STRICT == "TIER_3_STRICT"

    def test_valid_roles_contains_expected(self) -> None:
        """VALID_ROLES includes CRS, CE, IL."""
        from hestai_context_mcp.tools.shared.review_formats import VALID_ROLES

        assert "CRS" in VALID_ROLES
        assert "CE" in VALID_ROLES
        assert "IL" in VALID_ROLES

    def test_valid_verdicts_contains_expected(self) -> None:
        """VALID_VERDICTS includes APPROVED, BLOCKED, CONDITIONAL."""
        from hestai_context_mcp.tools.shared.review_formats import VALID_VERDICTS

        assert "APPROVED" in VALID_VERDICTS
        assert "BLOCKED" in VALID_VERDICTS
        assert "CONDITIONAL" in VALID_VERDICTS


@pytest.mark.unit
class TestMatchesApprovalPattern:
    """Test the pattern matching function extracted from validate_review.py."""

    def test_exact_crs_approved(self) -> None:
        """Matches 'CRS APPROVED: assessment text'."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert matches_approval_pattern("CRS APPROVED: Looks good", "CRS", "APPROVED")

    def test_exact_ce_approved(self) -> None:
        """Matches 'CE APPROVED: assessment text'."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert matches_approval_pattern("CE APPROVED: Architecture sound", "CE", "APPROVED")

    def test_il_self_reviewed(self) -> None:
        """Matches 'IL SELF-REVIEWED: rationale'."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert matches_approval_pattern("IL SELF-REVIEWED: Fixed typo", "IL", "SELF-REVIEWED")

    def test_parenthetical_model_annotation_with_colon(self) -> None:
        """Matches 'CRS (Gemini): APPROVED' format."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert matches_approval_pattern("CRS (Gemini): APPROVED - all good", "CRS", "APPROVED")

    def test_parenthetical_model_with_em_dash(self) -> None:
        """Matches 'CRS (Gemini) \u2014 APPROVED' format."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert matches_approval_pattern(
            "CRS (Gemini) \u2014 APPROVED: assessment", "CRS", "APPROVED"
        )

    def test_parenthetical_model_with_en_dash(self) -> None:
        """Matches 'CRS (Gemini) \u2013 APPROVED' format."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert matches_approval_pattern(
            "CRS (Gemini) \u2013 APPROVED: assessment", "CRS", "APPROVED"
        )

    def test_parenthetical_model_with_hyphen(self) -> None:
        """Matches 'CRS (Gemini) - APPROVED' format."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert matches_approval_pattern("CRS (Gemini) - APPROVED: assessment", "CRS", "APPROVED")

    def test_em_dash_no_parenthetical(self) -> None:
        """Matches 'CRS \u2014 APPROVED' without model annotation."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert matches_approval_pattern("CRS \u2014 APPROVED: assessment", "CRS", "APPROVED")

    def test_colon_separator(self) -> None:
        """Matches 'CRS: APPROVED' format."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert matches_approval_pattern("CRS: APPROVED: assessment", "CRS", "APPROVED")

    def test_extra_whitespace(self) -> None:
        """Matches 'CRS  APPROVED' with extra whitespace."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert matches_approval_pattern("CRS  APPROVED: assessment", "CRS", "APPROVED")

    def test_markdown_bold_keyword(self) -> None:
        """Matches '**APPROVED**' with markdown bold stripped."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert matches_approval_pattern("| CRS | Gemini | **APPROVED** |", "CRS", "APPROVED")

    def test_markdown_table_format(self) -> None:
        """Matches markdown table row format."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert matches_approval_pattern(
            "| CE | Claude | **APPROVED** | Architecture is sound |", "CE", "APPROVED"
        )

    def test_crs_go_keyword(self) -> None:
        """Matches 'CRS GO' format (alternative to APPROVED)."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert matches_approval_pattern("CRS GO: Ship it", "CRS", "GO")

    def test_no_match_wrong_prefix(self) -> None:
        """Does NOT match when prefix is wrong."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert not matches_approval_pattern("XCRS APPROVED: nope", "CRS", "APPROVED")

    def test_no_match_wrong_keyword(self) -> None:
        """Does NOT match when keyword is wrong."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert not matches_approval_pattern("CRS REJECTED: no", "CRS", "APPROVED")

    def test_no_match_keyword_before_prefix(self) -> None:
        """Does NOT match when keyword appears before prefix."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert not matches_approval_pattern("APPROVED CRS: wrong order", "CRS", "APPROVED")

    def test_multiline_matches_correct_line(self) -> None:
        """Matches when pattern is on one line of multiline text."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        text = "Some preamble\nCRS APPROVED: Looks good\nMore text"
        assert matches_approval_pattern(text, "CRS", "APPROVED")

    def test_empty_text_no_match(self) -> None:
        """Empty text does not match."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert not matches_approval_pattern("", "CRS", "APPROVED")

    def test_markdown_h2_heading_format(self) -> None:
        """Matches '## TMG APPROVED ✅' — agents naturally use heading format."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert matches_approval_pattern("## TMG APPROVED ✅", "TMG", "APPROVED")

    def test_markdown_h1_heading_format(self) -> None:
        """Matches '# CRS APPROVED: assessment' with h1 heading marker."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert matches_approval_pattern("# CRS APPROVED: assessment", "CRS", "APPROVED")

    def test_markdown_h3_heading_format(self) -> None:
        """Matches '### CIV APPROVED: assessment' with deep heading marker."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert matches_approval_pattern("### CIV APPROVED: assessment", "CIV", "APPROVED")

    def test_markdown_heading_with_go_keyword(self) -> None:
        """Matches '## TMG GO ✅' — heading format with GO keyword."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert matches_approval_pattern("## TMG GO ✅", "TMG", "GO")

    def test_markdown_heading_in_multiline(self) -> None:
        """Matches heading-format approval within multiline review comment."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        text = "Review summary:\n\n## TMG APPROVED ✅\n\nAll checks passed."
        assert matches_approval_pattern(text, "TMG", "APPROVED")

    def test_indented_markdown_heading_format(self) -> None:
        """Matches '  ## TMG APPROVED ✅' — heading with leading indentation."""
        from hestai_context_mcp.tools.shared.review_formats import (
            matches_approval_pattern,
        )

        assert matches_approval_pattern("  ## TMG APPROVED ✅", "TMG", "APPROVED")


@pytest.mark.unit
class TestHelperFunctions:
    """Test convenience helper functions."""

    def test_has_crs_approval_with_approved(self) -> None:
        """has_crs_approval returns True for CRS APPROVED."""
        from hestai_context_mcp.tools.shared.review_formats import has_crs_approval

        assert has_crs_approval(["CRS APPROVED: Good code"])

    def test_has_crs_approval_with_go(self) -> None:
        """has_crs_approval returns True for CRS GO."""
        from hestai_context_mcp.tools.shared.review_formats import has_crs_approval

        assert has_crs_approval(["CRS GO: Ship it"])

    def test_has_crs_approval_false(self) -> None:
        """has_crs_approval returns False when no CRS approval."""
        from hestai_context_mcp.tools.shared.review_formats import has_crs_approval

        assert not has_crs_approval(["CE APPROVED: Not CRS"])

    def test_has_ce_approval_with_approved(self) -> None:
        """has_ce_approval returns True for CE APPROVED."""
        from hestai_context_mcp.tools.shared.review_formats import has_ce_approval

        assert has_ce_approval(["CE APPROVED: Architecture sound"])

    def test_has_ce_approval_with_go(self) -> None:
        """has_ce_approval returns True for CE GO."""
        from hestai_context_mcp.tools.shared.review_formats import has_ce_approval

        assert has_ce_approval(["CE GO: Proceed"])

    def test_has_ce_approval_false(self) -> None:
        """has_ce_approval returns False when no CE approval."""
        from hestai_context_mcp.tools.shared.review_formats import has_ce_approval

        assert not has_ce_approval(["CRS APPROVED: Not CE"])

    def test_has_il_self_review_true(self) -> None:
        """has_il_self_review returns True for IL SELF-REVIEWED."""
        from hestai_context_mcp.tools.shared.review_formats import has_il_self_review

        assert has_il_self_review(["IL SELF-REVIEWED: Fixed typo"])

    def test_has_il_self_review_false(self) -> None:
        """has_il_self_review returns False when missing."""
        from hestai_context_mcp.tools.shared.review_formats import has_il_self_review

        assert not has_il_self_review(["CRS APPROVED: Not IL"])


@pytest.mark.unit
class TestHelperFunctionsHeadingFormat:
    """Test that helper functions accept heading-format approvals via matches_approval_pattern."""

    def test_has_crs_approval_with_h2_heading(self) -> None:
        """has_crs_approval returns True for an H2 CRS approval heading."""
        from hestai_context_mcp.tools.shared.review_formats import has_crs_approval

        assert has_crs_approval(["## CRS APPROVED: looks good"])

    def test_has_ce_approval_with_h2_heading(self) -> None:
        """has_ce_approval returns True for an H2 CE approval heading."""
        from hestai_context_mcp.tools.shared.review_formats import has_ce_approval

        assert has_ce_approval(["## CE APPROVED: architecture sound"])

    def test_has_tmg_approval_with_h2_heading(self) -> None:
        """has_tmg_approval returns True for an H2 TMG approval heading."""
        from hestai_context_mcp.tools.shared.review_formats import has_tmg_approval

        assert has_tmg_approval(["## TMG APPROVED ✅"])

    def test_has_civ_approval_with_h2_heading(self) -> None:
        """has_civ_approval returns True for an H2 CIV approval heading."""
        from hestai_context_mcp.tools.shared.review_formats import has_civ_approval

        assert has_civ_approval(["## CIV APPROVED: implementation valid"])

    def test_has_crs_approval_with_indented_heading(self) -> None:
        """has_crs_approval returns True for an indented H2 CRS approval heading."""
        from hestai_context_mcp.tools.shared.review_formats import has_crs_approval

        assert has_crs_approval(["  ## CRS APPROVED: indented"])


@pytest.mark.unit
class TestFormatReviewComment:
    """Test comment formatting that produces gate-clearable comments."""

    def test_format_crs_approved(self) -> None:
        """Format CRS APPROVED comment."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            matches_approval_pattern,
        )

        comment = format_review_comment(
            role="CRS", verdict="APPROVED", assessment="Code quality is excellent"
        )
        assert matches_approval_pattern(comment, "CRS", "APPROVED")
        assert "Code quality is excellent" in comment

    def test_format_ce_approved(self) -> None:
        """Format CE APPROVED comment."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            matches_approval_pattern,
        )

        comment = format_review_comment(
            role="CE", verdict="APPROVED", assessment="Architecture is sound"
        )
        assert matches_approval_pattern(comment, "CE", "APPROVED")
        assert "Architecture is sound" in comment

    def test_format_il_self_reviewed(self) -> None:
        """Format IL with APPROVED verdict produces SELF-REVIEWED."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            matches_approval_pattern,
        )

        comment = format_review_comment(
            role="IL", verdict="APPROVED", assessment="Fixed typo in error message"
        )
        assert matches_approval_pattern(comment, "IL", "SELF-REVIEWED")
        assert "Fixed typo in error message" in comment

    def test_format_with_model_annotation(self) -> None:
        """Format comment with model annotation included."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            matches_approval_pattern,
        )

        comment = format_review_comment(
            role="CRS",
            verdict="APPROVED",
            assessment="All tests pass",
            model_annotation="Gemini",
        )
        assert matches_approval_pattern(comment, "CRS", "APPROVED")
        assert "Gemini" in comment
        assert "All tests pass" in comment

    def test_format_blocked_verdict(self) -> None:
        """Format BLOCKED verdict comment."""
        from hestai_context_mcp.tools.shared.review_formats import format_review_comment

        comment = format_review_comment(
            role="CRS", verdict="BLOCKED", assessment="Security vulnerability found"
        )
        assert "BLOCKED" in comment
        assert "Security vulnerability found" in comment

    def test_format_conditional_verdict(self) -> None:
        """Format CONDITIONAL verdict comment."""
        from hestai_context_mcp.tools.shared.review_formats import format_review_comment

        comment = format_review_comment(
            role="CE", verdict="CONDITIONAL", assessment="Needs performance testing"
        )
        assert "CONDITIONAL" in comment
        assert "Needs performance testing" in comment

    def test_formatted_approved_clears_gate(self) -> None:
        """Formatted APPROVED comment would clear the review gate."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            has_crs_approval,
        )

        comment = format_review_comment(role="CRS", verdict="APPROVED", assessment="All good")
        assert has_crs_approval([comment])

    def test_formatted_ce_approved_clears_gate(self) -> None:
        """Formatted CE APPROVED comment would clear the CE gate."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            has_ce_approval,
        )

        comment = format_review_comment(
            role="CE", verdict="APPROVED", assessment="Sound architecture"
        )
        assert has_ce_approval([comment])

    def test_formatted_il_self_review_clears_gate(self) -> None:
        """Formatted IL APPROVED comment would clear the IL self-review gate."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            has_il_self_review,
        )

        comment = format_review_comment(role="IL", verdict="APPROVED", assessment="Trivial fix")
        assert has_il_self_review([comment])

    def test_formatted_with_model_clears_gate(self) -> None:
        """Formatted comment with model annotation still clears gate."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            has_crs_approval,
        )

        comment = format_review_comment(
            role="CRS",
            verdict="APPROVED",
            assessment="Tests pass",
            model_annotation="Claude",
        )
        assert has_crs_approval([comment])

    def test_ho_approved_formats_as_ho_reviewed(self) -> None:
        """Format HO with APPROVED verdict produces HO REVIEWED."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            has_ho_review,
            matches_approval_pattern,
        )

        comment = format_review_comment(
            role="HO", verdict="APPROVED", assessment="Delegated to IL, verified output"
        )
        assert matches_approval_pattern(comment, "HO", "REVIEWED")
        assert has_ho_review([comment])
        assert "Delegated to IL, verified output" in comment


@pytest.mark.unit
class TestReviewMetadata:
    """Test structured machine-readable metadata in review comments."""

    def test_format_includes_metadata_block(self) -> None:
        """Formatted comment contains <!-- review: JSON --> metadata."""
        from hestai_context_mcp.tools.shared.review_formats import format_review_comment

        comment = format_review_comment(
            role="CRS",
            verdict="APPROVED",
            assessment="All tests pass",
            model_annotation="Gemini",
            commit_sha="abc1234def5678",
        )
        assert "<!-- review:" in comment
        assert "-->" in comment

    def test_format_metadata_parseable(self) -> None:
        """Roundtrip: format -> parse returns correct dict."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            parse_review_metadata,
        )

        comment = format_review_comment(
            role="CRS",
            verdict="APPROVED",
            assessment="All tests pass",
            model_annotation="Gemini",
            commit_sha="abc1234def5678",
        )
        meta = parse_review_metadata(comment)
        assert meta is not None
        assert meta["role"] == "CRS"
        assert meta["provider"] == "gemini"
        assert meta["verdict"] == "APPROVED"
        assert meta["sha"] == "abc1234"

    def test_format_without_sha(self) -> None:
        """SHA is null when not provided."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            parse_review_metadata,
        )

        comment = format_review_comment(
            role="CRS",
            verdict="APPROVED",
            assessment="All tests pass",
            model_annotation="Gemini",
        )
        meta = parse_review_metadata(comment)
        assert meta is not None
        assert meta["sha"] is None

    def test_format_il_maps_verdict_in_metadata(self) -> None:
        """IL verdict becomes SELF-REVIEWED in metadata."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            parse_review_metadata,
        )

        comment = format_review_comment(
            role="IL",
            verdict="APPROVED",
            assessment="Fixed typo",
        )
        meta = parse_review_metadata(comment)
        assert meta is not None
        assert meta["verdict"] == "SELF-REVIEWED"

    def test_format_ho_maps_verdict_in_metadata(self) -> None:
        """HO verdict becomes REVIEWED in metadata."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            parse_review_metadata,
        )

        comment = format_review_comment(
            role="HO",
            verdict="APPROVED",
            assessment="Verified output",
        )
        meta = parse_review_metadata(comment)
        assert meta is not None
        assert meta["verdict"] == "REVIEWED"

    def test_parse_returns_none_for_no_metadata(self) -> None:
        """Plain text returns None."""
        from hestai_context_mcp.tools.shared.review_formats import parse_review_metadata

        assert parse_review_metadata("CRS APPROVED: All good") is None

    def test_parse_returns_none_for_invalid_json(self) -> None:
        """Malformed JSON returns None."""
        from hestai_context_mcp.tools.shared.review_formats import parse_review_metadata

        assert parse_review_metadata("<!-- review: {broken json -->") is None

    def test_parse_ignores_metadata_in_inline_code(self) -> None:
        """Metadata inside backtick-quoted inline code is not parsed.

        Prevents PR body documentation examples from being treated as
        real review metadata.
        """
        from hestai_context_mcp.tools.shared.review_formats import parse_review_metadata

        text = (
            'Example: `<!-- review: {"role":"CRS","provider":"gemini",'
            '"verdict":"APPROVED","sha":"abc1234"} -->`'
        )
        assert parse_review_metadata(text) is None

    def test_parse_ignores_metadata_in_fenced_code_block(self) -> None:
        """Metadata inside fenced code blocks is not parsed."""
        from hestai_context_mcp.tools.shared.review_formats import parse_review_metadata

        text = (
            "```\n"
            '<!-- review: {"role":"CRS","provider":null,'
            '"verdict":"APPROVED","sha":"abc1234"} -->\n'
            "```"
        )
        assert parse_review_metadata(text) is None

    def test_formatted_comment_still_clears_regex_gate(self) -> None:
        """Metadata line doesn't break existing regex matching."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            has_crs_approval,
        )

        comment = format_review_comment(
            role="CRS",
            verdict="APPROVED",
            assessment="All tests pass",
            model_annotation="Gemini",
            commit_sha="abc1234",
        )
        assert has_crs_approval([comment])

    def test_metadata_line_does_not_satisfy_regex_alone(self) -> None:
        """Metadata HTML comment must not satisfy regex on its own.

        Regression test: if cross-validation checks the full text including
        the metadata line, the JSON tokens (e.g. "role":"CRS","verdict":"APPROVED")
        could falsely match the regex, defeating anti-spoofing.
        """
        from hestai_context_mcp.tools.shared.review_formats import matches_approval_pattern

        # A comment where visible text says BLOCKED but metadata says APPROVED
        spoofed = (
            "CRS BLOCKED: Security vulnerability found\n"
            '<!-- review: {"role":"CRS","provider":null,'
            '"verdict":"APPROVED","sha":"abc1234"} -->'
        )
        # The full text WOULD match because the metadata line has CRS + APPROVED
        # But visible-only text should NOT match APPROVED
        import re

        visible_only = re.sub(r"<!--\s*review:.*?-->\s*", "", spoofed)
        assert not matches_approval_pattern(visible_only, "CRS", "APPROVED")
        # Visible text should match BLOCKED though
        assert matches_approval_pattern(visible_only, "CRS", "BLOCKED")

    def test_extract_multiple_metadata(self) -> None:
        """Batch extraction from multiple comments."""
        from hestai_context_mcp.tools.shared.review_formats import (
            extract_review_metadata,
            format_review_comment,
        )

        comments = [
            format_review_comment(
                role="CRS",
                verdict="APPROVED",
                assessment="Good",
                model_annotation="Gemini",
                commit_sha="abc1234",
            ),
            "Plain comment with no metadata",
            format_review_comment(
                role="CE",
                verdict="APPROVED",
                assessment="Sound",
                commit_sha="def5678",
            ),
        ]
        results = extract_review_metadata(comments)
        assert len(results) == 2
        assert results[0]["role"] == "CRS"
        assert results[1]["role"] == "CE"

    def test_format_rejects_invalid_sha(self) -> None:
        """Non-hex SHA results in null sha in metadata."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            parse_review_metadata,
        )

        comment = format_review_comment(
            role="CRS",
            verdict="APPROVED",
            assessment="All tests pass",
            commit_sha="not-a-real-sha",
        )
        meta = parse_review_metadata(comment)
        assert meta is not None
        assert meta["sha"] is None

    def test_format_accepts_valid_short_sha(self) -> None:
        """7-char hex SHA works and is preserved."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            parse_review_metadata,
        )

        comment = format_review_comment(
            role="CRS",
            verdict="APPROVED",
            assessment="All tests pass",
            commit_sha="abc1234",
        )
        meta = parse_review_metadata(comment)
        assert meta is not None
        assert meta["sha"] == "abc1234"

    def test_format_accepts_valid_full_sha(self) -> None:
        """40-char hex SHA is truncated to 7."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            parse_review_metadata,
        )

        full_sha = "abc1234def5678901234567890abcdef12345678"
        comment = format_review_comment(
            role="CRS",
            verdict="APPROVED",
            assessment="All tests pass",
            commit_sha=full_sha,
        )
        meta = parse_review_metadata(comment)
        assert meta is not None
        assert meta["sha"] == full_sha[:7]

    def test_cross_validation_visible_text_strips_code_blocks(self) -> None:
        """Approval text inside code blocks is not treated as visible approval.

        Regression test: if cross-validation does not strip code blocks, a
        spoofed comment could embed 'CRS APPROVED:' inside a fenced code block
        alongside valid metadata, and the regex would match the code block text.
        """
        import re

        from hestai_context_mcp.tools.shared.review_formats import matches_approval_pattern

        # Simulate what cross-validation does: strip metadata, strip code blocks
        spoofed = (
            "CRS BLOCKED: Security issue found\n"
            "```\n"
            "CRS APPROVED: spoofed inside code block\n"
            "```\n"
            '<!-- review: {"role":"CRS","provider":null,'
            '"verdict":"APPROVED","sha":"abc1234"} -->'
        )
        # Reproduce the cross-validation stripping pipeline
        visible_text = re.sub(r"<!--\s*review:.*?-->\s*", "", spoofed)
        visible_text = re.sub(r"```.*?```", "", visible_text, flags=re.DOTALL)
        visible_text = re.sub(r"`[^`]+`", "", visible_text)

        # The spoofed APPROVED inside the code block must NOT match
        assert not matches_approval_pattern(visible_text, "CRS", "APPROVED")
        # But the visible BLOCKED must still match
        assert matches_approval_pattern(visible_text, "CRS", "BLOCKED")


@pytest.mark.unit
class TestGoHyphenatedCompoundsNotApproval:
    """RED tests for issue #138 — GO as part of a hyphenated token must NOT clear the gate.

    Root cause: ``\\bGO\\b`` matches the leading token of ``GO-WITH-CONDITIONS``
    because the hyphen is a non-word character, satisfying the word boundary on
    both sides.  Same flaw affects ``NO-GO`` (the ``GO`` suffix is also bounded
    by the preceding hyphen).

    These tests pin the correct behaviour: conditional and no-go verdicts are
    NOT approvals, regardless of role.
    """

    def test_go_with_conditions_does_not_clear_civ_gate(self) -> None:
        """CIV (Codex) CONDITIONAL: GO-WITH-CONDITIONS must NOT clear the CIV gate."""
        from hestai_context_mcp.tools.shared.review_formats import has_civ_approval

        assert not has_civ_approval(["CIV (Codex) CONDITIONAL: GO-WITH-CONDITIONS"])

    def test_no_go_does_not_clear_civ_gate(self) -> None:
        """CIV NO-GO: ... must NOT clear the CIV gate."""
        from hestai_context_mcp.tools.shared.review_formats import has_civ_approval

        assert not has_civ_approval(["CIV NO-GO: implementation rejected"])

    def test_go_with_conditions_does_not_clear_crs_gate(self) -> None:
        """CRS (Codex) GO-WITH-CONDITIONS must NOT clear the CRS gate."""
        from hestai_context_mcp.tools.shared.review_formats import has_crs_approval

        assert not has_crs_approval(["CRS (Codex) GO-WITH-CONDITIONS: address nits"])

    def test_no_go_does_not_clear_crs_gate(self) -> None:
        """CRS NO-GO: ... must NOT clear the CRS gate."""
        from hestai_context_mcp.tools.shared.review_formats import has_crs_approval

        assert not has_crs_approval(["CRS NO-GO: security issue"])

    def test_go_with_conditions_does_not_clear_tmg_gate(self) -> None:
        """TMG GO-WITH-CONDITIONS must NOT clear the TMG gate."""
        from hestai_context_mcp.tools.shared.review_formats import has_tmg_approval

        assert not has_tmg_approval(["TMG (Gemini) GO-WITH-CONDITIONS: fix coverage first"])

    def test_no_go_does_not_clear_tmg_gate(self) -> None:
        """TMG NO-GO: ... must NOT clear the TMG gate."""
        from hestai_context_mcp.tools.shared.review_formats import has_tmg_approval

        assert not has_tmg_approval(["TMG NO-GO: test quality insufficient"])

    def test_matches_approval_pattern_go_with_conditions(self) -> None:
        """matches_approval_pattern must return False for GO-WITH-CONDITIONS."""
        from hestai_context_mcp.tools.shared.review_formats import matches_approval_pattern

        assert not matches_approval_pattern(
            "CIV (Codex) CONDITIONAL: GO-WITH-CONDITIONS", "CIV", "GO"
        )

    def test_matches_approval_pattern_no_go(self) -> None:
        """matches_approval_pattern must return False for NO-GO verdict."""
        from hestai_context_mcp.tools.shared.review_formats import matches_approval_pattern

        assert not matches_approval_pattern("CRS NO-GO: blocked", "CRS", "GO")

    def test_crs_model_approval_go_with_conditions(self) -> None:
        """has_crs_model_approval must return False for GO-WITH-CONDITIONS."""
        from hestai_context_mcp.tools.shared.review_formats import has_crs_model_approval

        assert not has_crs_model_approval(["CRS (Codex): GO-WITH-CONDITIONS"], "Codex")

    def test_crs_model_approval_no_go(self) -> None:
        """has_crs_model_approval must return False for NO-GO."""
        from hestai_context_mcp.tools.shared.review_formats import has_crs_model_approval

        assert not has_crs_model_approval(["CRS (Gemini): NO-GO"], "Gemini")

    # --- Regression: legitimate bare GO must still clear the gate ---

    def test_bare_go_still_clears_civ_gate(self) -> None:
        """A bare standalone GO still clears the CIV gate (no regression)."""
        from hestai_context_mcp.tools.shared.review_formats import has_civ_approval

        assert has_civ_approval(["CIV (Codex) GO: implementation valid"])

    def test_bare_go_still_clears_crs_gate(self) -> None:
        """A bare standalone GO still clears the CRS gate (no regression)."""
        from hestai_context_mcp.tools.shared.review_formats import has_crs_approval

        assert has_crs_approval(["CRS GO: Ship it"])

    def test_bare_go_heading_format_still_clears_gate(self) -> None:
        """'## TMG GO ✅' heading format still clears the TMG gate (no regression)."""
        from hestai_context_mcp.tools.shared.review_formats import has_tmg_approval

        assert has_tmg_approval(["## TMG GO ✅"])

    def test_crs_model_approval_bare_go_still_clears(self) -> None:
        """has_crs_model_approval with bare GO still clears (no regression)."""
        from hestai_context_mcp.tools.shared.review_formats import has_crs_model_approval

        assert has_crs_model_approval(["CRS (Gemini): GO"], "Gemini")

    # --- P2 regression: hyphen separator before GO must still clear the model-anchored path ---

    def test_crs_model_approval_hyphen_separator_go_clears(self) -> None:
        """CRS (Gemini)-GO must clear the model-anchored gate (hyphen is a valid separator).

        The separator class [:—–-]* in has_crs_model_approval deliberately allows a
        bare hyphen as a separator, so 'CRS (Gemini)-GO' is a legitimate approval
        format. The leading lookbehind (?<!-) in the original fix incorrectly rejected
        it because the char directly before GO is the separator hyphen (cubic P2).
        """
        from hestai_context_mcp.tools.shared.review_formats import has_crs_model_approval

        assert has_crs_model_approval(["CRS (Gemini)-GO"], "Gemini")

    def test_crs_model_approval_hyphen_separator_go_with_conditions_still_rejected(
        self,
    ) -> None:
        """CRS (Gemini)-GO-WITH-CONDITIONS must NOT clear (trailing guard still active)."""
        from hestai_context_mcp.tools.shared.review_formats import has_crs_model_approval

        assert not has_crs_model_approval(["CRS (Gemini)-GO-WITH-CONDITIONS"], "Gemini")

    def test_crs_model_approval_no_go_via_hyphen_separator_still_rejected(self) -> None:
        """CRS (Gemini): NO-GO must NOT clear (leading N blocks the keyword match)."""
        from hestai_context_mcp.tools.shared.review_formats import has_crs_model_approval

        assert not has_crs_model_approval(["CRS (Gemini): NO-GO"], "Gemini")

    # --- P3 coverage: CE, PE, SR roles through the shared matches_approval_pattern path ---

    def test_go_with_conditions_does_not_clear_ce_gate(self) -> None:
        """CE GO-WITH-CONDITIONS must NOT clear the CE gate."""
        from hestai_context_mcp.tools.shared.review_formats import has_ce_approval

        assert not has_ce_approval(["CE (Gemini) GO-WITH-CONDITIONS: address nits"])

    def test_go_with_conditions_does_not_clear_pe_gate(self) -> None:
        """PE GO-WITH-CONDITIONS must NOT clear the PE gate."""
        from hestai_context_mcp.tools.shared.review_formats import has_pe_approval

        assert not has_pe_approval(["PE (Claude) GO-WITH-CONDITIONS: revisit ADR"])

    def test_go_with_conditions_does_not_clear_sr_gate(self) -> None:
        """SR GO-WITH-CONDITIONS must NOT clear the SR gate."""
        from hestai_context_mcp.tools.shared.review_formats import has_sr_approval

        assert not has_sr_approval(["SR GO-WITH-CONDITIONS: update standards doc"])


@pytest.mark.unit
class TestParserAgreementGoWithConditions:
    """Verify parser/validator path agreement for conditional and no-go verdicts.

    Closes the #138 divergence: the visible-regex path (matches_approval_pattern,
    used by both scripts/validate_review.py and the submit_review tool) must agree
    with the metadata verdict path for GO-WITH-CONDITIONS and NO-GO comments.

    A CONDITIONAL/NO-GO comment formatted via format_review_comment() should:
    - Have metadata.verdict != an approval keyword → would_clear_gate=False (metadata path)
    - NOT be matched by matches_approval_pattern() → False (visible-text path)
    Both paths must reach the SAME conclusion (False) for these comments.
    """

    def test_conditional_comment_regex_and_metadata_both_non_approval(self) -> None:
        """A CONDITIONAL verdict comment is not approval by either path.

        The metadata verdict is 'CONDITIONAL' (not in approval keywords), and
        the visible regex must also not match GO/APPROVED.
        """
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            has_civ_approval,
            parse_review_metadata,
        )

        comment = format_review_comment(
            role="CIV",
            verdict="CONDITIONAL",
            assessment="GO-WITH-CONDITIONS: address nit on line 42",
        )

        # Metadata path: verdict is CONDITIONAL, not an approval
        meta = parse_review_metadata(comment)
        assert meta is not None
        approval_keywords = {"APPROVED", "SELF-REVIEWED", "REVIEWED", "GO"}
        assert (
            meta["verdict"] not in approval_keywords
        ), f"Metadata path incorrectly marks CONDITIONAL as approval: {meta['verdict']}"

        # Visible-regex path: must also not clear the gate
        assert not has_civ_approval(
            [comment]
        ), "Visible-regex path incorrectly cleared CIV gate for CONDITIONAL comment"

    def test_no_go_comment_regex_and_metadata_both_non_approval(self) -> None:
        """A comment with NO-GO in visible text is not approval by either path."""
        from hestai_context_mcp.tools.shared.review_formats import (
            has_crs_approval,
            matches_approval_pattern,
        )

        # This represents a reviewer writing a NO-GO verdict in plain text
        comment = "CRS NO-GO: security vulnerability in auth handler"

        # Metadata path: no structured metadata → no approval (treated as plain text)
        # Visible-regex path: must not match GO
        assert not matches_approval_pattern(
            comment, "CRS", "GO"
        ), "Visible-regex path incorrectly matched GO in 'NO-GO' token"
        assert not has_crs_approval(
            [comment]
        ), "has_crs_approval incorrectly returned True for NO-GO comment"

    def test_go_with_conditions_in_assessment_does_not_spoof_gate(self) -> None:
        """A CONDITIONAL comment whose assessment text includes 'GO-WITH-CONDITIONS' is not approval.

        This is the exact pattern from issue #138: a reviewer writes a CONDITIONAL
        verdict and uses 'GO-WITH-CONDITIONS' as the human-readable assessment,
        which the broken regex treated as a GO approval.
        """
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            has_civ_approval,
            parse_review_metadata,
        )

        comment = format_review_comment(
            role="CIV",
            verdict="CONDITIONAL",
            assessment="GO-WITH-CONDITIONS",
            model_annotation="Codex",
        )

        # Both paths must agree: this is NOT an approval
        meta = parse_review_metadata(comment)
        assert meta is not None
        assert meta["verdict"] == "CONDITIONAL"

        assert not has_civ_approval([comment]), (
            "Visible-regex path false-greened the T3 gate for 'CIV (Codex) CONDITIONAL: "
            "GO-WITH-CONDITIONS' comment (issue #138 root cause)"
        )
