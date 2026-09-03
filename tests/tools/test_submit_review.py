"""Tests for the submit_review MCP tool.

Written against the ADR-0353 interface contract:
- Input: repo, pr_number, role, verdict, assessment, model_annotation?, commit_sha?, dry_run?
- Output: { status, comment_url, validation, dry_run }
- 8 roles: CE, CIV, CRS, HO, IL, PE, SR, TMG
- 4 verdicts: APPROVED, BLOCKED, CONDITIONAL, REJECTED
- Supports dry_run validation without HTTP calls
- Supports commit_sha pinning for audit trail

TDD RED phase: These tests are written before the implementation.
"""

import io
import json
import subprocess
import sys
import tokenize
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import validate_review.py (the CI-side gate script) as ground truth for
# TestSubmitReviewCiParity below -- moved here from tests/test_validate_review.py
# (elevana-studio#1851 PR split, round 6): the test verifies submit_review.py's
# _matches_role_gate() agrees with validate_review.py's per-role checker, so it
# tests THIS module's subject and belongs in THIS file, even though it also
# imports validate_review.py as its independent ground truth.
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
import validate_review  # noqa: E402


# ---------------------------------------------------------------------------
# Source-level gating-check helpers (rework #3, PR #148 finding 1)
#
# Used by TestReviewGateRetriggerGating to prove submit_review's Step 6
# retrigger gate reads the computed `would_clear` value rather than a fresh
# `verdict == "APPROVED"` literal comparison -- a distinction no
# BEHAVIOURAL test can observe (Step 3's own fail-closed guard makes the
# two provably equivalent by the time Step 6 runs), so this has to be a
# source-level pin. Module-level (not nested in the test class) so a
# dedicated test can prove the checker itself discriminates, independent
# of any one call site.
# ---------------------------------------------------------------------------
def _strip_comments(source: str) -> str:
    """Blank out comment token text in place, preserving every other
    character, line, and column exactly -- so character offsets computed
    against the ORIGINAL source remain valid indices into the result.
    """
    lines = source.splitlines(keepends=True)
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for tok_type, _tok_string, start, end, _line in tokens:
        if tok_type == tokenize.COMMENT:
            start_row, start_col = start
            end_row, end_col = end
            assert start_row == end_row, "comment tokens are always single-line"
            line = lines[start_row - 1]
            lines[start_row - 1] = line[:start_col] + (" " * (end_col - start_col)) + line[end_col:]
    return "".join(lines)


def _step6_gating_window(source: str) -> str:
    """Extract the Step 6 (retrigger-gating) region, with comments blanked
    out, from ``source`` (expected to be ``submit_review``'s own source,
    real or mutated).

    Anchored on stable, comment-based landmarks that BRACKET the gating
    logic without being PART OF the condition under test: mutating the
    condition itself (e.g. reverting it to a literal verdict comparison)
    cannot also break the anchor search, unlike the prior (broken) version
    of this check, which anchored on text that was itself inside the
    window it was trying to validate.
    """
    start_marker = "# Step 6:"
    end_marker = '"retrigger": retrigger,'
    start_idx = source.index(start_marker)
    end_idx = source.index(end_marker, start_idx)
    stripped = _strip_comments(source)
    return stripped[start_idx:end_idx]


def _gating_reads_would_clear_not_literal_verdict(source: str) -> bool:
    """True iff the Step 6 gating window branches on ``would_clear`` AND
    contains no fresh ``verdict ==`` comparison or bare ``"APPROVED"``
    literal.

    The negative check is the load-bearing one: it is what actually
    catches a regression back to a literal verdict comparison. The
    positive check (the name ``would_clear`` appears) is necessary but, on
    its own, weak -- it is trivially satisfied by code that never uses the
    value at all, which is exactly how the prior version of this guard
    failed to discriminate.
    """
    window = _step6_gating_window(source)
    reads_would_clear = "would_clear" in window
    has_fresh_literal_comparison = "verdict ==" in window or '"APPROVED"' in window
    return reads_would_clear and not has_fresh_literal_comparison


# ---------------------------------------------------------------------------
# Input validation tests
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestInputValidation:
    """submit_review must reject invalid inputs before any GitHub interaction."""

    def test_invalid_role_rejected(self):
        """Roles not in the 8-role enum must be rejected."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="INVALID_ROLE",
            verdict="APPROVED",
            assessment="Test assessment",
        )
        assert result["status"] == "error"
        assert "role" in result["validation"]["error"].lower()

    def test_invalid_verdict_rejected(self):
        """Verdicts not in the 3-verdict enum must be rejected."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="INVALID_VERDICT",
            assessment="Test assessment",
        )
        assert result["status"] == "error"
        assert "verdict" in result["validation"]["error"].lower()

    def test_invalid_repo_format_rejected(self):
        """Repo must be in owner/name format (contain a slash)."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="invalid-repo-no-slash",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment="Test assessment",
        )
        assert result["status"] == "error"
        assert "repo" in result["validation"]["error"].lower()

    def test_empty_assessment_rejected(self):
        """Assessment must not be empty or whitespace-only."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment="   ",
        )
        assert result["status"] == "error"
        assert "assessment" in result["validation"]["error"].lower()

    @pytest.mark.parametrize(
        "hostile_repo",
        [
            "../../etc/passwd/x",
            "o/r?foo=bar",
            "o/r/../../../user",
            "owner/repo name",
            "owner/repo\n",
            "owner/../repo",
            "/etc/passwd",
            "owner/",
            "/repo",
            "owner//repo",
            "owner/repo/",
            "-owner/repo",
            "owner/..",
            "owner/.",
        ],
    )
    def test_hostile_repo_strings_rejected(self, hostile_repo):
        """Rework #2 (PR #148 finding 1, CE + CIV): ``repo`` was checked only
        for containing a slash, then interpolated straight into ``gh api``
        paths across four call sites (the original ``_post_comment`` plus
        the three new Actions-API sites this PR added). Must now enforce
        strict ``owner/name``: exactly one slash, each side matching
        GitHub's own allowed character set, no traversal, no query string,
        no whitespace.
        """
        from hestai_context_mcp.tools.submit_review import submit_review

        # Belt-and-braces: patch subprocess.run so that even if the
        # validator has a gap for a given hostile string, this test cannot
        # make a real `gh` call -- test isolation must not depend on the
        # validator being correct.
        with patch("subprocess.run") as mock_run:
            result = submit_review(
                repo=hostile_repo,
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="Test assessment",
            )

        assert result["status"] == "error"
        assert "repo" in result["validation"]["error"].lower()
        mock_run.assert_not_called()

    def test_hostile_repo_never_reaches_subprocess(self):
        """Not just "validation returned an error" -- the hostile value must
        never be handed to ``gh`` at all, for any of the four interpolation
        sites (post-comment, PR head-SHA lookup, run listing, rerun).
        """
        from hestai_context_mcp.tools.submit_review import submit_review

        with patch("subprocess.run") as mock_run:
            result = submit_review(
                repo="../../etc/passwd/x",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="Test assessment",
                dry_run=False,
            )

        assert result["status"] == "error"
        mock_run.assert_not_called()

    def test_valid_repo_with_dots_and_hyphens_accepted(self):
        """Legitimate repo names use '.', '_', '-' -- the strict validator
        must not over-reject real GitHub repo names. (Owner names cannot
        contain underscores per GitHub's own rules, so only the repo-name
        side exercises '_' here.)
        """
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="my-org-1/my.repo-name_2",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment="Verified.",
            dry_run=True,
        )
        assert result["status"] == "ok"

    def test_negative_pr_number_rejected(self):
        """PR number must be a positive integer."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=-1,
            role="CE",
            verdict="APPROVED",
            assessment="Test assessment",
        )
        assert result["status"] == "error"
        assert "pr" in result["validation"]["error"].lower()

    def test_zero_pr_number_rejected(self):
        """PR number 0 must be rejected."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=0,
            role="CE",
            verdict="APPROVED",
            assessment="Test assessment",
        )
        assert result["status"] == "error"

    @pytest.mark.parametrize("role", ["CE", "CIV", "CRS", "HO", "IL", "PE", "SR", "TMG"])
    def test_all_valid_roles_accepted(self, role: str):
        """All 8 valid roles must be accepted."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role=role,
            verdict="APPROVED",
            assessment="Test assessment",
            dry_run=True,
        )
        assert result["status"] == "ok"

    @pytest.mark.parametrize("verdict", ["APPROVED", "BLOCKED", "CONDITIONAL", "REJECTED"])
    def test_all_valid_verdicts_accepted(self, verdict: str):
        """All 4 valid verdicts must be accepted.

        REJECTED regression (elevanaltd/elevana-studio PR #1694): the tool used
        to reject REJECTED outright, forcing callers to pass verdict='BLOCKED'
        while leaving their own 'CE REJECTED: ...' header in the assessment
        text -- producing double-headered comments like
        'CE BLOCKED: CE REJECTED: ...'. REJECTED must now be accepted as a
        first-class, non-clearing verdict (see TestRejectedVerdict below).
        """
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict=verdict,
            assessment="Test assessment",
            dry_run=True,
        )
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Dry-run tests
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestDryRun:
    """dry_run=True must return validation results without HTTP calls."""

    def test_dry_run_returns_success_without_posting(self):
        """dry_run should not make any HTTP/subprocess calls."""
        from hestai_context_mcp.tools.submit_review import submit_review

        with patch("subprocess.run") as mock_run:
            result = submit_review(
                repo="owner/repo",
                pr_number=42,
                role="CRS",
                verdict="APPROVED",
                assessment="Code quality verified.",
                dry_run=True,
            )
            mock_run.assert_not_called()

        assert result["status"] == "ok"
        assert result["dry_run"] is True
        assert result["comment_url"] is None

    def test_dry_run_returns_validation_info(self):
        """dry_run must include validation details."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=42,
            role="CRS",
            verdict="APPROVED",
            assessment="Tests look good.",
            dry_run=True,
        )
        assert "validation" in result
        validation = result["validation"]
        assert "would_clear_gate" in validation
        assert validation["would_clear_gate"] is True

    def test_dry_run_blocked_does_not_clear_gate(self):
        """BLOCKED verdict in dry_run should report would_clear_gate=False."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=42,
            role="CRS",
            verdict="BLOCKED",
            assessment="Issues found.",
            dry_run=True,
        )
        assert result["status"] == "ok"
        assert result["validation"]["would_clear_gate"] is False

    def test_dry_run_conditional_does_not_clear_gate(self):
        """CONDITIONAL verdict in dry_run should report would_clear_gate=False."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=42,
            role="CE",
            verdict="CONDITIONAL",
            assessment="Minor issues.",
            dry_run=True,
        )
        assert result["status"] == "ok"
        assert result["validation"]["would_clear_gate"] is False

    def test_dry_run_with_commit_sha(self):
        """dry_run with commit_sha should include it in the response."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=42,
            role="CE",
            verdict="APPROVED",
            assessment="All good.",
            commit_sha="abc1234",
            dry_run=True,
        )
        assert result["status"] == "ok"
        # The formatted comment should contain the SHA reference

    def test_dry_run_with_model_annotation(self):
        """dry_run with model_annotation should include it in formatting."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=42,
            role="CRS",
            verdict="APPROVED",
            assessment="Verified.",
            model_annotation="Gemini",
            dry_run=True,
        )
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Comment formatting tests
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestCommentFormatting:
    """Formatted comments must match the review-gate pattern."""

    def test_approved_comment_contains_role_and_verdict(self):
        """The formatted comment must contain the role and APPROVED keyword."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment="Implementation verified.",
            dry_run=True,
        )
        comment = result["validation"]["formatted_comment"]
        assert "CE" in comment
        assert "APPROVED" in comment
        assert "Implementation verified." in comment

    def test_il_approved_maps_to_self_reviewed(self):
        """IL + APPROVED must use SELF-REVIEWED keyword for gate matching."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="IL",
            verdict="APPROVED",
            assessment="Quick fix verified.",
            dry_run=True,
        )
        comment = result["validation"]["formatted_comment"]
        assert "SELF-REVIEWED" in comment

    def test_ho_approved_maps_to_reviewed(self):
        """HO + APPROVED must use REVIEWED keyword for gate matching."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="HO",
            verdict="APPROVED",
            assessment="Delegated work verified.",
            dry_run=True,
        )
        comment = result["validation"]["formatted_comment"]
        assert "REVIEWED" in comment

    def test_model_annotation_in_comment(self):
        """Model annotation should appear in parentheses after the role."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CRS",
            verdict="APPROVED",
            assessment="Verified.",
            model_annotation="Gemini",
            dry_run=True,
        )
        comment = result["validation"]["formatted_comment"]
        assert "CRS (Gemini)" in comment

    def test_commit_sha_in_metadata(self):
        """commit_sha should appear in the machine-readable metadata."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment="Verified at commit.",
            commit_sha="abc1234def5678",
            dry_run=True,
        )
        comment = result["validation"]["formatted_comment"]
        # Metadata HTML comment should contain the SHA (truncated to 7 chars)
        assert "abc1234" in comment

    def test_blocked_comment_format(self):
        """BLOCKED comments should use the BLOCKED keyword directly."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="BLOCKED",
            assessment="Critical issues found.",
            dry_run=True,
        )
        comment = result["validation"]["formatted_comment"]
        assert "BLOCKED" in comment
        assert "Critical issues found." in comment

    def test_metadata_html_comment_present(self):
        """Formatted comment must include machine-readable metadata HTML comment."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="TMG",
            verdict="APPROVED",
            assessment="Tests verified.",
            dry_run=True,
        )
        comment = result["validation"]["formatted_comment"]
        assert "<!-- review:" in comment
        assert "-->" in comment

    def test_invalid_sha_silently_dropped(self):
        """A commit_sha that isn't valid hex should be silently dropped."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment="Verified.",
            commit_sha="not-a-valid-sha!",
            dry_run=True,
        )
        comment = result["validation"]["formatted_comment"]
        # The invalid SHA should not appear in metadata
        assert "not-a-valid-sha!" not in comment


