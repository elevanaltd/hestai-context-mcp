"""Behavioural tests for North Star structured constraint extraction.

Issue #6: Harvest SCOPE_BOUNDARIES and IMMUTABLES from the Product North Star
so the Payload Compiler can extract architectural constraints programmatically
(PROD::I4 STRUCTURED_RETURN_SHAPES) without re-implementing parsing.

The parser MUST be a pure function — no side effects, no I/O beyond DEBUG
logging for malformed content. Tests exercise the REAL repository North Star
summary file in place (not synthetic stubs) per the issue acceptance criterion.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from hestai_context_mcp.core.north_star_parser import (
    NorthStarConstraints,
    extract_constraints,
)

# Repository root: tests/unit/core/test_north_star_parser.py -> parents[3]
REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_NS_SUMMARY = (
    REPO_ROOT / ".hestai" / "north-star" / "000-HESTAI-CONTEXT-MCP-NORTH-STAR-SUMMARY.oct.md"
)


class TestEmptyOrMissingInput:
    """Graceful handling of empty / missing input (no exceptions)."""

    def test_empty_string_returns_empty_structured_result(self):
        """Empty string → empty structured result, no exception."""
        result = extract_constraints("")
        assert result == {"scope_boundaries": {}, "immutables": []}

    def test_none_input_returns_empty_structured_result(self):
        """None input → empty structured result, no exception."""
        # A None is an explicit contract option: clock_in may pass None when
        # no North Star file exists.
        result = extract_constraints(None)
        assert result == {"scope_boundaries": {}, "immutables": []}

    def test_whitespace_only_returns_empty_structured_result(self):
        """Whitespace-only input → empty structured result."""
        result = extract_constraints("   \n\n\t  \n")
        assert result == {"scope_boundaries": {}, "immutables": []}

    def test_document_without_sections_returns_empty_structured_result(self):
        """Document with no SCOPE_BOUNDARIES or IMMUTABLES → empty result."""
        result = extract_constraints("===NORTH_STAR===\nPURPOSE::foo\nROLE::bar\n===END===\n")
        assert result == {"scope_boundaries": {}, "immutables": []}


class TestMalformedContent:
    """Best-effort parse of malformed content with DEBUG logging."""

    def test_malformed_scope_boundaries_returns_empty_scope(self, caplog):
        """Unterminated/malformed SCOPE_BOUNDARIES → empty scope, no exception."""
        # Truncated mid-list — parser must not raise.
        malformed = '§4::SCOPE_BOUNDARIES\nIS::[\n  "incomplete'
        with caplog.at_level(logging.DEBUG, logger="hestai_context_mcp.core.north_star_parser"):
            result = extract_constraints(malformed)
        assert isinstance(result, dict)
        assert "scope_boundaries" in result
        assert "immutables" in result
        # Either partial or empty, but MUST be a dict/list shape, never an exception.
        assert isinstance(result["scope_boundaries"], dict)
        assert isinstance(result["immutables"], list)

    def test_malformed_does_not_raise(self):
        """Arbitrary garbage must not raise."""
        garbage = "\x00\x01random bytes [[{{ I1:: SCOPE_BOUNDARIES incomplete"
        # Must complete without raising.
        result = extract_constraints(garbage)
        assert isinstance(result, dict)
        assert set(result.keys()) == {"scope_boundaries", "immutables"}


class TestRealNorthStarSummary:
    """Behavioural tests against the REAL repository North Star summary file.

    Issue #6 acceptance: synthetic stubs do NOT satisfy this gate.

    Maintenance note: these tests are intentionally coupled to the live
    repo North Star summary (``.hestai/north-star/…-SUMMARY.oct.md``). If
    the NS format evolves (new immutables added, scope items changed), the
    assertions below will need updating in the same PR that updates the NS
    — that coupling is the point. A failure here means "the NS changed
    without a corresponding parser-gate update", which is exactly the
    signal the Payload Compiler depends on.
    """

    @pytest.fixture
    def real_ns_content(self) -> str:
        assert REAL_NS_SUMMARY.exists(), (
            f"Real North Star summary fixture missing: {REAL_NS_SUMMARY}. "
            "This test MUST exercise the live repo file in-place."
        )
        return REAL_NS_SUMMARY.read_text()

    def test_returns_typeddict_shape(self, real_ns_content: str):
        """Return value conforms to NorthStarConstraints TypedDict shape."""
        result = extract_constraints(real_ns_content)
        assert isinstance(result, dict)
        assert set(result.keys()) == {"scope_boundaries", "immutables"}
        assert isinstance(result["scope_boundaries"], dict)
        assert isinstance(result["immutables"], list)

    def test_scope_boundaries_has_is_and_is_not(self, real_ns_content: str):
        """§4 SCOPE_BOUNDARIES parses into 'is' and 'is_not' keys."""
        result = extract_constraints(real_ns_content)
        scope = result["scope_boundaries"]
        assert "is" in scope, f"Expected 'is' key, got: {list(scope.keys())}"
        assert "is_not" in scope, f"Expected 'is_not' key, got: {list(scope.keys())}"
        assert isinstance(scope["is"], list)
        assert isinstance(scope["is_not"], list)
        assert len(scope["is"]) >= 1
        assert len(scope["is_not"]) >= 1

    def test_scope_is_contains_expected_items(self, real_ns_content: str):
        """Real §4 IS list contains known substrings from the repo NS."""
        result = extract_constraints(real_ns_content)
        is_items = result["scope_boundaries"]["is"]
        joined = "\n".join(is_items)
        # From .hestai/north-star/000-HESTAI-CONTEXT-MCP-NORTH-STAR-SUMMARY.oct.md §4
        assert "session lifecycle management" in joined
        assert "context synthesis engine" in joined

    def test_scope_is_not_contains_expected_items(self, real_ns_content: str):
        """Real §4 IS_NOT list contains known substrings."""
        result = extract_constraints(real_ns_content)
        is_not_items = result["scope_boundaries"]["is_not"]
        joined = "\n".join(is_not_items)
        assert "agent identity or governance (Vault owns)" in joined
        assert "UI or dispatch system (Workbench owns)" in joined

    def test_immutables_extracted_in_order(self, real_ns_content: str):
        """Real §2 IMMUTABLES yields I1..I6 entries in declared order."""
        result = extract_constraints(real_ns_content)
        immutables = result["immutables"]
        # Real NS declares I1..I6 (six immutables)
        assert len(immutables) == 6, f"Expected 6 immutables, got {len(immutables)}: {immutables}"
        # Order preserved and each entry starts with its I# token
        for i, expected_prefix in enumerate(["I1::", "I2::", "I3::", "I4::", "I5::", "I6::"]):
            assert immutables[i].startswith(expected_prefix), (
                f"Immutable index {i} does not start with {expected_prefix!r}: "
                f"{immutables[i]!r}"
            )

    def test_immutables_preserve_declared_content(self, real_ns_content: str):
        """Known immutable bodies from real NS are present verbatim."""
        result = extract_constraints(real_ns_content)
        immutables = result["immutables"]
        joined = "\n".join(immutables)
        # Anchored substrings from NS summary §2
        assert "SESSION_LIFECYCLE_INTEGRITY" in joined
        assert "PROVIDER_AGNOSTIC_CONTEXT" in joined
        assert "STRUCTURED_RETURN_SHAPES" in joined
        assert "LEGACY_INDEPENDENCE" in joined


class TestPurity:
    """PROD::I5 — parser is a pure function with no side effects."""

    def test_does_not_mutate_input(self):
        """Parser does not mutate its string argument (strings are immutable
        in Python; we also check that repeated calls yield identical results).
        """
        content = REAL_NS_SUMMARY.read_text() if REAL_NS_SUMMARY.exists() else ""
        first = extract_constraints(content)
        second = extract_constraints(content)
        assert first == second

    def test_no_filesystem_access(self, tmp_path, monkeypatch):
        """Parser is text-in → dict-out; it must not touch the filesystem.

        We verify indirectly: calling the parser with non-existent 'paths'
        embedded in the text does not create files and does not raise.
        """
        text = (
            "§4::SCOPE_BOUNDARIES\n"
            'IS::[\n  "/nonexistent/path/should/not/be/opened"\n]\n'
            'IS_NOT::[\n  "other"\n]\n'
        )
        before = set(tmp_path.iterdir())
        _ = extract_constraints(text)
        after = set(tmp_path.iterdir())
        assert before == after


class TestTypedDictExport:
    """PROD::I4 — schema is exported as a TypedDict for static consumers."""

    def test_typeddict_schema_is_resolvable_by_typing_api(self):
        """The TypedDict exposes a schema via ``typing.get_type_hints``.

        This is the external contract static type checkers (mypy, pyright)
        use to validate producers and consumers — it does NOT depend on the
        TypedDict implementation's ``__annotations__`` attribute.
        """
        from typing import get_type_hints

        from hestai_context_mcp.core.north_star_parser import NorthStarConstraints

        hints = get_type_hints(NorthStarConstraints)
        assert "scope_boundaries" in hints
        assert "immutables" in hints

    def test_result_assigns_to_typeddict_variable(self):
        """Return value is assignable to the TypedDict type at runtime."""
        result: NorthStarConstraints = extract_constraints("")
        assert result == {"scope_boundaries": {}, "immutables": []}


class TestUnicodeAndBoundaryShapes:
    """Encoding boundaries and partial-section shape consistency (PROD::I4)."""

    def test_unicode_content_in_scope_boundaries(self):
        """Non-ASCII content in IS/IS_NOT items is preserved verbatim."""
        text = (
            "§4::SCOPE_BOUNDARIES\n"
            "IS::[\n"
            '  "日本語 context synthesis",\n'
            '  "émoji 🚀 handling"\n'
            "]\n"
            "IS_NOT::[\n"
            '  "漢字 governance"\n'
            "]\n"
        )
        result = extract_constraints(text)
        is_items = result["scope_boundaries"]["is"]
        is_not_items = result["scope_boundaries"]["is_not"]
        joined_is = "\n".join(is_items)
        assert "日本語 context synthesis" in joined_is
        assert "émoji 🚀 handling" in joined_is
        assert any("漢字 governance" in item for item in is_not_items)

    def test_unicode_content_in_immutables(self):
        """Non-ASCII body content in I# lines is preserved verbatim."""
        text = "§2::IMMUTABLES\n" 'I1::"CTX_日本<PRINCIPLE::a,WHY::b,STATUS::IMPLEMENTED>"\n'
        result = extract_constraints(text)
        immutables = result["immutables"]
        assert len(immutables) == 1
        assert "CTX_日本" in immutables[0]

    def test_scope_with_only_is_present(self):
        """PROD::I4 shape consistency: IS present, IS_NOT absent → both keys
        present with IS_NOT=[]."""
        text = "§4::SCOPE_BOUNDARIES\n" "IS::[\n" '  "only one"\n' "]\n"
        result = extract_constraints(text)
        scope = result["scope_boundaries"]
        assert "is" in scope
        assert "is_not" in scope
        assert scope["is_not"] == []
        assert any("only one" in item for item in scope["is"])

    def test_scope_with_only_is_not_present(self):
        """IS_NOT present, IS absent → both keys present with IS=[]."""
        text = "§4::SCOPE_BOUNDARIES\n" "IS_NOT::[\n" '  "excluded item"\n' "]\n"
        result = extract_constraints(text)
        scope = result["scope_boundaries"]
        assert "is" in scope
        assert "is_not" in scope
        assert scope["is"] == []
        assert any("excluded item" in item for item in scope["is_not"])


