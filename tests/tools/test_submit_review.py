"""Tests for the submit_review MCP tool.

Written against the ADR-0353 interface contract:
- Input: repo, pr_number, role, verdict, assessment, model_annotation?, commit_sha?, dry_run?
- Output: { status, comment_url, validation, dry_run }
- 8 roles: CE, CIV, CRS, HO, IL, PE, SR, TMG
- 3 verdicts: APPROVED, BLOCKED, CONDITIONAL
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

    @pytest.mark.parametrize("verdict", ["APPROVED", "BLOCKED", "CONDITIONAL"])
    def test_all_valid_verdicts_accepted(self, verdict: str):
        """All 3 valid verdicts must be accepted."""
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
        """Without GITHUB_TOKEN, posting should fail with auth error."""
        from hestai_context_mcp.tools.submit_review import submit_review

        with patch.dict("os.environ", {}, clear=True):
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
    """Verify the return dict matches the ADR-0353 contract."""

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
