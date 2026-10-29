"""PR-4 slice B1: a rejected YAML record is rejected LOUDLY, never silently skipped.

Each unsupported construct must surface a structured ``{path, line, construct}``
through the parser diagnosis, ``lookup_decision`` (RECORD_PARSE_FAILED context)
and ``list_decisions`` (the ``skipped`` entry). ``line`` is 1-based in the file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hestai_context_mcp.core.agent_readable_governance_parser import (
    diagnose_yaml_record,
    parse_decision_record,
)
from hestai_context_mcp.tools.list_decisions import list_decisions
from hestai_context_mcp.tools.lookup_decision import lookup_decision

from ._agr_fixtures import write_yaml_record, yaml_record_text

pytestmark = pytest.mark.unit

TOKEN = "HO-STRICT-YAML-20261029"

# (offending line, expected construct). One negative per construct named in B1/B2.
CASES = [
    ("extra: |", "block_scalar"),
    ("extra: >", "block_scalar"),
    ('extra: ["a", "b"]', "flow_collection"),
    ('extra: {"a": "b"}', "flow_collection"),
    ('extra: &anchor "x"', "anchor"),
    ("extra: *anchor", "alias"),
    ("# a comment line", "comment"),
    ('extra: "x" # trailing comment', "comment"),
    ('extra: "bad \\q escape"', "bad_escape"),
    ('extra: "short \\u12 hex"', "bad_escape"),
    ('extra: "\\x41"', "bad_escape"),
    ("extra: bare", "unquoted_value"),
    ("extra: 'single'", "unquoted_value"),
    ('status: "VOID"', "duplicate_key"),
    ('extra: "quote \\u0022 form"', "noncanonical_escape"),
    ('extra: "newline \\u000a form"', "noncanonical_escape"),
    ('extra: "letter \\u0041 form"', "noncanonical_escape"),
    ('extra: "upper hex \\u001F form"', "noncanonical_escape"),
    ('extra: "lone \\ud800 surrogate"', "surrogate_escape"),
    ('extra: "lone \\uDFFF surrogate"', "surrogate_escape"),
    ('extra: "literal\ttab"', "control_character"),
    ('extra: "unterminated', "unterminated_string"),
    ('extra: "a" trailing', "trailing_garbage"),
    ('  indented: "x"', "indentation"),
    ('- "item"', "sequence_item"),
    ('Upper: "x"', "invalid_key"),
    ("extra:", "empty_value"),
    ('current: "scalar"', "block_header_with_value"),
    ('rulings: "scalar"', "block_header_with_value"),
]


def _text(line: str) -> str:
    return yaml_record_text(token=TOKEN, extra_lines=[line])


def _line_no(text: str, line: str) -> int:
    return text.split("\n").index(line) + 1


@pytest.mark.parametrize(("line", "construct"), CASES)
def test_parser_diagnoses_line_and_construct(line: str, construct: str) -> None:
    text = _text(line)
    assert diagnose_yaml_record(text) == {"line": _line_no(text, line), "construct": construct}
    assert parse_decision_record(text)["token"] is None


@pytest.mark.parametrize(("line", "construct"), CASES)
def test_lookup_decision_surfaces_path_line_construct(
    tmp_path: Path, line: str, construct: str
) -> None:
    text = _text(line)
    path = write_yaml_record(tmp_path, token=TOKEN, extra_lines=[line])
    result = lookup_decision(str(tmp_path), TOKEN)
    assert result["ok"] is False
    error = result["error"]
    assert error["code"] == "RECORD_PARSE_FAILED"
    assert error["context"]["path"] == path.relative_to(tmp_path).as_posix()
    assert error["context"]["line"] == _line_no(text, line)
    assert error["context"]["construct"] == construct


@pytest.mark.parametrize(("line", "construct"), CASES)
def test_list_decisions_skipped_entry_surfaces_path_line_construct(
    tmp_path: Path, line: str, construct: str
) -> None:
    text = _text(line)
    path = write_yaml_record(tmp_path, token=TOKEN, extra_lines=[line])
    result = list_decisions(str(tmp_path))
    assert result["records"] == []
    assert len(result["skipped"]) == 1
    entry = result["skipped"][0]
    assert entry["path"] == path.relative_to(tmp_path).as_posix()
    assert entry["line"] == _line_no(text, line)
    assert entry["construct"] == construct
    assert set(entry) == {"path", "parse_error", "line", "construct"}


def test_first_offending_line_is_reported_with_blanks_and_later_errors() -> None:
    lines = [
        "---",
        'type: "DECISION_RECORD"',
        "",
        'token: "HO-STRICT-YAML-20261029"',
        "",
        "",
        "first: bare",
        'ok: "fine"',
        "second: |",
        "---",
    ]
    assert diagnose_yaml_record("\n".join(lines) + "\n") == {
        "line": 7,
        "construct": "unquoted_value",
    }


def test_crlf_file_reports_same_line_numbers() -> None:
    text = _text("extra: bare").replace("\n", "\r\n")
    assert diagnose_yaml_record(text) == {"line": 10, "construct": "unquoted_value"}


def test_comment_markers_and_indicators_inside_quotes_are_not_constructs() -> None:
    literal = '"a # hash, [seq], {map}, &amp, *star, |pipe, >fold, - dash: colon"'
    text = yaml_record_text(token=TOKEN, decision_literal=literal)
    assert diagnose_yaml_record(text) is None
    parsed = parse_decision_record(text)
    assert parsed["decision"] == "a # hash, [seq], {map}, &amp, *star, |pipe, >fold, - dash: colon"


def test_syntactically_valid_record_missing_required_field_is_not_a_syntax_reject(
    tmp_path: Path,
) -> None:
    text = yaml_record_text(token=TOKEN).replace('because: "A one-sentence rationale."\n', "")
    assert diagnose_yaml_record(text) is None
    (tmp_path / ".hestai" / "decisions").mkdir(parents=True)
    (tmp_path / ".hestai" / "decisions" / f"{TOKEN}.md").write_text(text, encoding="utf-8")
    error = lookup_decision(str(tmp_path), TOKEN)["error"]
    assert error["code"] == "RECORD_PARSE_FAILED"
    assert "line" not in error["context"] and "construct" not in error["context"]
    skipped = list_decisions(str(tmp_path))["skipped"]
    assert len(skipped) == 1 and "construct" not in skipped[0]


def test_missing_closing_fence_is_loud() -> None:
    text = "---\n" + 'type: "DECISION_RECORD"\n' + f'token: "{TOKEN}"\n'
    assert diagnose_yaml_record(text) == {"line": 3, "construct": "missing_closing_fence"}


def test_valid_yaml_record_has_no_diagnosis() -> None:
    assert diagnose_yaml_record(yaml_record_text(token=TOKEN)) is None


def test_octave_record_has_no_yaml_diagnosis() -> None:
    assert diagnose_yaml_record("===DECISION_RECORD===\nMETA:\n===END===\n") is None


def test_octave_skipped_entry_shape_is_unchanged(tmp_path: Path) -> None:
    from ._agr_fixtures import write_malformed_record

    write_malformed_record(tmp_path)
    entry = list_decisions(str(tmp_path))["skipped"][0]
    assert set(entry) == {"path", "parse_error"}
