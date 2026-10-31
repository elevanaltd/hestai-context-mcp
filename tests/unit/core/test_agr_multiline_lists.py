"""RED suite - the OCTAVE reader reads list fields that span several lines (issue #224).

``octave_write`` (the only allowed ``.oct.md`` writer) wraps long lists::

      RELATED_DECISIONS::[
        TOKEN-A,
        TOKEN-B
      ]

The reader used to keep only ``[`` for such a field and silently drop the item lines.
Ruling (HC control room, option 2): ONE grammar for every list field, edge fields
included. A wrapped list is read in full and is represented in ``fields`` exactly as a
compact single-line list is: ``[A,B]``. A list that is never closed is NOT half-read: the
record is unparseable and ``agr_read.parse_failure_detail`` names the line and construct.
Regex and indent only (North Star section 4).
"""

from __future__ import annotations

import pytest

from hestai_context_mcp.core.agent_readable_governance_parser import parse_decision_record
from hestai_context_mcp.tools.governance import agr_read

_HEAD = (
    "===DECISION_RECORD===\n"
    "META:\n"
    "  TYPE::DECISION_RECORD\n"
    '  VERSION::"1.0"\n'
    "  TOKEN::HO-CUBIC-A-20260101\n"
    "  STATUS::RATIFIED\n"
    "  TIER::STRATEGIC\n"
    '  AUTHORED_AT::"2026-01-01T00:00:00Z"\n'
)
_TAIL = (
    '  DECISION::"A binding decision sentence."\n'
    '  BECAUSE::"A one-sentence rationale."\n'
    "===END===\n"
)


def _record(middle: str) -> str:
    return _HEAD + middle + _TAIL


def _fields(middle: str) -> dict[str, str]:
    return parse_decision_record(_record(middle))["fields"]


# --- 1. a wrapped list is read in full ------------------------------------------------


def test_wrapped_list_is_read_in_full() -> None:
    fields = _fields("  RELATED_DECISIONS::[\n    TOKEN-A,\n    TOKEN-B\n  ]\n")
    assert fields["RELATED_DECISIONS"] == "[TOKEN-A,TOKEN-B]"


def test_wrapped_list_equals_the_compact_single_line_form() -> None:
    """I4: consumers see the same string shape whichever way the list was written."""
    wrapped = _fields("  AFFECTS::[\n    submit_governance,\n    lookup_decision\n  ]\n")
    single = _fields("  AFFECTS::[submit_governance,lookup_decision]\n")
    assert wrapped == single


def test_quoted_items_keep_their_inner_commas_and_quotes() -> None:
    fields = _fields(
        "  AFFECTS::[\n"
        "    lookup_decision,\n"
        '    "ADR-RFC-ARCH-004 sections 1.1, 1.6, 1.7",\n'
        '    "hestai-context-mcp#218"\n'
        "  ]\n"
    )
    assert fields["AFFECTS"] == (
        '[lookup_decision,"ADR-RFC-ARCH-004 sections 1.1, 1.6, 1.7","hestai-context-mcp#218"]'
    )


def test_trailing_comma_is_dropped() -> None:
    assert _fields("  AFFECTS::[\n    A,\n    B,\n  ]\n")["AFFECTS"] == "[A,B]"


def test_closing_bracket_alone_on_its_line_and_mixed_indentation() -> None:
    middle = "  AFFECTS::[\n" "\tTOKEN-A,\n" "      TOKEN-B,\n" "TOKEN-C\n" "  ]\n"
    assert _fields(middle)["AFFECTS"] == "[TOKEN-A,TOKEN-B,TOKEN-C]"


@pytest.mark.parametrize(
    ("middle", "key", "expected"),
    [
        # Only ``KEY::[`` alone opens list mode (what octave_write emits). Anything else
        # that opens ``[`` without closing it on its line reads exactly as before #224.
        ("  NOTE::[see below\n", "NOTE", "[see below"),
        ("  AFFECTS::[A,\n    B\n  ]\n", "AFFECTS", "[A,"),
        ("  NOTE::[ see below  \n", "NOTE", "[ see below"),
        ('  NOTE::[say "hi\n', "NOTE", '[say "hi'),
    ],
)
def test_only_a_bare_open_bracket_enters_list_mode(middle: str, key: str, expected: str) -> None:
    parsed = parse_decision_record(_record(middle))
    assert parsed["token"] == "HO-CUBIC-A-20260101"
    assert parsed["fields"][key] == expected
    assert agr_read.parse_failure_detail(_record(middle)) is None


