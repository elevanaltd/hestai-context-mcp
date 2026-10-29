"""PR-4 slice A step 2: regex-only quoted-YAML front-matter adapter (RED -> GREEN).

A YAML record parses into the SAME DecisionRecord dict (and uppercase ``fields``)
an equivalent OCTAVE record produces (PROD I4), and fails CLOSED on anything
outside the one-line double-quoted subset.
"""

from __future__ import annotations

import pytest

from hestai_context_mcp.core.agent_readable_governance_parser import (
    extract_yaml_token,
    has_yaml_decision_header,
    parse_decision_record,
)
from tests.unit.tools.governance._agr_fixtures import yaml_record_text

pytestmark = pytest.mark.unit

TOKEN = "HO-YAML-PARSER-20261029"

OCTAVE_TEXT = (
    "===DECISION_RECORD===\n"
    "META:\n"
    "  TYPE::DECISION_RECORD\n"
    '  VERSION::"1.0"\n'
    f"  TOKEN::{TOKEN}\n"
    "  STATUS::SUPERSEDED\n"
    "  TIER::STRATEGIC\n"
    '  AUTHORED_AT::"2026-06-01T00:00:00Z"\n'
    '  DECISION::"A binding decision sentence."\n'
    '  BECAUSE::"A one-sentence rationale."\n'
    '  SCOPE::"repo"\n'
    '  TOPIC::"some-topic"\n'
    f"  SUPERSEDED_BY::{TOKEN}-X\n"
    "===END===\n"
)


def _yaml(**kw: object) -> str:
    return yaml_record_text(
        token=TOKEN,
        status="SUPERSEDED",
        scope="repo",
        topic="some-topic",
        superseded_by=f"{TOKEN}-X",
        **kw,  # type: ignore[arg-type]
    )


def _with_extra(*extra: str) -> str:
    return yaml_record_text(token=TOKEN, extra_lines=list(extra))


def test_yaml_record_parses_to_same_dict_as_octave() -> None:
    assert parse_decision_record(_yaml()) == parse_decision_record(OCTAVE_TEXT)


def test_yaml_fields_are_uppercase_keys() -> None:
    parsed = parse_decision_record(_yaml())
    assert parsed["token"] == TOKEN
    assert parsed["type"] == "DECISION_RECORD"
    assert parsed["fields"] == {
        "SCOPE": "repo",
        "TOPIC": "some-topic",
        "SUPERSEDED_BY": f"{TOKEN}-X",
    }


def test_escapes_quote_and_backslash_are_decoded() -> None:
    text = yaml_record_text(token=TOKEN, decision='say "hi" to C:\\dir')
    assert parse_decision_record(text)["decision"] == 'say "hi" to C:\\dir'


def test_markdown_body_after_closing_fence_is_ignored() -> None:
    body = 'TOKEN::HO-BODY-20260101\nstatus: "VOID"\n---\ntype: "x"\n'
    parsed = parse_decision_record(yaml_record_text(token=TOKEN, body=body))
    assert parsed["token"] == TOKEN
    assert parsed["status"] == "RATIFIED"
    assert parsed["fields"] == {}


@pytest.mark.parametrize(
    "extra",
    [
        "extra: bare",  # unquoted value
        "extra: 'single'",  # single-quoted
        # (the slice-A `\t` case was removed: B2 ruling 2026-10-29 makes `\t` a valid escape)
        'extra: "unicode \\u00e9"',  # other escape
        'extra: "unterminated',  # unterminated
        'extra: "a" trailing',  # trailing garbage
        "extra: |",  # block scalar
        "extra: >",  # folded scalar
        'extra: ["a", "b"]',  # flow seq
        'extra: {"a": "b"}',  # flow map
        'extra: &anchor "x"',  # anchor
        "extra: *anchor",  # alias
        'extra: "x" # comment',  # trailing comment
        "# a comment line",  # comment line
        '  indented: "x"',  # continuation / indented
        '- "list item"',  # sequence item
        'Upper: "x"',  # not lowercase key
        'status: "DUP"',  # duplicate key
        "current:",  # interim rule: topic block header
        "rulings:",  # interim rule: topic block header
        'current: "scalar"',  # reserved key as a scalar
        "no colon here",
    ],
)
def test_anything_else_inside_fences_is_unparseable(extra: str) -> None:
    parsed = parse_decision_record(_with_extra(extra))
    assert parsed["token"] is None
    assert parsed["type"] is None
    assert parsed["fields"] == {}


def test_missing_closing_fence_is_unparseable() -> None:
    text = yaml_record_text(token=TOKEN).replace("\n---\n# Notes", "\n# Notes")
    assert parse_decision_record(text)["token"] is None


def test_fence_must_be_first_line() -> None:
    assert parse_decision_record("\n" + yaml_record_text(token=TOKEN))["token"] is None


def test_has_yaml_decision_header() -> None:
    assert has_yaml_decision_header(yaml_record_text(token=TOKEN)) is True
    assert has_yaml_decision_header("---\ntitle: README\n---\n# hi\n") is False
    assert has_yaml_decision_header("# README\n") is False
    assert has_yaml_decision_header(OCTAVE_TEXT) is False
    # type line only in the body, not inside the fences
    assert has_yaml_decision_header('---\ntitle: "x"\n---\ntype: "DECISION_RECORD"\n') is False


def test_header_is_recognised_even_when_record_is_malformed() -> None:
    assert has_yaml_decision_header(_with_extra("extra: bare")) is True


def test_extract_yaml_token() -> None:
    assert extract_yaml_token(yaml_record_text(token=TOKEN)) == TOKEN
    assert extract_yaml_token(_with_extra("extra: bare")) == TOKEN
    assert extract_yaml_token(OCTAVE_TEXT) is None
    assert extract_yaml_token('---\ntitle: "x"\n---\ntoken: "HO-BODY-20260101"\n') is None
