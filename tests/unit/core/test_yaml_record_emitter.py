"""EPIC4 PR-5 phase 1A: the canonical quoted-YAML record emitter.

``emit_yaml_record`` is pure, deterministic and regex-free. The same input gives
byte-identical output, in exactly the canonical form the PR-4 reader accepts, so a
later record_hash/CAS step can hash the bytes. It refuses every input the reader
would reject, so it can never write a record the reader refuses.
"""

from __future__ import annotations

from typing import Any

import pytest

from hestai_context_mcp.core.agent_readable_governance_parser import (
    YamlSyntaxError,
    classify_record_text,
    collect_topic_blocks,
    diagnose_yaml_record,
    emit_yaml_record,
    parse_decision_record,
    parse_supersedes_list,
)

pytestmark = pytest.mark.unit

TOKEN = "HO-ESCAPES-20261029"
OLD_A = "HO-CUBIC-A-20260101"
OLD_T = "HO-CUBIC-T-20260301"

CORE = {
    "TYPE": "DECISION_RECORD",
    "VERSION": "1.4",
    "TOKEN": TOKEN,
    "STATUS": "RATIFIED",
    "TIER": "STRATEGIC",
    "AUTHORED_AT": "2026-10-29T00:00:00Z",
    "DECISION": "A binding decision sentence.",
    "BECAUSE": "A one-sentence rationale.",
}

BLOCKS: Any = {
    "current": [{"id": "R2", "rule": "rule two"}, {"id": "R3", "rule": 'rule "three"'}],
    "rulings": [
        {
            "id": "R2",
            "rule": "rule two",
            "verbatim": "the operator said\tthis\nexactly",
            "ruled": "human, 2026-10-29",
            "replaces": "R1",
        },
        {"id": "R3", "rule": 'rule "three"', "verbatim": None, "ruled": None, "replaces": None},
    ],
}


def _fields(**extra: str) -> dict[str, str]:
    return {**CORE, **extra}


def _rebuild(text: str) -> str:
    """Re-emit from what the READER recovered (emit -> read -> emit)."""
    record = parse_decision_record(text)
    fields = {k.upper(): v for k, v in record.items() if k != "fields" and v is not None}
    others = {k: v for k, v in record["fields"].items() if k != "SUPERSEDES"}
    supersedes_value = record["fields"].get("SUPERSEDES")
    supersedes = parse_supersedes_list(supersedes_value) if supersedes_value else None
    blocks = collect_topic_blocks(text)
    return emit_yaml_record({**fields, **others}, blocks, supersedes)


def test_emitted_core_record_has_exact_canonical_bytes() -> None:
    text = emit_yaml_record(_fields(), None, None)
    assert text == (
        "---\n"
        'type: "DECISION_RECORD"\n'
        'version: "1.4"\n'
        'token: "HO-ESCAPES-20261029"\n'
        'status: "RATIFIED"\n'
        'tier: "STRATEGIC"\n'
        'authored_at: "2026-10-29T00:00:00Z"\n'
        'decision: "A binding decision sentence."\n'
        'because: "A one-sentence rationale."\n'
        "---\n"
    )


def test_emission_is_deterministic_and_independent_of_input_order() -> None:
    forward = emit_yaml_record(_fields(SCOPE="repo", TOPIC="records"), BLOCKS, [OLD_A, OLD_T])
    backward = emit_yaml_record(
        dict(reversed(list(_fields(SCOPE="repo", TOPIC="records").items()))),
        BLOCKS,
        [OLD_A, OLD_T],
    )
    assert forward == backward
    assert forward == emit_yaml_record(
        _fields(SCOPE="repo", TOPIC="records"), BLOCKS, [OLD_A, OLD_T]
    )


def test_core_fields_come_first_in_adr_order_then_optional_then_extras_sorted() -> None:
    text = emit_yaml_record(
        _fields(ZEBRA="z", ALPHA="a", TOPIC="records", ISSUE_REF="repo:hestai-context-mcp#220"),
        None,
        [OLD_A],
    )
    keys = [line.split(":", 1)[0] for line in text.splitlines()[1:-1]]
    assert keys == [
        "type",
        "version",
        "token",
        "status",
        "tier",
        "authored_at",
        "decision",
        "because",
        "issue_ref",
        "topic",
        "supersedes",
        "alpha",
        "zebra",
    ]


def test_lowercase_and_uppercase_field_keys_emit_identically() -> None:
    lower = {k.lower(): v for k, v in _fields(SCOPE="repo").items()}
    assert emit_yaml_record(lower, None, None) == emit_yaml_record(
        _fields(SCOPE="repo"), None, None
    )


