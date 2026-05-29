"""Persistent regression guard: North Star OCTAVE summaries MUST stay UPOG-clean.

Why this guard exists
---------------------
The legacy immutable container forms silently LOSE DATA under octave-mcp's
strict lexer (>=1.13):

* chained ``I#::NAME::[KEY::v, ...]`` parses as an assignment that hoists the
  inner keys to file-top-level, so ``PRINCIPLE`` / ``WHY`` / ``STATUS`` collide
  across ``I1..IN`` (duplicate-key, last-write-wins);
* flat section keys repeated across ``§N`` sections (e.g. a ``TRANSPORT`` under
  both ``§1`` and ``§5``) collide the same way;
* markdown ``## headings`` inside the ``===ENVELOPE===`` fail tokenisation
  (``E_TOKENIZE`` / ``E005``).

The bundled regex validator and the ``octave validate`` CLI report the broken
form as "valid" (exit 0) and silently canonicalise the data away -- that false
confidence is exactly what let the bug live. The ONLY reliable detector is the
strict lexer, exercised here via :func:`octave_mcp.parse_with_warnings`.

Anti-rot: the negative-control tests prove the detector still FIRES on a
known-bad legacy fixture and RAISES on a ``## heading`` fixture, so this guard
cannot silently degrade into a no-op. The discovery test fails if the North
Star glob is empty.

Reference implementation: ``elevanaltd/HestAI-MCP``
``tests/unit/governance/test_north_star_upog_compliance.py``.
"""

from __future__ import annotations

from pathlib import Path

import octave_mcp
import pytest

# tests/unit/governance/test_*.py -> parents[3] == repository root.
REPO_ROOT = Path(__file__).resolve().parents[3]

# Strict-lexer warning subtypes that each indicate silent data loss. These are
# the ``subtype`` values emitted in the warning dicts from parse_with_warnings.
REGRESSION_SUBTYPES = {
    "duplicate_key",
    "bare_line_dropped",
    "bare_flow",
    "multi_word_coalesce",
}


def _discover_ns_summaries() -> list[Path]:
    """Return every committed North Star OCTAVE summary in this repository.

    Skips the gitignored ``.hestai-sys/`` delivery tree (regenerated from the
    Vault on restart -- not a source artefact this repo governs).
    """
    return sorted(
        p for p in REPO_ROOT.glob("**/*NORTH-STAR-SUMMARY.oct.md") if ".hestai-sys" not in p.parts
    )


NS_SUMMARIES = _discover_ns_summaries()


def _regression_subtypes(warnings: list[dict]) -> set[str]:
    """Intersection of observed warning subtypes with the data-loss set."""
    return {w.get("subtype") for w in warnings if w.get("subtype")} & REGRESSION_SUBTYPES


@pytest.mark.unit
class TestDiscovery:
    """A guard that passes over zero files is a silent no-op."""

    def test_at_least_one_north_star_summary_found(self) -> None:
        assert NS_SUMMARIES, (
            f"No *NORTH-STAR-SUMMARY.oct.md found under {REPO_ROOT}. "
            "The UPOG guard would silently pass over nothing -- check the glob."
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "ns_path",
    NS_SUMMARIES,
    ids=lambda p: str(p.relative_to(REPO_ROOT)),
)
class TestNorthStarUpogCompliance:
    """Every North Star summary must parse cleanly under the strict lexer."""

    def test_parses_without_lexer_error(self, ns_path: Path) -> None:
        """Strict lexer must accept the document (no markdown / E_TOKENIZE)."""
        try:
            octave_mcp.parse_with_warnings(ns_path.read_text())
        except octave_mcp.LexerError as exc:
            pytest.fail(
                f"{ns_path.relative_to(REPO_ROOT)} fails the strict lexer "
                f"(markdown heading or bad token?): {exc}"
            )

    def test_no_regression_subtypes(self, ns_path: Path) -> None:
        """Zero silent-data-loss subtypes in the strict-lexer warnings."""
        _doc, warnings = octave_mcp.parse_with_warnings(ns_path.read_text())
        offending = _regression_subtypes(warnings)
        assert not offending, (
            f"{ns_path.relative_to(REPO_ROOT)} regressed to a data-losing form: "
            f"{sorted(offending)}. Full warnings: {warnings}"
        )


# --- Negative controls: prove the detector still works (anti-rot) -----------

_LEGACY_BROKEN = """===NORTH_STAR_SUMMARY===
META:
  TYPE::NORTH_STAR_SUMMARY
  VERSION::"1.0"
§1::IDENTITY
TRANSPORT::"stdio JSON-RPC"
§2::IMMUTABLES
I1::SESSION_LIFECYCLE::[PRINCIPLE::a,WHY::b,STATUS::c]
I2::CREDENTIAL_SAFETY::[PRINCIPLE::d,WHY::e,STATUS::f]
§5::CONSTRAINED_VARIABLES
TRANSPORT::[IMMUTABLE::x]
===END===
"""

_MARKDOWN_HEADING = """===NORTH_STAR_SUMMARY===
META:
  TYPE::NORTH_STAR_SUMMARY
  VERSION::"1.0"
## IMMUTABLES (6 Total)
I1::"X<PRINCIPLE::a>"
===END===
"""


@pytest.mark.unit
class TestDetectorAntiRot:
    """The detector itself is tested, so the guard cannot silently rot."""

    def test_detector_fires_on_legacy_duplicate_key_form(self) -> None:
        """Chained ``I#::NAME::[...]`` plus a flat repeated section key MUST
        surface ``duplicate_key`` -- if this stops firing, the guard is a
        no-op masquerading as protection.
        """
        _doc, warnings = octave_mcp.parse_with_warnings(_LEGACY_BROKEN)
        offending = _regression_subtypes(warnings)
        assert offending, (
            "Strict lexer failed to flag the known-bad legacy form. "
            f"Guard has rotted. Warnings: {warnings}"
        )
        assert "duplicate_key" in offending

    def test_detector_raises_on_markdown_heading(self) -> None:
        """A markdown ``## heading`` inside the envelope MUST fail tokenisation."""
        with pytest.raises(octave_mcp.LexerError):
            octave_mcp.parse_with_warnings(_MARKDOWN_HEADING)
