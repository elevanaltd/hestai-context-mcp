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


def _record(
    decision: str = "",
    because: str = "",
    *,
    rationale: str = "",
    why: str = "",
    status: str = "RATIFIED",
    extra: tuple[str, str] | None = None,
) -> str:
    """A minimal valid-shaped DECISION_RECORD with the given reasoning values.

    ``rationale``/``why`` cover the remaining two _REASONING_KEYS. ``status`` lets a
    test emit an overlong NON-reasoning STATUS value, and ``extra`` injects an
    arbitrary ``(KEY, value)`` quoted assignment (e.g. a made-up NOTE) to prove
    non-reasoning keys are skipped by the lint.
    """
    parts = [
        "===DECISION_RECORD===",
        "META:",
        "  TYPE::DECISION_RECORD",
        '  TOKEN::"HO-CONTEXT-MCP-LINTREC-20260601"',
        "---",
        f'STATUS::"{status}"',
        "TIER::STRATEGIC",
    ]
    if decision:
        parts.append(f'DECISION::"{decision}"')
    if because:
        parts.append(f'BECAUSE::"{because}"')
    if rationale:
        parts.append(f'RATIONALE::"{rationale}"')
    if why:
        parts.append(f'WHY::"{why}"')
    if extra is not None:
        key, value = extra
        parts.append(f'{key}::"{value}"')
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


class TestThresholdBoundaries:
    """On/off-by-one boundary proofs for each threshold (referencing constants)."""

    def test_decision_at_exactly_max_words_passes(self) -> None:
        # words == MAX_WORDS uses ``words > MAX_WORDS`` so the boundary value PASSES.
        decision = " ".join(f"w{i}" for i in range(verbosity_lint.MAX_WORDS))
        assert lint_verbosity(_record(decision=decision)) == []

    def test_decision_at_max_words_plus_one_flags_length(self) -> None:
        # words == MAX_WORDS + 1 is the first count that trips the length rule.
        decision = " ".join(f"w{i}" for i in range(verbosity_lint.MAX_WORDS + 1))
        errors = lint_verbosity(_record(decision=decision))
        assert any("DECISION" in e and "words" in e for e in errors)

    def test_density_not_checked_below_min_words(self) -> None:
        # A dense value ONE WORD below DENSITY_MIN_WORDS must NOT be density-checked.
        # All-stopword pool repeated to the exact boundary count (density 1.0 if checked).
        pool = ["the", "of", "to", "in", "a"]  # all in _STOPWORDS
        count = verbosity_lint.DENSITY_MIN_WORDS - 1
        value = " ".join(pool[i % len(pool)] for i in range(count))
        assert verbosity_lint._word_count(value) == count
        assert not any("stopword" in e.lower() for e in lint_verbosity(_record(because=value)))

    def test_density_checked_at_min_words(self) -> None:
        # At exactly DENSITY_MIN_WORDS the density rule engages (and fires, dense).
        pool = ["the", "of", "to", "in", "a"]
        count = verbosity_lint.DENSITY_MIN_WORDS
        value = " ".join(pool[i % len(pool)] for i in range(count))
        assert verbosity_lint._word_count(value) == count
        assert any("stopword" in e.lower() for e in lint_verbosity(_record(because=value)))

    def test_enum_not_flagged_below_min_words(self) -> None:
        # A value ONE WORD below ENUM_MIN_WORDS with (1)(2) must NOT flag enum.
        count = verbosity_lint.ENUM_MIN_WORDS - 1
        # Build exactly ``count`` whitespace-separated words, two of which are
        # the enumeration markers "(1)" and "(2)".
        words = ["(1)", "(2)"] + [f"w{i}" for i in range(count - 2)]
        value = " ".join(words)
        assert verbosity_lint._word_count(value) == count
        assert not any("enumeration" in e.lower() for e in lint_verbosity(_record(decision=value)))

    def test_enum_flagged_at_min_words(self) -> None:
        # At exactly ENUM_MIN_WORDS with two markers the enum rule fires.
        count = verbosity_lint.ENUM_MIN_WORDS
        words = ["(1)", "(2)"] + [f"w{i}" for i in range(count - 2)]
        value = " ".join(words)
        assert verbosity_lint._word_count(value) == count
        assert any("enumeration" in e.lower() for e in lint_verbosity(_record(decision=value)))


class TestAllReasoningKeysAreLinted:
    """RATIONALE and WHY are in _REASONING_KEYS and must be linted too."""

    def test_overlong_rationale_is_flagged(self) -> None:
        rationale = " ".join(f"word{i}" for i in range(verbosity_lint.MAX_WORDS + 10))
        errors = lint_verbosity(_record(rationale=rationale))
        assert any("RATIONALE" in e and "words" in e for e in errors)

    def test_overlong_why_is_flagged(self) -> None:
        why = " ".join(f"word{i}" for i in range(verbosity_lint.MAX_WORDS + 10))
        errors = lint_verbosity(_record(why=why))
        assert any("WHY" in e and "words" in e for e in errors)

    def test_reasoning_keys_constant_covers_all_four(self) -> None:
        # Guards against silent drift between the helper and the module contract.
        assert set(verbosity_lint._REASONING_KEYS) == {"DECISION", "BECAUSE", "RATIONALE", "WHY"}