def test_emit_then_read_recovers_the_same_record() -> None:
    text = emit_yaml_record(_fields(SCOPE="repo", TOPIC="records"), BLOCKS, [OLD_A, OLD_T])
    assert classify_record_text(text).syntax == "yaml"
    assert diagnose_yaml_record(text) is None
    record = parse_decision_record(text)
    assert record["token"] == TOKEN
    assert record["type"] == "DECISION_RECORD"
    assert record["version"] == "1.4"
    assert record["status"] == "RATIFIED"
    assert record["tier"] == "STRATEGIC"
    assert record["authored_at"] == "2026-10-29T00:00:00Z"
    assert record["decision"] == "A binding decision sentence."
    assert record["because"] == "A one-sentence rationale."
    assert record["fields"] == {
        "SCOPE": "repo",
        "TOPIC": "records",
        "SUPERSEDES": f"{OLD_A}, {OLD_T}",
    }
    assert collect_topic_blocks(text) == BLOCKS


def test_emit_read_emit_is_byte_identical_for_a_full_record() -> None:
    text = emit_yaml_record(_fields(SCOPE="repo", TOPIC="records"), BLOCKS, [OLD_A, OLD_T])
    assert _rebuild(text) == text


_AWKWARD = [
    'say "hi"',
    "back\\slash and \\n literal",
    "tab\there",
    "line1\nline2",
    "crlf\r\nline",
    "lone\rcr",
    "\x00\x01\x1f\x7f",
    "bell\x07 esc\x1b",
    "café →   \u0085",
    "non-bmp \U0001f600 text",
    "",
    "  padded  ",
    "colon: and # hash",
    "---",
]


@pytest.mark.parametrize("value", _AWKWARD)
def test_awkward_scalars_round_trip_byte_identically(value: str) -> None:
    text = emit_yaml_record(_fields(NOTE=value, DECISION=value), None, None)
    assert diagnose_yaml_record(text) is None
    record = parse_decision_record(text)
    assert record["decision"] == value
    assert record["fields"]["NOTE"] == value
    assert _rebuild(text) == text


def test_awkward_scalars_in_blocks_round_trip() -> None:
    blocks: Any = {
        "current": [{"id": "R1", "rule": "a\tb\n\x00"}],
        "rulings": [
            {
                "id": "R1",
                "rule": "a\tb\n\x00",
                "verbatim": 'q"\\\r',
                "ruled": "",
                "replaces": None,
            }
        ],
    }
    text = emit_yaml_record(_fields(TOPIC="records"), blocks, None)
    assert diagnose_yaml_record(text) is None
    assert collect_topic_blocks(text) == blocks
    assert _rebuild(text) == text


def test_output_uses_lf_only_and_exact_fences() -> None:
    text = emit_yaml_record(_fields(NOTE="a\r\nb"), BLOCKS, None)
    assert "\r" not in text
    lines = text.split("\n")
    assert lines[0] == "---" and lines[-2] == "---" and lines[-1] == ""
    assert lines.count("---") == 2


def test_topic_block_indentation_is_canonical() -> None:
    text = emit_yaml_record(_fields(TOPIC="records"), BLOCKS, None)
    assert text.endswith(
        "current:\n"
        '  R2: "rule two"\n'
        '  R3: "rule \\"three\\""\n'
        "rulings:\n"
        "  R2:\n"
        '    rule: "rule two"\n'
        '    verbatim: "the operator said\\tthis\\nexactly"\n'
        '    ruled: "human, 2026-10-29"\n'
        '    replaces: "R1"\n'
        "  R3:\n"
        '    rule: "rule \\"three\\""\n'
        "---\n"
    )


def test_empty_blocks_and_empty_supersedes_emit_nothing() -> None:
    plain = emit_yaml_record(_fields(), None, None)
    assert emit_yaml_record(_fields(), {"current": [], "rulings": []}, []) == plain
    assert "current:" not in plain and "supersedes" not in plain


def test_supersedes_emits_one_quoted_comma_list() -> None:
    text = emit_yaml_record(_fields(), None, [OLD_A, OLD_T])
    assert f'supersedes: "{OLD_A}, {OLD_T}"\n' in text
    assert parse_decision_record(text)["fields"]["SUPERSEDES"] == f"{OLD_A}, {OLD_T}"


def _rejects(construct: str, *args: Any) -> None:
    with pytest.raises(YamlSyntaxError) as info:
        emit_yaml_record(*args)
    assert info.value.construct == construct


