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
    diagnose_octave_record,
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
        '  NOTES::[\n// c\n    "x\nRULINGS:\n  R1:\n    RULE::phantom",\n    B\n  ]\n',
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
        'CURRENT:\n  R1::"real"\n  NOTES::[\n    "x\nRULINGS:\n  R2:\n    RULE::phantom",\n  ]\n',
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


# --- the combinatorial corpus: context x gap line x header-shaped line inside a quote ----------

_GAPS = {
    "none": "",
    "blank": "\n",
    "spaces": "   \n",
    "comment-col0": "// c\n",
    "comment-deep": "      // c\n",
    "crlf-blank": "\r\n",
}
_HEADERS = {
    "current": "CURRENT:",
    "rulings": "RULINGS:",
    "envelope": "===END===",
    "indented-header": "  CURRENT:",
    "key-value": "NOTE::val",
}
_CONTEXTS = {
    "meta": (
        '  NOTES::[\n    A,\n{gap}    "x\n{hdr}\n  R9::p",\n    B\n  ]\n',
        [],
        [],
    ),
    "rulings": (
        'RULINGS:\n  R1:\n    RULE::"real"\n    NOTES::[\n      A,\n{gap}      "x\n{hdr}\n'
        '  R9::p",\n      B\n    ]\n',
        [],
        ["R1"],
    ),
    "current": (
        'CURRENT:\n  R1::"real"\n  NOTES::[\n    A,\n{gap}    "x\n{hdr}\n  R9::p",\n    B\n  ]\n',
        ["real"],
        [],
    ),
}
_COMBOS = [(ctx, gap, hdr) for ctx in _CONTEXTS for gap in _GAPS for hdr in _HEADERS]


def _combo_text(ctx: str, gap: str, hdr: str) -> str:
    template, _, _ = _CONTEXTS[ctx]
    return _text(template.format(gap=_GAPS[gap], hdr=_HEADERS[hdr]))


@pytest.mark.parametrize(("ctx", "gap", "hdr"), _COMBOS)
def test_every_consumer_agrees_on_the_combinatorial_corpus(
    tmp_path: Path, ctx: str, gap: str, hdr: str
) -> None:
    text = _combo_text(ctx, gap, hdr)
    _, current, rulings = _CONTEXTS[ctx]
    # collect_topic_blocks: only the real entries.
    blocks = collect_topic_blocks(text)
    assert [e["rule"] for e in blocks["current"]] == current
    assert [e["id"] for e in blocks["rulings"]] == rulings
    # exactly one wrapped list, every interior line inherits the opener's block.
    spans = wrapped_list_spans(text)
    assert len(spans) == 1, spans
    annotated = list(annotate_lines(text))
    opener, closer = spans[0]
    for number in range(opener + 1, closer + 1):
        assert annotated[number - 1][0] in (None, annotated[opener - 1][0])
    # the META scan, the collapsed view and Gate A's interior set agree with the spans.
    in_meta = annotated[opener - 1][0] is None
    scanned = [(f.line, f.end_line) for f in read_octave_fields(text)[0] if f.wrapped]
    assert scanned == (spans if in_meta else [])
    removed = (closer - opener) if in_meta else 0
    assert len(collapse_wrapped_lists(text).splitlines()) == len(text.splitlines()) - removed
    assert _list_interior_lines(text) == set(range(opener + 1, closer + 1))
    # Gate A and the reader read one record.
    assert validate_octave_content(tmp_path, text).valid


# --- malformed lists: every consumer agrees on the rejection ----------------------------------

_BAD = [
    # (id, body, construct)
    (
        "col0-header-outside-quote",
        '  NOTES::[\n    "a",\nCURRENT:\n  R1::"b"\n  ]\n',
        "unterminated_list",
    ),
    ("envelope-outside-quote", "  NOTES::[\n    A,\n===END===\n", "unterminated_list"),
    ("sibling-at-opener-indent", "  NOTES::[\n    A,\n  SCOPE::PROD\n  ]\n", "unterminated_list"),
    ("text-after-bracket", "  NOTES::[\n    A\n  ] stray\n", "text_after_list"),
    ("eof-unterminated", "  NOTES::[\n    A,\n", "unterminated_list"),
]


@pytest.mark.parametrize(("name", "body", "construct"), _BAD, ids=[b[0] for b in _BAD])
def test_a_malformed_list_is_rejected_the_same_way_by_every_consumer(
    tmp_path: Path, name: str, body: str, construct: str
) -> None:
    text = _HEAD + body + ("" if "===END===" in body else _END)
    reject = read_octave_fields(text)[1]
    assert reject is not None and reject["construct"] == construct
    assert wrapped_list_spans(text) == []
    result = validate_octave_content(tmp_path, text)
    assert result.valid is False
    assert construct in result.errors[0]


