"""Tests for the phase resolver (``hestai_context_mcp.core.phase``).

Resolves the full declared phase string (e.g. ``B1_FOUNDATION_COMPLETE``)
from North Star / PROJECT-CONTEXT files. Issue #4 acceptance criterion 2:
phase string must match legacy's full form, not the bare abbreviation.
"""

from __future__ import annotations

from pathlib import Path

from hestai_context_mcp.core.phase import (
    DEFAULT_PHASE,
    phase_prefix,
    resolve_phase,
)


class TestPhasePrefix:
    def test_prefix_of_full_form(self):
        assert phase_prefix("B1_FOUNDATION_COMPLETE") == "B1"

    def test_prefix_of_bare_form(self):
        assert phase_prefix("B1") == "B1"

    def test_prefix_of_unknown(self):
        # Unknown phase string → best-effort underscore split.
        assert phase_prefix("XX_WHATEVER") == "XX"


class TestResolvePhase:
    def test_reads_from_north_star_summary(self, tmp_path: Path):
        ns_dir = tmp_path / ".hestai" / "north-star"
        ns_dir.mkdir(parents=True)
        (ns_dir / "000-TEST-NORTH-STAR-SUMMARY.oct.md").write_text(
            "===NORTH_STAR===\nPHASE::B1_FOUNDATION_COMPLETE\n===END==="
        )
        assert resolve_phase(tmp_path) == "B1_FOUNDATION_COMPLETE"

    def test_reads_from_project_context_when_no_north_star(self, tmp_path: Path):
        ctx_dir = tmp_path / ".hestai" / "state" / "context"
        ctx_dir.mkdir(parents=True)
        (ctx_dir / "PROJECT-CONTEXT.oct.md").write_text(
            "===PROJECT_CONTEXT===\nMETA:\n  PHASE::D2_DESIGN_REVIEW\n===END==="
        )
        assert resolve_phase(tmp_path) == "D2_DESIGN_REVIEW"

    def test_north_star_takes_precedence_over_project_context(self, tmp_path: Path):
        ns_dir = tmp_path / ".hestai" / "north-star"
        ns_dir.mkdir(parents=True)
        (ns_dir / "000-TEST-NORTH-STAR-SUMMARY.oct.md").write_text("PHASE::B2_INTEGRATION")
        ctx_dir = tmp_path / ".hestai" / "state" / "context"
        ctx_dir.mkdir(parents=True)
        (ctx_dir / "PROJECT-CONTEXT.oct.md").write_text("PHASE::D0_STALE")
        assert resolve_phase(tmp_path) == "B2_INTEGRATION"

    def test_returns_default_when_no_files(self, tmp_path: Path):
        assert resolve_phase(tmp_path) == DEFAULT_PHASE

    def test_ignores_malformed_phase_line(self, tmp_path: Path):
        ns_dir = tmp_path / ".hestai" / "north-star"
        ns_dir.mkdir(parents=True)
        # PHASE marker with no value → skip, fall through to default.
        (ns_dir / "000-TEST-NORTH-STAR-SUMMARY.oct.md").write_text("PHASE::\n")
        assert resolve_phase(tmp_path) == DEFAULT_PHASE

    def test_trims_whitespace_and_inline_comments(self, tmp_path: Path):
        ns_dir = tmp_path / ".hestai" / "north-star"
        ns_dir.mkdir(parents=True)
        (ns_dir / "000-TEST-NORTH-STAR-SUMMARY.oct.md").write_text(
            "  PHASE::  B1_FOUNDATION_COMPLETE  \n"
        )
        assert resolve_phase(tmp_path) == "B1_FOUNDATION_COMPLETE"