class TestNonReasoningKeysIgnored:
    """The ``continue`` branch: overlong NON-reasoning values are skipped."""

    def test_overlong_status_value_is_ignored(self) -> None:
        # An overlong STATUS (not a reasoning key) must produce NO errors.
        long_status = " ".join(f"word{i}" for i in range(verbosity_lint.MAX_WORDS + 50))
        assert lint_verbosity(_record(status=long_status)) == []

    def test_overlong_arbitrary_non_reasoning_key_is_ignored(self) -> None:
        # A made-up NOTE key with an overlong, stopword-dense, enumerated value
        # still returns [] — proving the lint scopes strictly to _REASONING_KEYS.
        dense = ("the of to in a " * 40).strip()  # long + dense + would trip every rule
        note = f"(1) {dense} (2) more (3) more"
        assert lint_verbosity(_record(extra=("NOTE", note))) == []


class TestDensityOnNonAlphabeticValue:
    """_stopword_density returns 0.0 when a long value has no [A-Za-z'] words."""

    def test_long_non_alphabetic_value_is_not_flagged_dense(self) -> None:
        # A value long enough to enter the density branch (>= DENSITY_MIN_WORDS by
        # whitespace split) but containing ZERO alphabetic words: ``_WORD_RE``
        # finds nothing, density short-circuits to 0.0, so the density rule does
        # NOT fire (covers the empty-words guard in _stopword_density).
        count = verbosity_lint.DENSITY_MIN_WORDS + 5
        value = " ".join("123" for _ in range(count))  # numeric tokens only
        assert verbosity_lint._word_count(value) == count
        assert verbosity_lint._stopword_density(value) == 0.0
        assert not any("stopword" in e.lower() for e in lint_verbosity(_record(because=value)))


class TestMultiErrorAccumulation:
    """One field can be simultaneously overlong AND dense AND enumerated."""

    def test_single_field_accumulates_distinct_errors(self) -> None:
        # Construct a DECISION that violates all three rules at once:
        #   - over MAX_WORDS (length),
        #   - stopword-dense (> DENSITY_THRESHOLD over DENSITY_MIN_WORDS),
        #   - inline enumeration ((1)...(2)...) over ENUM_MIN_WORDS.
        dense_tail = "the of to in a " * 30  # ~150 dense words -> length + density
        decision = f"(1) {dense_tail} (2) and {dense_tail} (3) done"
        assert verbosity_lint._word_count(decision) > verbosity_lint.MAX_WORDS
        errors = lint_verbosity(_record(decision=decision))
        assert len(errors) >= 2
        # Assert the three DISTINCT rule messages are each present.
        assert any("words" in e and "max" in e.lower() for e in errors)  # length rule
        assert any("stopword" in e.lower() for e in errors)  # density rule
        assert any("enumeration" in e.lower() for e in errors)  # enum rule
        # All three accumulate for the one field -> three distinct errors.
        assert len(errors) == 3


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
        # Escape handling on a MEANINGFUL case: a LONG value (> MAX_WORDS) that
        # contains escaped quotes must still be captured *whole* by the regex
        # (the ``\\.`` alternation consumes the escaped ``\"`` rather than
        # terminating the value early) — so the full length is measured and the
        # length rule fires. A premature termination at the first ``\"`` would
        # truncate the value and hide the verbosity, so this proves the escape
        # branch on a load-bearing input, not a vacuous short one.
        n = verbosity_lint.MAX_WORDS + 5
        # Embed escaped quotes mid-value; each ``\"word\"`` token still counts as
        # whitespace-separated words, keeping the count deterministic and > MAX_WORDS.
        body = " ".join(f'\\"word{i}\\"' for i in range(n))
        octave = _record(decision=body)
        # The regex must capture the whole escaped value as a single match.
        matches = list(verbosity_lint._QUOTED_ASSIGNMENT_RE.finditer(octave))
        decision_match = next(m for m in matches if m.group("key") == "DECISION")
        captured = decision_match.group("val")
        assert captured.count("word") == n  # full value captured, not truncated at first \"
        # And the length rule fires on the full (escaped) value.
        errors = lint_verbosity(octave)
        assert any("DECISION" in e and "words" in e for e in errors)
        # Sanity: the capture regex is the documented string-only form.
        assert isinstance(verbosity_lint._QUOTED_ASSIGNMENT_RE, re.Pattern)