def test_a_non_exact_opener_never_starts_list_mode_in_any_consumer(tmp_path: Path) -> None:
    """``KEY::[A,`` keeps its single-line read, so the header after it is a real header."""
    text = _text('  NOTES::[A,\nCURRENT:\n  R1::"real"\n')
    assert wrapped_list_spans(text) == []
    assert [e["rule"] for e in collect_topic_blocks(text)["current"]] == ["real"]
    assert read_octave_fields(text)[1] is None


# --- malformed lists in EVERY context (#239 round 4) -------------------------------------------
#
# CE/CRS reproduced: an unterminated list (or text after the ``]``) INSIDE a RULINGS / CURRENT
# block was marked by the walk but dropped by the field scan, so Gate A accepted the record and
# ``collect_topic_blocks`` read entries from after the break. Malformed handling is total:
# context (META / RULINGS / CURRENT) x shape (header break, envelope, sibling break,
# text after ``]``, EOF) x line ending. Every consumer must reject identically.

# context -> (text before the list, the list opener + one item, entries read BEFORE the break)
_BAD_CONTEXTS = {
    "meta": ("", "  NOTES::[\n    A,\n", [], []),
    "rulings": ('RULINGS:\n  R1:\n    RULE::"real"\n', "    NOTES::[\n      A,\n", [], ["R1"]),
    "current": ('CURRENT:\n  R1::"real"\n', "  NOTES::[\n    A,\n", ["real"], []),
}
# shape -> (per-context text after the item, construct); "{after}" is a field-shaped entry
# in the context's own syntax that sits AFTER the break and must never be read.
_AFTER = {
    "meta": 'CURRENT:\n  R8::"after"\n',
    "rulings": '  R8:\n    RULE::"after"\n',
    "current": '  R8::"after"\n',
}
_BAD_SHAPES = {
    "header-break": ("{header}{after}", "unterminated_list"),
    "envelope": ("===END===\n", "unterminated_list"),
    "sibling-break": ("{sibling}{closer}{after}", "unterminated_list"),
    "text-after-bracket": ("{closer_stray}{after}", "text_after_list"),
    "eof": ("", "unterminated_list"),
}
_SIBLING = {
    "meta": "  SCOPE::PROD\n",
    "rulings": '    VERBATIM::"sib"\n',
    "current": '  R7::"sib"\n',
}
_CLOSER = {"meta": "  ]\n", "rulings": "    ]\n", "current": "  ]\n"}
_STRAY = {"meta": "  ] stray\n", "rulings": "    ] stray\n", "current": "  ] stray\n"}
_HEADER = {"meta": "", "rulings": 'CURRENT:\n  R9::"hdr"\n', "current": "RULINGS:\n  R9:\n"}
_EOLS = {"lf": "\n", "crlf": "\r\n"}
_BAD_COMBOS = [(ctx, shape, eol) for ctx in _BAD_CONTEXTS for shape in _BAD_SHAPES for eol in _EOLS]


def _bad_text(ctx: str, shape: str, eol: str) -> tuple[str, int, str]:
    """``(record text, 1-based opener line, construct)`` for one malformed-list combination."""
    before, opener, _cur, _rul = _BAD_CONTEXTS[ctx]
    template, construct = _BAD_SHAPES[shape]
    tail = template.format(
        header=_HEADER[ctx],
        after=_AFTER[ctx],
        sibling=_SIBLING[ctx],
        closer=_CLOSER[ctx],
        closer_stray=_STRAY[ctx],
    )
    # META lists sit among META fields; block lists after the META block.
    body = before + opener + tail
    text = _HEAD + body + ("" if "===END===" in tail else _END)
    opener_line = _HEAD.count("\n") + before.count("\n") + 1
    return text.replace("\n", _EOLS[eol]), opener_line, construct


@pytest.mark.parametrize(("ctx", "shape", "eol"), _BAD_COMBOS)
def test_a_malformed_list_in_any_context_is_rejected_by_every_consumer(
    tmp_path: Path, ctx: str, shape: str, eol: str
) -> None:
    text, opener_line, construct = _bad_text(ctx, shape, eol)
    expected = {"line": opener_line, "construct": construct}
    # the reader and its diagnosis
    assert read_octave_fields(text)[1] == expected
    assert diagnose_octave_record(text) == expected
    # no malformed list is ever a well-formed span, so no interior is carved out anywhere
    assert wrapped_list_spans(text) == []
    assert _list_interior_lines(text) == set()
    # Gate A rejects, naming the line and the construct, first
    result = validate_octave_content(tmp_path, text)
    assert result.valid is False
    assert f"line {opener_line}: {construct}" in result.errors[0], result.errors
    # topic extraction does not read past the break
    blocks = collect_topic_blocks(text)
    _, _, current, rulings = _BAD_CONTEXTS[ctx]
    assert [e["rule"] for e in blocks["current"]] == current
    assert [e["id"] for e in blocks["rulings"]] == rulings
