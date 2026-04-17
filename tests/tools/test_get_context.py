"""Tests for the get_context MCP tool handler.

Tests the read-only context synthesis per interface contract.
Verifies ZERO side effects — no session dirs, no FAST layer writes.
"""

import json
from unittest.mock import patch

import pytest

from hestai_context_mcp.tools.get_context import get_context


class TestGetContextReturnShape:
    """Verify get_context returns the correct structure per interface contract."""

    @patch("hestai_context_mcp.tools.get_context.get_git_state", return_value=None)
    def test_returns_working_dir(self, mock_git, tmp_path):
        """Return dict includes working_dir."""
        result = get_context(working_dir=str(tmp_path))
        assert "working_dir" in result
        assert result["working_dir"] == str(tmp_path.resolve())

    @patch("hestai_context_mcp.tools.get_context.get_git_state", return_value=None)
    def test_returns_context_object(self, mock_git, tmp_path):
        """Return dict includes context object with all required fields."""
        result = get_context(working_dir=str(tmp_path))

        ctx = result["context"]
        assert "product_north_star" in ctx
        assert "project_context" in ctx
        assert "phase_constraints" in ctx
        assert "git_state" in ctx
        assert "active_sessions" in ctx

    @patch("hestai_context_mcp.tools.get_context.get_git_state", return_value=None)
    def test_git_state_structure_when_unavailable(self, mock_git, tmp_path):
        """git_state has correct fallback shape when git unavailable."""
        result = get_context(working_dir=str(tmp_path))

        git_state = result["context"]["git_state"]
        assert "branch" in git_state
        assert "ahead" in git_state
        assert "behind" in git_state
        assert "modified_files" in git_state
        assert git_state["ahead"] == 0
        assert git_state["behind"] == 0
        assert git_state["modified_files"] == []


class TestGetContextNoSideEffects:
    """Verify get_context creates NO files or directories."""

    @patch("hestai_context_mcp.tools.get_context.get_git_state", return_value=None)
    def test_no_session_directory_created(self, mock_git, tmp_path):
        """get_context must NOT create any session directories."""
        get_context(working_dir=str(tmp_path))

        sessions_dir = tmp_path / ".hestai" / "state" / "sessions" / "active"
        if sessions_dir.exists():
            # No session subdirectories should exist
            assert list(sessions_dir.iterdir()) == []

    @patch("hestai_context_mcp.tools.get_context.get_git_state", return_value=None)
    def test_no_fast_layer_files_written(self, mock_git, tmp_path):
        """get_context must NOT write FAST layer files."""
        get_context(working_dir=str(tmp_path))

        state_dir = tmp_path / ".hestai" / "state" / "context" / "state"
        if state_dir.exists():
            written_files = list(state_dir.iterdir())
            assert written_files == [], f"FAST layer files created: {written_files}"

    @patch("hestai_context_mcp.tools.get_context.get_git_state", return_value=None)
    def test_no_hestai_directory_created(self, mock_git, tmp_path):
        """get_context must NOT create .hestai/ if it doesn't exist."""
        get_context(working_dir=str(tmp_path))

        hestai_dir = tmp_path / ".hestai"
        assert not hestai_dir.exists(), ".hestai/ directory was created by get_context"

    @patch("hestai_context_mcp.tools.get_context.get_git_state", return_value=None)
    def test_no_session_json_created(self, mock_git, tmp_path):
        """get_context must NOT create session.json."""
        get_context(working_dir=str(tmp_path))

        # Search recursively for any session.json
        for path in tmp_path.rglob("session.json"):
            pytest.fail(f"session.json created at {path}")


class TestGetContextNorthStar:
    """Test North Star file reading."""

    @patch("hestai_context_mcp.tools.get_context.get_git_state", return_value=None)
    def test_returns_north_star_contents_when_exists(self, mock_git, tmp_path):
        """Returns product_north_star contents when file exists."""
        ns_dir = tmp_path / ".hestai" / "north-star"
        ns_dir.mkdir(parents=True)
        ns_content = "===NORTH_STAR===\ntest content\n===END==="
        (ns_dir / "000-TEST-NORTH-STAR.oct.md").write_text(ns_content)

        result = get_context(working_dir=str(tmp_path))
        assert result["context"]["product_north_star"] == ns_content

    @patch("hestai_context_mcp.tools.get_context.get_git_state", return_value=None)
    def test_returns_none_when_north_star_missing(self, mock_git, tmp_path):
        """Returns None for product_north_star when no file exists."""
        result = get_context(working_dir=str(tmp_path))
        assert result["context"]["product_north_star"] is None


class TestGetContextProjectContext:
    """Test PROJECT-CONTEXT.oct.md reading."""

    @patch("hestai_context_mcp.tools.get_context.get_git_state", return_value=None)
    def test_returns_project_context_contents_when_exists(self, mock_git, tmp_path):
        """Returns project_context contents when file exists."""
        ctx_dir = tmp_path / ".hestai" / "state" / "context"
        ctx_dir.mkdir(parents=True)
        ctx_content = "===PROJECT_CONTEXT===\ntest\n===END==="
        (ctx_dir / "PROJECT-CONTEXT.oct.md").write_text(ctx_content)

        result = get_context(working_dir=str(tmp_path))
        assert result["context"]["project_context"] == ctx_content

    @patch("hestai_context_mcp.tools.get_context.get_git_state", return_value=None)
    def test_returns_none_when_project_context_missing(self, mock_git, tmp_path):
        """Returns None for project_context when no file exists."""
        result = get_context(working_dir=str(tmp_path))
        assert result["context"]["project_context"] is None