class TestSectionAnchoring:
    """PR #10 cubic P2 regression guard: section tokens must be matched as
    OCTAVE headers (``TOKEN::``), never as bare-substring occurrences inside
    free-text bullet bodies. Otherwise a scope-boundary description such as
    ``"cross-reference IMMUTABLES section"`` would be mistaken for a section
    header and corrupt the slice (silently truncating SCOPE_BOUNDARIES at
    the spurious match, and shifting IMMUTABLES to start mid-bullet).
    """

    @pytest.mark.parametrize(
        "free_text_token",
        [
            "IMMUTABLES",
            "SCOPE_BOUNDARIES",
            "ASSUMPTIONS",
            "CONSTRAINED_VARIABLES",
            "GATES",
            "ESCALATION",
            "TRIGGERS",
            "PROTECTION",
            "IDENTITY",
        ],
    )
    def test_free_text_section_token_does_not_shift_section_slice(self, free_text_token: str):
        """A bare section-token word inside a bullet body must not be treated
        as a header. SCOPE_BOUNDARIES must continue to capture both bullets
        and IMMUTABLES must still parse to a single I1 line, regardless of
        which token appears as free text inside the IS list.
        """
        text = (
            "§4::SCOPE_BOUNDARIES\n"
            "IS::[\n"
            f'  "documentation must cross-reference the {free_text_token} section",\n'
            '  "second legitimate boundary item"\n'
            "]\n"
            "IS_NOT::[\n"
            '  "out of scope"\n'
            "]\n"
            "§2::IMMUTABLES\n"
            'I1::"REAL<PRINCIPLE::p,WHY::w,STATUS::IMPLEMENTED>"\n'
            "===END===\n"
        )
        result = extract_constraints(text)

        # SCOPE_BOUNDARIES bullets are intact (not truncated at the spurious
        # token occurrence, and not corrupted by re-anchoring on it).
        is_items = result["scope_boundaries"]["is"]
        assert len(is_items) == 2, (
            f"Expected both IS bullets to parse; free-text {free_text_token!r} "
            f"shifted the slice. Got: {is_items!r}"
        )
        assert any("second legitimate boundary item" in item for item in is_items)
        assert any("out of scope" in item for item in result["scope_boundaries"]["is_not"])

        # IMMUTABLES still resolves to exactly one I1 declaration (not pulled
        # forward by a spurious in-body match).
        immutables = result["immutables"]
        assert (
            len(immutables) == 1
        ), f"Expected exactly one immutable; got {len(immutables)}: {immutables!r}"
        assert immutables[0].startswith('I1::"REAL')

    @pytest.mark.parametrize(
        "adversarial_token",
        ["IMMUTABLES", "SCOPE_BOUNDARIES", "ASSUMPTIONS", "GATES"],
    )
    def test_inline_double_colon_token_does_not_anchor(self, adversarial_token: str):
        """CRS delta P1: an inline ``::TOKEN`` reference inside a quoted body
        (e.g. ``"depends on ::IMMUTABLES section"``) must NOT match as a
        section header — the OCTAVE header form requires the TOKEN to occupy
        its own line (``\\n§N::TOKEN`` or ``\\nTOKEN::``).
        """
        text = (
            "§4::SCOPE_BOUNDARIES\n"
            "IS::[\n"
            f'  "downstream code depends on ::{adversarial_token} parsing",\n'
            '  "second legitimate boundary item"\n'
            "]\n"
            "§2::IMMUTABLES\n"
            'I1::"REAL<PRINCIPLE::p,WHY::w,STATUS::IMPLEMENTED>"\n'
        )
        result = extract_constraints(text)
        # Both bullets present — slice was not truncated by the inline ::TOKEN.
        is_items = result["scope_boundaries"]["is"]
        assert (
            len(is_items) == 2
        ), f"Inline ::{adversarial_token} corrupted slice. Got: {is_items!r}"
        assert any("second legitimate boundary item" in item for item in is_items)
        # IMMUTABLES still parses to exactly the one declaration.
        assert len(result["immutables"]) == 1
        assert result["immutables"][0].startswith('I1::"REAL')

    @pytest.mark.parametrize(
        "sentence_token",
        ["IMMUTABLES", "SCOPE_BOUNDARIES", "ASSUMPTIONS", "GATES"],
    )
    def test_line_start_token_without_double_colon_does_not_anchor(self, sentence_token: str):
        """CRS delta P2: a sentence opener at line start whose first word
        happens to be a section TOKEN (``\\nIMMUTABLES are essential ...``)
        must NOT match as a header. The OCTAVE header form requires the
        ``::`` separator immediately after the TOKEN.
        """
        text = (
            "§4::SCOPE_BOUNDARIES\n"
            "IS::[\n"
            '  "first item",\n'
            '  "second item"\n'
            "]\n"
            f"\n{sentence_token} are essential to this design but not a section.\n"
            "\n"
            "§2::IMMUTABLES\n"
            'I1::"REAL<PRINCIPLE::p,WHY::w,STATUS::IMPLEMENTED>"\n'
        )
        result = extract_constraints(text)
        is_items = result["scope_boundaries"]["is"]
        assert (
            len(is_items) == 2
        ), f"Line-start '{sentence_token} are ...' corrupted slice. Got: {is_items!r}"
        assert len(result["immutables"]) == 1

    def test_crlf_line_endings_do_not_falsely_anchor(self):
        """CRS delta P3: CRLF (``\\r\\n``) inputs must not produce false
        anchors via the trailing ``\\n`` of the CRLF pair followed by an
        otherwise-bare TOKEN. The header form still requires ``::`` after.
        """
        text = (
            "§4::SCOPE_BOUNDARIES\r\n"
            "IS::[\r\n"
            '  "first item",\r\n'
            '  "second item"\r\n'
            "]\r\n"
            "\r\n"
            "IMMUTABLES are referenced but not headed here.\r\n"
            "\r\n"
            "§2::IMMUTABLES\r\n"
            'I1::"REAL<PRINCIPLE::p,WHY::w,STATUS::IMPLEMENTED>"\r\n'
        )
        result = extract_constraints(text)
        is_items = result["scope_boundaries"]["is"]
        assert len(is_items) == 2, f"CRLF false anchor; got: {is_items!r}"
        assert len(result["immutables"]) == 1

    def test_bare_line_start_token_with_double_colon_does_anchor(self):
        """Positive sanity: ``\\nTOKEN::`` (no ``§N`` prefix) IS still a
        valid OCTAVE header and MUST anchor — the fix must not over-tighten.
        """
        text = (
            "IMMUTABLES::\n"
            'I1::"FIRST<PRINCIPLE::a,WHY::b,STATUS::IMPLEMENTED>"\n'
            'I2::"SECOND<PRINCIPLE::c,WHY::d,STATUS::IMPLEMENTED>"\n'
            "SCOPE_BOUNDARIES::\n"
            'IS::["only one"]\n'
        )
        result = extract_constraints(text)
        assert len(result["immutables"]) == 2
        assert any("only one" in item for item in result["scope_boundaries"]["is"])

    def test_real_repo_north_star_still_parses_after_anchoring(self):
        """Belt-and-braces: anchoring fix must not regress the live repo NS.

        Equivalent to the TestRealNorthStarSummary suite but co-located with
        the cubic regression tests so a single targeted run covers both.
        """
        if not REAL_NS_SUMMARY.exists():
            pytest.skip(f"Live North Star summary fixture missing: {REAL_NS_SUMMARY}")
        result = extract_constraints(REAL_NS_SUMMARY.read_text())
        # Same anchors as TestRealNorthStarSummary — duplicated intentionally
        # so this regression class is self-contained.
        assert len(result["immutables"]) == 6
        assert "is" in result["scope_boundaries"]
        assert "is_not" in result["scope_boundaries"]
        assert any(
            "session lifecycle management" in item for item in result["scope_boundaries"]["is"]
        )