def test_a_bare_open_bracket_with_trailing_whitespace_or_cr_enters_list_mode() -> None:
    text = _record("  AFFECTS::[  \r\n    A,\r\n    B\r\n  ]\r\n").replace("\n  TYPE", "\r\n  TYPE")
    assert parse_decision_record(text)["fields"]["AFFECTS"] == "[A,B]"


def test_a_bracket_inside_a_quoted_item_does_not_close_the_list() -> None:
    fields = _fields('  AFFECTS::[\n    "see [1] and ]",\n    B\n  ]\n')
    assert fields["AFFECTS"] == '["see [1] and ]",B]'


def test_the_field_after_a_wrapped_list_is_still_read() -> None:
    fields = _fields("  AFFECTS::[\n    A,\n    B\n  ]\n  SCOPE::PROD\n")
    assert fields["SCOPE"] == "PROD"
    assert fields["AFFECTS"] == "[A,B]"


def test_core_fields_after_a_wrapped_list_are_read() -> None:
    parsed = parse_decision_record(_record("  AFFECTS::[\n    A\n  ]\n"))
    assert parsed["decision"] == "A binding decision sentence."
    assert parsed["because"] == "A one-sentence rationale."


def test_a_wrapped_edge_field_reads_like_any_other_list() -> None:
    fields = _fields("  AMENDS::[\n    HO-CUBIC-T-20260301,\n    HO-ESCAPES-20261029\n  ]\n")
    assert fields["AMENDS"] == "[HO-CUBIC-T-20260301,HO-ESCAPES-20261029]"


def test_an_empty_wrapped_list_reads_as_the_empty_list() -> None:
    assert _fields("  AFFECTS::[\n  ]\n")["AFFECTS"] == "[]"


def test_nested_brackets_are_kept_inside_their_item() -> None:
    assert _fields("  AFFECTS::[\n    A,\n    [B, C],\n    D\n  ]\n")["AFFECTS"] == "[A,[B, C],D]"


def test_comment_lines_inside_a_wrapped_list_are_ignored() -> None:
    fields = _fields("  AFFECTS::[\n    A,\n    // a note\n    B\n  ]\n")
    assert fields["AFFECTS"] == "[A,B]"


def test_crlf_line_endings_read_the_same() -> None:
    text = _record("  AFFECTS::[\n    A,\n    B\n  ]\n").replace("\n", "\r\n")
    assert parse_decision_record(text)["fields"]["AFFECTS"] == "[A,B]"


def test_first_occurrence_of_a_key_wins_for_wrapped_lists_too() -> None:
    middle = "  AFFECTS::[\n    A\n  ]\n  AFFECTS::[\n    B\n  ]\n"
    assert _fields(middle)["AFFECTS"] == "[A]"


def test_a_second_wrapped_list_is_still_checked_for_termination() -> None:
    text = _record("  AFFECTS::[\n    A\n  ]\n  RELATED::[\n    B,\n")
    assert parse_decision_record(text)["token"] is None


# --- byte parity: records whose lists are single-line read as before ------------------


@pytest.mark.parametrize(
    "line",
    [
        "  AMENDS::[HO-CUBIC-T-20260301, HO-ESCAPES-20261029]",
        "  AMENDS::[HO-CUBIC-T-20260301]",
        "  AFFECTS::[]",
        '  AFFECTS::["a, b",  c ]',
        "  NOTE::see [the issue] for more",
        '  NOTE::"[quoted bracket"',
        "  SUPERSEDED_BY::HO-CUBIC-T-20260301",
        "  FORMAT::[A, B] trailing prose",
    ],
)
def test_single_line_values_are_returned_verbatim(line: str) -> None:
    key, _, raw = line.strip().partition("::")
    parsed = parse_decision_record(_record(line + "\n"))
    expected = raw[1:-1] if raw.startswith('"') and raw.endswith('"') else raw.strip()
    assert parsed["fields"][key] == expected


# --- 3. an unterminated list is rejected loudly, never half-read -----------------------


