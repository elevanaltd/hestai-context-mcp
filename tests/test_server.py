"""Smoke tests for the MCP server skeleton."""

import pytest


@pytest.mark.smoke
class TestServerImport:
    """Verify the server module can be imported and tools are registered."""

    def test_server_module_imports(self):
        """The server module should import without errors."""
        from hestai_context_mcp import server

        assert server is not None

    def test_mcp_instance_exists(self):
        """The FastMCP instance should be available."""
        from hestai_context_mcp.server import mcp

        assert mcp is not None
        assert mcp.name == "hestai-context-mcp"

    def test_main_entry_point_exists(self):
        """The main() entry point should be callable."""
        from hestai_context_mcp.server import main

        assert callable(main)

    def test_package_version(self):
        """The package should expose a version string."""
        from hestai_context_mcp import __version__

        assert isinstance(__version__, str)
        assert __version__ == "0.1.0"


@pytest.mark.smoke
class TestToolStubs:
    """Verify that all tool stubs exist and return not-yet-implemented."""

    def test_clock_in_implemented(self, tmp_path):
        """clock_in should return structured response per interface contract."""
        from unittest.mock import patch

        from hestai_context_mcp.tools.clock_in import clock_in

        with patch("hestai_context_mcp.tools.clock_in.get_current_branch", return_value="main"):
            result = clock_in(role="test", working_dir=str(tmp_path))
        assert "session_id" in result
        assert result["role"] == "test"
        assert "context" in result

    def test_clock_out_stub(self):
        """clock_out should return a not-yet-implemented response."""
        from hestai_context_mcp.tools.clock_out import clock_out

        result = clock_out(session_id="test-123")
        assert result["status"] == "not_yet_implemented"
        assert result["tool"] == "clock_out"

    def test_get_context_implemented(self, tmp_path):
        """get_context should return structured context response."""
        from unittest.mock import patch

        from hestai_context_mcp.tools.get_context import get_context

        with patch(
            "hestai_context_mcp.tools.get_context.get_git_state",
            return_value=None,
        ):
            result = get_context(working_dir=str(tmp_path))
        assert "working_dir" in result
        assert "context" in result
        assert "product_north_star" in result["context"]

    def test_submit_review_implemented(self):
        """submit_review should be functional (no longer a stub)."""
        from hestai_context_mcp.tools.submit_review import submit_review

        result = submit_review(
            repo="owner/repo",
            pr_number=1,
            role="IL",
            verdict="APPROVED",
            assessment="Looks good",
            dry_run=True,
        )
        assert result["status"] == "ok"
        assert result["dry_run"] is True


@pytest.mark.smoke
class TestCoreModules:
    """Verify that core modules can be imported."""

    def test_context_steward_import(self, tmp_path):
        """ContextSteward should be importable."""
        from hestai_context_mcp.core.context_steward import ContextSteward

        workflow_path = tmp_path / "workflow.oct.md"
        steward = ContextSteward(workflow_path=workflow_path)
        assert steward.workflow_path == workflow_path

    def test_redaction_engine_import(self):
        """RedactionEngine should be importable."""
        from hestai_context_mcp.core.redaction import RedactionEngine

        engine = RedactionEngine()
        assert engine is not None

    def test_session_manager_import(self, tmp_path):
        """SessionManager should be importable."""

        from hestai_context_mcp.core.session import SessionManager

        manager = SessionManager(working_dir=str(tmp_path))
        assert manager.working_dir == tmp_path
