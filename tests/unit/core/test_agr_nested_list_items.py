"""RED suite - nested ``KEY::`` items inside a wrapped list (ADR-004 v1.9, part of #196).

``octave_write`` writes a nested list as a wrapped list whose ITEMS are themselves
``KEY::[...]`` or ``KEY::value`` lines. The #229 reader treated any ``KEY::`` line inside an
open list as a list break (``unterminated_list``). Rule (HC-approved, option (i)): inside an
open wrapped list, a non-blank line indented DEEPER than the opener line is a list ITEM; only
a non-blank line at the opener's indent or SHALLOWER can break the list. Bracket depth and
quote state are tracked as before, and a closing ``]`` at the opener's indent still closes.
"""

from __future__ import annotations

import pytest

from hestai_context_mcp.core.agent_readable_governance_parser import (
    diagnose_octave_record,
    list_items,
    parse_decision_record,
)

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
_OPENS_AT = 9  # the line number of the first line after _HEAD


def _record(middle: str) -> str:
    return _HEAD + middle + _TAIL


def _fields(middle: str) -> dict[str, str]:
    return parse_decision_record(_record(middle))["fields"]


_NESTED_LIST_ITEM = (
    "  SCOPE_MATRIX::[\n"
    "    [\n"
    "      SIMPLE::[\n"
    '        "<100_users",\n'
    "        single_component\n"
    "      ]\n"
    "    ],\n"
    "    COMPLEX\n"
    "  ]\n"
)


def test_a_wrapped_list_with_a_nested_key_list_item_reads_in_full() -> None:
    fields = _fields(_NESTED_LIST_ITEM + "  SCOPE::PROD\n")
    items = list_items(fields["SCOPE_MATRIX"])
    assert len(items) == 2
    assert "SIMPLE::[" in items[0] and "single_component" in items[0] and '"<100_users"' in items[0]
    assert items[1] == "COMPLEX"
    assert fields["SCOPE"] == "PROD"


def test_a_nested_item_key_does_not_leak_into_the_record_fields() -> None:
    fields = _fields(_NESTED_LIST_ITEM)
    assert "SIMPLE" not in fields


def test_a_wrapped_list_with_key_value_items_reads_in_full() -> None:
    middle = '  NOTES::[\n    ALPHA::one,\n    BETA::"two, three"\n  ]\n'
    fields = _fields(middle)
    assert fields["NOTES"] == '[ALPHA::one,BETA::"two, three"]'
    assert "ALPHA" not in fields and "BETA" not in fields


def test_a_nested_item_that_reuses_a_reserved_core_key_does_not_override_the_record() -> None:
    parsed = parse_decision_record(_record('  NOTES::[\n    STATUS::"VOID",\n    B\n  ]\n'))
    assert parsed["status"] == "RATIFIED"
    assert parsed["fields"]["NOTES"] == '[STATUS::"VOID",B]'


def test_a_closing_bracket_at_the_openers_indent_closes_the_list() -> None:
    fields = _fields("  AFFECTS::[\n      A::x,\n      B\n  ]\n  SCOPE::PROD\n")
    assert fields["AFFECTS"] == "[A::x,B]"
    assert fields["SCOPE"] == "PROD"


def test_a_column_zero_opener_and_closing_bracket_close_the_list() -> None:
    text = _record('TOP::[\n  [\n    INNER::"u"\n  ]\n]\n  SCOPE::PROD\n')
    assert parse_decision_record(text)["fields"]["SCOPE"] == "PROD"
    assert diagnose_octave_record(text) is None


# --- a real unterminated list still fails loudly --------------------------------------------


@pytest.mark.parametrize(
    "middle",
    [
        # a SIBLING at the opener's indent breaks the list
        "  AFFECTS::[\n    A,\n    B\n  SCOPE::PROD\n",
        # ... even after nested key items
        "  AFFECTS::[\n    A::x,\n    B::[\n      C\n    ]\n  SCOPE::PROD\n",
        # a field SHALLOWER than the opener breaks it
        "    AFFECTS::[\n      A,\n  SCOPE::PROD\n",
        # a column-zero block header breaks it
        "  AFFECTS::[\n    A::x,\nCURRENT:\n",
    ],
)
def test_an_unterminated_list_followed_by_a_sibling_still_fails_loudly(middle: str) -> None:
    text = _record(middle)
    assert parse_decision_record(text)["token"] is None
    assert diagnose_octave_record(text) == {"line": _OPENS_AT, "construct": "unterminated_list"}


def test_an_unclosed_nested_bracket_is_unterminated_at_the_envelope_end() -> None:
    text = _HEAD + "  AFFECTS::[\n    A::[\n      B\n    ]\n===END===\n"
    assert diagnose_octave_record(text) == {"line": _OPENS_AT, "construct": "unterminated_list"}
