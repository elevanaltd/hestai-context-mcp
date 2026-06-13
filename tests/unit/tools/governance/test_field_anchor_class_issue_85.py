"""Class-closer regression tests for issue #85 — the FULL *FIELD:: substring-leak class.

CE re-gate on PR #91 found the audit incomplete: two MORE same-class siblings live
in ``type_checker.py``'s OWN regexes (distinct from the already-anchored manifest
copies):

  * ``_TOKEN_RE = (?m)TOKEN::(?:"..."|...)\\s*$`` — end-anchored but NO ``^``
    line-start, so ``DOCUMENT_TOKEN::<tok>`` leaks via ``_extract_token``.
  * ``_SUPERSEDED_BY_RE = SUPERSEDED_BY::"([^"]+)"`` — NO anchors at all, so
    ``PARENT_SUPERSEDED_BY::"<tok>"`` leaks straight into the supersedure-target
    path (the exact corruption class #85 exists to kill).

This module:
  1. Pins the two confirmed leak vectors (+ shadow + downstream e2e) — RED.
  2. Adds a TABLE-DRIVEN CLASS-GUARD meta-test enumerating EVERY ``FIELD::value``
     META extractor in type_checker.py AND lexer.py, asserting each is
     line-anchored (rejects a ``PREFIX<FIELD>::value`` decoy, accepts the real
     ``^\\s*<FIELD>::value``). This prevents any future sibling from regressing
     the class. The already-anchored family members (type_checker _TYPE_RE /
     _REPO_ID_RE / _ID_QUOTED_RE, lexer field template, manifest _TOKEN_RE /
     _TOKEN_BARE_RE / _ID_RE / _ID_BARE_RE) are included so they are proven to
     STAY anchored; _SENTINEL_RE (the ===NAME=== doc-start form) is asserted to
     stay \\A-anchored separately.

TDD RED: the two unanchored siblings fail the meta-test and the targeted leak
tests; everything else passes. GREEN adds the two ``^\\s*`` anchors.

North Star §4 regex-only; PROD I4 structured returns; tighten-only.
"""

from pathlib import Path

import pytest

from hestai_context_mcp.tools.governance import lexer as lexer_mod
from hestai_context_mcp.tools.governance import manifest as manifest_mod
from hestai_context_mcp.tools.governance import type_checker as tc

# A token whose shape is irrelevant to the anchoring (these extractors do not
# validate token shape — that is _TOKEN_FORMAT_RE's job downstream).
_TOK = "HO-FOO-BAR-20260101"


# ---------------------------------------------------------------------------
# Targeted leak vectors — _extract_token
# ---------------------------------------------------------------------------


class TestExtractTokenLineAnchored:
    """``_extract_token`` must reject a ``*TOKEN::``-suffixed key."""

    @pytest.mark.unit
    def test_document_token_does_not_leak(self) -> None:
        """``DOCUMENT_TOKEN::<tok>`` (no real TOKEN) must extract None."""
        content = f"===DECISION_RECORD===\nMETA:\n  DOCUMENT_TOKEN::{_TOK}\n===END===\n"
        assert tc._extract_token(content) is None

    @pytest.mark.unit
    def test_suffixed_token_does_not_shadow_real_token(self) -> None:
        """A ``DOCUMENT_TOKEN::`` line ABOVE the real TOKEN must not win (.search first-match)."""
        content = (
            "===DECISION_RECORD===\n"
            "META:\n"
            "  DOCUMENT_TOKEN::HO-EVIL-XX-20260101\n"
            '  TOKEN::"HO-REAL-YY-20260101"\n'
            "===END===\n"
        )
        assert tc._extract_token(content) == "HO-REAL-YY-20260101"

    @pytest.mark.unit
    def test_real_quoted_token_still_extracts(self) -> None:
        """A real indented quoted ``TOKEN::"..."`` line still extracts (no loosening)."""
        assert tc._extract_token('  TOKEN::"HO-REAL-YY-20260101"\n') == "HO-REAL-YY-20260101"

    @pytest.mark.unit
    def test_real_bare_token_still_extracts(self) -> None:
        """The bare canonical ``TOKEN::<value>`` form still extracts."""
        assert tc._extract_token("  TOKEN::HO-REAL-YY-20260101\n") == "HO-REAL-YY-20260101"


# ---------------------------------------------------------------------------
# Targeted leak vectors — _extract_superseded_by
# ---------------------------------------------------------------------------


