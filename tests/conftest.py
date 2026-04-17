"""Shared test fixtures for hestai-context-mcp."""

import pytest


@pytest.fixture
def working_dir(tmp_path: object) -> str:
    """Provide a temporary working directory for tests."""
    return str(tmp_path)
