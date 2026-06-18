"""Deterministic verbosity lint for authored governance OCTAVE (RFC #53 Gate C).

The prose->OCTAVE Semantic Compiler can emit *syntactically valid* OCTAVE that is
nonetheless uncompressed prose wearing OCTAVE clothing — a single multi-hundred-word
``DECISION``/``BECAUSE`` string with ``(1)...(2)...(3)`` enumeration. Gate A (regex)
and Gate B (octave-mcp validator) both pass it (it is valid), and the scoped semantic
reviewer (precedence/contradiction/scope/concept-validity per
HO-AGR-SEMANTIC-REVIEWER-ANALYSIS-TIER-20260611) does not cover density. Verbosity
therefore lives in an ungated gap.

This module is that backstop: a deterministic, regex/string-only density check on the
reasoning-bearing fields. It enforces the compression contract the compiler prompt
*requests* — turning a probability shift into a structural invariant. No OCTAVE AST,
no LLM (North Star PROD §4: octave-mcp owns the format). It performs no writes.

Wired into ``intake_pipeline._gate`` so a verbose first attempt triggers the existing
informed retry, and a verbose second attempt aborts — no verbose record reaches a PR.
"""

from __future__ import annotations

import re

__all__ = ["lint_verbosity"]

# Reasoning-bearing fields whose values must be telegraphic, not paragraphs.
_REASONING_KEYS = ("DECISION", "BECAUSE", "RATIONALE", "WHY")

# KEY::"value" assignment capture. The value is a double-quoted OCTAVE string that
# may span physical lines; ``(?:[^"\\]|\\.)*`` consumes everything up to the first
# unescaped closing quote (escaped \" is honoured). String-only — no AST.
_QUOTED_ASSIGNMENT_RE = re.compile(
    r'(?ms)^[ \t]*(?P<key>[A-Z][A-Z0-9_]*)::"(?P<val>(?:[^"\\]|\\.)*)"'
)

# Inline enumeration inside a single value: "(1)", "(2)", ... — the prose-bleed tell.
_INLINE_ENUM_RE = re.compile(r"\(\s*\d+\s*\)")

# --- Thresholds (module-level so tests can pin them; conservative by design to
# flag only egregious verbosity, never normally-compressed records). ---
# Absolute word ceiling for any single reasoning value.
MAX_WORDS = 120
# Stopword-density check only applies to already-long values, and only fires when
# the value is BOTH long and stopword-dense (English prose ~0.35-0.45; telegraphic
# OCTAVE far lower).
DENSITY_MIN_WORDS = 80
DENSITY_THRESHOLD = 0.33
# Inline enumeration is a signal only inside a long value (a short "(1)" is fine).
ENUM_MIN_WORDS = 60

# Common English stopwords. Deliberately EXCLUDES causal/relational connectives
# (because, therefore, via, while) — those carry semantic payload we want kept.
# Split over a named constant (not a string literal) so the readable wrapped form
# survives both black and ruff SIM905 (which only fires on a literal .split()).
_STOPWORD_SOURCE = (
    "a an the and or but of to in on at for with by from as is are was were "
    "be been being that which this these those it its into than then so such "
    "not no nor do does did has have had will would can could should may might "
    "must also only just even about over under out up down off their there they "
    "them what who whom whose any all each both more most other some if we our "
    "you your he she"
)
_STOPWORDS = frozenset(_STOPWORD_SOURCE.split())

_WORD_RE = re.compile(r"[A-Za-z']+")


def _word_count(value: str) -> int:
    return len(value.split())


def _stopword_density(value: str) -> float:
    words = _WORD_RE.findall(value.lower())
    if not words:
        return 0.0
    stop = sum(1 for w in words if w in _STOPWORDS)
    return stop / len(words)


def lint_verbosity(octave: str) -> list[str]:
    """Return actionable verbosity errors for an OCTAVE governance artifact.

    Empty list == the reasoning fields are adequately compressed. Each error is a
    single string suitable for the informed-retry feedback block (it tells the
    compiler exactly which field is too verbose and how to compress it).

    Pure function: no I/O, no AST, no LLM. Deterministic for identical input.
    """
    errors: list[str] = []
    for match in _QUOTED_ASSIGNMENT_RE.finditer(octave):
        key = match.group("key")
        if key not in _REASONING_KEYS:
            continue
        value = match.group("val")
        words = _word_count(value)

        if words > MAX_WORDS:
            errors.append(
                f"VERBOSITY: {key} value is {words} words (max {MAX_WORDS}). Compress to a "
                "telegraphic phrase — drop stopwords and let operators (⊕ ⇌ →) carry the "
                "connectives; split enumerated sub-points into BLOCK-structured keyed children, "
                "never one prose paragraph (octave-compression CONSERVATIVE, R3a)."
            )

        if words >= DENSITY_MIN_WORDS:
            density = _stopword_density(value)
            if density > DENSITY_THRESHOLD:
                errors.append(
                    f"VERBOSITY: {key} value is stopword-dense ({round(density * 100)}% stopwords "
                    f"over {words} words). Drop stopwords and let operators carry the connectives "
                    "(octave-compression R3a telegraphic phrase)."
                )

        if words >= ENUM_MIN_WORDS and len(_INLINE_ENUM_RE.findall(value)) >= 2:
            errors.append(
                f"VERBOSITY: {key} value embeds inline enumeration ((1)…(2)…) inside a single "
                "string — prose-bleed. Use BLOCK form with keyed children for the enumerated "
                "points (octave-mastery §6 PROSE_BLEED / §5 BLOCK_NOTATION_RULE)."
            )

    return errors
