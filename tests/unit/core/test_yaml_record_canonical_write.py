"""EPIC4 PR-5 write-mode ruling (C), RED: content mode CANONICALISES a submitted YAML record.

The write path parses the submitted record, then writes the canonical re-emission of
the front matter (``emit_yaml_record``) followed by the markdown body after the closing
fence copied VERBATIM (no body normalisation, CR/CRLF included). File bytes ==
canonical bytes, so S2's ``record_hash = hash(file bytes)`` is stable.

* ``emit_yaml_record(..., body="")`` appends the body verbatim after the closing fence.
* ``canonicalize_yaml_record(raw)`` is the one parse -> gate -> re-emit step.
* ROUND-TRIP GATE: every decoded field value of the submitted record must equal the
  value decoded from the re-emitted bytes, else a loud ``round_trip_mismatch`` naming
  the field.
* IDEMPOTENT EMISSION: ``canonicalize(canonical) == canonical`` byte for byte
  (``append_ruling`` re-emits through this path; one changed byte would be a spurious
  EXPECTED_HASH_MISMATCH).
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from hestai_context_mcp.core import agent_readable_governance_parser as _parser
from hestai_context_mcp.core import agent_readable_governance_parser as parser
from hestai_context_mcp.core.agent_readable_governance_parser import (
    YamlSyntaxError,
    collect_topic_blocks,
    diagnose_yaml_record,
    emit_yaml_record,
    encode_yaml_scalar,
    parse_decision_record,
)

from ..tools.governance._agr_fixtures import yaml_record_text

pytestmark = pytest.mark.unit


def canonicalize_yaml_record(raw: str | bytes) -> str:
    """Late-bound so a missing implementation fails the test, not collection of the suite."""
    return _parser.canonicalize_yaml_record(raw)  # type: ignore[attr-defined,no-any-return]


TOKEN = "HO-ESCAPES-20261029"
OLD_A = "HO-CUBIC-A-20260101"

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

# Every ruled escape, controls with no short escape, DEL, non-BMP, exotic separators,
# and an OPERATOR_RULING-shaped value with mixed quotes.
VALUES = [
    "back\\slash",
    'say "hi"',
    "line1\nline2",
    "cr\rhere",
    "tab\there",
    "\x00\x01\x1f\x7f",
    "non-bmp \U0001f600 and café →   \u0085",
    "",
    "  padded  ",
    'OPERATOR_RULING: "keep \'X\' and \\"Y\\"" -- said: it\'s "fine" \\ \t\r\n end',
]

BODIES = [
    "",
    "# Notes\n\nFree-form body.\n",
    "no trailing newline",
    "crlf\r\nbody\r\nlines\r\n",
    "lone\rcr and mixed\r\n\n",
    '---\ncurrent:\n  R1: "not a block"\nstatus: "VOID"\n---\n',
    "\n\n\n",
]


def _submitted(body: str = "", eol: str = "\n", **kw: Any) -> str:
    return yaml_record_text(token=TOKEN, body=body, eol=eol, **kw)


# --- emitter carries the body ------------------------------------------------------


@pytest.mark.parametrize("body", BODIES)
def test_emit_appends_the_body_verbatim_after_the_closing_fence(body: str) -> None:
    head = emit_yaml_record(CORE, None, None)
    text = emit_yaml_record(CORE, None, None, body=body)
    assert text == head + body
    assert diagnose_yaml_record(text) is None
    assert parse_decision_record(text)["token"] == TOKEN
    assert collect_topic_blocks(text) == {"current": [], "rulings": []}  # body is never a block


def test_emit_rejects_a_non_string_body() -> None:
    with pytest.raises(YamlSyntaxError):
        emit_yaml_record(CORE, None, None, body=b"bytes")  # type: ignore[arg-type]


# --- canonicalisation ---------------------------------------------------------------


def test_canonicalise_reorders_front_matter_and_keeps_the_body() -> None:
    shuffled = (
        "---\n"
        'because: "A one-sentence rationale."\n'
        'token:    "HO-ESCAPES-20261029"\n'
        'decision: "A binding decision sentence."\n'
        'type: "DECISION_RECORD"\n'
        'authored_at: "2026-10-29T00:00:00Z"\n'
        'tier: "STRATEGIC"\n'
        'version: "1.4"\n'
        'status: "RATIFIED"\n'
        "---\n"
        "# Body\n"
    )
    assert canonicalize_yaml_record(shuffled) == emit_yaml_record(CORE, None, None, body="# Body\n")


@pytest.mark.parametrize("body", BODIES)
@pytest.mark.parametrize("eol", ["\n", "\r\n"])
def test_body_is_copied_verbatim_whatever_the_front_matter_line_endings(
    body: str, eol: str
) -> None:
    out = canonicalize_yaml_record(_submitted(body=body, eol=eol, scope="repo"))
    assert out.endswith("---\n" + body)
    assert "\r" not in out[: len(out) - len(body)]  # front matter is canonical LF
    assert diagnose_yaml_record(out) is None


def test_canonicalise_accepts_bytes_and_str_alike() -> None:
    text = _submitted(body="b\r\n")
    assert canonicalize_yaml_record(text.encode("utf-8")) == canonicalize_yaml_record(text)


def test_blocks_and_supersedes_survive_in_canonical_form() -> None:
    blocks: Any = {
        "current": [{"id": "R2", "rule": "rule two"}],
        "rulings": [
            {"id": "R2", "rule": "rule two", "verbatim": "v", "ruled": "r", "replaces": "R1"}
        ],
    }
    fields = {**CORE, "VERSION": "1.0", "AUTHORED_AT": "2026-06-01T00:00:00Z", "TOPIC": "records"}
    expected = emit_yaml_record(fields, blocks, [OLD_A], body="body\n")
    scrambled = _submitted(
        body="body\n",
        topic="records",
        supersedes=OLD_A,
        extra_lines=[
            "rulings:",
            "  R2:",
            '    replaces: "R1"',
            '    ruled: "r"',
            '    verbatim: "v"',
            '    rule: "rule two"',
            "current:",
            '  R2: "rule two"',
        ],
    )
    assert canonicalize_yaml_record(scrambled) == expected


@pytest.mark.parametrize(
    ("text", "construct"),
    [
        (_submitted(decision_literal="unquoted words"), "unquoted_value"),
        (_submitted(extra_lines=['scope: "a"', 'scope: "b"']), "duplicate_key"),
        ('---\ntype: "DECISION_RECORD"\n', "missing_closing_fence"),
    ],
)
def test_a_submission_the_reader_rejects_is_never_canonicalised(text: str, construct: str) -> None:
    with pytest.raises(YamlSyntaxError) as info:
        canonicalize_yaml_record(text)
    assert info.value.construct == construct


# --- condition 1: the round-trip gate ----------------------------------------------


@pytest.mark.parametrize("value", VALUES)
def test_every_decoded_value_survives_canonicalisation_exactly(value: str) -> None:
    text = _submitted(
        body="b\n",
        decision_literal=encode_yaml_scalar(value),
        because=value,
        scope=value,
    )
    before = parse_decision_record(text)
    after = parse_decision_record(canonicalize_yaml_record(text))
    assert after == before
    assert after["decision"] == value and after["fields"]["SCOPE"] == value


def test_a_value_changed_by_re_emission_is_rejected_loudly_with_field_and_construct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = parser.emit_yaml_record

    def lossy(*args: Any, **kwargs: Any) -> str:
        return real(*args, **kwargs).replace("rationale", "rationalX")

    monkeypatch.setattr(parser, "emit_yaml_record", lossy)
    with pytest.raises(YamlSyntaxError) as info:
        canonicalize_yaml_record(_submitted())
    assert info.value.construct == "round_trip_mismatch"
    assert "because" in str(info.value).lower()


def test_a_dropped_block_entry_is_also_a_round_trip_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = parser.emit_yaml_record

    def lossy(*args: Any, **kwargs: Any) -> str:
        return real(*args, **kwargs).replace('  R1: "r"\n', "")

    monkeypatch.setattr(parser, "emit_yaml_record", lossy)
    text = _submitted(extra_lines=["current:", '  R1: "r"'])
    with pytest.raises(YamlSyntaxError) as info:
        canonicalize_yaml_record(text)
    assert info.value.construct == "round_trip_mismatch"


# --- condition 3: idempotent emission (property-style, deterministic corpus) --------

_POOL = (
    list("abcXYZ019 _-.,:;!?#'")
    + ['"', "\\", "\n", "\r", "\t"]
    + [chr(c) for c in (0, 1, 7, 27, 31, 127)]
    + ["é", "→", "\U0001f600", " ", "\u0085", "﻿"]
)


def _rand_text(rng: random.Random, limit: int = 24) -> str:
    return "".join(rng.choice(_POOL) for _ in range(rng.randint(0, limit)))


def _rand_record(rng: random.Random) -> str:
    fields = {**CORE, "DECISION": _rand_text(rng), "BECAUSE": _rand_text(rng)}
    for index in range(rng.randint(0, 3)):
        fields[f"NOTE_{index}"] = _rand_text(rng)
    blocks: Any = None
    if rng.random() < 0.6:
        ids = [f"R{n}" for n in rng.sample(range(1, 9), rng.randint(1, 3))]
        blocks = {
            "current": [{"id": i, "rule": _rand_text(rng)} for i in ids],
            "rulings": [
                {
                    "id": i,
                    "rule": _rand_text(rng),
                    "verbatim": _rand_text(rng),
                    "ruled": _rand_text(rng),
                    "replaces": rng.choice([None, "R0", _rand_text(rng)]),
                }
                for i in ids
            ],
        }
    supersedes = [OLD_A] if rng.random() < 0.3 else None
    return emit_yaml_record(fields, blocks, supersedes, body=_rand_text(rng, 60))


def test_canonical_bytes_are_a_fixed_point_of_parse_then_emit() -> None:
    rng = random.Random(20261029)
    for case in range(300):
        text = _rand_record(rng)
        assert diagnose_yaml_record(text) is None, case
        assert canonicalize_yaml_record(text) == text, case
        assert canonicalize_yaml_record(canonicalize_yaml_record(text)) == text, case


def test_front_matter_line_endings_do_not_change_the_canonical_bytes() -> None:
    expected = emit_yaml_record(
        {**CORE, "VERSION": "1.0", "AUTHORED_AT": "2026-06-01T00:00:00Z"},
        None,
        None,
        body="x\r\n",
    )
    assert canonicalize_yaml_record(_submitted(body="x\r\n", eol="\n")) == expected
    assert canonicalize_yaml_record(_submitted(body="x\r\n", eol="\r\n")) == expected
