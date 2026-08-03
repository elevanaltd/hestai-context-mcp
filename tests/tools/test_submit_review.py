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

from unittest.mock import patch

import pytest


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

        historical_comment = (
            "CE BLOCKED: CE REJECTED: fundamental design flaw in the retry logic"
        )
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
