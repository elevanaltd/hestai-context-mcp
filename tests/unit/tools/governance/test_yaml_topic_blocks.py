"""PR-4 slice B3: YAML topic blocks (``current:`` / ``rulings:``) beside the OCTAVE ones.

A column-0 ``current:`` / ``rulings:`` header with no value opens a block that
runs until the next non-blank line indented no deeper than the header (ADR-RFC-
ARCH-004 v1.3 §1.7). Block lines stay out of ``fields``; a lowercase reserved key
inside a block is rejected loudly; a ``current:`` line in the markdown body is
never a block. Both syntaxes share ONE ``annotate_lines`` / ``collect_topic_blocks``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hestai_context_mcp.core.agent_readable_governance_parser import (
    annotate_lines,
    collect_topic_blocks,
    diagnose_yaml_record,
    parse_decision_record,
)
from hestai_context_mcp.tools.governance.type_checker import validate_octave_content
from hestai_context_mcp.tools.list_decisions import list_decisions
from hestai_context_mcp.tools.lookup_decision import lookup_decision

from ._agr_fixtures import write_record, write_yaml_record, yaml_record_text, yaml_topic_lines

pytestmark = pytest.mark.unit

TOKEN = "TOPIC-YAML-ACCESS-20261029"
CURRENT = [("R2", "Access is granted per project."), ("R3", 'Offboarding "revokes" in 24h.')]
RULINGS = [
    {
        "id": "R2",
        "rule": "Access is granted per project.",
        "verbatim": "Access per project.",
        "ruled": "Operator, 2026-10-15",
        "replaces": "R1",
    },
    {"id": "R3", "rule": 'Offboarding "revokes" in 24h.', "ruled": "Operator, 2026-10-16"},
]

OCTAVE_EQUIVALENT = (
    "===DECISION_RECORD===\n"
    "META:\n"
    "  TYPE::DECISION_RECORD\n"
    '  VERSION::"1.0"\n'
    f"  TOKEN::{TOKEN}\n"
    "  STATUS::RATIFIED\n"
    "  TIER::STRATEGIC\n"
    '  AUTHORED_AT::"2026-06-01T00:00:00Z"\n'
    '  DECISION::"A binding decision sentence."\n'
    '  BECAUSE::"A one-sentence rationale."\n'
    '  TOPIC::"client-access"\n'
    "CURRENT:\n"
    '  R2::"Access is granted per project."\n'
    '  R3::"Offboarding "revokes" in 24h."\n'
    "RULINGS:\n"
    "  R2:\n"
    '    RULE::"Access is granted per project."\n'
    '    VERBATIM::"Access per project."\n'
    '    RULED::"Operator, 2026-10-15"\n'
    '    REPLACES::"R1"\n'
    "  R3:\n"
    '    RULE::"Offboarding "revokes" in 24h."\n'
    '    RULED::"Operator, 2026-10-16"\n'
    "===END===\n"
)


def _yaml(**kw: object) -> str:
    lines = yaml_topic_lines(CURRENT, RULINGS)
    return yaml_record_text(token=TOKEN, topic="client-access", extra_lines=lines, **kw)  # type: ignore[arg-type]


def test_yaml_topic_record_parses_with_blocks_outside_fields() -> None:
    parsed = parse_decision_record(_yaml())
    assert parsed["token"] == TOKEN
    assert parsed["fields"] == {"TOPIC": "client-access"}
    assert diagnose_yaml_record(_yaml()) is None


def test_collect_topic_blocks_yaml_equals_octave_equivalent() -> None:
    assert collect_topic_blocks(_yaml()) == collect_topic_blocks(OCTAVE_EQUIVALENT)
    blocks = collect_topic_blocks(_yaml())
    assert blocks["current"][1] == {"id": "R3", "rule": 'Offboarding "revokes" in 24h.'}
    assert blocks["rulings"][1] == {
        "id": "R3",
        "rule": 'Offboarding "revokes" in 24h.',
        "verbatim": None,
        "ruled": "Operator, 2026-10-16",
        "replaces": None,
    }


def test_header_only_blocks_are_empty_not_rejected() -> None:
    text = yaml_record_text(token=TOKEN, topic="t", extra_lines=["current:", "rulings:"])
    assert diagnose_yaml_record(text) is None
    assert collect_topic_blocks(text) == {"current": [], "rulings": []}


def test_block_ends_at_next_column_zero_line_and_later_keys_are_fields() -> None:
    lines = [*yaml_topic_lines(CURRENT), 'scope: "repo"']
    text = yaml_record_text(token=TOKEN, topic="t", extra_lines=lines)
    assert parse_decision_record(text)["fields"] == {"TOPIC": "t", "SCOPE": "repo"}
    assert [e["id"] for e in collect_topic_blocks(text)["current"]] == ["R2", "R3"]


def test_blank_lines_inside_blocks_do_not_end_them() -> None:
    lines = [
        "current:",
        '  R1: "one"',
        "",
        '  R2: "two"',
        "rulings:",
        "  R1:",
        "",
        '    rule: "one"',
        "",
        "  R2:",
        '    rule: "two"',
    ]
    text = yaml_record_text(token=TOKEN, topic="t", extra_lines=lines)
    assert diagnose_yaml_record(text) is None
    assert parse_decision_record(text)["token"] == TOKEN
    blocks = collect_topic_blocks(text)
    assert [e["id"] for e in blocks["current"]] == ["R1", "R2"]
    assert [e["id"] for e in blocks["rulings"]] == ["R1", "R2"]
    assert blocks["rulings"][0]["rule"] == "one"


def test_annotate_lines_marks_yaml_block_lines_only_inside_fences() -> None:
    body = (
        'current:\n  R9: "smuggled"\nrulings:\n  R9:\n    rule: "smuggled"\n'
        'CURRENT:\n  R9::"smuggled"\n'
    )
    text = yaml_record_text(
        token=TOKEN, topic="t", extra_lines=yaml_topic_lines(CURRENT), body=body
    )
    marked = [(block, line.rstrip("\n")) for block, line in annotate_lines(text)]
    assert ("CURRENT", '  R2: "Access is granted per project."') in marked
    in_block = [line for block, line in marked if block is not None]
    assert all("smuggled" not in line for line in in_block)
    assert collect_topic_blocks(text)["rulings"] == []


def test_body_current_header_is_never_a_block() -> None:
    body = 'current:\n  R1: "from the body"\n'
    text = yaml_record_text(token=TOKEN, topic="t", body=body)
    assert collect_topic_blocks(text) == {"current": [], "rulings": []}


RESERVED = [
    "version",
    "token",
    "id",
    "type",
    "status",
    "tier",
    "decision",
    "because",
    "authored_at",
    "superseded_by",
]


@pytest.mark.parametrize("key", RESERVED)
def test_reserved_key_inside_current_is_a_loud_reject(key: str) -> None:
    lines = ["current:", '  R1: "ok"', f'  {key}: "nested"']
    text = yaml_record_text(token=TOKEN, topic="t", extra_lines=lines)
    reject = diagnose_yaml_record(text)
    assert reject == {
        "line": text.split("\n").index(f'  {key}: "nested"') + 1,
        "construct": "reserved_key_in_block",
    }
    assert parse_decision_record(text)["token"] is None


@pytest.mark.parametrize("key", RESERVED)
def test_reserved_key_inside_rulings_is_a_loud_reject(key: str) -> None:
    lines = ["rulings:", "  R1:", '    rule: "ok"', f'    {key}: "nested"']
    text = yaml_record_text(token=TOKEN, topic="t", extra_lines=lines)
    reject = diagnose_yaml_record(text)
    assert reject == {
        "line": text.split("\n").index(f'    {key}: "nested"') + 1,
        "construct": "reserved_key_in_block",
    }
    assert parse_decision_record(text)["token"] is None


@pytest.mark.parametrize(
    ("lines", "construct"),
    [
        (["current:", "  R1: bare"], "unquoted_value"),
        (["current:", "  R1: |"], "block_scalar"),
        (["current:", '  R1: "x" # c'], "comment"),
        (["current:", '  r1: "x"'], "invalid_block_entry"),
        (["current:", '   R1: "x"'], "indentation"),
        (["current:", '    R1: "x"'], "indentation"),
        (["current:", "  R1:"], "empty_value"),
        (["current:", '  R1: "x"', "  # note"], "comment"),
        (["rulings:", '    rule: "orphan"'], "orphan_block_line"),
        (["rulings:", "  R1:", '    rule: "a"', '    rule: "b"'], "duplicate_key"),
        (["rulings:", "  R1:", '    nonsense: "a"'], "unknown_block_key"),
        (["rulings:", "  R1:", "    rule: bare"], "unquoted_value"),
        (["rulings:", "  R1:", '   rule: "a"'], "indentation"),
        (["rulings:", '  R1: "value-not-header"'], "invalid_block_entry"),
        (["current:", "current:"], "duplicate_key"),
        (["current:", '  R1: "a"', "scope: x"], "unquoted_value"),
        (["current:", '  R1: "a"', '  R1: "b"'], "duplicate_key"),
        (["rulings:", "  R1:", '    rule: "a"', "  R1:"], "duplicate_key"),
        (["rulings:", "rulings:"], "duplicate_key"),
        (["rulings:", "  r1:"], "invalid_block_entry"),
        (["rulings:", "  status:"], "reserved_key_in_block"),
        (["CURRENT:"], "invalid_key"),
    ],
)
def test_malformed_block_lines_are_loud_rejects(lines: list[str], construct: str) -> None:
    text = yaml_record_text(token=TOKEN, topic="t", extra_lines=lines)
    reject = diagnose_yaml_record(text)
    first_extra = text.split("\n").index(lines[0]) + 1
    assert reject is not None and reject["construct"] == construct, reject
    assert first_extra <= reject["line"] <= first_extra + len(lines) - 1
    assert reject["line"] == first_extra + len(lines) - 1  # each case fails on its last line
    assert parse_decision_record(text)["token"] is None


def test_lookup_decision_current_state_for_yaml(tmp_path: Path) -> None:
    write_yaml_record(
        tmp_path, token=TOKEN, topic="client-access", extra_lines=yaml_topic_lines(CURRENT, RULINGS)
    )
    record = lookup_decision(str(tmp_path), TOKEN)["record"]
    assert record["current_state"] == [
        {"id": "R2", "rule": "Access is granted per project."},
        {"id": "R3", "rule": 'Offboarding "revokes" in 24h.'},
    ]
    assert record["fields"] == {"TOPIC": "client-access"}


def test_yaml_topic_without_current_block_gives_empty_list_and_non_topic_gives_none(
    tmp_path: Path,
) -> None:
    write_yaml_record(tmp_path, token=TOKEN, topic="client-access")
    write_yaml_record(tmp_path, token="TOPIC-YAML-PLAIN-20261030")
    assert lookup_decision(str(tmp_path), TOKEN)["record"]["current_state"] == []
    assert (
        lookup_decision(str(tmp_path), "TOPIC-YAML-PLAIN-20261030")["record"]["current_state"]
        is None
    )


def test_list_decisions_topic_filter_for_yaml(tmp_path: Path) -> None:
    write_yaml_record(
        tmp_path, token=TOKEN, topic="client-access", extra_lines=yaml_topic_lines(CURRENT, RULINGS)
    )
    write_yaml_record(tmp_path, token="TOPIC-YAML-OTHER-20261030", topic="other")
    write_record(
        tmp_path, token="TOPIC-OCT-ACCESS-20261031", extra_lines=["  TOPIC::client-access"]
    )
    result = list_decisions(str(tmp_path), topic="client-access")
    assert sorted(r["token"] for r in result["records"]) == ["TOPIC-OCT-ACCESS-20261031", TOKEN]
    assert all(r["topic"] == "client-access" for r in result["records"])
    assert result["skipped"] == []


# --- OCTAVE regression: every OCTAVE topic behaviour is unchanged -------------

_OCT_SAMPLE = (
    "===DECISION_RECORD===\n"
    "META:\n"
    "  TOPIC::t\n"
    "CURRENT:\n"
    '  R1::"a"\n'
    "\n"
    "  NESTED:\n"
    "RULINGS:\n"
    "  R1:\n"
    '    RULE::"a"\n'
    "tail::x\n"
    "===END===\n"
)


def test_octave_annotate_lines_golden() -> None:
    expected = [
        None,
        None,
        None,
        None,  # CURRENT: header
        "CURRENT",
        None,  # blank line yields None
        "CURRENT",
        None,  # RULINGS: header
        "RULINGS",
        "RULINGS",
        None,
        None,
    ]
    assert [block for block, _ in annotate_lines(_OCT_SAMPLE)] == expected
    assert "".join(line for _, line in annotate_lines(_OCT_SAMPLE)) == _OCT_SAMPLE


def test_octave_ignores_lowercase_block_headers() -> None:
    text = '===DECISION_RECORD===\nMETA:\n  TYPE::DECISION_RECORD\ncurrent:\n  R1::"a"\n===END===\n'
    assert all(block is None for block, _ in annotate_lines(text))
    assert collect_topic_blocks(text) == {"current": [], "rulings": []}


def test_collect_topic_blocks_never_raises_on_bad_yaml_scalars() -> None:
    for lines in (
        ["current:", '  R1: "unterminated'],
        ["current:", "  R1: bare"],
        ["rulings:", "  R1:", '    rule: "bad \\q"'],
    ):
        text = yaml_record_text(token=TOKEN, topic="t", extra_lines=lines)
        assert collect_topic_blocks(text) == collect_topic_blocks(text)  # no exception
        assert parse_decision_record(text)["token"] is None


def test_octave_topic_filter_current_state_and_gate_a_14_unchanged(tmp_path: Path) -> None:
    blocks = [
        "  TOPIC::client-access",
        "CURRENT:",
        '  R2::"Access is granted per project."',
        "RULINGS:",
        "  R2:",
        '    RULE::"Access is granted per project."',
    ]
    write_record(tmp_path, token="TOPIC-OCT-REGRESSION-20261029", extra_lines=blocks)
    assert [
        r["token"] for r in list_decisions(str(tmp_path), topic="client-access")["records"]
    ] == ["TOPIC-OCT-REGRESSION-20261029"]
    state = lookup_decision(str(tmp_path), "TOPIC-OCT-REGRESSION-20261029")["record"][
        "current_state"
    ]
    assert state == [{"id": "R2", "rule": "Access is granted per project."}]

    nested = OCTAVE_EQUIVALENT.replace(
        '    RULE::"Access', '    TOKEN::"HO-NESTED-20261029"\n    RULE::"Access', 1
    )
    result = validate_octave_content(tmp_path, nested)
    assert not result.valid
    assert any("TOKEN" in e and "RULINGS" in e for e in result.errors), result.errors
