"""Gate A §4.1 invariant #13 — reasoning-field density (ADR-RFC-ARCH-004 v1.1).

HO-AGR-BYTECODE-FORMAT-TWO-BIRDS-20260620 (#101, RATIFIED) ruled AGRs are
LLM "bytecode": DECISION and BECAUSE are flat, compressed-OCTAVE strings of
``≤40 words`` with ``no embedded newline``. The ratified ``GATE_A_GUARD`` is a
value-level word-count/newline check with **NO structural parser change**.

This module is the RED specification for that guard. It asserts:

  #13a  DECISION over 40 words is an ERROR, field-named.
  #13b  BECAUSE over 40 words is an ERROR, field-named.
  #13c  exactly 40 words PASSES (the ≤40 boundary is inclusive).
  #13d  an embedded newline inside DECISION/BECAUSE is an ERROR.
  #13e  a compliant compressed record stays valid (regression).

Plus a #88 PARITY proof: the 40-word threshold and the reasoning-field tuple
are SHARED CONSTANTS exported from ``type_checker`` and imported by ``agr_read``
so the write-side guard and the read side cannot drift.

Regex/string-only (North Star §4 / PROD I3); structured ``ValidationResult``
errors, never raised (PROD I4). Mirrors the #88 invariant-test style.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hestai_context_mcp.tools.governance.type_checker import (
    MAX_REASONING_WORDS,
    REASONING_FIELDS,
    validate_octave_content,
)

_VALID_TOKEN = "HO-CONTEXT-MCP-DENSITY-V11-20260619"
_VALID_AUTHORED_AT = "2026-06-19T00:00:00Z"


def _record(
    *,
    decision: str = "Adopt the bytecode form for reasoning fields.",
    because: str = "Compressed strings optimise LLM retrieval and attention.",
) -> str:
    """Build a fully-valid DECISION_RECORD parameterised on DECISION/BECAUSE.

    DECISION/BECAUSE are injected verbatim inside a quoted OCTAVE string so a
    value may carry an embedded newline (for the #13d newline test) without
    breaking the surrounding record shape.
    """
    return (
        "===DECISION_RECORD===\n"
        "META:\n"
        "  TYPE::DECISION_RECORD\n"
        '  VERSION::"1.0"\n'
        f"  TOKEN::{_VALID_TOKEN}\n"
        "  STATUS::PROPOSED\n"
        "  TIER::OPERATIONAL\n"
        f'  DECISION::"{decision}"\n'
        f'  BECAUSE::"{because}"\n'
        f'  AUTHORED_AT::"{_VALID_AUTHORED_AT}"\n'
        "===END===\n"
    )


def _words(n: int) -> str:
    """A whitespace-separated string of exactly ``n`` words (no operators/quotes)."""
    return " ".join(f"w{i}" for i in range(n))


# ---------------------------------------------------------------------------
# #13a / #13b — over 40 words is an error, field-named
# ---------------------------------------------------------------------------


class TestReasoningWordCeiling:
    @pytest.mark.unit
    def test_decision_over_40_words_rejected(self, tmp_path: Path) -> None:
        content = _record(decision=_words(MAX_REASONING_WORDS + 1))
        result = validate_octave_content(tmp_path, content)
        assert result.valid is False
        assert any("DECISION" in e for e in result.errors), result.errors

    @pytest.mark.unit
    def test_because_over_40_words_rejected(self, tmp_path: Path) -> None:
        content = _record(because=_words(MAX_REASONING_WORDS + 1))
        result = validate_octave_content(tmp_path, content)
        assert result.valid is False
        assert any("BECAUSE" in e for e in result.errors), result.errors

    @pytest.mark.unit
    def test_far_over_ceiling_still_one_clear_error(self, tmp_path: Path) -> None:
        """A 112-word BECAUSE (the worst real offender) is rejected and named."""
        content = _record(because=_words(112))
        result = validate_octave_content(tmp_path, content)
        assert result.valid is False
        assert any("BECAUSE" in e and "40" in e for e in result.errors), result.errors


# ---------------------------------------------------------------------------
# #13c — the ≤40 boundary is inclusive
# ---------------------------------------------------------------------------


class TestReasoningBoundary:
    @pytest.mark.unit
    def test_exactly_40_words_passes(self, tmp_path: Path) -> None:
        """40 words is compliant (≤40); only 41+ trips the guard."""
        content = _record(
            decision=_words(MAX_REASONING_WORDS),
            because=_words(MAX_REASONING_WORDS),
        )
        result = validate_octave_content(tmp_path, content)
        assert result.valid, result.errors

    @pytest.mark.unit
    def test_forty_one_words_is_first_failing_count(self, tmp_path: Path) -> None:
        content = _record(decision=_words(MAX_REASONING_WORDS + 1))
        result = validate_octave_content(tmp_path, content)
        assert result.valid is False


# ---------------------------------------------------------------------------
# #13d — embedded newline inside a reasoning value is an error
# ---------------------------------------------------------------------------


class TestNoEmbeddedNewline:
    @pytest.mark.unit
    def test_decision_with_embedded_newline_rejected(self, tmp_path: Path) -> None:
        """A multi-physical-line DECISION value violates the flat-string rule."""
        content = _record(decision="First clause of the decision\n  spilling onto a second line")
        result = validate_octave_content(tmp_path, content)
        assert result.valid is False
        assert any("DECISION" in e and "newline" in e.lower() for e in result.errors), result.errors

    @pytest.mark.unit
    def test_because_with_embedded_newline_rejected(self, tmp_path: Path) -> None:
        content = _record(because="Rationale clause one\n  rationale clause two")
        result = validate_octave_content(tmp_path, content)
        assert result.valid is False
        assert any("BECAUSE" in e and "newline" in e.lower() for e in result.errors), result.errors


# ---------------------------------------------------------------------------
# #13e — compliant compressed record stays valid (regression)
# ---------------------------------------------------------------------------


class TestCompliantRecordValid:
    @pytest.mark.unit
    def test_compressed_record_valid(self, tmp_path: Path) -> None:
        content = _record(
            decision="Adopt AGR-as-bytecode: flat compressed DECISION∧BECAUSE, "
            "nested keys REJECTED, HUMAN_ADR_REF as greppable token (v1.1 MINOR-additive).",
            because="AGRs ~99% LLM-read→optimise retrieval∧attention; flat compression "
            "preserves #88 parity∴Wall-safe.",
        )
        result = validate_octave_content(tmp_path, content)
        assert result.valid, result.errors


# ---------------------------------------------------------------------------
# #88 PARITY — threshold + field tuple are SHARED CONSTANTS, not duplicated
# ---------------------------------------------------------------------------


class TestSharedConstantParity:
    @pytest.mark.unit
    def test_threshold_is_forty(self) -> None:
        assert MAX_REASONING_WORDS == 40

    @pytest.mark.unit
    def test_reasoning_fields_are_decision_and_because(self) -> None:
        assert REASONING_FIELDS == ("DECISION", "BECAUSE")

    @pytest.mark.unit
    def test_agr_read_imports_the_same_constants(self) -> None:
        """agr_read MUST source the guard constants from type_checker (one truth).

        Mirrors the established ``REQUIRED_META_FIELDS`` import-parity pattern so
        the write-side guard and the read side can never disagree (issue #88).
        """
        from hestai_context_mcp.tools.governance import agr_read, type_checker

        assert agr_read.MAX_REASONING_WORDS is type_checker.MAX_REASONING_WORDS
        assert agr_read.REASONING_FIELDS is type_checker.REASONING_FIELDS
