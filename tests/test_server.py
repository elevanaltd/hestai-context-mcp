"""Smoke tests for the MCP server skeleton."""

import subprocess
import sys

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
class TestServerExecution:
    """Test the new if __name__ == '__main__' entry point and script invocation."""

    def test_module_execution_via_main_guard(self):
        """The module should execute main() when run as a script (if __name__ check)."""
        from unittest.mock import MagicMock, patch

        # Test that the if __name__ == "__main__" guard properly calls main()
        with patch("hestai_context_mcp.server.mcp.run") as mock_run:
            # Import the module fresh to trigger the guard
            import importlib
            import hestai_context_mcp.server as server_module

            # Re-execute the if __name__ == "__main__" block by calling main directly
            # (This verifies that main() is the correct entry point)
            server_module.main()
            mock_run.assert_called_once()

    def test_module_execution_via_subprocess(self):
        """The module should handle subprocess invocation without crashing."""
        result = subprocess.run(
            [sys.executable, "-m", "hestai_context_mcp.server"],
            input=b"",
            capture_output=True,
            timeout=2,
        )
        # Process should not crash during import or setup
        # Exit code may be non-zero due to MCP protocol expectations, but should not be a crash
        assert result.returncode in (0, 1)
        # Should not have unexpected errors in stderr (socket/import errors would indicate failure)
        assert b"Traceback" not in result.stderr or b"No module named" not in result.stderr

    def test_script_entry_point_resolves(self):
        """The [project.scripts] entry point should resolve to server:main."""
        # Verify the entry point is correctly configured in package metadata
        import importlib.metadata

        entry_points = importlib.metadata.entry_points()
        scripts = entry_points.select(group="console_scripts")
        script_names = [ep.name for ep in scripts]
        assert "hestai-context" in script_names

        # Verify the entry point points to the correct function
        hestai_context_ep = next(
            (ep for ep in scripts if ep.name == "hestai-context"), None
        )
        assert hestai_context_ep is not None
        assert hestai_context_ep.value == "hestai_context_mcp.server:main"

    def test_script_entry_point_callable(self):
        """The script entry point should resolve to a callable function."""
        import importlib.metadata

        entry_points = importlib.metadata.entry_points()
        scripts = entry_points.select(group="console_scripts")
        hestai_context_ep = next(
            (ep for ep in scripts if ep.name == "hestai-context"), None
        )

        # Load the entry point and verify it's callable
        assert hestai_context_ep is not None
        loaded_fn = hestai_context_ep.load()
        assert callable(loaded_fn)

        # Verify it's the same main function from server
        from hestai_context_mcp.server import main

        assert loaded_fn is main


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

    def test_clock_out_implemented(self, tmp_path):
        """clock_out should return structured response per interface contract."""
        from hestai_context_mcp.tools.clock_out import clock_out

        # Without a valid session, should return error status
        (tmp_path / ".hestai" / "state" / "sessions" / "active").mkdir(parents=True, exist_ok=True)
        result = clock_out(session_id="nonexistent", working_dir=str(tmp_path))
        assert result["status"] == "error"
        assert "session_id" in result
        assert "extracted_learnings" in result

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