class TestExtractSupersededByLineAnchored:
    """``_extract_superseded_by`` must reject a ``*SUPERSEDED_BY::``-suffixed key."""

    @pytest.mark.unit
    def test_parent_superseded_by_does_not_leak(self) -> None:
        """``PARENT_SUPERSEDED_BY::"X"`` (no real field) must extract None."""
        content = (
            '===DECISION_RECORD===\nMETA:\n  PARENT_SUPERSEDED_BY::"HO-X-AB-20260101"\n===END===\n'
        )
        assert tc._extract_superseded_by(content) is None

    @pytest.mark.unit
    def test_suffixed_superseded_by_does_not_shadow_real(self) -> None:
        """A ``PARENT_SUPERSEDED_BY::`` line ABOVE the real one must not win."""
        content = (
            "===DECISION_RECORD===\n"
            "META:\n"
            '  PARENT_SUPERSEDED_BY::"HO-EVIL-AB-20260101"\n'
            '  SUPERSEDED_BY::"HO-REAL-CD-20260101"\n'
            "===END===\n"
        )
        assert tc._extract_superseded_by(content) == "HO-REAL-CD-20260101"

    @pytest.mark.unit
    def test_real_superseded_by_still_extracts(self) -> None:
        """A real indented ``SUPERSEDED_BY::"X"`` line still extracts (no loosening)."""
        assert (
            tc._extract_superseded_by('  SUPERSEDED_BY::"HO-REAL-CD-20260101"\n')
            == "HO-REAL-CD-20260101"
        )


# ---------------------------------------------------------------------------
# End-to-end: the leaks must not corrupt validate_octave_content / supersedure
# ---------------------------------------------------------------------------


class TestLeakDownstreamEffectPinned:
    """The leaks' downstream Gate-A effects are pinned (mirrors issue-85 e2e style)."""

    @pytest.mark.unit
    def test_document_token_only_record_reports_missing_token(self, tmp_path: Path) -> None:
        """A DECISION_RECORD whose only token-like line is ``DOCUMENT_TOKEN::`` must
        be rejected for a MISSING TOKEN — not silently accepted with the leaked value.
        """
        content = (
            "===DECISION_RECORD===\n"
            "META:\n"
            "  TYPE::DECISION_RECORD\n"
            f"  DOCUMENT_TOKEN::{_TOK}\n"
            "===END===\n"
        )
        result = tc.validate_octave_content(tmp_path, content)

        assert result.valid is False
        assert any("requires a TOKEN field" in e for e in result.errors)
        assert result.token is None

    @pytest.mark.unit
    def test_suffixed_superseded_by_does_not_trigger_supersedure_path(self, tmp_path: Path) -> None:
        """A ``PARENT_SUPERSEDED_BY::`` key must NOT drive the supersedure-target check.

        If the leak fired, ``_extract_superseded_by`` would return a value and
        validation would error that the (non-existent) SUPERSEDED_BY target is
        missing from the store. Anchored, the field is invisible, so a valid
        record with NO real SUPERSEDED_BY passes without any supersedure error.
        """
        content = (
            "===DECISION_RECORD===\n"
            "META:\n"
            "  TYPE::DECISION_RECORD\n"
            '  TOKEN::"HO-CONTEXT-MCP-REAL-20260101"\n'
            '  PARENT_SUPERSEDED_BY::"HO-GHOST-ZZ-20260101"\n'
            "===END===\n"
        )
        result = tc.validate_octave_content(tmp_path, content)

        assert not any("SUPERSEDED_BY target" in e for e in result.errors)


# ---------------------------------------------------------------------------
# CLASS-GUARD META-TEST — the real class-closer
# ---------------------------------------------------------------------------

# Family of ``FIELD::value`` META-line extractors across type_checker + lexer +
# manifest. Each entry: (id, compiled_or_template, field_key, sample_value,
# quoted). ``quoted`` controls whether the value is wrapped in double quotes on
# the rendered line (some extractors are quoted-only). The lexer template is a
# format string keyed on ``{token}`` and is handled specially below.
#
# Every member MUST be line-anchored: it must REJECT a ``PREFIX<FIELD>::value``
# decoy line and ACCEPT the genuine ``  <FIELD>::value`` (indented) line.
_FIELD_EXTRACTOR_FAMILY = [
    # type_checker.py
    ("tc._TYPE_RE", tc._TYPE_RE, "TYPE", "DECISION_RECORD", False),
    ("tc._TOKEN_RE", tc._TOKEN_RE, "TOKEN", _TOK, True),
    ("tc._REPO_ID_RE", tc._REPO_ID_RE, "REPO_ID", "hestai-context-mcp", False),
    ("tc._SUPERSEDED_BY_RE", tc._SUPERSEDED_BY_RE, "SUPERSEDED_BY", _TOK, True),
    ("tc._ID_QUOTED_RE", tc._ID_QUOTED_RE, "ID", "GATE_A_TEST_CONCEPT", True),
    # manifest.py (already anchored — must STAY anchored)
    ("manifest._TOKEN_RE", manifest_mod._TOKEN_RE, "TOKEN", _TOK, True),
    ("manifest._TOKEN_BARE_RE", manifest_mod._TOKEN_BARE_RE, "TOKEN", _TOK, False),
    ("manifest._ID_RE", manifest_mod._ID_RE, "ID", "GATE_A_TEST_CONCEPT", True),
    ("manifest._ID_BARE_RE", manifest_mod._ID_BARE_RE, "ID", "GATE_A_TEST_CONCEPT", False),
]

