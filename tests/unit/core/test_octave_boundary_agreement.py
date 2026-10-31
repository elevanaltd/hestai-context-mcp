"""Boundary agreement (#239 round 3): every place that decides a block, list or quote boundary.

CRS found the same class of defect three rounds running: two scanners disagreeing on where a
wrapped list is open. This table runs one corpus of tricky layouts through EVERY consumer
and asserts they agree:

* ``annotate_lines`` (block membership),
* ``read_octave_fields`` (the META field scan),
* ``wrapped_list_spans`` (spans, blocks included),
* ``collapse_wrapped_lists`` (Gate A's view),
* ``collect_topic_blocks`` (CURRENT / RULINGS entries),
* Gate A's #14/#15 scans (``_list_interior_lines``) and ``validate_octave_content``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hestai_context_mcp.core.agent_readable_governance_parser import (
    annotate_lines,
    collapse_wrapped_lists,
    collect_topic_blocks,
    read_octave_fields,
    wrapped_list_spans,
)
from hestai_context_mcp.tools.governance.type_checker import (
    _list_interior_lines,
    validate_octave_content,
)

from ..tools.governance._agr_fixtures import TOKEN_OLD

pytestmark = pytest.mark.unit

_HEAD = (
    "===DECISION_RECORD===\n"
    "META:\n"
    "  TYPE::DECISION_RECORD\n"
    '  VERSION::"1.3"\n'
    f"  TOKEN::{TOKEN_OLD}\n"
    "  TOPIC::t\n"
    "  STATUS::PROPOSED\n"
    "  TIER::OPERATIONAL\n"
    '  AUTHORED_AT::"2026-01-01T00:00:00Z"\n'
    '  DECISION::"A binding decision sentence."\n'
    '  BECAUSE::"A one-sentence rationale."\n'
)
_END = "===END===\n"

# (id, text after META, expected CURRENT rules, expected RULINGS ids)
_LAYOUTS = [
    (
        "meta-list-quoted-header",
        '  NOTES::[\n    A,\n    "x\nCURRENT:\n  R1::phantom",\n    B\n  ]\n',
        [],
        [],
    ),
    (
        "meta-list-blank-then-quoted-header",
        '  NOTES::[\n    A,\n\n    "x\nCURRENT:\n  R1::phantom",\n    B\n  ]\n',
        [],
        [],
    ),
    (
        "meta-list-col0-comment-then-quoted-header",
        '  NOTES::[\n// c\n    "x\nRULINGS:\n  R1:\n    RULE::"phantom",\n    B\n  ]\n',
        [],
        [],
    ),
    (
        "rulings-list-quoted-current-header",
        'RULINGS:\n  R1:\n    RULE::"real"\n    NOTES::[\n      A,\n      "x\nCURRENT:\n'
        '  R2::phantom",\n      B\n    ]\n',
        [],
        ["R1"],
    ),
    (
        "current-list-quoted-rulings-header",
        'CURRENT:\n  R1::"real"\n  NOTES::[\n    "x\nRULINGS:\n  R2:\n    RULE::"phantom",\n  ]\n',
        ["real"],
        [],
    ),
    (
        "rulings-list-nested-entry-and-rule-items",
        'RULINGS:\n  R1:\n    RULE::"real"\n    NOTES::[\n      RULE::"nested",\n      R9:\n    ]\n',
        [],
        ["R1"],
    ),
    (
        "rulings-list-shallow-plain-item",
        'RULINGS:\n  R1:\n    RULE::"real"\n    NOTES::[\n      A,\nB,\n    ]\n    VERBATIM::"v"\n',
        [],
        ["R1"],
    ),
    (
        "list-then-real-block",
        '  NOTES::[\n    "x\nCURRENT:\n  R1::phantom"\n  ]\nCURRENT:\n  R1::"real"\n',
        ["real"],
        [],
    ),
    (
        "tabs-in-list-and-block",
        '\tNOTES::[\n\t\tA::x,\n\t\tB\n\t]\nCURRENT:\n\tR1::"real"\n',
        ["real"],
        [],
    ),
    (
        "crlf-lines",
        '  NOTES::[\r\n    A,\r\n\r\n    "x\r\nCURRENT:\r\n  R1::phantom",\r\n  ]\r\n',
        [],
        [],
    ),
]
_IDS = [layout[0] for layout in _LAYOUTS]


def _text(body: str) -> str:
    return _HEAD + body + _END


@pytest.mark.parametrize(("name", "body", "current", "rulings"), _LAYOUTS, ids=_IDS)
def test_collect_topic_blocks_returns_only_the_real_entries(
    name: str, body: str, current: list[str], rulings: list[str]
) -> None:
    blocks = collect_topic_blocks(_text(body))
    assert [e["rule"] for e in blocks["current"]] == current
    assert [e["id"] for e in blocks["rulings"]] == rulings


@pytest.mark.parametrize(("name", "body", "current", "rulings"), _LAYOUTS, ids=_IDS)
def test_a_list_interior_is_never_a_header_or_block_boundary(
    name: str, body: str, current: list[str], rulings: list[str]
) -> None:
    text = _text(body)
    annotated = list(annotate_lines(text))
    for opener, closer in wrapped_list_spans(text):
        opener_block = annotated[opener - 1][0]
        for number in range(opener + 1, closer + 1):
            block, line = annotated[number - 1]
            assert block in (None, opener_block), (name, number, block, line)
            if opener_block is None:
                assert block is None, (name, number, line)


@pytest.mark.parametrize(("name", "body", "current", "rulings"), _LAYOUTS, ids=_IDS)
def test_the_meta_field_scan_and_the_span_helper_agree(
    name: str, body: str, current: list[str], rulings: list[str]
) -> None:
    text = _text(body)
    annotated = list(annotate_lines(text))
    meta_spans = [(o, c) for o, c in wrapped_list_spans(text) if annotated[o - 1][0] is None]
    scanned = [(f.line, f.end_line) for f in read_octave_fields(text)[0] if f.wrapped]
    assert scanned == meta_spans


@pytest.mark.parametrize(("name", "body", "current", "rulings"), _LAYOUTS, ids=_IDS)
def test_the_collapsed_view_removes_exactly_the_meta_list_interiors(
    name: str, body: str, current: list[str], rulings: list[str]
) -> None:
    text = _text(body)
    annotated = list(annotate_lines(text))
    meta_spans = [(o, c) for o, c in wrapped_list_spans(text) if annotated[o - 1][0] is None]
    removed = sum(c - o for o, c in meta_spans)
    assert len(collapse_wrapped_lists(text).splitlines()) == len(text.splitlines()) - removed


@pytest.mark.parametrize(("name", "body", "current", "rulings"), _LAYOUTS, ids=_IDS)
def test_gate_a_interior_lines_are_the_span_interiors(
    name: str, body: str, current: list[str], rulings: list[str]
) -> None:
    text = _text(body)
    expected = {n for o, c in wrapped_list_spans(text) for n in range(o + 1, c + 1)}
    assert _list_interior_lines(text) == expected


@pytest.mark.parametrize(("name", "body", "current", "rulings"), _LAYOUTS, ids=_IDS)
def test_gate_a_accepts_every_layout_without_phantom_errors(
    tmp_path: Path, name: str, body: str, current: list[str], rulings: list[str]
) -> None:
    result = validate_octave_content(tmp_path, _text(body))
    assert result.valid, (name, result.errors)
