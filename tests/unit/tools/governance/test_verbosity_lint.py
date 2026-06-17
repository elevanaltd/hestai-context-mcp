"""Tests for the deterministic verbosity lint (RFC #53 Gate C backstop).

``lint_verbosity`` enforces the compression contract that the prose->OCTAVE
compiler prompt *requests*: reasoning-bearing fields (DECISION/BECAUSE/...) must
be telegraphic, not multi-hundred-word prose paragraphs. It is regex/string-only
(North Star PROD §4: no OCTAVE AST, no LLM) and performs no I/O.

The lint exists because Gate A (regex), Gate B (octave-mcp validator) and the
scoped semantic reviewer all PASS a verbose-but-valid record — verbosity lives in
an ungated gap. This backstop closes it deterministically.
"""

from __future__ import annotations

import re

from hestai_context_mcp.tools.governance import verbosity_lint
from hestai_context_mcp.tools.governance.verbosity_lint import lint_verbosity


def _record(decision: str = "", because: str = "") -> str:
    """A minimal valid-shaped DECISION_RECORD with the given reasoning values."""
    parts = [
        "===DECISION_RECORD===",
        "META:",
        "  TYPE::DECISION_RECORD",
        '  TOKEN::"HO-CONTEXT-MCP-LINTREC-20260601"',
        "---",
        "STATUS::RATIFIED",
        "TIER::STRATEGIC",
    ]
    if decision:
        parts.append(f'DECISION::"{decision}"')
    if because:
        parts.append(f'BECAUSE::"{because}"')
    parts.append("===END===")
    return "\n".join(parts) + "\n"


class TestCompressedRecordsPass:
    def test_tight_compressed_record_has_no_errors(self) -> None:
        # Mirrors the density of the repo's own merged AGRs (~30-50 words).
        octave = _record(
            decision=(
                "public.comments → SHARED cross-app spine table (not app-local); "
                "cross-app authorship carried by app_source enum ⊕ context_label."
            ),
            because=(
                "Shared-comments architecture live ∧ enforced in schema⊕RLS, but its only "
                "governance home was archived → invariant orphaned. Re-home → discoverable. "
                "Basis PROD::I4 ∧ PROD::I2."
            ),
        )
        assert lint_verbosity(octave) == []

    def test_empty_reasoning_fields_have_no_errors(self) -> None:
        assert lint_verbosity(_record()) == []

    def test_short_value_with_single_paren_marker_is_fine(self) -> None:
        # A short value containing one "(1)" must not trip the enumeration rule.
        assert lint_verbosity(_record(decision="adopt option (1) of the two proposals.")) == []


class TestVerboseRecordsFail:
    def test_overlong_decision_is_flagged(self) -> None:
        decision = " ".join(f"word{i}" for i in range(verbosity_lint.MAX_WORDS + 30))
        errors = lint_verbosity(_record(decision=decision))
        assert any("DECISION" in e and "words" in e for e in errors)

    def test_stopword_dense_long_value_is_flagged(self) -> None:
        # A long value that is mostly stopwords -> density rule fires.
        sentence = "this is the one that we have for it as of the day "
        because = (sentence * 12).strip()  # well over DENSITY_MIN_WORDS, high stopword ratio
        errors = lint_verbosity(_record(because=because))
        assert any("BECAUSE" in e and "stopword" in e.lower() for e in errors)

    def test_inline_enumeration_in_long_value_is_flagged(self) -> None:
        body = " ".join(f"clause{i}" for i in range(verbosity_lint.ENUM_MIN_WORDS + 5))
        decision = f"the invariant is captured as follows: (1) {body} (2) more (3) and more"
        errors = lint_verbosity(_record(decision=decision))
        assert any("enumeration" in e.lower() for e in errors)

    def test_errors_are_actionable_single_strings(self) -> None:
        decision = " ".join(f"word{i}" for i in range(verbosity_lint.MAX_WORDS + 30))
        errors = lint_verbosity(_record(decision=decision))
        assert errors and all(isinstance(e, str) and e.strip() for e in errors)


class TestSourceInvariants:
    def test_no_ast_or_llm_dependency(self) -> None:
        # North Star PROD §4: regex/string-only, no OCTAVE AST, no LLM/provider.
        import inspect

        src = inspect.getsource(verbosity_lint)
        # Precise tokens — a bare "ast" would false-match "mastery" in prose.
        for forbidden in ("import ast", "AIClient", "get_octave_validator", "complete_text"):
            assert forbidden not in src

    def test_thresholds_are_tunable_constants(self) -> None:
        assert isinstance(verbosity_lint.MAX_WORDS, int)
        assert isinstance(verbosity_lint.DENSITY_THRESHOLD, float)
        assert 0.0 < verbosity_lint.DENSITY_THRESHOLD < 1.0

    def test_quoted_value_regex_handles_escaped_quotes(self) -> None:
        # A value containing an escaped quote must still parse as one value.
        octave = _record(decision='he said \\"hi\\" and left')
        # No exception, no spurious flag for a short value.
        assert lint_verbosity(octave) == []
        # Sanity: the capture regex is the documented string-only form.
        assert isinstance(verbosity_lint._QUOTED_ASSIGNMENT_RE, re.Pattern)