# Genuine META body lines are rendered with a two-space indent. This is exact
# for the ID-family extractors anchored to ``^  `` and admitted by the ``^\s*``
# members too, so the accept-case is fair for every family member.


def _render_field_line(field_key: str, value: str, quoted: bool, indent: str) -> str:
    rendered_value = f'"{value}"' if quoted else value
    return f"{indent}{field_key}::{rendered_value}\n"


class TestFieldAnchorClassGuard:
    """Every ``FIELD::value`` META extractor in the family must be line-anchored.

    This is the class-closer: it fails for ANY family member that lacks a
    line-start anchor, so a future edit that drops ``^\\s*`` from a sibling is
    caught here rather than shipping a fresh substring leak.
    """

    @pytest.mark.parametrize(
        "extractor_id, compiled, field_key, value, quoted",
        [pytest.param(*row, id=row[0]) for row in _FIELD_EXTRACTOR_FAMILY],
    )
    @pytest.mark.unit
    def test_extractor_rejects_prefixed_decoy(
        self,
        extractor_id: str,
        compiled: "object",
        field_key: str,
        value: str,
        quoted: bool,
    ) -> None:
        """A ``PREFIX<FIELD>::value`` decoy line must NOT match (no substring leak)."""
        decoy = _render_field_line(field_key, value, quoted, indent="  PREFIX_")
        # Decoy renders as e.g. ``  PREFIX_TOKEN::"<tok>"`` — a *FIELD:: suffixed key.
        assert compiled.search(decoy) is None, f"{extractor_id} leaked on decoy: {decoy!r}"  # type: ignore[attr-defined]

    @pytest.mark.parametrize(
        "extractor_id, compiled, field_key, value, quoted",
        [pytest.param(*row, id=row[0]) for row in _FIELD_EXTRACTOR_FAMILY],
    )
    @pytest.mark.unit
    def test_extractor_accepts_real_line(
        self,
        extractor_id: str,
        compiled: "object",
        field_key: str,
        value: str,
        quoted: bool,
    ) -> None:
        """The genuine indented ``<FIELD>::value`` line must still match (no loosening)."""
        indent = "  "
        real = _render_field_line(field_key, value, quoted, indent=indent)
        assert compiled.search(real) is not None, f"{extractor_id} rejected real line: {real!r}"  # type: ignore[attr-defined]

    @pytest.mark.unit
    def test_lexer_field_template_is_line_anchored(self) -> None:
        """The lexer field-exact template (keyed on {token}) rejects ``*TOKEN::``/``*ID::``."""
        import re

        pat = re.compile(lexer_mod._FIELD_EXACT_RE_TEMPLATE.format(token=re.escape(_TOK)))
        # Decoys: suffixed keys must NOT match.
        assert pat.search(f"  DOCUMENT_TOKEN::{_TOK}\n") is None
        assert pat.search(f"  PARENT_ID::{_TOK}\n") is None
        # Real lines: must match.
        assert pat.search(f'  TOKEN::"{_TOK}"\n') is not None
        assert pat.search(f"  ID::{_TOK}\n") is not None

    @pytest.mark.unit
    def test_sentinel_re_stays_doc_start_anchored(self) -> None:
        """``_SENTINEL_RE`` is the ===NAME=== doc-start form — must stay \\A-anchored.

        It is in the META-extractor family conceptually but not a ``FIELD::value``
        line; this pins it so the doc-start anchor is not regressed either.
        """
        # Genuine first-line sentinel matches.
        assert tc._SENTINEL_RE.match("===DECISION_RECORD===\n") is not None
        # A sentinel NOT at document start must not match (\\A anchor).
        assert tc._SENTINEL_RE.match("garbage\n===DECISION_RECORD===\n") is None