# ---------------------------------------------------------------------------
# Review-gate format compliance tests
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestGateCompliance:
    """The formatted comment must match the specific pattern that CI checks for."""

    @pytest.mark.parametrize("role", ["CE", "CIV", "CRS", "PE", "SR", "TMG"])
    def test_approved_clears_gate_for_standard_roles(self, role: str):
        """APPROVED verdict for standard roles must produce gate-clearing comments."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role=role,
            verdict="APPROVED",
            assessment="Verified.",
            dry_run=True,
        )
        assert result["status"] == "ok"
        assert result["validation"]["would_clear_gate"] is True

    def test_il_approved_clears_gate(self):
        """IL APPROVED (mapped to SELF-REVIEWED) must clear the gate."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="IL",
            verdict="APPROVED",
            assessment="Self-reviewed.",
            dry_run=True,
        )
        assert result["validation"]["would_clear_gate"] is True

    def test_ho_approved_clears_gate(self):
        """HO APPROVED (mapped to REVIEWED) must clear the gate."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="HO",
            verdict="APPROVED",
            assessment="Supervisory review.",
            dry_run=True,
        )
        assert result["validation"]["would_clear_gate"] is True


# ---------------------------------------------------------------------------
# REJECTED verdict tests (defect A: verdict vocabulary gap)
# ---------------------------------------------------------------------------
# Diagnosis correction: the original bug report described this as "REJECTED
# silently rewritten to BLOCKED". That mechanism does NOT exist in this code
# -- there is no rewrite anywhere. The actual mechanism is that
# _validate_inputs() rejected the verdict='REJECTED' call outright (REJECTED
# was absent from VALID_VERDICTS), so callers worked around the hard failure
# by passing verdict='BLOCKED' while leaving their own "CE REJECTED: ..."
# text at the head of the assessment -- producing the observed double-headed
# "CE BLOCKED: CE REJECTED: ..." comments on elevana-studio PR #1694.
@pytest.mark.unit
class TestRejectedVerdict:
    """REJECTED must be a first-class, non-gate-clearing verdict."""

    def test_rejected_verdict_is_accepted_not_rewritten(self):
        """A REJECTED verdict must be accepted verbatim, not rejected or rewritten.

        Pins requirement: 'never silently rewrite a reviewer's verdict'. The
        formatted comment must contain the literal token REJECTED -- not
        BLOCKED, and not a duplicated/rewritten verdict.
        """
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="REJECTED",
            assessment="Fundamental design flaw.",
            dry_run=True,
        )
        assert result["status"] == "ok"
        comment = result["validation"]["formatted_comment"]
        assert "CE REJECTED: Fundamental design flaw." in comment
        assert "BLOCKED" not in comment

    @pytest.mark.parametrize("role", ["CE", "CIV", "CRS", "PE", "SR", "TMG", "IL", "HO"])
    def test_rejected_never_clears_gate(self, role: str):
        """REJECTED must never clear the review gate, for any role.

        Same non-clearing class as BLOCKED -- a REJECTED verdict is a valid
        review comment but must not satisfy the gate's approval check.
        """
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role=role,
            verdict="REJECTED",
            assessment="Not acceptable.",
            dry_run=True,
        )
        assert result["status"] == "ok"
        assert result["validation"]["would_clear_gate"] is False

    def test_rejected_comment_does_not_satisfy_approval_matcher(self):
        """A REJECTED comment must not match any role's approval pattern.

        Proves non-clearing with a test, not just an assertion on the tool's
        own self-check: runs the formatted comment through the same matcher
        the CI gate uses.
        """
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            has_ce_approval,
        )

        comment = format_review_comment(role="CE", verdict="REJECTED", assessment="No.")
        assert has_ce_approval([comment]) is False

    def test_invalid_verdict_error_lists_rejected_as_accepted(self):
        """The invalid-verdict error message must name REJECTED as accepted."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="NOT_A_REAL_VERDICT",
            assessment="Test assessment",
        )
        assert result["status"] == "error"
        assert "REJECTED" in result["validation"]["error"]

    def test_historical_double_headed_ce_blocked_rejected_comment_still_parses(self):
        """Backwards compatibility: pre-fix 'CE BLOCKED: CE REJECTED: ...'
        comments already posted on elevana-studio PR #1694 must remain
        legible/parseable by the gate -- i.e. still recognized as a BLOCKED
        (non-clearing) comment, not silently reinterpreted as an approval.
        """
        from hestai_context_mcp.tools.shared.review_formats import (
            has_ce_approval,
            matches_approval_pattern,
        )

        historical_comment = "CE BLOCKED: CE REJECTED: fundamental design flaw in the retry logic"
        assert matches_approval_pattern(historical_comment, "CE", "BLOCKED") is True
        assert has_ce_approval([historical_comment]) is False


# ---------------------------------------------------------------------------
# Byte-exact header tests (requirement 6)
# ---------------------------------------------------------------------------
# "Worth pinning as a test, since this is a gate whose own tooling can't
# currently emit a gate-readable verdict." -- pins the exact header shape for
# the pass-through path (no pre-existing header in the assessment): no
# parenthetical, no duplication.
@pytest.mark.unit
class TestByteExactHeader:
    """The formatted comment must begin with an exact, unadorned header."""

    def test_approved_header_is_byte_exact(self):
        from hestai_context_mcp.tools.shared.review_formats import format_review_comment

        comment = format_review_comment(role="CE", verdict="APPROVED", assessment="Looks good.")
        assert comment.startswith("CE APPROVED: Looks good.")
        assert comment.split("\n", 1)[0] == "CE APPROVED: Looks good."

    def test_rejected_header_is_byte_exact(self):
        from hestai_context_mcp.tools.shared.review_formats import format_review_comment

        comment = format_review_comment(
            role="CE", verdict="REJECTED", assessment="Fundamental design flaw."
        )
        assert comment.startswith("CE REJECTED: Fundamental design flaw.")
        assert comment.split("\n", 1)[0] == "CE REJECTED: Fundamental design flaw."


# ---------------------------------------------------------------------------
# Header/verdict conflict validation (rework #2: structural fix)
# ---------------------------------------------------------------------------
# Rework #1 closed BLOCKED and REJECTED fail-opens with a prose-negation
# denylist widening, but CONDITIONAL stayed open -- it isn't a negation word
# and never will be, so no denylist entry could ever cover it. That coupling
# (verdict vocabulary <-> denylist upkeep) is the actual defect. The
# structural fix rejects the submit_review() call outright -- through the
# standard validation error envelope, at _validate_inputs() -- whenever the
# assessment's own header disagrees with the submitted verdict, for ANY
# verdict. No formatted_comment, no gate-clearing artifact, is ever produced.
@pytest.mark.unit
class TestHeaderVerdictConflictValidation:
    """submit_review() rejects (not silently resolves) a header/verdict conflict."""

    @pytest.mark.parametrize("verdict", ["BLOCKED", "REJECTED", "CONDITIONAL"])
    def test_non_approving_verdict_with_approved_header_is_rejected(self, verdict: str):
        """Table-driven contradiction case across ALL non-approving verdicts.

        This is the RED case for CONDITIONAL: prior to the structural fix,
        submit_review(role='CE', verdict='CONDITIONAL',
        assessment="CE APPROVED: looks fine to me") returned status='ok'
        with a formatted_comment that satisfied has_ce_approval() --
        i.e. cleared the gate on a non-approving verdict. Must now be
        REJECTED as a validation error instead, for all three non-approving
        verdicts uniformly.
        """
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict=verdict,
            assessment="CE APPROVED: looks fine to me",
            dry_run=True,
        )
        assert result["status"] == "error"
        assert result["error_type"] == "validation"
        error = result["validation"]["error"]
        assert "CE APPROVED" in error
        assert verdict in error
        # No gate-clearing (or any) comment artifact is produced on the error path.
        assert "formatted_comment" not in result["validation"]

    def test_conditional_contradiction_produces_no_gate_clearing_body(self):
        """Direct proof for the CONDITIONAL case the coordinator flagged:
        no body is ever produced, so has_ce_approval() has nothing to
        wrongly clear on.
        """
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="CONDITIONAL",
            assessment="CE APPROVED: looks fine to me",
            dry_run=True,
        )
        assert result["status"] == "error"
        assert result.get("comment_url") is None

    def test_approved_verdict_with_blocked_header_is_also_rejected(self):
        """Disagreement in the harmless direction is rejected too -- the tool
        never silently prepends over, or silently trusts, the caller's own
        conflicting header text.
        """
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment="CE BLOCKED: actually there are issues",
            dry_run=True,
        )
        assert result["status"] == "error"
        assert result["error_type"] == "validation"

    def test_agreement_case_is_accepted(self):
        """Control: a header that AGREES with the verdict is unaffected."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment="CE APPROVED: https://example.com/evidence",
            dry_run=True,
        )
        assert result["status"] == "ok"
        assert result["validation"]["would_clear_gate"] is True

    def test_no_header_case_is_accepted(self):
        """Control: ordinary assessment text with no header is unaffected."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="BLOCKED",
            assessment="There are real issues here.",
            dry_run=True,
        )
        assert result["status"] == "ok"

    def test_il_substituted_keyword_agreement_is_accepted(self):
        """Control: IL/APPROVED against a body already agreeing via the
        substituted SELF-REVIEWED keyword is unaffected.
        """
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="IL",
            verdict="APPROVED",
            assessment="IL SELF-REVIEWED: fixed typo",
            dry_run=True,
        )
        assert result["status"] == "ok"

    def test_il_approved_header_conflicts_with_self_reviewed_substitution(self):
        """IL/APPROVED resolves to SELF-REVIEWED; a body opening
        'IL APPROVED:' disagrees with that resolved keyword and is rejected,
        not silently treated as agreement.
        """
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="IL",
            verdict="APPROVED",
            assessment="IL APPROVED: fixed typo",
            dry_run=True,
        )
        assert result["status"] == "error"
        assert result["error_type"] == "validation"


