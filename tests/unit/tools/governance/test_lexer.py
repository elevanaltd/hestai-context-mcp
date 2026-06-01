"""Behavioral tests for governance.lexer.

Core lookup tests live in
tests/unit/tools/test_submit_governance.py::TestLookupTokenDeterministic.

This module hardens the remaining branches:
  - MANIFEST OSError fall-through (unreadable manifest).
  - Non-table / header / blank lines in MANIFEST are skipped.
  - Filesystem grep OSError on an unreadable oct.md is swallowed.
  - assemble_context budget clipping, ordering, and empty-tree handling.
"""

from pathlib import Path

import pytest

from hestai_context_mcp.tools.governance import lexer
from hestai_context_mcp.tools.governance.lexer import (
    _CONTEXT_BUDGET_CHARS,
    assemble_context,
    lookup_token_deterministic,
)


class TestSearchManifestEdgeCases:
    """_search_manifest OSError and non-table-row handling."""

    @pytest.mark.unit
    def test_unreadable_manifest_falls_through_to_filesystem(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An OSError reading MANIFEST.md must not raise; lookup falls back to FS.

        The token lives only in the filesystem tree, so a True result proves
        the manifest read raised, was swallowed (lexer.py:45-46), and the
        filesystem fallback ran and found the token.
        """
        manifest = tmp_path / ".hestai" / "MANIFEST.md"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("| HO-OTHER-20260101 | path |\n")

        decisions = tmp_path / ".hestai" / "decisions"
        decisions.mkdir(parents=True)
        (decisions / "HO-CONTEXT-MCP-REAL-20260101.oct.md").write_text(
            '===DECISION_RECORD===\nMETA:\n  TOKEN::"HO-CONTEXT-MCP-REAL-20260101"\n===END===\n'
        )

        real_read_text = Path.read_text

        def boom(self: Path, *args: object, **kwargs: object) -> str:
            if self == manifest:
                raise OSError("simulated unreadable manifest")
            return real_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "read_text", boom)

        assert lookup_token_deterministic(tmp_path, "HO-CONTEXT-MCP-REAL-20260101") is True

    @pytest.mark.unit
    def test_non_table_lines_are_skipped(self, tmp_path: Path) -> None:
        """Header text, blank lines and prose (not starting with '|') are ignored.

        Exercises the ``continue`` branch at lexer.py:52 for lines that do not
        start with the table-cell delimiter.
        """
        manifest = tmp_path / ".hestai" / "MANIFEST.md"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(
            "# MANIFEST\n"
            "\n"
            "Some prose describing the manifest.\n"
            "| TOKEN/ID | path |\n"
            "| --- | --- |\n"
            "| HO-CONTEXT-MCP-REAL-20260101 | .hestai/decisions/x.oct.md |\n"
        )

        assert lookup_token_deterministic(tmp_path, "HO-CONTEXT-MCP-REAL-20260101") is True
        # A bare word that only appears in prose must NOT match a table cell.
        assert lookup_token_deterministic(tmp_path, "prose") is False


class TestSearchFilesystemEdgeCases:
    """_search_filesystem OSError handling."""

    @pytest.mark.unit
    def test_unreadable_oct_file_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An oct.md that raises OSError on read is skipped, not fatal.

        The sole governance file raises OSError on read. The lookup must NOT
        raise; it swallows the error at lexer.py:90-91 (``continue``) and,
        finding nothing else, returns False.
        """
        decisions = tmp_path / ".hestai" / "decisions"
        decisions.mkdir(parents=True)
        bad = decisions / "AAA-unreadable.oct.md"
        bad.write_text(
            '===DECISION_RECORD===\nMETA:\n  TOKEN::"HO-CONTEXT-MCP-BAD-20260101"\n===END===\n'
        )

        real_read_text = Path.read_text

        def boom(self: Path, *args: object, **kwargs: object) -> str:
            if self == bad:
                raise OSError("simulated unreadable oct file")
            return real_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "read_text", boom)

        # No MANIFEST -> straight to filesystem grep. The only file is
        # unreadable, so its token is never seen and lookup returns False
        # WITHOUT raising (OSError swallowed).
        assert lookup_token_deterministic(tmp_path, "HO-CONTEXT-MCP-BAD-20260101") is False


class TestAssembleContext:
    """assemble_context concatenation, ordering, budget clipping, empty tree."""

    @pytest.mark.unit
    def test_empty_tree_returns_empty_string(self, tmp_path: Path) -> None:
        """No .hestai subtrees -> empty result (both roots skipped)."""
        assert assemble_context(tmp_path) == ""

    @pytest.mark.unit
    def test_concatenates_decisions_and_concepts(self, tmp_path: Path) -> None:
        """Content from both decisions/ and context/concepts/ is included."""
        decisions = tmp_path / ".hestai" / "decisions"
        decisions.mkdir(parents=True)
        (decisions / "DR.oct.md").write_text("DECISION_CONTENT_MARKER")

        concepts = tmp_path / ".hestai" / "context" / "concepts" / "repo"
        concepts.mkdir(parents=True)
        (concepts / "C.oct.md").write_text("CONCEPT_CONTENT_MARKER")

        out = assemble_context(tmp_path)

        assert "DECISION_CONTENT_MARKER" in out
        assert "CONCEPT_CONTENT_MARKER" in out

    @pytest.mark.unit
    def test_clips_to_budget(self, tmp_path: Path) -> None:
        """Total assembled length never exceeds the character budget.

        Writes two oct.md files each larger than the budget; the result must
        be clipped to exactly _CONTEXT_BUDGET_CHARS and stop reading further
        files (exercises the ``break`` and ``remaining`` clip at 152/158-161).
        """
        decisions = tmp_path / ".hestai" / "decisions"
        decisions.mkdir(parents=True)
        big = "X" * (_CONTEXT_BUDGET_CHARS + 5_000)
        (decisions / "a.oct.md").write_text(big)
        (decisions / "b.oct.md").write_text("SECOND_FILE_MARKER" + big)

        out = assemble_context(tmp_path)

        assert len(out) == _CONTEXT_BUDGET_CHARS
        # Budget was exhausted by the first file, so the second never appears.
        assert "SECOND_FILE_MARKER" not in out

    @pytest.mark.unit
    def test_skips_unreadable_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """An OSError on one oct.md is swallowed; remaining files still assemble.

        Covers the OSError ``continue`` inside assemble_context (lexer.py:157).
        """
        decisions = tmp_path / ".hestai" / "decisions"
        decisions.mkdir(parents=True)
        bad = decisions / "AAA.oct.md"
        good = decisions / "ZZZ.oct.md"
        bad.write_text("UNREADABLE")
        good.write_text("READABLE_MARKER")

        real_read_text = Path.read_text

        def boom(self: Path, *args: object, **kwargs: object) -> str:
            if self == bad:
                raise OSError("simulated unreadable oct file")
            return real_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "read_text", boom)

        out = assemble_context(tmp_path)

        assert "READABLE_MARKER" in out
        assert "UNREADABLE" not in out


@pytest.mark.unit
def test_lexer_module_exposes_public_lookup() -> None:
    """Smoke: the module's public API is importable and callable."""
    assert callable(lexer.lookup_token_deterministic)
    assert callable(lexer.assemble_context)
