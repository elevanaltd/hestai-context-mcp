"""RED suite - Gate A and the reader agree on nested ``KEY::`` items in wrapped lists (#239).

ADR-004 v1.9: a line indented deeper than a wrapped list's opener is list text. The reader
(``read_octave_fields``) already treats it so; Gate A must use the SAME rule for every META
extraction (field map, TYPE/TOKEN/SUPERSEDED_BY/ISSUE_REF/... regexes) and for the #14/#15
reserved-key scans, so a nested ``STATUS::VOID`` item can never shadow the real META.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hestai_context_mcp.core.agent_readable_governance_parser import parse_decision_record
from hestai_context_mcp.tools.governance.type_checker import (
    _extract_meta_fields,
    _strip_block_lines,
    validate_octave_content,
)

pytestmark = pytest.mark.unit

_HEAD = (
    "===DECISION_RECORD===\n"
    "META:\n"
    "  TYPE::DECISION_RECORD\n"
    '  VERSION::"1.0"\n'
    "  TOKEN::HO-CUBIC-A-20260101\n"
)
_REAL = (
    "  STATUS::RATIFIED\n"
    "  TIER::STRATEGIC\n"
    '  AUTHORED_AT::"2026-01-01T00:00:00Z"\n'
    '  RATIFIED_BY::"human:operator"\n'
    '  DECISION::"A binding decision sentence."\n'
    '  BECAUSE::"A one-sentence rationale."\n'
)


def _nested(*items: str) -> str:
    body = "".join(f"    {item},\n" for item in items)
    return f"  AFFECTS::[\n{body}    last\n  ]\n"


def _record(list_text: str) -> str:
    """The nested list comes BEFORE the real fields, where first-match would be shadowed."""
    return _HEAD + list_text + _REAL + "===END===\n"


_SHADOWS = [
    'STATUS::"VOID"',
    "TIER::BOGUS",
    "SUPERSEDED_BY::HO-ESCAPES-20261029",
    "TOKEN::HO-CUBIC-T-20260301",
    'DECISION::"x"',
    "TYPE::OTHER",
    "ISSUE_REF::nonsense",
    "HUMAN_ADR_REF::missing/path.md",
]


@pytest.mark.parametrize("shadow", _SHADOWS)
def test_reader_and_gate_a_see_neither_a_nested_item(tmp_path: Path, shadow: str) -> None:
    text = _record(_nested(shadow))
    key = shadow.split("::", 1)[0]
    parsed = parse_decision_record(text)
    meta = _extract_meta_fields(_strip_block_lines(text))
    real = {"STATUS": "RATIFIED", "TIER": "STRATEGIC", "TOKEN": "HO-CUBIC-A-20260101"}
    if key in real:
        assert meta[key] == real[key], (key, meta[key])
    else:
        assert key not in meta or key in {"TYPE", "DECISION"}, (key, meta.get(key))
    assert key not in parsed["fields"]
    assert parsed["status"] == "RATIFIED" and parsed["tier"] == "STRATEGIC"
    assert parsed["token"] == "HO-CUBIC-A-20260101"


@pytest.mark.parametrize("shadow", _SHADOWS)
def test_a_nested_item_cannot_shadow_meta_in_gate_a(tmp_path: Path, shadow: str) -> None:
    result = validate_octave_content(tmp_path, _record(_nested(shadow)))
    assert result.valid, (shadow, result.errors)
    assert result.token == "HO-CUBIC-A-20260101"


def test_a_nested_status_item_in_a_wrapped_affects_list_leaves_gate_a_on_ratified(
    tmp_path: Path,
) -> None:
    meta = _extract_meta_fields(_strip_block_lines(_record(_nested('STATUS::"VOID"'))))
    assert meta["STATUS"] == "RATIFIED"
    assert "SUPERSEDED_BY" not in meta


def test_a_wrapped_superseded_by_list_still_reads_in_gate_a(tmp_path: Path) -> None:
    """The collapse to the compact form keeps a real wrapped list readable by Gate A."""
    text = _HEAD + "  SUPERSEDED_BY::[\n    HO-ESCAPES-20261029\n  ]\n" + _REAL + "===END===\n"
    assert (
        _extract_meta_fields(_strip_block_lines(text))["SUPERSEDED_BY"] == "[HO-ESCAPES-20261029]"
    )


def test_the_core_key_before_meta_scan_ignores_nested_list_text(tmp_path: Path) -> None:
    """#15: a nested reserved key in a list that precedes ``META:`` is list text."""
    text = (
        "===DECISION_RECORD===\n"
        "NOTES::[\n  STATUS::x,\n  TOKEN::y\n]\n"
        "META:\n"
        "  TYPE::DECISION_RECORD\n"
        '  VERSION::"1.0"\n'
        "  TOKEN::HO-CUBIC-A-20260101\n" + _REAL + "===END===\n"
    )
    result = validate_octave_content(tmp_path, text)
    assert result.valid, result.errors


def test_a_real_core_key_before_meta_is_still_rejected(tmp_path: Path) -> None:
    text = (
        "===DECISION_RECORD===\n"
        "STATUS::VOID\n"
        "META:\n"
        "  TYPE::DECISION_RECORD\n"
        '  VERSION::"1.0"\n'
        "  TOKEN::HO-CUBIC-A-20260101\n" + _REAL + "===END===\n"
    )
    result = validate_octave_content(tmp_path, text)
    assert any("before the META block" in e for e in result.errors), result.errors


def test_the_block_key_scan_ignores_nested_list_text_in_a_block(tmp_path: Path) -> None:
    """#14: a nested reserved key inside a wrapped list that sits INSIDE a block is list text."""
    blocks = (
        "CURRENT:\n"
        '  R2::"Access is granted per project."\n'
        "RULINGS:\n"
        "  R2:\n"
        '    RULE::"Access is granted per project."\n'
        "    AFFECTS::[\n"
        "      STATUS::x,\n"
        "      TIER::y\n"
        "    ]\n"
    )
    text = _HEAD + "  TOPIC::t\n" + _REAL + blocks + "===END===\n"
    result = validate_octave_content(tmp_path, text)
    assert result.valid, result.errors


def test_a_real_reserved_key_in_a_block_is_still_rejected(tmp_path: Path) -> None:
    blocks = 'CURRENT:\n  R2::"x"\nRULINGS:\n  R2:\n    RULE::"x"\n    STATUS::VOID\n'
    text = _HEAD + "  TOPIC::t\n" + _REAL + blocks + "===END===\n"
    result = validate_octave_content(tmp_path, text)
    assert any("MUST NOT appear" in e for e in result.errors), result.errors
