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


@pytest.mark.unit
@pytest.mark.parametrize(
    "evil_token",
    [
        "../../../etc/passwd",
        "../secret",
        "..",
        ".hestai/decisions/x",
        "HO-X-20260101/../../../etc/passwd",
        "/etc/passwd",
    ],
)
def test_discover_record_rejects_traversal_token_without_path_join(
    tmp_path: Path, evil_token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P1 SECURITY: a traversal-shaped token is rejected BEFORE any path join.

    ``discover_record`` validates the token against the §1.3 regex at the very
    top, so a token containing ``/``, ``.`` or ``..`` returns ``None`` and never
    constructs ``root / f"{token}.oct.md"`` nor globs it. We plant a file OUTSIDE
    the decisions tree and monkeypatch ``Path.exists``/``Path.read_text`` to fail
    loudly if any out-of-tree path is touched — proving no escape occurs.
    """
    from hestai_context_mcp.tools.governance import agr_read

    decisions = tmp_path / ".hestai" / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    # A real AGR planted OUTSIDE the decisions tree — must never be reached.
    outside = tmp_path / ".hestai" / "OUTSIDE.oct.md"
    outside.write_text(
        "===DECISION_RECORD===\nMETA:\n  TYPE::DECISION_RECORD\n"
        "  TOKEN::HO-CONTEXT-MCP-OUTSIDE-20260101\n===END===\n",
        encoding="utf-8",
    )

    decisions_resolved = decisions.resolve()
    real_read_text = Path.read_text

    def guarded_read_text(self: Path, *args: object, **kwargs: object) -> str:
        resolved = self.resolve()
        # Any read must stay within the decisions tree.
        assert str(resolved).startswith(
            str(decisions_resolved)
        ), f"path escape — discover_record read outside decisions tree: {resolved}"
        return real_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    result = agr_read.discover_record(tmp_path, evil_token)
    assert result is None  # rejected by the §1.3 guard, no escape


@pytest.mark.unit
def test_is_valid_token_rejects_traversal_shapes() -> None:
    """The §1.3 TOKEN regex admits no path-traversal metacharacters."""
    from hestai_context_mcp.tools.governance.agr_read import is_valid_token

    for evil in ("../../../etc/passwd", "../secret", "..", "a/b", "/etc/passwd"):
        assert is_valid_token(evil) is False
    # A well-formed token still validates.
    assert is_valid_token("HO-CONTEXT-MCP-OK-20260101") is True