# ---------------------------------------------------------------------------
# Cross-role GATE-CORRUPTION rejection (elevana-studio#1851, PARTIAL; REWORK
# after four-reviewer rejection of the position-0 header-shape approach).
#
# TMG/CE/CRS/CIV rejected the original position-0 header-shape denylist
# (_detect_cross_role_header / _match_existing_header_token) with
# independently reproduced false-approval evidence: CIV enumerated nine
# distinct shapes -- leading space, the "(Model)" relay annotation, a BOM
# character, a tab separator, markdown bold markers, the APPROVES
# conjugation, the GO keyword, a dotless-i case-fold of "CIV" (Unicode
# U+0131, which Python's re.IGNORECASE maps to "I"), and a markdown table
# row -- ALL of which bypass the position-0-of-first-line shape check while
# still clearing the FINISHED comment's REAL gate matcher (has_*_approval).
# Four reviewers agreed: a shape denylist guarding a matcher that is not
# shape-based is guaranteed to keep leaking. TMG additionally showed the
# original position-zero-only control test was itself gate-corrupting: it
# asserted status=="ok" for a body whose second line manufactures a TMG
# approval that has_tmg_approval() actually recognises -- i.e. it ratified
# the defect as intended behaviour. The "reviewers legitimately quote each
# other" premise behind that test was WITHDRAWN by the coordinator after
# CIV showed every "legitimate quoting" example CIV tried also cleared the
# quoted role's gate.
#
# ROOT-CAUSE FIX (root-caused in the codebase's own prior art --
# _matches_role_gate()'s docstring already states shape checks are not the
# safety boundary and warns against maintaining a shape-specific denylist):
# compose the FINISHED comment, then run every OTHER role's REAL
# has_*_approval() matcher over it. If the finished comment would clear ANY
# role's gate other than the submitted role, hard-reject -- unconditionally,
# with no abstain posture, because a body that clears a foreign gate is
# counted by the CI gate exactly as if that role had posted it. This closes
# all nine shapes above (and any future one) in one rule, because it
# consults the actual matcher rather than modelling it.
#
# NOT provenance validation: this closes the gate-CORRUPTION shape only
# (a body that would clear an ADDITIONAL role's gate beyond the one it is
# submitted under). It has NO ability to catch a body that self-labels with
# the MATCHING (wrong) role and clears ONLY that role's own gate -- per
# technical-architect deep-tier ruling, PR #1840's mislabelled verdict was
# lexically self-consistent as CE at every layer (it never touched a second
# role's gate), so this check would NOT have caught it. Establishing an
# actual dispatched-reviewer identity requires a Workbench-issued dispatch
# attestation, out of this repo's scope per North Star §4 ("agent identity
# or governance (Vault owns)").
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestCrossRoleGateCorruptionRejection:
    """submit_review() rejects a FINISHED comment that would clear any
    role's gate other than the one it is submitted under -- matcher-based,
    not shape-based. Each of CIV's nine reproduced bypass shapes is proven
    individually (RATIFIED record ASSERTION_SCOPE: per-assertion evidence,
    not file-level RED)."""

    def test_leading_space_shape_is_rejected(self):
        """A foreign role's approval on its own line, preceded by a space,
        clears that role's gate and must be rejected."""
        from hestai_context_mcp.tools.shared.review_formats import has_tmg_approval
        from hestai_context_mcp.tools.submit_review import submit_review

        assessment = "Implementation looks solid.\n TMG APPROVED: methodology verified"
        # Pre-condition: prove the finished comment WOULD clear TMG's real
        # gate before asserting the tool rejects it -- this is what makes
        # the shape a genuine bypass, not just cosmetic text.
        from hestai_context_mcp.tools.shared.review_formats import format_review_comment

        would_be_comment = format_review_comment(
            role="CE", verdict="APPROVED", assessment=assessment
        )
        assert has_tmg_approval([would_be_comment]) is True

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment=assessment,
            dry_run=True,
        )
        assert result["status"] == "error"
        assert result["error_type"] == "validation"
        assert result["comment_url"] is None

    def test_model_annotation_relay_shape_is_rejected(self):
        """The '(Model)' relay-annotation format -- the codebase's own
        documented, tested format for relayed foreign-model verdicts --
        clears the named role's gate and must be rejected when it names a
        role other than the submitted one."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            has_tmg_approval,
        )
        from hestai_context_mcp.tools.submit_review import submit_review

        assessment = "Implementation looks solid.\nTMG (Codex): APPROVED methodology verified"
        would_be_comment = format_review_comment(
            role="CE", verdict="APPROVED", assessment=assessment
        )
        assert has_tmg_approval([would_be_comment]) is True

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment=assessment,
            dry_run=True,
        )
        assert result["status"] == "error"

    def test_bom_shape_is_rejected(self):
        """A leading BOM (Unicode format character, category Cf) before a
        foreign role's header is stripped by the real matcher's
        normalisation and still clears that role's gate."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            has_tmg_approval,
        )
        from hestai_context_mcp.tools.submit_review import submit_review

        assessment = "Implementation looks solid.\n\ufeffTMG APPROVED: methodology verified"
        would_be_comment = format_review_comment(
            role="CE", verdict="APPROVED", assessment=assessment
        )
        assert has_tmg_approval([would_be_comment]) is True

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment=assessment,
            dry_run=True,
        )
        assert result["status"] == "error"

    def test_tab_separator_shape_is_rejected(self):
        """A tab character between a foreign role's name and its verdict
        keyword still clears that role's gate."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            has_tmg_approval,
        )
        from hestai_context_mcp.tools.submit_review import submit_review

        assessment = "Implementation looks solid.\nTMG\tAPPROVED: methodology verified"
        would_be_comment = format_review_comment(
            role="CE", verdict="APPROVED", assessment=assessment
        )
        assert has_tmg_approval([would_be_comment]) is True

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment=assessment,
            dry_run=True,
        )
        assert result["status"] == "error"

    def test_bold_markers_shape_is_rejected(self):
        """Markdown bold markers around a foreign role's header are
        stripped by the real matcher before matching and still clear that
        role's gate."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            has_tmg_approval,
        )
        from hestai_context_mcp.tools.submit_review import submit_review

        assessment = "Implementation looks solid.\n**TMG APPROVED**: methodology verified"
        would_be_comment = format_review_comment(
            role="CE", verdict="APPROVED", assessment=assessment
        )
        assert has_tmg_approval([would_be_comment]) is True

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment=assessment,
            dry_run=True,
        )
        assert result["status"] == "error"

    def test_approves_conjugation_shape_is_rejected(self):
        """The APPROVES conjugation (outside the header-shape token
        allowlist) still clears the foreign role's real gate matcher, which
        widens APPROVED to the APPROVE(D|S)? family."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            has_tmg_approval,
        )
        from hestai_context_mcp.tools.submit_review import submit_review

        assessment = "Implementation looks solid.\nTMG APPROVES: methodology verified"
        would_be_comment = format_review_comment(
            role="CE", verdict="APPROVED", assessment=assessment
        )
        assert has_tmg_approval([would_be_comment]) is True

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment=assessment,
            dry_run=True,
        )
        assert result["status"] == "error"

    def test_go_keyword_shape_is_rejected(self):
        """The GO keyword (outside the header-shape token allowlist) still
        clears the foreign role's real gate matcher, which accepts GO as an
        approval synonym."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            has_tmg_approval,
        )
        from hestai_context_mcp.tools.submit_review import submit_review

        assessment = "Implementation looks solid.\nTMG GO: methodology verified"
        would_be_comment = format_review_comment(
            role="CE", verdict="APPROVED", assessment=assessment
        )
        assert has_tmg_approval([would_be_comment]) is True

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment=assessment,
            dry_run=True,
        )
        assert result["status"] == "error"

    def test_dotless_i_case_fold_shape_is_rejected(self):
        """A Turkish dotless-i (U+0131) spelling of 'CIV' -- 'C\u0131V' --
        still matches \bCIV\b under Python's re.IGNORECASE (which maps
        U+0131 up to 'I'), so it still clears CIV's real gate matcher even
        though it visually reads as a different token."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            has_civ_approval,
        )
        from hestai_context_mcp.tools.submit_review import submit_review

        assessment = "Implementation looks solid.\nC\u0131V APPROVED: architecture validates"
        would_be_comment = format_review_comment(
            role="CE", verdict="APPROVED", assessment=assessment
        )
        assert has_civ_approval([would_be_comment]) is True

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment=assessment,
            dry_run=True,
        )
        assert result["status"] == "error"

    def test_markdown_table_row_shape_is_rejected(self):
        """The markdown-table verdict-summary row -- the codebase's own
        documented, tested format ('| CE | Gemini | **APPROVED** |') --
        clears CE's gate when submitted under a different role. This is the
        coordinator's original reproduction: role='SR' with a body opening
        the table row clears CE's gate, not SR's."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            has_ce_approval,
        )
        from hestai_context_mcp.tools.submit_review import submit_review

        assessment = "| CE | Gemini | **APPROVED** |"
        would_be_comment = format_review_comment(
            role="SR", verdict="APPROVED", assessment=assessment
        )
        assert has_ce_approval([would_be_comment]) is True

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="SR",
            verdict="APPROVED",
            assessment=assessment,
            dry_run=True,
        )
        assert result["status"] == "error"

    def test_cross_role_rejection_precedes_posting(self):
        """The rejection must happen in validation, before _post_comment is
        ever called -- regression carried over from the original (withdrawn)
        position-0 implementation."""
        from hestai_context_mcp.tools.submit_review import submit_review

        with patch("hestai_context_mcp.tools.submit_review._post_comment") as mock_post:
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="Implementation looks solid.\nTMG APPROVED: methodology verified",
                dry_run=False,
            )
            assert result["status"] == "error"
            mock_post.assert_not_called()

    @pytest.mark.parametrize(
        "role",
        ["CRS", "CE", "SR", "IL", "HO", "TMG", "CIV", "PE"],
    )
    def test_matching_role_header_still_posts_regression(self, role: str):
        """Regression sweep: a header that AGREES with the submitted role
        (and clears ONLY that role's own gate) must still post normally for
        every VALID_ROLES member."""
        from hestai_context_mcp.tools.shared.review_formats import (
            resolve_verdict_keyword,
        )
        from hestai_context_mcp.tools.submit_review import submit_review

        keyword = resolve_verdict_keyword(role, "APPROVED")
        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role=role,
            verdict="APPROVED",
            assessment=f"{role} {keyword}: evidence checks out",
            dry_run=True,
        )
        assert result["status"] == "ok"

    def test_unknown_provenance_does_not_block(self):
        """An assessment with NO role header at all proceeds with no block
        and no flag -- deliberately no `role_provenance` field, since it
        would be emitted on ~100% of calls and read as coverage nobody can
        act on."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment="Architecture validates cleanly, no issues found.",
            dry_run=True,
        )
        assert result["status"] == "ok"
        assert "role_provenance" not in result["validation"]
        # Verified against the real return shape, not asserted on faith:
        # format_review_comment() PREPENDS the role's own "CE APPROVED: "
        # header when the assessment has none, so the FINISHED comment
        # always carries a matching header and would_clear_gate is True
        # here, exactly as expected.
        assert result["validation"]["would_clear_gate"] is True

    def test_legitimate_cross_role_reference_that_does_not_clear_foreign_gate_still_posts(self):
        """INVERTED per coordinator addendum: the withdrawn premise was
        that a body which clears a foreign role's gate should be tolerated
        as "reviewers legitimately quoting each other" (see the removed
        test_cross_role_scan_is_position_zero_only, which this test set
        replaces). That premise was wrong -- if it clears the gate, the CI
        gate counts it, so it must be rejected regardless of intent (see
        the nine rejection tests above).

        This is the positive control that protects against OVER-blocking:
        a reviewer CAN still reference another role's verdict status in
        prose, as long as that prose does NOT independently satisfy the
        referenced role's own real gate matcher (e.g. no bare
        "<ROLE> APPROVED"-shaped line). Confirmed the referenced role's
        matcher is actually False on the finished comment, not assumed.
        """
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            has_tmg_approval,
        )
        from hestai_context_mcp.tools.submit_review import submit_review

        assessment = (
            "Implementation is sound.\n"
            "Test methodology (TMG) sign-off is tracked separately and is "
            "not represented in this comment."
        )
        would_be_comment = format_review_comment(
            role="CE", verdict="APPROVED", assessment=assessment
        )
        # Pre-condition: this phrasing does NOT clear TMG's gate -- "TMG"
        # never appears at true line-start (it's inside a parenthetical
        # mid-sentence), so has_tmg_approval's line-start-or-after-pipe
        # anchor never fires.
        assert has_tmg_approval([would_be_comment]) is False

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment=assessment,
            dry_run=True,
        )
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Symmetric gate guard (rework #3): the invariant enforced on the FINISHED
# artifact, not inferred from header shape
# ---------------------------------------------------------------------------
# Cubic (bot review) found four additional fail-open shapes on top of the
# rework #2 structural (header-shape) fix, all against role=CE:
#
#   format_review_comment('CE','CONDITIONAL','CE GO: fine')
#     -> 'CE CONDITIONAL: CE GO: fine'               has_ce_approval TRUE
#   format_review_comment('CE','CONDITIONAL','CE APPROVES: fine')
#     -> 'CE CONDITIONAL: CE APPROVES: fine'         has_ce_approval TRUE
#   format_review_comment('CE','REJECTED','summary text\nCE APPROVED: fine')
#     -> approval survives on line 2                 has_ce_approval TRUE
#   format_review_comment('CE','REJECTED','ce approved: fine')
#     -> 'CE REJECTED: ce approved: fine'            has_ce_approval TRUE
#   format_review_comment('CE','REJECTED','CE REJECTED: the SR APPROVED this')
#     -> 'CE REJECTED: the SR APPROVED this'         has_ce_approval TRUE
#
# Root cause: detect_header_verdict_conflict() only inspects the assessment's
# LEADING header shape ("<role> <token>:" at position 0, token drawn from
# _RECOGNIZED_HEADER_TOKENS which does NOT include GO or the APPROVE(D|S)?
# conjugation family). It cannot see approving text using a token outside
# that allowlist, on a later line, in a different case, or with no header
# shape at all.
#
# Fix: submit_review() now runs the role's REAL gate matcher
# (_matches_role_gate(), the same has_*_approval() functions the CI gate
# uses) over the FINISHED formatted comment, symmetrically:
#   verdict == APPROVED  and NOT matches -> error (existed already)
#   verdict != APPROVED  and     matches -> error (this fix)
# This is exhaustive by construction -- it consults the actual matcher, not
# a model of it -- so no future token/case/position variant can evade it.
@pytest.mark.unit
class TestSymmetricGateGuard:
    """A non-approving verdict must never emit a comment that satisfies the
    role's gate matcher, regardless of shape, case, position, or token."""

    # Evasion shapes, parametrized by role, using each role's OWN gate
    # keyword family (APPROVED-family roles use APPROVED/APPROVES/GO; IL
    # uses SELF-REVIEWED; HO uses REVIEWED -- has_ho_review only recognizes
    # REVIEWED, no GO alias for HO).
    _APPROVED_FAMILY_ROLES = ["CRS", "CE", "TMG", "CIV", "PE", "SR"]

    @staticmethod
    def _evasion_shapes_for(role: str) -> dict[str, str]:
        """Map shape-name -> assessment text containing an evasive approval
        for this role, using tokens/positions/case the header-shape check
        (detect_header_verdict_conflict) does NOT cover."""
        if role in TestSymmetricGateGuard._APPROVED_FAMILY_ROLES:
            return {
                "leading_go_header": f"{role} GO: fine",
                "leading_approves_header": f"{role} APPROVES: fine",
                "approval_on_later_line": f"Summary text.\n{role} APPROVED: fine",
                "lowercase_header": f"{role.lower()} approved: fine",
                "documented_table_format": f"| {role} | Gemini | **APPROVED** |",
            }
        if role == "IL":
            return {
                "approval_on_later_line": "Summary text.\nIL SELF-REVIEWED: fine",
                "lowercase_header": "il self-reviewed: fine",
            }
        if role == "HO":
            return {
                "approval_on_later_line": "Summary text.\nHO REVIEWED: fine",
                "lowercase_header": "ho reviewed: fine",
            }
        raise ValueError(f"no evasion shapes defined for role {role!r}")

    # --- Matrix A: role=CE fixed, full cross of verdict x evasion shape ---
    @pytest.mark.parametrize("verdict", ["BLOCKED", "REJECTED", "CONDITIONAL"])
    @pytest.mark.parametrize(
        "shape",
        [
            "leading_go_header",
            "leading_approves_header",
            "approval_on_later_line",
            "lowercase_header",
            "documented_table_format",
        ],
    )
    def test_ce_evasion_matrix_is_refused(self, verdict: str, shape: str):
        """The invariant under test is 'never emits gate-clearing text for a
        non-approving verdict', not 'always refuses'. For most cells the
        symmetric guard enforces this by REFUSING the call (status=error).
        For BLOCKED specifically combined with a shape where the evasive
        token sits on the SAME LINE immediately after the canonical
        "CE BLOCKED:" prefix (leading_go_header, leading_approves_header,
        documented_table_format), the invariant already held BEFORE this
        fix and without refusal: "BLOCKED" is itself a pre-existing
        _NEGATION_HEDGE_RE denylist word, and it lands literally in the gap
        between the role prefix and the evasive approval keyword on that
        same line, so has_ce_approval() already correctly returns False --
        verified directly:
            has_ce_approval(['CE BLOCKED: CE GO: fine']) -> False
            has_ce_approval(['CE BLOCKED: CE APPROVES: fine']) -> False
            has_ce_approval(['CE BLOCKED: | CE | Gemini | **APPROVED** |']) -> False
        Forcing an outright refusal for an input that is ALREADY safe would
        be over-fitting the test to a blanket claim ("every cell is a
        fail-open") that doesn't hold for those three specific cells, not
        testing the actual invariant. REJECTED and CONDITIONAL are not
        negation words, so the same same-line shapes DO leak for those two
        verdicts without this fix, and must be refused -- asserted below via
        the general invariant, which is what actually matters.
        """
        from hestai_context_mcp.tools.submit_review import submit_review

        assessment = self._evasion_shapes_for("CE")[shape]
        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict=verdict,
            assessment=assessment,
            dry_run=True,
        )
        if result["status"] == "error":
            assert result["error_type"] == "validation"
            assert "formatted_comment" not in result["validation"]
        else:
            # Not refused -- acceptable ONLY if it is independently proven
            # (via the real matcher the tool itself just ran) to never have
            # been gate-clearing in the first place.
            assert result["status"] == "ok"
            assert result["validation"]["would_clear_gate"] is False, (
                f"role=CE verdict={verdict} shape={shape} assessment={assessment!r} "
                f"was neither refused NOR proven safe: {result}"
            )

    # --- Matrix B: role coverage, one representative shape per role ---
    @pytest.mark.parametrize("role", ["CRS", "CE", "TMG", "CIV", "PE", "SR", "IL", "HO"])
    @pytest.mark.parametrize("verdict", ["BLOCKED", "REJECTED", "CONDITIONAL"])
    def test_every_role_evasion_via_later_line_is_refused(self, role: str, verdict: str):
        """Every role the gate checks has its OWN matcher (has_crs_approval,
        has_ce_approval, ..., has_self_review, has_ho_review) -- a role-blind
        test suite is how the next one of these gets through. Uses the
        'approval on a later line' shape, which is representative and
        applicable to every role's keyword family.
        """
        from hestai_context_mcp.tools.submit_review import submit_review

        assessment = self._evasion_shapes_for(role)["approval_on_later_line"]
        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role=role,
            verdict=verdict,
            assessment=assessment,
            dry_run=True,
        )
        assert result["status"] == "error", (
            f"role={role} verdict={verdict} assessment={assessment!r} " f"was NOT refused: {result}"
        )
        assert result["error_type"] == "validation"

    def test_exact_reported_cubic_repro_ce_conditional_go(self):
        """Byte-exact pin of the first cubic-reported repro."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="CONDITIONAL",
            assessment="CE GO: fine",
            dry_run=True,
        )
        assert result["status"] == "error"
        # Belt-and-braces: prove against the real matcher there is nothing
        # to accidentally post that would clear the gate.
        assert "formatted_comment" not in result["validation"]

    def test_exact_reported_cubic_repro_ce_rejected_approved_second_line(self):
        """Byte-exact pin of the third cubic-reported repro (later-line evasion)."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="REJECTED",
            assessment="summary text\nCE APPROVED: fine",
            dry_run=True,
        )
        assert result["status"] == "error"

    def test_exact_reported_cubic_repro_ce_rejected_lowercase(self):
        """Byte-exact pin of the fourth cubic-reported repro (case evasion)."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="REJECTED",
            assessment="ce approved: fine",
            dry_run=True,
        )
        assert result["status"] == "error"

    def test_exact_reported_cubic_repro_ce_rejected_other_role_approved(self):
        """Byte-exact pin of the fifth cubic-reported repro (own-verdict header,
        but a DIFFERENT role's approval embedded in the trailing prose)."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="REJECTED",
            assessment="CE REJECTED: the SR APPROVED this",
            dry_run=True,
        )
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Legitimate APPROVED formats must remain unaffected (regression risk of the
# symmetric guard above -- it must never turn a genuine approval into a
# refusal)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestLegitimateApprovalFormatsUnaffectedBySymmetricGuard:
    """The APPROVED direction, across every documented format, still clears."""

    def test_plain_approved_clears(self):
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment="Looks good, all tests pass.",
            dry_run=True,
        )
        assert result["status"] == "ok"
        assert result["validation"]["would_clear_gate"] is True

    def test_parenthetical_model_annotation_approved_clears(self):
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CRS",
            verdict="APPROVED",
            assessment="All tests pass.",
            model_annotation="Gemini",
            dry_run=True,
        )
        assert result["status"] == "ok"
        assert result["validation"]["would_clear_gate"] is True

    def test_go_alias_read_side_still_accepted_by_matcher(self):
        """GO remains a valid alias for APPROVED on the read side (this
        change does not touch matches_approval_pattern / has_*_approval).
        """
        from hestai_context_mcp.tools.shared.review_formats import has_ce_approval

        assert has_ce_approval(["CE GO: ship it"]) is True

    def test_documented_table_format_read_side_still_accepted_by_matcher(self):
        from hestai_context_mcp.tools.shared.review_formats import has_crs_approval

        assert has_crs_approval(["| CRS | Gemini | **APPROVED** |"]) is True

    def test_markdown_heading_format_read_side_still_accepted_by_matcher(self):
        from hestai_context_mcp.tools.shared.review_formats import has_tmg_approval

        assert has_tmg_approval(["## TMG APPROVED ✅"]) is True

    @pytest.mark.parametrize("role", ["CRS", "CE", "TMG", "CIV", "PE", "SR"])
    def test_every_approved_family_role_still_clears_plain_approval(self, role: str):
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role=role,
            verdict="APPROVED",
            assessment="Verified, no issues.",
            dry_run=True,
        )
        assert result["status"] == "ok"
        assert result["validation"]["would_clear_gate"] is True

    def test_il_self_reviewed_still_clears(self):
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="IL",
            verdict="APPROVED",
            assessment="Trivial fix, self-reviewed.",
            dry_run=True,
        )
        assert result["status"] == "ok"
        assert result["validation"]["would_clear_gate"] is True

    def test_ho_reviewed_still_clears(self):
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="HO",
            verdict="APPROVED",
            assessment="Delegated to IL, verified output.",
            dry_run=True,
        )
        assert result["status"] == "ok"
        assert result["validation"]["would_clear_gate"] is True