@pytest.mark.parametrize("bad", ["not-a-token", "", "HO-X-2026", "ho-lower-20260101", "A,B"])
def test_invalid_token_in_supersedes_is_rejected(bad: str) -> None:
    _rejects("invalid_supersedes", _fields(), None, [bad])


def test_duplicate_or_self_supersedes_is_rejected() -> None:
    _rejects("invalid_supersedes", _fields(), None, [OLD_A, OLD_A])
    _rejects("invalid_supersedes", _fields(), None, [TOKEN])


def test_supersedes_inside_fields_is_rejected_as_a_second_source() -> None:
    _rejects("duplicate_key", _fields(SUPERSEDES=OLD_A), None, [OLD_T])


@pytest.mark.parametrize("key", ["", "1abc", "has space", "has-dash", "bad:key", "ünï"])
def test_invalid_field_key_is_rejected(key: str) -> None:
    _rejects("invalid_key", _fields(**{key: "v"}), None, None)


def test_block_header_names_cannot_be_field_keys() -> None:
    _rejects("block_header_with_value", _fields(CURRENT="x"), None, None)
    _rejects("block_header_with_value", _fields(rulings="x"), None, None)


def test_key_spelled_in_two_cases_is_a_duplicate() -> None:
    _rejects("duplicate_key", {**_fields(), "token": TOKEN}, None, None)


@pytest.mark.parametrize("missing", sorted(CORE))
def test_missing_required_field_is_rejected(missing: str) -> None:
    fields = {k: v for k, v in CORE.items() if k != missing}
    _rejects("missing_required_field", fields, None, None)


def test_wrong_type_literal_and_bad_token_format_are_rejected() -> None:
    _rejects("invalid_type", _fields(TYPE="BUILD_PLAN"), None, None)
    _rejects("invalid_token", _fields(TOKEN="not-a-token"), None, None)


def test_non_string_value_and_lone_surrogate_are_rejected() -> None:
    with pytest.raises(YamlSyntaxError):
        emit_yaml_record(_fields(NOTE=7), None, None)  # type: ignore[arg-type]
    with pytest.raises(YamlSyntaxError):
        emit_yaml_record(_fields(NOTE="bad\ud800"), None, None)


def test_reserved_key_in_a_block_entry_is_rejected() -> None:
    entry: Any = {"id": "R1", "rule": "r", "status": "VOID"}
    _rejects("reserved_key_in_block", _fields(), {"current": [], "rulings": [entry]}, None)
    _rejects("reserved_key_in_block", _fields(), {"current": [entry], "rulings": []}, None)


def test_unknown_block_key_and_bad_entry_id_and_duplicate_id_are_rejected() -> None:
    odd: Any = {"id": "R1", "rule": "r", "extra": "x"}
    _rejects("unknown_block_key", _fields(), {"current": [], "rulings": [odd]}, None)
    _rejects(
        "invalid_block_entry",
        _fields(),
        {"current": [{"id": "X1", "rule": "r"}], "rulings": []},
        None,
    )
    dup: Any = {"current": [{"id": "R1", "rule": "a"}, {"id": "R1", "rule": "b"}], "rulings": []}
    _rejects("duplicate_key", _fields(), dup, None)


def test_current_entry_without_a_rule_string_is_rejected() -> None:
    _rejects("invalid_block_entry", _fields(), {"current": [{"id": "R1"}], "rulings": []}, None)  # type: ignore[typeddict-item]


def test_every_emitted_record_is_accepted_by_the_reader() -> None:
    """Sweep: whatever the emitter writes, the strict reader parses with no diagnostic."""
    for value in _AWKWARD:
        text = emit_yaml_record(
            _fields(NOTE=value, TOPIC=value),
            {"current": [{"id": "R9", "rule": value}], "rulings": []},
            [OLD_A],
        )
        assert diagnose_yaml_record(text) is None, value


@pytest.mark.parametrize("bad_id", ["R1\n", "R1 ", "r1", "R", "R1\r"])
def test_block_entry_id_must_fully_match_r_digits(bad_id: str) -> None:
    """``$`` matches before a trailing newline, so the id check must be a full match."""
    _rejects(
        "invalid_block_entry",
        _fields(),
        {"current": [{"id": bad_id, "rule": "r"}], "rulings": []},
        None,
    )
    _rejects("invalid_block_entry", _fields(), {"current": [], "rulings": [{"id": bad_id}]}, None)  # type: ignore[list-item]
