"""Tests for the clock_in MCP tool handler.

Tests the full return shape per interface contract.
"""

from unittest.mock import patch

import pytest

from hestai_context_mcp.tools.clock_in import clock_in


class TestClockInReturnShape:
    """Verify the clock_in return matches the interface contract."""

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_returns_all_required_fields(self, mock_branch, tmp_path):
        """Return dict has all fields from interface contract."""
        result = clock_in(
            role="implementation-lead",
            working_dir=str(tmp_path),
            focus="test-focus",
        )

        # Top-level fields
        assert "session_id" in result
        assert "role" in result
        assert "focus" in result
        assert "focus_source" in result
        assert "branch" in result
        assert "working_dir" in result
        assert "context_paths" in result
        assert "context" in result

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_context_object_structure(self, mock_branch, tmp_path):
        """Context object has the required nested structure."""
        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
        )

        ctx = result["context"]
        assert "product_north_star" in ctx
        assert "project_context" in ctx
        assert "phase_constraints" in ctx
        assert "git_state" in ctx
        assert "active_sessions" in ctx

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_git_state_structure(self, mock_branch, tmp_path):
        """git_state has branch, ahead, behind, modified_files."""
        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
        )

        git_state = result["context"]["git_state"]
        assert "branch" in git_state
        assert "ahead" in git_state
        assert "behind" in git_state
        assert "modified_files" in git_state

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_role_propagated(self, mock_branch, tmp_path):
        """Role is propagated to return value."""
        result = clock_in(
            role="implementation-lead",
            working_dir=str(tmp_path),
        )
        assert result["role"] == "implementation-lead"

    @patch(
        "hestai_context_mcp.tools.clock_in.get_current_branch",
        return_value="feat/my-feature",
    )
    def test_focus_resolution_from_branch(self, mock_branch, tmp_path):
        """Focus is resolved from branch when not explicitly provided."""
        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
        )
        assert result["focus"] == "feat: my-feature"
        assert result["focus_source"] == "branch"

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_explicit_focus_takes_priority(self, mock_branch, tmp_path):
        """Explicit focus overrides branch inference."""
        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
            focus="my-explicit-focus",
        )
        assert result["focus"] == "my-explicit-focus"
        assert result["focus_source"] == "explicit"

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_creates_session_directory(self, mock_branch, tmp_path):
        """Clock-in creates the session directory in active/."""
        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
        )
        session_dir = tmp_path / ".hestai" / "state" / "sessions" / "active" / result["session_id"]
        assert session_dir.exists()

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_context_paths_is_list(self, mock_branch, tmp_path):
        """context_paths is a list of strings."""
        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
        )
        assert isinstance(result["context_paths"], list)

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_active_sessions_is_list(self, mock_branch, tmp_path):
        """active_sessions is a list of strings."""
        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
        )
        assert isinstance(result["context"]["active_sessions"], list)

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_reads_north_star_contents(self, mock_branch, tmp_path):
        """Returns North Star file contents when available."""
        ns_dir = tmp_path / ".hestai" / "north-star"
        ns_dir.mkdir(parents=True)
        ns_content = "===NORTH_STAR===\ntest content\n===END==="
        (ns_dir / "000-TEST-NORTH-STAR.oct.md").write_text(ns_content)

        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
        )
        assert result["context"]["product_north_star"] == ns_content

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_reads_project_context_contents(self, mock_branch, tmp_path):
        """Returns PROJECT-CONTEXT.oct.md contents when available."""
        ctx_dir = tmp_path / ".hestai" / "state" / "context"
        ctx_dir.mkdir(parents=True)
        ctx_content = "===PROJECT_CONTEXT===\ntest\n===END==="
        (ctx_dir / "PROJECT-CONTEXT.oct.md").write_text(ctx_content)

        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
        )
        assert result["context"]["project_context"] == ctx_content

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_ai_synthesis_always_present_as_structured_dict(self, mock_branch, tmp_path):
        """ai_synthesis is ALWAYS in the response (PROD::I4 structured shape).

        Issue #4: ai_synthesis must never be absent. With no provider wired,
        the fallback dict must still be returned with {source, synthesis}.
        """
        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
        )
        assert "ai_synthesis" in result
        ai_syn = result["ai_synthesis"]
        assert isinstance(ai_syn, dict)
        assert set(ai_syn.keys()) == {"source", "synthesis"}
        assert ai_syn["source"] == "fallback"
        assert isinstance(ai_syn["synthesis"], str)
        assert len(ai_syn["synthesis"]) > 0

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_ai_synthesis_fallback_synthesis_is_octave_template(self, mock_branch, tmp_path):
        """Fallback synthesis string follows the OCTAVE template shape."""
        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
            focus="explicit-focus",
        )
        synthesis_str = result["ai_synthesis"]["synthesis"]
        # OCTAVE template contract: contains key::value lines per legacy reference
        assert "FOCUS::" in synthesis_str
        assert "PHASE::" in synthesis_str
        assert "CONTEXT_FILES::" in synthesis_str

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_ai_synthesis_ai_seam_returns_source_ai(self, mock_branch, tmp_path, monkeypatch):
        """When the AI seam returns a synthesis dict, response carries source:'ai'.

        Issue #4: AI-success path is wired in #5; this test proves the seam exists
        and is honoured. No provider SDK is imported here — we monkeypatch the seam
        function directly.
        """
        from hestai_context_mcp.core import synthesis as synthesis_mod

        def fake_ai_synthesis(**_kwargs):
            return {"source": "ai", "synthesis": "PHASE::B1_FOUNDATION_COMPLETE\nFOCUS::mocked"}

        monkeypatch.setattr(synthesis_mod, "synthesize_ai_context", fake_ai_synthesis)

        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
        )
        assert result["ai_synthesis"]["source"] == "ai"
        assert "mocked" in result["ai_synthesis"]["synthesis"]

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_phase_string_is_full_form_not_abbreviated(self, mock_branch, tmp_path):
        """Phase string returned is the full declared form (e.g. B1_FOUNDATION_COMPLETE).

        Issue #4 acceptance criterion 2: legacy returns full phase strings, new
        server must too. The bare 'B1' form would break the Payload Compiler
        shape-parity gate.
        """
        ns_dir = tmp_path / ".hestai" / "north-star"
        ns_dir.mkdir(parents=True)
        (ns_dir / "000-TEST-NORTH-STAR-SUMMARY.oct.md").write_text(
            "===NORTH_STAR===\nPHASE::B1_FOUNDATION_COMPLETE\n===END==="
        )

        result = clock_in(
            role="test-role",
            working_dir=str(tmp_path),
        )
        assert result["phase"] == "B1_FOUNDATION_COMPLETE"
        # Must NOT be the bare abbreviation
        assert result["phase"] != "B1"


class TestClockInValidation:
    """Test input validation."""

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_rejects_empty_role(self, mock_branch, tmp_path):
        """Rejects empty role string."""
        with pytest.raises(ValueError, match="[Rr]ole"):
            clock_in(role="", working_dir=str(tmp_path))

    @patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main")
    def test_rejects_path_traversal_in_role(self, mock_branch, tmp_path):
        """Rejects role with path traversal characters."""
        with pytest.raises(ValueError):
            clock_in(role="../evil", working_dir=str(tmp_path))

    def test_rejects_nonexistent_working_dir(self):
        """Rejects working directory that doesn't exist."""
        with pytest.raises(FileNotFoundError):
            clock_in(role="test-role", working_dir="/nonexistent/path/TESTONLY_xyz")