# ---------------------------------------------------------------------------
# Denylist scope confirmation (rework #2 reverted a rework #1 widening of
# _NEGATION_HEDGE_RE; rework #3 must NOT restore it -- pin the false-negative
# it caused, closed, and must stay closed)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestNegationDenylistAtMainScope:
    """_NEGATION_HEDGE_RE stays at its original (main) scope -- the symmetric
    guard makes the REJECTED-specific widening from rework #1 unnecessary,
    and that widening caused a real false-negative on a production gate.
    """

    def test_tmg_rejected_prose_does_not_block_a_later_genuine_approval(self):
        """'reject' (not 'reject(?:ed|s)?') is main's scope. Widening it in
        rework #1 caused this exact string to stop clearing -- a new
        false-negative on a production gate, found and reverted in rework
        #2. Must still clear on this HEAD.
        """
        from hestai_context_mcp.tools.shared.review_formats import has_tmg_approval

        text = "TMG rejected the first attempt; TMG APPROVED now"
        assert has_tmg_approval([text]) is True


# ---------------------------------------------------------------------------
# GitHub posting tests (mocked)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestGitHubPosting:
    """When dry_run=False, the tool must post via gh CLI."""

    def test_successful_post_returns_comment_url(self):
        """A successful post should return the comment URL."""
        from hestai_context_mcp.tools.submit_review import submit_review

        mock_stdout = (
            "HTTP/2 201 Created\n"
            "content-type: application/json\n"
            "\n"
            '{"html_url": "https://github.com/owner/repo/pull/1#issuecomment-123"}'
        )
        with (
            patch("subprocess.run") as mock_run,
            patch.dict("os.environ", {"GITHUB_TOKEN": "fake-token"}),
        ):
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = mock_stdout
            mock_run.return_value.stderr = ""

            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )

        assert result["status"] == "ok"
        assert "github.com" in result["comment_url"]

    def test_missing_github_token_returns_error(self):
        """Without GITHUB_TOKEN/GH_TOKEN AND no usable ``gh auth token``,
        posting should fail with an auth error.

        Patches subprocess so the test is deterministic regardless of
        whether the test host has ``gh`` installed and authenticated.
        Issue #34 introduces a third lookup tier (``gh auth token``); this
        test asserts the auth-error contract still holds when ALL three
        tiers fail.
        """
        from hestai_context_mcp.tools.submit_review import submit_review

        with (
            patch("subprocess.run", side_effect=FileNotFoundError("gh not installed")),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )

        assert result["status"] == "error"

    def test_gh_cli_error_returns_error(self):
        """gh CLI failures should be reported as errors."""
        from hestai_context_mcp.tools.submit_review import submit_review

        with (
            patch("subprocess.run") as mock_run,
            patch.dict("os.environ", {"GITHUB_TOKEN": "fake-token"}),
        ):
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = "Not Found"

            result = submit_review(
                repo="owner/repo",
                pr_number=999,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )

        assert result["status"] == "error"

    def test_timeout_returns_error(self):
        """Subprocess timeout should be handled gracefully."""
        import subprocess as sp

        from hestai_context_mcp.tools.submit_review import submit_review

        with (
            patch("subprocess.run", side_effect=sp.TimeoutExpired("gh", 30)),
            patch.dict("os.environ", {"GITHUB_TOKEN": "fake-token"}),
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )

        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# Return shape contract tests
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestReturnShape:
    """Verify the return dict matches the ADR-0353 contract.

    Issue #30 extends the contract: top-level ``commit_sha`` on BOTH success and
    error paths, top-level ``error_type`` on the error path. The nested
    ``validation.error_type`` form is RETAINED additively for backwards
    compatibility (deprecation deferred — see docstring).
    """

    def test_success_return_shape(self):
        """Successful dry_run must have: status, comment_url, validation, dry_run."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment="Verified.",
            dry_run=True,
        )
        assert "status" in result
        assert "comment_url" in result
        assert "validation" in result
        assert "dry_run" in result
        assert result["status"] == "ok"
        assert result["dry_run"] is True

    def test_error_return_shape(self):
        """Error responses must have: status, validation with error."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="bad-repo",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment="Test.",
        )
        assert result["status"] == "error"
        assert "validation" in result
        assert "error" in result["validation"]

    # ------------------------------------------------------------------
    # Issue #30 AC1: top-level commit_sha on BOTH success and error paths
    # ------------------------------------------------------------------
    def test_success_path_includes_top_level_commit_sha_echo(self):
        """When commit_sha is provided, success returns echo it at top level."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment="Verified.",
            commit_sha="abc1234def5678",
            dry_run=True,
        )
        assert result["status"] == "ok"
        assert "commit_sha" in result
        assert result["commit_sha"] == "abc1234def5678"

    def test_success_path_commit_sha_none_when_not_provided(self):
        """When commit_sha is omitted, success path exposes commit_sha=None at top level."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment="Verified.",
            dry_run=True,
        )
        assert result["status"] == "ok"
        assert "commit_sha" in result
        assert result["commit_sha"] is None

    def test_error_path_input_validation_includes_top_level_commit_sha(self):
        """Input-validation error path exposes commit_sha at top level (echo or None)."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="bad-repo",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment="Test.",
            commit_sha="deadbeef",
        )
        assert result["status"] == "error"
        assert "commit_sha" in result
        assert result["commit_sha"] == "deadbeef"

    def test_error_path_post_failure_includes_top_level_commit_sha(self):
        """Post-failure error path exposes commit_sha at top level."""
        from hestai_context_mcp.tools.submit_review import submit_review

        with (
            patch("subprocess.run") as mock_run,
            patch.dict("os.environ", {"GITHUB_TOKEN": "fake-token"}),
        ):
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = "rate limit exceeded"

            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="Verified.",
                commit_sha="abc1234",
                dry_run=False,
            )

        assert result["status"] == "error"
        assert "commit_sha" in result
        assert result["commit_sha"] == "abc1234"

    # ------------------------------------------------------------------
    # Issue #30 AC2: top-level error_type on error path; nested form
    # RETAINED additively for backwards compatibility (deprecation deferred)
    # ------------------------------------------------------------------
    def test_error_path_input_validation_includes_top_level_error_type(self):
        """Input-validation errors expose error_type at top level."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="bad-repo",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment="Test.",
        )
        assert result["status"] == "error"
        assert "error_type" in result
        assert result["error_type"] == "validation"

    def test_error_path_post_failure_includes_top_level_error_type(self):
        """Post-failure errors expose error_type at top level."""
        from hestai_context_mcp.tools.submit_review import submit_review

        with (
            patch("subprocess.run") as mock_run,
            patch.dict("os.environ", {"GITHUB_TOKEN": "fake-token"}),
        ):
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = "rate limit exceeded"

            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="Verified.",
                dry_run=False,
            )

        assert result["status"] == "error"
        assert "error_type" in result
        assert result["error_type"] == "rate_limit"

    def test_error_path_post_failure_retains_nested_error_type(self):
        """AC2 ADDITIVE: nested validation.error_type is RETAINED for backwards compat."""
        from hestai_context_mcp.tools.submit_review import submit_review

        with (
            patch("subprocess.run") as mock_run,
            patch.dict("os.environ", {"GITHUB_TOKEN": "fake-token"}),
        ):
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = "rate limit exceeded"

            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="Verified.",
                dry_run=False,
            )

        assert result["status"] == "error"
        # Nested form retained for backwards compatibility — DO NOT remove
        # without coordinated workbench-team signal (see docstring).
        assert "error_type" in result["validation"]
        assert result["validation"]["error_type"] == "rate_limit"
        # Top-level and nested values must agree while both forms coexist.
        assert result["error_type"] == result["validation"]["error_type"]

    # ------------------------------------------------------------------
    # AC1 surface coverage: commit_sha echo on remaining error branches
    # (gate-validation failure, missing token, timeout). Per TMG verdict
    # on f6c6fdc — issue #30.
    # ------------------------------------------------------------------
    def test_error_path_gate_validation_failure_includes_top_level_commit_sha(self):
        """Gate-validation error path exposes commit_sha at top level (echo)."""
        from hestai_context_mcp.tools.submit_review import submit_review

        # Patch _check_would_clear_gate to force the format-validation
        # error branch (status=error, validation.would_clear_gate=False).
        with patch(
            "hestai_context_mcp.tools.submit_review._check_would_clear_gate",
            return_value=False,
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="Verified.",
                commit_sha="gatefail123",
                dry_run=True,
            )
        assert result["status"] == "error"
        assert "commit_sha" in result
        assert result["commit_sha"] == "gatefail123"

    def test_error_path_gate_validation_failure_includes_top_level_error_type(self):
        """Gate-validation errors expose error_type='validation' at top level."""
        from hestai_context_mcp.tools.submit_review import submit_review

        with patch(
            "hestai_context_mcp.tools.submit_review._check_would_clear_gate",
            return_value=False,
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="Verified.",
                dry_run=True,
            )
        assert result["status"] == "error"
        assert "error_type" in result
        assert result["error_type"] == "validation"

    def test_error_path_missing_token_includes_top_level_commit_sha(self):
        """Missing-token auth error exposes commit_sha at top level (echo).

        Patches subprocess to deterministically simulate ``gh`` being absent
        so the third lookup tier (issue #34) cannot accidentally satisfy
        the precondition on hosts where ``gh auth token`` would succeed.
        """
        from hestai_context_mcp.tools.submit_review import submit_review

        with (
            patch("subprocess.run", side_effect=FileNotFoundError("gh not installed")),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="Verified.",
                commit_sha="authtest456",
                dry_run=False,
            )
        assert result["status"] == "error"
        assert "commit_sha" in result
        assert result["commit_sha"] == "authtest456"

    def test_error_path_missing_token_includes_top_level_error_type(self):
        """Missing-token auth error exposes error_type='auth' at top level.

        Patches subprocess to deterministically simulate ``gh`` being absent
        (see sibling test for rationale).
        """
        from hestai_context_mcp.tools.submit_review import submit_review

        with (
            patch("subprocess.run", side_effect=FileNotFoundError("gh not installed")),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="Verified.",
                dry_run=False,
            )
        assert result["status"] == "error"
        assert "error_type" in result
        assert result["error_type"] == "auth"

    def test_error_path_timeout_includes_top_level_commit_sha(self):
        """Timeout error path exposes commit_sha at top level (echo)."""
        import subprocess as sp

        from hestai_context_mcp.tools.submit_review import submit_review

        with (
            patch("subprocess.run", side_effect=sp.TimeoutExpired("gh", 30)),
            patch.dict("os.environ", {"GITHUB_TOKEN": "fake-token"}),
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="Verified.",
                commit_sha="timeout789",
                dry_run=False,
            )
        assert result["status"] == "error"
        assert "commit_sha" in result
        assert result["commit_sha"] == "timeout789"

    def test_error_path_timeout_includes_top_level_error_type(self):
        """Timeout error path exposes error_type='network' at top level."""
        import subprocess as sp

        from hestai_context_mcp.tools.submit_review import submit_review

        with (
            patch("subprocess.run", side_effect=sp.TimeoutExpired("gh", 30)),
            patch.dict("os.environ", {"GITHUB_TOKEN": "fake-token"}),
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="Verified.",
                dry_run=False,
            )
        assert result["status"] == "error"
        assert "error_type" in result
        assert result["error_type"] == "network"

    def test_success_path_does_not_include_top_level_error_type(self):
        """Top-level error_type appears ONLY on the error path."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment="Verified.",
            dry_run=True,
        )
        assert result["status"] == "ok"
        assert "error_type" not in result


# ---------------------------------------------------------------------------
# Token-resolution tests (issue #34)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestTokenResolution:
    """Three-tier token lookup: GITHUB_TOKEN -> GH_TOKEN -> ``gh auth token``.

    Per issue #34: the MCP server runs as a stdio subprocess and does not
    inherit the operator's ``gh`` keyring credentials. Falling back to
    ``gh auth token`` lets ``submit_review`` work whenever the operator has
    authenticated their CLI, without requiring a manual env-var export.

    Security invariants (must hold across ALL tests in this class):
      - The resolved token MUST NOT appear in any returned dict field.
      - The resolved token MUST NOT appear in any error message.
      - Subprocess calls to the real ``gh`` binary MUST be mocked.
    """

    # The sentinel token value used across this class. Any test that
    # exercises a successful resolution path MUST assert this string does
    # NOT appear in the returned result.
    SENSITIVE_TOKEN = "ghp_SENSITIVE_TOKEN_NEVER_LEAK_xxxxxxxxxxxxxxxx"

    @staticmethod
    def _post_success_completed(stdout_body: str = '{"html_url": "https://x/y"}'):
        """Build a CompletedProcess-like double for a successful API post."""

        class _CP:
            returncode = 0
            stdout = "HTTP/2 201 Created\ncontent-type: application/json\n\n" + stdout_body
            stderr = ""

        return _CP()

    # ------------------------------------------------------------------
    # Tier 1: GITHUB_TOKEN env wins; gh subprocess never invoked.
    # ------------------------------------------------------------------
    def test_github_token_env_skips_gh_auth_subprocess(self):
        """When GITHUB_TOKEN is set, the gh-auth-token fallback MUST NOT run."""
        from hestai_context_mcp.tools.submit_review import submit_review

        recorded_calls: list[list[str]] = []

        def _spy(cmd, *args, **kwargs):
            recorded_calls.append(list(cmd))
            return self._post_success_completed()

        with (
            patch("subprocess.run", side_effect=_spy),
            patch.dict("os.environ", {"GITHUB_TOKEN": self.SENSITIVE_TOKEN}, clear=True),
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )

        # Only the gh-api post call should be made; never `gh auth token`.
        assert all(call[:3] != ["gh", "auth", "token"] for call in recorded_calls), (
            f"gh auth token was unexpectedly invoked when GITHUB_TOKEN was set: "
            f"{recorded_calls}"
        )
        assert result["status"] == "ok"

    # ------------------------------------------------------------------
    # Tier 2: GH_TOKEN env wins; gh subprocess never invoked.
    # ------------------------------------------------------------------
    def test_gh_token_env_skips_gh_auth_subprocess(self):
        """When GH_TOKEN is set, the gh-auth-token fallback MUST NOT run."""
        from hestai_context_mcp.tools.submit_review import submit_review

        recorded_calls: list[list[str]] = []

        def _spy(cmd, *args, **kwargs):
            recorded_calls.append(list(cmd))
            return self._post_success_completed()

        with (
            patch("subprocess.run", side_effect=_spy),
            patch.dict("os.environ", {"GH_TOKEN": self.SENSITIVE_TOKEN}, clear=True),
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )

        assert all(call[:3] != ["gh", "auth", "token"] for call in recorded_calls)
        assert result["status"] == "ok"

    # ------------------------------------------------------------------
    # Tier 3: env empty, gh present, gh auth token succeeds.
    # ------------------------------------------------------------------
    def test_gh_auth_fallback_succeeds_when_env_empty(self):
        """env empty + ``gh auth token`` returns 0 with token -> posting proceeds."""
        from hestai_context_mcp.tools.submit_review import submit_review

        gh_auth_returned = False

        class _AuthCP:
            returncode = 0
            stdout = TestTokenResolution.SENSITIVE_TOKEN + "\n"
            stderr = ""

        def _router(cmd, *args, **kwargs):
            nonlocal gh_auth_returned
            if list(cmd[:3]) == ["gh", "auth", "token"]:
                gh_auth_returned = True
                return _AuthCP()
            # API post call
            return TestTokenResolution._post_success_completed()

        with (
            patch("subprocess.run", side_effect=_router),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )

        assert gh_auth_returned, "gh auth token fallback was not invoked"
        assert result["status"] == "ok"

    # ------------------------------------------------------------------
    # Tier 3 failures: each should produce the auth error.
    # ------------------------------------------------------------------
    def test_gh_not_installed_returns_auth_error(self):
        """env empty + gh not on PATH -> auth error (FileNotFoundError handled)."""
        from hestai_context_mcp.tools.submit_review import submit_review

        with (
            patch("subprocess.run", side_effect=FileNotFoundError("gh not found")),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )
        assert result["status"] == "error"
        assert result["error_type"] == "auth"

    def test_gh_auth_nonzero_returns_auth_error(self):
        """env empty + ``gh auth token`` returns non-zero -> auth error."""
        from hestai_context_mcp.tools.submit_review import submit_review

        class _AuthFailCP:
            returncode = 1
            stdout = ""
            stderr = "not logged in"

        with (
            patch("subprocess.run", return_value=_AuthFailCP()),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )
        assert result["status"] == "error"
        assert result["error_type"] == "auth"

    def test_gh_auth_empty_stdout_returns_auth_error(self):
        """env empty + ``gh auth token`` returns 0 but stdout is whitespace
        only -> auth error (empty token is not a valid credential)."""
        from hestai_context_mcp.tools.submit_review import submit_review

        class _EmptyCP:
            returncode = 0
            stdout = "   \n\t  "
            stderr = ""

        with (
            patch("subprocess.run", return_value=_EmptyCP()),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )
        assert result["status"] == "error"
        assert result["error_type"] == "auth"

    def test_gh_auth_unexpected_exception_returns_auth_error(self):
        """env empty + ``gh auth token`` raises unexpected exception ->
        auth error (NOT an unhandled crash that would kill the MCP server).

        Per TMG verdict on 73f2672 (continuation 961b3109-72e1-4084-a370-
        edf70824fa22): the gh-auth-token call is a precondition gate; any
        failure mode there must produce a structured auth error, not bubble
        up as an unhandled exception that crashes the stdio subprocess.
        """
        from hestai_context_mcp.tools.submit_review import submit_review

        with (
            patch("subprocess.run", side_effect=RuntimeError("gh binary corrupted")),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )
        assert result["status"] == "error"
        assert result["error_type"] == "auth"

    def test_gh_auth_timeout_returns_auth_error(self):
        """env empty + ``gh auth token`` times out -> auth error (NOT network).

        The gh-auth-token call is a precondition gate, not the network
        request; classifying its timeout as ``auth`` keeps retry strategies
        from hammering an unreachable token resolver.
        """
        import subprocess as sp

        from hestai_context_mcp.tools.submit_review import submit_review

        with (
            patch(
                "subprocess.run",
                side_effect=sp.TimeoutExpired("gh", 5),
            ),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )
        assert result["status"] == "error"
        assert result["error_type"] == "auth"

    # ------------------------------------------------------------------
    # Security: the resolved token must NEVER leak into the response.
    # ------------------------------------------------------------------
    def test_resolved_token_does_not_leak_into_response_env_path(self):
        """Token from GITHUB_TOKEN env MUST NOT appear anywhere in the result."""
        from hestai_context_mcp.tools.submit_review import submit_review

        with (
            patch("subprocess.run", return_value=self._post_success_completed()),
            patch.dict("os.environ", {"GITHUB_TOKEN": self.SENSITIVE_TOKEN}, clear=True),
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )
        assert self.SENSITIVE_TOKEN not in repr(result)

    def test_resolved_token_does_not_leak_into_response_gh_path(self):
        """Token from ``gh auth token`` MUST NOT appear anywhere in the result."""
        from hestai_context_mcp.tools.submit_review import submit_review

        class _AuthCP:
            returncode = 0
            stdout = TestTokenResolution.SENSITIVE_TOKEN + "\n"
            stderr = ""

        def _router(cmd, *args, **kwargs):
            if list(cmd[:3]) == ["gh", "auth", "token"]:
                return _AuthCP()
            return TestTokenResolution._post_success_completed()

        with (
            patch("subprocess.run", side_effect=_router),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )
        assert self.SENSITIVE_TOKEN not in repr(result)

    # ------------------------------------------------------------------
    # UX: auth error message names all three lookup paths so operators
    # can fix the right one.
    # ------------------------------------------------------------------
    def test_auth_error_message_names_all_three_lookup_paths(self):
        """The auth-error message must mention GITHUB_TOKEN, GH_TOKEN, and
        ``gh auth token`` so operators can diagnose which tier failed."""
        from hestai_context_mcp.tools.submit_review import submit_review

        with (
            patch("subprocess.run", side_effect=FileNotFoundError("gh not found")),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )
        assert result["status"] == "error"
        message = result["validation"]["error"]
        assert "GITHUB_TOKEN" in message
        assert "GH_TOKEN" in message
        assert "gh auth token" in message

    # ------------------------------------------------------------------
    # Token-shape validation (CE rework on PR #35).
    #
    # Per CE CONDITIONAL verdict on commit 8732750: the helper must
    # collapse a malformed ``gh auth token`` payload (error text echoed
    # to stdout, HTML wrapper, multi-line junk, too-short candidate) to
    # ``None`` BEFORE the precondition gate proceeds, rather than
    # passing the malformed string through and letting it fail
    # downstream at the GitHub API. Permissive on accepts (false
    # negatives on a real token break the user's workflow); strict on
    # obvious garbage.
    #
    # Accepted shapes:
    #   - Modern gh prefixes: ghp_, gho_, ghu_, ghs_, ghr_ + ≥20
    #     [A-Za-z0-9_] chars (covers ghp_ personal tokens, gho_ OAuth
    #     tokens, ghu_ user-to-server, ghs_ server-to-server, ghr_
    #     refresh tokens — per GitHub's published prefix taxonomy).
    #   - Classic 40-char hex personal access tokens for accounts that
    #     have not rotated since the prefix scheme rolled out.
    # ------------------------------------------------------------------
    def test_gh_auth_malformed_error_text_rejected(self):
        """``gh auth token`` returning error text on stdout collapses to auth error."""
        from hestai_context_mcp.tools.submit_review import submit_review

        class _MalformedCP:
            returncode = 0  # gh erroneously exited 0 with junk on stdout
            stdout = "error: not authenticated. Run `gh auth login`.\n"
            stderr = ""

        with (
            patch("subprocess.run", return_value=_MalformedCP()),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )
        assert result["status"] == "error"
        assert result["error_type"] == "auth"

    def test_gh_auth_html_payload_rejected(self):
        """``gh auth token`` returning an HTML wrapper collapses to auth error.

        Defensive case: a misconfigured proxy or man-in-the-middle could
        in principle cause gh to surface HTML on stdout. Token-shape
        validation MUST reject it.
        """
        from hestai_context_mcp.tools.submit_review import submit_review

        class _HtmlCP:
            returncode = 0
            stdout = "<html><body>401 Unauthorized</body></html>"
            stderr = ""

        with (
            patch("subprocess.run", return_value=_HtmlCP()),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )
        assert result["status"] == "error"
        assert result["error_type"] == "auth"

    def test_gh_auth_multiline_payload_rejected(self):
        """A multi-line stdout (token plus diagnostic chatter) collapses to
        auth error — the helper must not echo a multi-line credential."""
        from hestai_context_mcp.tools.submit_review import submit_review

        class _MultilineCP:
            returncode = 0
            stdout = "ghp_validlookingtokenxxxxxxxxxxxxxxxx\nWARN: refresh recommended\n"
            stderr = ""

        with (
            patch("subprocess.run", return_value=_MultilineCP()),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )
        assert result["status"] == "error"
        assert result["error_type"] == "auth"

    def test_gh_auth_too_short_candidate_rejected(self):
        """A candidate shorter than the minimum modern-prefix length is rejected."""
        from hestai_context_mcp.tools.submit_review import submit_review

        class _ShortCP:
            returncode = 0
            stdout = "ghp_short\n"  # ghp_ + 5 chars; modern prefix needs ≥20 trailing
            stderr = ""

        with (
            patch("subprocess.run", return_value=_ShortCP()),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )
        assert result["status"] == "error"
        assert result["error_type"] == "auth"

    def test_gh_auth_classic_40hex_pat_accepted(self):
        """Classic 40-char hex personal access tokens MUST still resolve.

        Older gh installs that have not rotated credentials since the
        prefix scheme rolled out (2021-04) still emit 40-hex PATs. We
        MUST accept these; a false negative here breaks the user's
        workflow on a perfectly valid credential.
        """
        from hestai_context_mcp.tools.submit_review import submit_review

        classic_pat = "0123456789abcdef0123456789abcdef01234567"  # 40 hex chars
        assert len(classic_pat) == 40

        class _AuthCP:
            returncode = 0
            stdout = classic_pat + "\n"
            stderr = ""

        def _router(cmd, *args, **kwargs):
            if list(cmd[:3]) == ["gh", "auth", "token"]:
                return _AuthCP()
            return TestTokenResolution._post_success_completed()

        with (
            patch("subprocess.run", side_effect=_router),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )
        assert result["status"] == "ok"

    def test_gh_auth_modern_prefix_accepted(self):
        """A canonical modern ``ghp_…`` token MUST resolve cleanly.

        Belt-and-braces with the existing fallback success test, which
        also uses a ghp_-prefixed sentinel; this test pins the contract
        explicitly so a future change to the sentinel value does not
        silently weaken the modern-prefix accept path.
        """
        from hestai_context_mcp.tools.submit_review import submit_review

        # ghp_ + 36 [A-Za-z0-9_] chars — comfortably above the 20-char
        # minimum and within the realistic published shape.
        modern_token = "ghp_" + "A" * 36

        class _AuthCP:
            returncode = 0
            stdout = modern_token + "\n"
            stderr = ""

        def _router(cmd, *args, **kwargs):
            if list(cmd[:3]) == ["gh", "auth", "token"]:
                return _AuthCP()
            return TestTokenResolution._post_success_completed()

        with (
            patch("subprocess.run", side_effect=_router),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )
        assert result["status"] == "ok"

    def test_resolve_accepts_fine_grained_pat_prefix(self):
        """Fine-grained personal access tokens (github_pat_, 2022+) MUST resolve.

        Per cubic P1 finding on PR #35 HEAD e6382a7: the original guard
        ``^(?:gh[pousr]_[A-Za-z0-9_]{20,}|[a-f0-9]{40})$`` rejected the
        ``github_pat_`` prefix entirely, so ``gh auth token`` returning
        a valid fine-grained PAT would be silently dropped — exactly
        the false-negative failure mode the PERMISSIVE-on-accepts
        directive was meant to prevent.
        """
        from hestai_context_mcp.tools.submit_review import submit_review

        # github_pat_ + 30 [A-Za-z0-9_] chars; well above the 20-char
        # minimum the alternation requires.
        fine_grained_pat = "github_pat_" + "A" * 30

        class _AuthCP:
            returncode = 0
            stdout = fine_grained_pat + "\n"
            stderr = ""

        def _router(cmd, *args, **kwargs):
            if list(cmd[:3]) == ["gh", "auth", "token"]:
                return _AuthCP()
            return TestTokenResolution._post_success_completed()

        with (
            patch("subprocess.run", side_effect=_router),
            patch.dict("os.environ", {}, clear=True),
        ):
            result = submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Review Gate re-trigger wiring (issue #145)
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestReviewGateRetrigger:
    """After a verdict comment posts successfully, submit_review must invoke
    the best-effort Review Gate re-trigger and surface its outcome under a
    new, additive ``retrigger`` key -- WITHOUT disturbing the existing
    ``status``/``comment_url``/``commit_sha``/``error_type`` contract.

    The re-trigger call itself is exercised in isolation in
    tests/unit/tools/shared/test_review_gate_retrigger.py; here we only
    verify the WIRING: is it called, with what, when, and does its outcome
    (including failure) ever leak into or break the post's own result.
    """

    @staticmethod
    def _post_success_mock_run():
        from unittest.mock import MagicMock

        mock_run = MagicMock()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = (
            "HTTP/2 201 Created\ncontent-type: application/json\n\n"
            '{"html_url": "https://github.com/owner/repo/pull/1#issuecomment-1"}'
        )
        mock_run.return_value.stderr = ""
        return mock_run

    def test_successful_post_calls_retrigger_with_repo_and_pr_number(self):
        from hestai_context_mcp.tools import submit_review as submit_review_module

        with (
            patch("subprocess.run", self._post_success_mock_run()),
            patch.dict("os.environ", {"GITHUB_TOKEN": "fake-token"}),
            patch.object(
                submit_review_module,
                "_retrigger_review_gate",
                return_value={
                    "status": "re-triggered",
                    "reason": None,
                    "run_id": 42,
                    "head_sha": "abc123",
                },
            ) as mock_retrigger,
        ):
            result = submit_review_module.submit_review(
                repo="owner/repo",
                pr_number=17,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )

        mock_retrigger.assert_called_once_with("owner/repo", 17)
        assert result["status"] == "ok"
        assert result["retrigger"] == {
            "status": "re-triggered",
            "reason": None,
            "run_id": 42,
            "head_sha": "abc123",
        }

    def test_retrigger_outcome_included_when_skipped(self):
        """A "skipped" retrigger outcome is surfaced verbatim -- the post
        itself must still read as a success.
        """
        from hestai_context_mcp.tools import submit_review as submit_review_module

        skipped = {
            "status": "skipped",
            "reason": "no GitHub token available for the Actions API",
            "run_id": None,
            "head_sha": None,
        }
        with (
            patch("subprocess.run", self._post_success_mock_run()),
            patch.dict("os.environ", {"GITHUB_TOKEN": "fake-token"}),
            patch.object(submit_review_module, "_retrigger_review_gate", return_value=skipped),
        ):
            result = submit_review_module.submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )

        assert result["status"] == "ok"
        assert result["retrigger"] == skipped

    def test_retrigger_exception_never_fails_the_post(self):
        """Defense in depth: even if retrigger_review_gate somehow raises
        (it is designed not to), submit_review must swallow it -- the post
        already succeeded and must be reported as such.
        """
        from hestai_context_mcp.tools import submit_review as submit_review_module

        with (
            patch("subprocess.run", self._post_success_mock_run()),
            patch.dict("os.environ", {"GITHUB_TOKEN": "fake-token"}),
            patch.object(
                submit_review_module,
                "_retrigger_review_gate",
                side_effect=RuntimeError("boom"),
            ),
        ):
            result = submit_review_module.submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )

        assert result["status"] == "ok"
        assert result["comment_url"]
        assert result["retrigger"]["status"] == "skipped"
        assert "boom" in result["retrigger"]["reason"]

    def test_dry_run_never_calls_retrigger_and_omits_key(self):
        """dry_run=True must NOT re-trigger anything -- it never even posts."""
        from hestai_context_mcp.tools import submit_review as submit_review_module

        with patch.object(submit_review_module, "_retrigger_review_gate") as mock_retrigger:
            result = submit_review_module.submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="Verified.",
                dry_run=True,
            )

        mock_retrigger.assert_not_called()
        assert result["status"] == "ok"
        assert result["dry_run"] is True
        assert "retrigger" not in result

    def test_post_failure_never_calls_retrigger_and_omits_key(self):
        """If the comment post itself fails, there is no new verdict for the
        gate to observe -- retrigger must not be attempted.
        """
        from hestai_context_mcp.tools import submit_review as submit_review_module

        with (
            patch("subprocess.run") as mock_run,
            patch.dict("os.environ", {"GITHUB_TOKEN": "fake-token"}),
            patch.object(submit_review_module, "_retrigger_review_gate") as mock_retrigger,
        ):
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = "Not Found"

            result = submit_review_module.submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="LGTM.",
                dry_run=False,
            )

        mock_retrigger.assert_not_called()
        assert result["status"] == "error"
        assert "retrigger" not in result

    def test_validation_failure_never_calls_retrigger(self):
        """Input-validation errors happen before any GitHub interaction --
        retrigger must not be attempted.
        """
        from hestai_context_mcp.tools import submit_review as submit_review_module

        with patch.object(submit_review_module, "_retrigger_review_gate") as mock_retrigger:
            result = submit_review_module.submit_review(
                repo="bad-repo",
                pr_number=1,
                role="CE",
                verdict="APPROVED",
                assessment="Test.",
            )

        mock_retrigger.assert_not_called()
        assert result["status"] == "error"
        assert "retrigger" not in result


@pytest.mark.unit
class TestReviewGateRetriggerGating:
    """Finding 3 (cubic triage on PR #148, P2): re-trigger must be gated on
    ``would_clear`` -- the SAME computed value already used to decide
    whether the formatted comment clears the gate (submit_review.py, Step
    3) -- NOT a literal ``verdict == "APPROVED"`` comparison. A literal
    comparison happens to coincide with ``would_clear`` for standard roles,
    but the intent is to use the single source of truth, and the IL/HO
    substitution cases are the trap that would expose a literal check as
    wrong if it diverged.

    A non-approving verdict cannot change the gate outcome (the gate counts
    approvals; only their absence blocks), so retrigger must not even be
    attempted for BLOCKED/CONDITIONAL/REJECTED -- this also eliminates the
    latency cost (retry sleeps + subprocess calls) on the common non-
    approving path.
    """

    @staticmethod
    def _post_success_mock_run():
        from unittest.mock import MagicMock

        mock_run = MagicMock()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = (
            "HTTP/2 201 Created\ncontent-type: application/json\n\n"
            '{"html_url": "https://github.com/owner/repo/pull/1#issuecomment-1"}'
        )
        mock_run.return_value.stderr = ""
        return mock_run

    @pytest.mark.parametrize("verdict", ["BLOCKED", "CONDITIONAL", "REJECTED"])
    def test_non_approving_verdict_never_calls_retrigger(self, verdict):
        from hestai_context_mcp.tools import submit_review as submit_review_module

        with (
            patch("subprocess.run", self._post_success_mock_run()),
            patch.dict("os.environ", {"GITHUB_TOKEN": "fake-token"}),
            patch.object(submit_review_module, "_retrigger_review_gate") as mock_retrigger,
        ):
            result = submit_review_module.submit_review(
                repo="owner/repo",
                pr_number=1,
                role="CE",
                verdict=verdict,
                assessment=f"Explaining the {verdict.lower()} state in detail.",
                dry_run=False,
            )

        mock_retrigger.assert_not_called()
        assert result["status"] == "ok"
        assert result["retrigger"]["status"] == "skipped"
        assert result["retrigger"]["reason"]
        assert result["retrigger"]["run_id"] is None
        assert result["retrigger"]["head_sha"] is None
        reason_lower = result["retrigger"]["reason"].lower()
        assert "gate" in reason_lower

    def test_il_approved_still_calls_retrigger(self):
        """IL/APPROVED clears the gate via the SELF-REVIEWED substitution --
        verdict is the literal string "APPROVED", so this also guards
        against a would_clear check that was accidentally inverted or
        skipped, not just against a naive verdict != "APPROVED" trap.
        """
        from hestai_context_mcp.tools import submit_review as submit_review_module

        with (
            patch("subprocess.run", self._post_success_mock_run()),
            patch.dict("os.environ", {"GITHUB_TOKEN": "fake-token"}),
            patch.object(
                submit_review_module,
                "_retrigger_review_gate",
                return_value={
                    "status": "re-triggered",
                    "reason": None,
                    "run_id": 1,
                    "head_sha": "abc",
                },
            ) as mock_retrigger,
        ):
            result = submit_review_module.submit_review(
                repo="owner/repo",
                pr_number=1,
                role="IL",
                verdict="APPROVED",
                assessment="Self-reviewed and verified.",
                dry_run=False,
            )

        mock_retrigger.assert_called_once_with("owner/repo", 1)
        assert result["status"] == "ok"
        assert result["retrigger"]["status"] == "re-triggered"

    def test_ho_approved_still_calls_retrigger(self):
        """HO/APPROVED clears the gate via the REVIEWED substitution."""
        from hestai_context_mcp.tools import submit_review as submit_review_module

        with (
            patch("subprocess.run", self._post_success_mock_run()),
            patch.dict("os.environ", {"GITHUB_TOKEN": "fake-token"}),
            patch.object(
                submit_review_module,
                "_retrigger_review_gate",
                return_value={
                    "status": "re-triggered",
                    "reason": None,
                    "run_id": 2,
                    "head_sha": "def",
                },
            ) as mock_retrigger,
        ):
            result = submit_review_module.submit_review(
                repo="owner/repo",
                pr_number=1,
                role="HO",
                verdict="APPROVED",
                assessment="Supervisory review complete.",
                dry_run=False,
            )

        mock_retrigger.assert_called_once_with("owner/repo", 1)
        assert result["status"] == "ok"
        assert result["retrigger"]["status"] == "re-triggered"

    def test_gating_reads_would_clear_not_a_fresh_literal_verdict_comparison(self):
        """Source-level pin for the trap named in the finding (rework #3
        fix, PR #148 finding 1): ``verdict == "APPROVED"`` and the computed
        ``would_clear`` are provably equivalent at the point retrigger is
        gated (Step 3 already rejects any APPROVED verdict whose formatted
        comment would not clear the gate, before Step 6 is ever reached) --
        so no BEHAVIOURAL test can distinguish "reads would_clear" from
        "re-derives verdict == 'APPROVED'" today; the coordinator tried and
        confirmed this independently. A source-level guard is the only
        option, but the FIRST version of this guard (rework #2) was itself
        broken: it sliced from the ``would_clear = ...`` ASSIGNMENT (which
        trivially contains the substring "would_clear") to the first
        substring match of "_retrigger_review_gate(" -- which resolved to
        a COMMENT mentioning that name, several lines before the real call
        site, so the window never actually covered the gating condition.
        That version would have passed even if the code reverted to a
        literal comparison.

        This version fixes both defects: it anchors on stable,
        comment-based landmarks that bracket the REAL gating region without
        being part of the condition itself (so mutating the condition can't
        also break the anchor search), strips comment text before
        searching (so a comment mentioning either name can't satisfy or
        pollute the check), and asserts the LOAD-BEARING negative --
        no fresh ``verdict ==`` / bare ``"APPROVED"`` literal appears in
        the window -- rather than only the weak positive that the name
        ``would_clear`` appears somewhere in it.
        """
        import inspect

        from hestai_context_mcp.tools import submit_review as submit_review_module

        source = inspect.getsource(submit_review_module.submit_review)
        assert _gating_reads_would_clear_not_literal_verdict(source) is True

    def test_gating_check_discriminates_against_a_reverted_literal_comparison(self):
        """Proof the check above is not assurance theatre (rework #3
        finding 1): apply the SAME assertion logic to the real source
        mutated to reintroduce exactly the literal ``verdict == "APPROVED"``
        comparison the AGR rejected, and confirm that source FAILS the
        check. A checker that cannot fail on this mutant cannot catch the
        regression it exists to catch -- which is precisely what was wrong
        with the prior version of this test.
        """
        import inspect

        from hestai_context_mcp.tools import submit_review as submit_review_module

        real_source = inspect.getsource(submit_review_module.submit_review)
        assert "if not would_clear:" in real_source

        mutant_source = real_source.replace(
            "if not would_clear:", 'if not (verdict == "APPROVED"):'
        )
        assert mutant_source != real_source
        # Sanity: the mutation must land INSIDE the window the checker
        # inspects, or this proof is vacuous for a different reason.
        assert "# Step 6:" in mutant_source
        assert '"retrigger": retrigger,' in mutant_source

        assert _gating_reads_would_clear_not_literal_verdict(mutant_source) is False


# ---------------------------------------------------------------------------
# GR legacy-alias foreign-gate gap (elevana-studio#1851, second rework round,
# BLOCKING -- CIV reproduction, coordinator-confirmed).
#
# _matches_role_gate() (submit_review.py) maps SR to has_sr_approval() ONLY.
# scripts/validate_review.py's CI-side per-role checker maps SR to
# has_sr_approval() OR has_gr_approval() -- "GR" was renamed to "SR", and
# has_gr_approval() still matches both prefixes for backward compatibility
# with pre-rename comments. Because the cross-role gate-corruption guard
# (Step 2a) only tests submit_review's OWN matcher set, a body opening
# "GR APPROVED: ..." submitted under a DIFFERENT role (e.g. role="CE") does
# NOT trip has_sr_approval() -- so Step 2a sees no foreign-gate clear -- yet
# CI's checker DOES accept it as an SR approval. A single CE-role comment
# therefore silently satisfies CI's SR requirement.
#
# This matters more than its size suggests: SR is the sole required
# reviewer for the GOVERNANCE facet, and SR could not bind at all during
# this PR's own review cycle (Vault skill drift, elevana-studio#67) -- so
# the scarcest, most bypass-pressured approval was also the one that was
# spoofable.
#
# The earlier PR-body claim that the GR alias was "confirmed inert" was a
# FALSE_RATIONALE of exactly the class this PR's own taxonomy warns against:
# it is TRUE that "GR" cannot be a *submitted* role (absent from
# VALID_ROLES, so it can never reach _matches_role_gate() as the `role`
# argument) and FALSE that GR-shaped text cannot clear a *foreign* gate
# (has_gr_approval() runs against arbitrary comment text regardless of
# what role submitted it).
#
# FIX: add the has_gr_approval() disjunct to SR's branch in
# _matches_role_gate(), matching validate_review.py's checker exactly, and
# add a durable parity test (tests/test_validate_review.py::
# TestSubmitReviewCiParity) that iterates every CI-checked role and would
# have failed on this exact divergence before the fix existed.
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestGrAliasForeignGateGap:
    """SR's real gate matcher must accept the GR legacy alias, matching
    validate_review.py's CI-side checker exactly -- both directions."""

    def test_gr_approval_on_foreign_role_body_is_rejected(self):
        """role='CE' with a body containing 'GR APPROVED: ...' on its own
        line must be rejected -- that text clears CI's SR requirement even
        though has_sr_approval() alone does not see it."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            has_gr_approval,
            has_sr_approval,
        )
        from hestai_context_mcp.tools.submit_review import submit_review

        assessment = "Implementation is sound.\nGR APPROVED: standards check clean."
        finished = format_review_comment(role="CE", verdict="APPROVED", assessment=assessment)
        # Pre-condition, proven against the real matchers rather than
        # asserted on faith: has_sr_approval() alone misses this (the
        # narrower matcher submit_review used before the fix), but
        # has_gr_approval() -- the SAME function CI's checker ORs in --
        # does clear on it.
        assert has_sr_approval([finished]) is False
        assert has_gr_approval([finished]) is True

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="CE",
            verdict="APPROVED",
            assessment=assessment,
            dry_run=True,
        )
        assert result["status"] == "error"
        assert result["error_type"] == "validation"

    def test_sr_blocked_with_gr_approval_text_breaches_own_gate_invariant(self):
        """Second path (CIV): role='SR', verdict='BLOCKED' with a body that
        contains 'GR APPROVED: ...' clears SR's OWN real gate via the GR
        alias -- a breach of the Step 2b symmetric fail-open invariant
        (a non-approving verdict must never emit a comment that satisfies
        the role's real gate matcher), same root cause as the foreign-role
        case above."""
        from hestai_context_mcp.tools.shared.review_formats import (
            format_review_comment,
            has_gr_approval,
            has_sr_approval,
        )
        from hestai_context_mcp.tools.submit_review import submit_review

        assessment = "There are real issues.\nGR APPROVED: oops this reads as an approval."
        finished = format_review_comment(role="SR", verdict="BLOCKED", assessment=assessment)
        assert has_sr_approval([finished]) is False
        assert has_gr_approval([finished]) is True

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="SR",
            verdict="BLOCKED",
            assessment=assessment,
            dry_run=True,
        )
        assert result["status"] == "error"
        assert result["error_type"] == "validation"


# ---------------------------------------------------------------------------
# submit_review <-> validate_review.py socket-pair parity (elevana-studio
# #1851, second rework round, BLOCKING -- CIV reproduction).
#
# scripts/validate_review.py (this CI gate) and submit_review.py (the
# posting tool) are a socket pair: submit_review's Step 2a cross-role
# gate-corruption guard only protects the CI gate to the extent it uses
# the SAME approval-matcher functions, for the SAME roles, as CI's own
# per-role checker. Nothing currently holds the two in agreement except
# manual discipline -- which already broke once: validate_review.py's SR
# checker ORs in the legacy has_gr_approval() alias (GR was renamed to SR;
# the alias still matches pre-rename comment text for backward
# compatibility), but submit_review._matches_role_gate() mapped SR to
# has_sr_approval() alone. A GR-shaped foreign-role body therefore cleared
# CI's SR requirement while submit_review's own guard saw nothing to
# reject.
#
# This test iterates every role validate_review.py's check_pr_comments()
# actually verifies via its required_roles path (TMG, CRS, CE, CIV, PE,
# SR) and, for each of the canonical positive-approval probes for every
# role (including the GR legacy alias), asserts CI's real acceptance
# and submit_review's real acceptance agree. It is intentionally scoped
# to those six roles: IL and HO are verified through a STRUCTURALLY
# DIFFERENT mechanism in validate_review.py -- the TIER_1_SELF self-review
# branch (checked only when tier=="TIER_1_SELF" and required_roles is
# empty), not the _role_checkers/required_roles dispatch this test
# exercises -- so they are out of scope for this particular parity check
# by design, not silently dropped from coverage.
#
# KNOWN LIMIT (recorded, not fixed): this test compares the copy of
# validate_review.py and review_formats.py installed in THIS repo's
# venv against the copy of review_formats.py submit_review.py imports
# from the SAME repo -- i.e. it proves parity within one commit of this
# repo. It does NOT, and cannot, prove parity against what a consumer
# repo's CI actually runs, because review-gate.yml sparse-checks-out
# scripts/validate_review.py and review_formats.py from `main` at
# workflow-run time (see PR body deploy-path note), independent of
# whatever version of submit_review.py posted the comment. Parity holds
# only as far as version alignment between the poster and the CI gate's
# main-branch snapshot does -- a pre-existing property of the unpinned
# socket, not introduced or fixed by this test.
# ---------------------------------------------------------------------------
@pytest.mark.security
class TestSubmitReviewCiParity:
    """submit_review._matches_role_gate() and validate_review.py's CI-side
    per-role checker must accept exactly the same approval-matcher
    functions for every role CI actually gates on required_roles."""

    # Canonical positive probe per underlying review_formats matcher
    # function. Each probe is a single line naming ONE role/alias so a
    # mismatch pinpoints exactly which matcher function diverges.
    _PROBES: dict[str, str] = {
        "TMG": "TMG APPROVED: probe text",
        "CRS": "CRS APPROVED: probe text",
        "CE": "CE APPROVED: probe text",
        "CIV": "CIV APPROVED: probe text",
        "PE": "PE APPROVED: probe text",
        "SR": "SR APPROVED: probe text",
        "GR": "GR APPROVED: probe text",  # legacy alias, not in VALID_ROLES
    }

    # Roles validate_review.py's check_pr_comments() actually verifies via
    # its required_roles / _role_checkers dispatch. IL and HO are excluded
    # deliberately -- see module-level comment above.
    _CI_CHECKED_ROLES = ["TMG", "CRS", "CE", "CIV", "PE", "SR"]

    @staticmethod
    def _ci_accepts(monkeypatch, role: str, probe_text: str) -> bool:
        """True if validate_review.check_pr_comments() would accept
        ``probe_text`` as satisfying ``role``, mocking the ``gh pr view``
        call it makes internally."""
        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("PR_NUMBER", "999")

        def mock_run(*args, **kwargs):
            mock = MagicMock()
            mock.stdout = json.dumps(
                {
                    "body": "",
                    "comments": [{"author": {"login": "reviewer1"}, "body": probe_text}],
                    "reviews": [],
                }
            )
            return mock

        monkeypatch.setattr(subprocess, "run", mock_run)
        approved, _message, _missing = validate_review.check_pr_comments(
            required_roles={role}, tier="TIER_2_STANDARD"
        )
        return approved

    @staticmethod
    def _submit_review_accepts(role: str, probe_text: str) -> bool:
        """True if submit_review._matches_role_gate() would accept
        ``probe_text`` as satisfying ``role``."""
        from hestai_context_mcp.tools.submit_review import _matches_role_gate

        return _matches_role_gate(probe_text, role)

    @pytest.mark.parametrize("role", _CI_CHECKED_ROLES)
    def test_matcher_acceptance_agrees_for_every_probe(self, role: str, monkeypatch):
        """For a fixed required role, every probe's CI-acceptance must
        match submit_review's acceptance -- this is the assertion that
        fails concretely on role='SR', probe='GR' before the fix (CI
        accepts via the legacy alias; submit_review did not)."""
        mismatches = []
        for probe_name, probe_text in self._PROBES.items():
            ci_result = self._ci_accepts(monkeypatch, role, probe_text)
            submit_review_result = self._submit_review_accepts(role, probe_text)
            if ci_result != submit_review_result:
                mismatches.append(
                    f"probe={probe_name!r} ({probe_text!r}): "
                    f"CI={ci_result} submit_review={submit_review_result}"
                )
        assert not mismatches, (
            f"Parity mismatch for required role={role!r} -- "
            "validate_review.py (CI) and submit_review.py's "
            "_matches_role_gate() disagree on whether the following "
            "probe(s) satisfy this role:\n" + "\n".join(mismatches)
        )

