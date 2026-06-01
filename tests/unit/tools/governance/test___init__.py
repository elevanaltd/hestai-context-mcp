"""Tests for governance package __init__.py (smoke import test)."""

import pytest


@pytest.mark.smoke
def test_governance_package_importable() -> None:
    """The governance package can be imported without error."""
    import hestai_context_mcp.tools.governance  # noqa: F401
