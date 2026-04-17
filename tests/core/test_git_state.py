"""Tests for git state detection module.

All subprocess calls are mocked to avoid actual git operations in tests.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from hestai_context_mcp.core.git_state import (
    check_context_freshness,
    get_current_branch,
    get_git_state,
)


class TestGetCurrentBranch:
    """Test git branch detection."""

    @patch("hestai_context_mcp.core.git_state.subprocess.run")
    def test_returns_branch_name(self, mock_run):
        """Returns the current branch name from git."""
        mock_run.return_value = MagicMock(returncode=0, stdout="feat/my-feature\n")
        result = get_current_branch(Path("/tmp/test"))  # nosec
        assert result == "feat/my-feature"

    @patch("hestai_context_mcp.core.git_state.subprocess.run")
    def test_returns_unknown_on_failure(self, mock_run):
        """Returns 'unknown' when git command fails."""
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        result = get_current_branch(Path("/tmp/test"))  # nosec
        assert result == "unknown"

    @patch("hestai_context_mcp.core.git_state.subprocess.run")
    def test_returns_unknown_on_timeout(self, mock_run):
        """Returns 'unknown' when git command times out."""
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=5)
        result = get_current_branch(Path("/tmp/test"))  # nosec
        assert result == "unknown"

    @patch("hestai_context_mcp.core.git_state.subprocess.run")
    def test_returns_unknown_when_git_not_found(self, mock_run):
        """Returns 'unknown' when git binary is not found."""
        mock_run.side_effect = FileNotFoundError("git not found")
        result = get_current_branch(Path("/tmp/test"))  # nosec
        assert result == "unknown"


class TestGetGitState:
    """Test full git state detection."""

    @patch("hestai_context_mcp.core.git_state.subprocess.run")
    def test_returns_complete_state(self, mock_run):
        """Returns branch, ahead/behind, and modified files."""

        def side_effect(cmd, **kwargs):
            if "rev-parse" in cmd and "--abbrev-ref" in cmd:
                return MagicMock(returncode=0, stdout="main\n")
            elif "rev-list" in cmd and "--left-right" in cmd:
                return MagicMock(returncode=0, stdout="2\t1\n")
            elif "status" in cmd and "--short" in cmd:
                return MagicMock(returncode=0, stdout=" M src/foo.py\n?? new.py\n")
            return MagicMock(returncode=1, stdout="")

        mock_run.side_effect = side_effect

        result = get_git_state(Path("/tmp/test"))  # nosec
        assert result is not None
        assert result["branch"] == "main"
        assert result["ahead"] == 2
        assert result["behind"] == 1
        assert "src/foo.py" in result["modified_files"]
        assert "new.py" in result["modified_files"]

    @patch("hestai_context_mcp.core.git_state.subprocess.run")
    def test_returns_none_on_total_failure(self, mock_run):
        """Returns None when all git commands fail."""
        mock_run.side_effect = FileNotFoundError("git not found")
        result = get_git_state(Path("/tmp/test"))  # nosec
        assert result is None

    @patch("hestai_context_mcp.core.git_state.subprocess.run")
    def test_ahead_behind_defaults_to_zero(self, mock_run):
        """ahead/behind default to 0 when rev-list fails."""

        def side_effect(cmd, **kwargs):
            if "rev-parse" in cmd and "--abbrev-ref" in cmd:
                return MagicMock(returncode=0, stdout="main\n")
            elif "rev-list" in cmd:
                return MagicMock(returncode=1, stdout="")
            elif "status" in cmd:
                return MagicMock(returncode=0, stdout="")
            return MagicMock(returncode=1, stdout="")

        mock_run.side_effect = side_effect

        result = get_git_state(Path("/tmp/test"))  # nosec
        assert result is not None
        assert result["ahead"] == 0
        assert result["behind"] == 0

    @patch("hestai_context_mcp.core.git_state.subprocess.run")
    def test_empty_status_returns_empty_list(self, mock_run):
        """Empty git status returns empty modified_files list."""

        def side_effect(cmd, **kwargs):
            if "rev-parse" in cmd and "--abbrev-ref" in cmd:
                return MagicMock(returncode=0, stdout="main\n")
            elif "rev-list" in cmd:
                return MagicMock(returncode=0, stdout="0\t0\n")
            elif "status" in cmd:
                return MagicMock(returncode=0, stdout="")
            return MagicMock(returncode=1, stdout="")

        mock_run.side_effect = side_effect

        result = get_git_state(Path("/tmp/test"))  # nosec
        assert result is not None
        assert result["modified_files"] == []


class TestCheckContextFreshness:
    """Test I4 context freshness checking."""

    @patch("hestai_context_mcp.core.git_state.subprocess.run")
    def test_fresh_context_returns_none(self, mock_run):
        """Returns None for recently committed context file."""
        import time

        # Simulate a recent commit (now - 1 hour)
        recent_timestamp = str(int(time.time()) - 3600)
        mock_run.return_value = MagicMock(returncode=0, stdout=f"{recent_timestamp}\n")

        result = check_context_freshness(
            Path("/tmp/test/PROJECT-CONTEXT.oct.md"),  # nosec
            Path("/tmp/test"),  # nosec
        )
        assert result is None  # None means fresh

    @patch("hestai_context_mcp.core.git_state.subprocess.run")
    def test_stale_context_returns_warning(self, mock_run):
        """Returns warning string for stale context file."""
        import time

        # Simulate an old commit (now - 48 hours)
        old_timestamp = str(int(time.time()) - 172800)
        mock_run.return_value = MagicMock(returncode=0, stdout=f"{old_timestamp}\n")

        result = check_context_freshness(
            Path("/tmp/test/PROJECT-CONTEXT.oct.md"),  # nosec
            Path("/tmp/test"),  # nosec
        )
        assert result is not None
        assert "I4 WARNING" in result

    @patch("hestai_context_mcp.core.git_state.subprocess.run")
    def test_uncommitted_file_returns_warning(self, mock_run):
        """Returns warning when file has never been committed."""
        mock_run.return_value = MagicMock(returncode=0, stdout="")

        result = check_context_freshness(
            Path("/tmp/test/PROJECT-CONTEXT.oct.md"),  # nosec
            Path("/tmp/test"),  # nosec
        )
        assert result is not None
        assert "never been committed" in result

    @patch("hestai_context_mcp.core.git_state.subprocess.run")
    def test_git_unavailable_returns_warning(self, mock_run):
        """Returns warning when git is not available."""
        mock_run.side_effect = FileNotFoundError("git not found")

        result = check_context_freshness(
            Path("/tmp/test/PROJECT-CONTEXT.oct.md"),  # nosec
            Path("/tmp/test"),  # nosec
        )
        assert result is not None
        assert "git unavailable" in result
