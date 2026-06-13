"""Regression tests for issue #85 — lexer TOKEN/ID existence match must be line-anchored.

``lexer._FIELD_EXACT_RE_TEMPLATE`` end-anchors each branch with ``\\s*$`` but has
NO line-START anchor, so a field whose KEY merely *ends* in ``TOKEN`` / ``ID``
(e.g. ``DOCUMENT_TOKEN::<value>`` or ``PARENT_ID::<value>``) substring-leaks and
registers as a clean existence hit. ``lookup_token_deterministic`` drives
supersedure-target verification and duplicate detection in Gate A, so a leak
here can cause a false "already exists" rejection or a false "supersedure target
found".

TDD RED: these MUST fail against the un-line-anchored template and pass once a
``^`` (with ``^\\s*`` to admit OCTAVE indentation) line-start anchor is added,
mirroring the read-side / manifest line-anchoring approach.

North Star §4 regex-only; deterministic.
"""

import re

import pytest

from hestai_context_mcp.tools.governance.lexer import (
    _FIELD_EXACT_RE_TEMPLATE,
    lookup_token_deterministic,
)

_TOKEN = "HO-FOO-20260101"


def _compiled(token: str) -> "re.Pattern[str]":
    return re.compile(_FIELD_EXACT_RE_TEMPLATE.format(token=re.escape(token)))


class TestFieldExactRegexLineAnchored:
    """The compiled field-exact template must reject ``*TOKEN::`` / ``*ID::`` leaks."""

    @pytest.mark.unit
    def test_legitimate_token_line_still_matches(self) -> None:
        """A real indented ``TOKEN::"<value>"`` line still matches (no loosening)."""
        assert _compiled(_TOKEN).search(f'  TOKEN::"{_TOKEN}"\n') is not None

    @pytest.mark.unit
    def test_bare_token_line_still_matches(self) -> None:
        """The bare canonical ``TOKEN::<value>`` form still matches."""
        assert _compiled(_TOKEN).search(f"  TOKEN::{_TOKEN}\n") is not None

    @pytest.mark.unit
    def test_document_token_key_does_not_leak(self) -> None:
        """``DOCUMENT_TOKEN::<value>`` must NOT register as a TOKEN existence hit."""
        assert _compiled(_TOKEN).search(f"  DOCUMENT_TOKEN::{_TOKEN}\n") is None

    @pytest.mark.unit
    def test_suffix_id_key_does_not_leak(self) -> None:
        """``PARENT_ID::<value>`` must NOT register as an ID existence hit."""
        assert _compiled(_TOKEN).search(f"  PARENT_ID::{_TOKEN}\n") is None


class TestLookupTokenDeterministicNoSuffixLeak:
    """End-to-end: a ``*TOKEN::``-suffixed field must not satisfy a token lookup."""

    @pytest.mark.unit
    def test_suffixed_token_field_is_not_a_lookup_hit(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A file containing only ``SOURCE_TOKEN::<value>`` must not count as existing.

        No MANIFEST -> the filesystem grep runs ``_FIELD_EXACT_RE_TEMPLATE``.
        Pre-fix the un-anchored template matches the ``SOURCE_TOKEN::`` line and
        ``lookup_token_deterministic`` wrongly returns True; post-fix it returns
        False because the KEY is not exactly ``TOKEN`` at line start.
        """
        decisions = tmp_path / ".hestai" / "decisions"
        decisions.mkdir(parents=True)
        (decisions / "x.oct.md").write_text(
            f"===DECISION_RECORD===\nMETA:\n  SOURCE_TOKEN::{_TOKEN}\n===END===\n"
        )

        assert lookup_token_deterministic(tmp_path, _TOKEN) is False

    @pytest.mark.unit
    def test_real_token_field_is_a_lookup_hit(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """A genuine ``TOKEN::"<value>"`` line is still found (no loosening)."""
        decisions = tmp_path / ".hestai" / "decisions"
        decisions.mkdir(parents=True)
        (decisions / "x.oct.md").write_text(
            f'===DECISION_RECORD===\nMETA:\n  TOKEN::"{_TOKEN}"\n===END===\n'
        )

        assert lookup_token_deterministic(tmp_path, _TOKEN) is True
