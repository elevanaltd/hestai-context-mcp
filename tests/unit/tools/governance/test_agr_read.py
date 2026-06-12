"""Locator/marker test for the shared AGR read primitive.

``tools/governance/agr_read.py`` is exercised end-to-end through the three
public tool suites (test_lookup_decision / test_list_decisions /
test_trace_supersedure), which is where its behaviour is asserted. This module
exists so the test-locator finds a co-located test for the shared module and to
pin its public surface (a smoke import) — it adds no behavioural assertions
beyond what the tool suites already cover.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.smoke
def test_shared_read_surface_importable() -> None:
    """The shared primitive exposes the envelope + discovery helpers."""
    from hestai_context_mcp.tools.governance.agr_read import (
        TOKEN_FORMAT_RE,
        discover_record,
        error_envelope,
        validate_working_dir,
    )

    assert TOKEN_FORMAT_RE is not None
    assert callable(discover_record)
    assert callable(error_envelope)
    assert callable(validate_working_dir)


@pytest.mark.unit
def test_discover_record_falls_back_to_embedded_token(tmp_path: Path) -> None:
    """A record whose FILENAME drifted from its TOKEN still resolves (§1.1).

    Path-first resolution misses (filename != token), so discovery falls back to
    scanning the store and matching the embedded TOKEN via the Gate-A extractor.
    This exercises the fallback branch the canonical-filename fixtures bypass.
    """
    from hestai_context_mcp.tools.governance.agr_read import discover_record

    token = "HO-CONTEXT-MCP-FILENAME-DRIFT-20260601"
    decisions = tmp_path / ".hestai" / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    # Filename deliberately does NOT match the embedded TOKEN.
    (decisions / "renamed-by-hand.oct.md").write_text(
        "===DECISION_RECORD===\n"
        "META:\n"
        "  TYPE::DECISION_RECORD\n"
        f"  TOKEN::{token}\n"
        "===END===\n",
        encoding="utf-8",
    )

    found = discover_record(tmp_path, token)
    assert found is not None
    assert found.name == "renamed-by-hand.oct.md"


@pytest.mark.unit
def test_discover_record_returns_none_when_store_absent(tmp_path: Path) -> None:
    """No .hestai/decisions store => discovery returns None (defensive guard)."""
    from hestai_context_mcp.tools.governance.agr_read import discover_record

    assert discover_record(tmp_path, "HO-CONTEXT-MCP-ANY-20260601") is None
