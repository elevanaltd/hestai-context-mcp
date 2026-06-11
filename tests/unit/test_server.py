"""Tests for .env loading at server startup (Gate C prose mode support).

The MCP server launches via ``python -m hestai_context_mcp`` and must load a
``.env`` file so that ``submit_governance(prose_input=...)`` (Gate C) can resolve
``OPENROUTER_API_KEY`` / ``HESTAI_AI_MODEL`` when started by an MCP client whose
CWD is unrelated to the repo.

Invariants under test:
- A ``.env`` file is loaded into ``os.environ`` at startup.
- ``override=False`` is honoured: a pre-set process env var is NEVER overwritten
  (PROD I2 — never clobber an explicit secret / keyring value with a file value).
- A missing ``.env`` does not crash; ``_load_env`` returns ``False``.
- ``main()`` loads .env before ``mcp.run()`` (additive; PROD I5 unaffected).
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def clean_env():
    """Snapshot and restore os.environ around each test."""
    saved = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


class TestLoadEnv:
    """Unit tests for the _load_env startup helper."""

    def test_env_file_loaded_into_environ(self, tmp_path: Path, clean_env):
        """A .env file at the given path is loaded into os.environ."""
        from hestai_context_mcp.server import _load_env

        env_file = tmp_path / ".env"
        env_file.write_text("HESTAI_TEST_LOADED=from_dotenv\n")
        os.environ.pop("HESTAI_TEST_LOADED", None)

        loaded = _load_env(dotenv_path=env_file)

        assert loaded is True
        assert os.environ.get("HESTAI_TEST_LOADED") == "from_dotenv"

    def test_override_false_does_not_clobber_existing(self, tmp_path: Path, clean_env):
        """A pre-set process env var must NOT be overwritten (override=False, PROD I2)."""
        from hestai_context_mcp.server import _load_env

        env_file = tmp_path / ".env"
        env_file.write_text("OPENROUTER_API_KEY=value_from_file\n")
        os.environ["OPENROUTER_API_KEY"] = "value_already_in_process"

        _load_env(dotenv_path=env_file)

        assert os.environ["OPENROUTER_API_KEY"] == "value_already_in_process"

    def test_missing_env_file_does_not_crash(self, tmp_path: Path, clean_env):
        """A missing .env path returns False and does not raise."""
        from hestai_context_mcp.server import _load_env

        missing = tmp_path / "does_not_exist.env"

        assert _load_env(dotenv_path=missing) is False

    def test_no_args_resolves_project_root_then_cwd(self, tmp_path: Path, clean_env):
        """With no explicit path, the CWD/.env fallback is honoured when project-root has none."""
        from hestai_context_mcp.server import _load_env

        # Point project-root resolution at a dir with no .env so the CWD
        # fallback is exercised deterministically.
        empty_root = tmp_path / "no_repo_env"
        empty_root.mkdir()
        cwd_dir = tmp_path / "cwd"
        cwd_dir.mkdir()
        (cwd_dir / ".env").write_text("HESTAI_TEST_CWD=from_cwd\n")
        os.environ.pop("HESTAI_TEST_CWD", None)

        with (
            patch("hestai_context_mcp.server._project_root_env", return_value=empty_root / ".env"),
            patch("hestai_context_mcp.server.Path.cwd", return_value=cwd_dir),
        ):
            loaded = _load_env()

        assert loaded is True
        assert os.environ.get("HESTAI_TEST_CWD") == "from_cwd"

    def test_project_root_env_preferred_over_cwd(self, tmp_path: Path, clean_env):
        """Project-root .env takes precedence over CWD/.env when both exist."""
        from hestai_context_mcp.server import _load_env

        root_dir = tmp_path / "repo_root"
        root_dir.mkdir()
        (root_dir / ".env").write_text("HESTAI_TEST_SOURCE=from_root\n")
        cwd_dir = tmp_path / "cwd"
        cwd_dir.mkdir()
        (cwd_dir / ".env").write_text("HESTAI_TEST_SOURCE=from_cwd\n")
        os.environ.pop("HESTAI_TEST_SOURCE", None)

        with (
            patch("hestai_context_mcp.server._project_root_env", return_value=root_dir / ".env"),
            patch("hestai_context_mcp.server.Path.cwd", return_value=cwd_dir),
        ):
            loaded = _load_env()

        assert loaded is True
        assert os.environ.get("HESTAI_TEST_SOURCE") == "from_root"


class TestMainLoadsEnv:
    """main() must load .env before starting the server transport."""

    def test_main_calls_load_env_before_run(self):
        """main() invokes _load_env, then mcp.run() (load happens before transport starts)."""
        call_order = []

        def record_load(*args, **kwargs):
            call_order.append("load_env")
            return False

        def record_run(*args, **kwargs):
            call_order.append("run")

        with (
            patch("hestai_context_mcp.server._load_env", side_effect=record_load),
            patch("fastmcp.FastMCP.run", side_effect=record_run),
        ):
            from hestai_context_mcp.server import main

            main()

        assert call_order == ["load_env", "run"]