@pytest.mark.parametrize(
    ("middle", "line"),
    [
        # next field starts before the closing bracket
        ("  AFFECTS::[\n    A,\n    B\n  SCOPE::PROD\n", 9),
        # envelope end before the closing bracket
        ("  AFFECTS::[\n    A,\n    B\n===END===\n", 9),
    ],
)
def test_unterminated_list_makes_the_record_unparseable(middle: str, line: int) -> None:
    text = _HEAD + middle + ("" if "===END===" in middle else _TAIL)
    parsed = parse_decision_record(text)
    assert parsed["token"] is None
    assert parsed["fields"] == {}
    assert not agr_read.record_is_parseable(parsed)
    assert agr_read.parse_failure_detail(text) == {"line": line, "construct": "unterminated_list"}


def test_unterminated_list_at_end_of_file_without_an_end_marker() -> None:
    text = _HEAD + "  AFFECTS::[\n    A,\n"
    assert parse_decision_record(text)["token"] is None
    assert agr_read.parse_failure_detail(text) == {"line": 9, "construct": "unterminated_list"}


def test_list_cut_off_by_a_block_header_is_unterminated() -> None:
    text = _record("  AFFECTS::[\n    A,\nCURRENT:\n")
    assert parse_decision_record(text)["token"] is None
    assert agr_read.parse_failure_detail(text) == {"line": 9, "construct": "unterminated_list"}


def test_a_key_value_line_inside_an_open_quote_is_not_a_new_field() -> None:
    """``::`` inside a quoted item must not be mistaken for the next field."""
    fields = _fields('  AFFECTS::[\n    "KEY::value",\n    B\n  ]\n')
    assert fields["AFFECTS"] == '["KEY::value",B]'


def test_text_after_the_closing_bracket_is_rejected_not_dropped() -> None:
    text = _record("  AFFECTS::[\n    A\n  ] stray words\n")
    assert parse_decision_record(text)["token"] is None
    assert agr_read.parse_failure_detail(text) == {
        "line": 9,
        "construct": "text_after_list",
    }


def test_a_well_formed_record_has_no_octave_parse_failure_detail() -> None:
    assert agr_read.parse_failure_detail(_record("  AFFECTS::[\n    A\n  ]\n")) is None


# --- 4. the key-collision rule (4.1 #14) still holds -----------------------------------

_BLOCKS_WITH_WRAPPED_LIST = (
    "CURRENT:\n"
    '  R1::"Access is granted per project."\n'
    "RULINGS:\n"
    "  R1:\n"
    '    RULE::"Access is granted per project."\n'
    "    AFFECTS::[\n"
    "      LEAKED-A,\n"
    "      LEAKED-B\n"
    "    ]\n"
    "    STATUS::[\n"
    "      SHADOW\n"
    "    ]\n"
)


def test_a_wrapped_list_inside_a_block_does_not_leak_into_meta_fields() -> None:
    parsed = parse_decision_record(_record("  TOPIC::t\n" + _BLOCKS_WITH_WRAPPED_LIST))
    assert "AFFECTS" not in parsed["fields"]
    assert parsed["status"] == "RATIFIED"
    assert parsed["fields"]["TOPIC"] == "t"


def test_an_unclosed_list_inside_a_block_is_not_a_meta_reject() -> None:
    """Block lines are not META: a never-closed list in a block is out of this reader's scope."""
    text = _record("  TOPIC::t\nRULINGS:\n  R1:\n    AFFECTS::[\n      A,\n")
    assert parse_decision_record(text)["token"] == "HO-CUBIC-A-20260101"
    assert agr_read.parse_failure_detail(text) is None


def test_a_meta_wrapped_list_before_a_block_still_reads_and_the_block_is_untouched() -> None:
    text = _record("  AFFECTS::[\n    A,\n    B\n  ]\n  TOPIC::t\n" + _BLOCKS_WITH_WRAPPED_LIST)
    fields = parse_decision_record(text)["fields"]
    assert fields["AFFECTS"] == "[A,B]"


def test_an_inline_comment_after_an_item_does_not_swallow_the_next_item() -> None:
    fields = _fields("  AFFECTS::[\n    X, // a note [with] brackets\n    Y,\n  ]\n")
    assert fields["AFFECTS"] == "[X,Y]"


def test_a_url_item_is_not_mistaken_for_an_inline_comment() -> None:
    fields = _fields("  AFFECTS::[\n    https://example.com/a,\n    Y\n  ]\n")
    assert fields["AFFECTS"] == "[https://example.com/a,Y]"


def test_a_quoted_item_continuing_onto_a_line_that_starts_with_equals_is_not_the_envelope_end() -> (
    None
):
    fields = _fields('  AFFECTS::[\n    "one\n=== two",\n    C\n  ]\n')
    assert fields["AFFECTS"] == '["one === two",C]'