class TestGetContextGitState:
    """Test git state detection."""

    def test_returns_git_state_with_branch_and_files(self, tmp_path):
        """Returns git_state with branch and modified files when git available."""
        mock_state = {
            "branch": "feat/my-feature",
            "ahead": 2,
            "behind": 1,
            "modified_files": ["src/foo.py", "tests/test_foo.py"],
        }
        with patch(
            "hestai_context_mcp.tools.get_context.get_git_state",
            return_value=mock_state,
        ):
            result = get_context(working_dir=str(tmp_path))

        git_state = result["context"]["git_state"]
        assert git_state["branch"] == "feat/my-feature"
        assert git_state["ahead"] == 2
        assert git_state["behind"] == 1
        assert git_state["modified_files"] == ["src/foo.py", "tests/test_foo.py"]


class TestGetContextActiveSessions:
    """Test active sessions listing."""

    @patch("hestai_context_mcp.tools.get_context.get_git_state", return_value=None)
    def test_returns_active_sessions_listing(self, mock_git, tmp_path):
        """Returns active session focuses when sessions exist."""
        # Create active session structure
        active_dir = tmp_path / ".hestai" / "state" / "sessions" / "active"
        session_dir = active_dir / "test-session-id"
        session_dir.mkdir(parents=True)
        session_data = {
            "session_id": "test-session-id",
            "role": "test-role",
            "focus": "feature-work",
        }
        (session_dir / "session.json").write_text(json.dumps(session_data))

        result = get_context(working_dir=str(tmp_path))
        assert "feature-work" in result["context"]["active_sessions"]

    @patch("hestai_context_mcp.tools.get_context.get_git_state", return_value=None)
    def test_returns_empty_list_when_no_sessions(self, mock_git, tmp_path):
        """Returns empty list when no active sessions exist."""
        result = get_context(working_dir=str(tmp_path))
        assert result["context"]["active_sessions"] == []


class TestGetContextPhaseConstraints:
    """Test phase constraints synthesis."""

    @patch("hestai_context_mcp.tools.get_context.get_git_state", return_value=None)
    def test_returns_phase_constraints_when_workflow_exists(self, mock_git, tmp_path):
        """Returns phase_constraints when workflow file exists."""
        workflow_dir = tmp_path / ".hestai" / "workflow"
        workflow_dir.mkdir(parents=True)
        workflow_content = """===WORKFLOW===
B1_BUILD_PLAN::BUILD_PLAN_EXECUTION
PURPOSE::"Execute build plan with TDD"
RACI::"IL[R] CE[A] PE[C]"
DELIVERABLE::[code, tests]
ENTRY::[approved_plan]
EXIT::[passing_ci]
===END==="""
        (workflow_dir / "OPERATIONAL-WORKFLOW.oct.md").write_text(workflow_content)

        result = get_context(working_dir=str(tmp_path))
        constraints = result["context"]["phase_constraints"]
        assert constraints is not None
        assert constraints["phase"] == "B1"

    @patch("hestai_context_mcp.tools.get_context.get_git_state", return_value=None)
    def test_returns_none_when_no_workflow(self, mock_git, tmp_path):
        """Returns None for phase_constraints when no workflow file exists."""
        result = get_context(working_dir=str(tmp_path))
        assert result["context"]["phase_constraints"] is None


class TestGetContextGracefulDegradation:
    """Test graceful handling of missing files and directories."""

    @patch("hestai_context_mcp.tools.get_context.get_git_state", return_value=None)
    def test_handles_missing_hestai_directory(self, mock_git, tmp_path):
        """Works without .hestai/ directory — returns None fields."""
        result = get_context(working_dir=str(tmp_path))

        ctx = result["context"]
        assert ctx["product_north_star"] is None
        assert ctx["project_context"] is None
        assert ctx["phase_constraints"] is None
        assert ctx["active_sessions"] == []

    @patch("hestai_context_mcp.tools.get_context.get_git_state", return_value=None)
    def test_handles_partial_hestai_structure(self, mock_git, tmp_path):
        """Works with partial .hestai/ structure."""
        # Only create north-star dir, no state/context
        ns_dir = tmp_path / ".hestai" / "north-star"
        ns_dir.mkdir(parents=True)
        ns_content = "===NS===\npartial\n===END==="
        (ns_dir / "000-PARTIAL-NORTH-STAR.oct.md").write_text(ns_content)

        result = get_context(working_dir=str(tmp_path))

        ctx = result["context"]
        assert ctx["product_north_star"] == ns_content
        assert ctx["project_context"] is None
        assert ctx["active_sessions"] == []


class TestGetContextValidation:
    """Test input validation."""

    def test_rejects_nonexistent_working_dir(self):
        """Rejects working directory that doesn't exist."""
        with pytest.raises(FileNotFoundError):
            get_context(working_dir="/nonexistent/path/TESTONLY_xyz")

    def test_rejects_path_traversal(self, tmp_path):
        """Rejects path traversal attempts."""
        with pytest.raises(ValueError, match="[Pp]ath traversal"):
            get_context(working_dir=str(tmp_path) + "/../../../etc")
