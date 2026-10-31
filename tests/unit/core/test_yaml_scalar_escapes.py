"""PR-4 slice B2: the one-line double-quoted scalar escape set and canonical encoder.

Decoder accepts EXACTLY ``\\\\ \\" \\n \\r \\t \\uXXXX`` from ONE table. ``\\uXXXX`` is
canonical ONLY for control characters with no short escape (U+0000-U+001F except
LF/CR/TAB, plus U+007F), written as four LOWERCASE hex digits. Everything else
non-canonical is rejected loudly. Non-BMP text is literal UTF-8. The encoder is a
pure function PR-5's emitter reuses; ``encode -> decode -> encode`` is byte-stable.
(``hypothesis`` is not a dependency, so the property is checked over a broad
deterministic corpus.)
"""

from __future__ import annotations

import random

import pytest

from hestai_context_mcp.core.agent_readable_governance_parser import (
    YamlSyntaxError,
    decode_yaml_scalar,
    encode_yaml_scalar,
    parse_decision_record,
)

from ..tools.governance._agr_fixtures import yaml_record_text

pytestmark = pytest.mark.unit

_FIXED = [
    "",
    "plain ascii",
    'say "hi"',
    "back\\slash",
    '\\\\ \\" mixed \\n literal backslash-n',
    "tab\there",
    "line1\nline2",
    "crlf\r\nline",
    "lone\rcr",
    "\x00\x01\x02\x1f\x7f",
    "bell\x07 and vt\x0b and ff\x0c and esc\x1b",
    "C1 \x80\x85\x9f stay literal",
    "sep   and   literal",
    "bmp é ñ 中文 ✓",
    "non-bmp 😀 𝔘 🧪",
    "boundary ￿ ￾ ퟿ ",
    '"' * 5 + "\\" * 5,
    "ends with backslash\\",
]


def _random_corpus() -> list[str]:
    rng = random.Random(20261029)
    pool = (
        [chr(c) for c in range(0x00, 0x80)]
        + list("éñ中✓\u0085   ﻿")
        + ["😀", "𝔘", "\U0010ffff", "\U00010000"]
    )
    return ["".join(rng.choice(pool) for _ in range(rng.randint(0, 24))) for _ in range(400)]


CORPUS = _FIXED + [chr(c) for c in range(0x80)]


def _assert_round_trip(value: str) -> None:
    encoded = encode_yaml_scalar(value)
    assert decode_yaml_scalar(encoded) == value, repr(value)
    assert encode_yaml_scalar(decode_yaml_scalar(encoded)) == encoded, repr(value)
    assert "\n" not in encoded and "\r" not in encoded, repr(value)
    assert encoded.encode("utf-8").decode("utf-8") == encoded, repr(value)


@pytest.mark.parametrize("value", CORPUS)
def test_round_trip_is_lossless_and_byte_stable(value: str) -> None:
    _assert_round_trip(value)


def test_round_trip_over_seeded_random_corpus() -> None:
    for value in _random_corpus():
        _assert_round_trip(value)


def test_encoder_escapes_exactly_the_ruled_set_of_ascii() -> None:
    short = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}
    for code in range(0x80):
        ch = chr(code)
        if ch in short:
            expected = f'"{short[ch]}"'
        elif code < 0x20 or code == 0x7F:
            expected = f'"\\u{code:04x}"'
        else:
            expected = f'"{ch}"'
        assert encode_yaml_scalar(ch) == expected, code


def test_encoder_output_shape_for_known_values() -> None:
    assert encode_yaml_scalar("") == '""'
    assert encode_yaml_scalar('a"b\\c') == '"a\\"b\\\\c"'
    assert encode_yaml_scalar("a\tb\nc\rd") == '"a\\tb\\nc\\rd"'
    assert encode_yaml_scalar("\x00") == '"\\u0000"'
    assert encode_yaml_scalar("\x1f\x7f") == '"\\u001f\\u007f"'
    assert encode_yaml_scalar("é😀 ") == '"é😀 "'


def test_encoder_refuses_lone_surrogates() -> None:
    with pytest.raises(ValueError):
        encode_yaml_scalar("bad \ud800 surrogate")


@pytest.mark.parametrize(
    ("literal", "expected"),
    [
        ('"\\\\"', "\\"),
        ('"\\""', '"'),
        ('"\\n"', "\n"),
        ('"\\r"', "\r"),
        ('"\\t"', "\t"),
        ('"\\u0000"', "\x00"),
        ('"\\u0001"', "\x01"),
        ('"\\u000b"', "\x0b"),
        ('"\\u001f"', "\x1f"),
        ('"\\u007f"', "\x7f"),
    ],
)
def test_decoder_accepts_exactly_the_ruled_escapes(literal: str, expected: str) -> None:
    assert decode_yaml_scalar(literal) == expected


@pytest.mark.parametrize(
    ("literal", "construct"),
    [
        ('"\\u0022"', "noncanonical_escape"),  # printable (quote)
        ('"\\u005c"', "noncanonical_escape"),  # printable (backslash)
        ('"\\u000a"', "noncanonical_escape"),  # short-escapable (LF)
        ('"\\u000d"', "noncanonical_escape"),  # short-escapable (CR)
        ('"\\u0009"', "noncanonical_escape"),  # short-escapable (TAB)
        ('"\\u0041"', "noncanonical_escape"),  # printable (A)
        ('"\\u00e9"', "noncanonical_escape"),  # printable non-ASCII
        ('"\\u0080"', "noncanonical_escape"),  # C1 stays literal
        ('"\\u0020"', "noncanonical_escape"),  # space: upper neighbour of U+001F
        ('"\\u007e"', "noncanonical_escape"),  # tilde: lower neighbour of U+007F
        ('"\\u007F"', "noncanonical_escape"),  # uppercase hex on a control char
        ('"\\u001F"', "noncanonical_escape"),  # uppercase hex is non-canonical
        ('"\\ud800"', "surrogate_escape"),
        ('"\\udbff"', "surrogate_escape"),
        ('"\\udc00"', "surrogate_escape"),
        ('"\\uDFFF"', "surrogate_escape"),
        ('"\\u12"', "bad_escape"),
        ('"\\u12zz"', "bad_escape"),
        ('"\\U0001f600"', "bad_escape"),
        ('"\\x41"', "bad_escape"),
        ('"\\/"', "bad_escape"),
        ('"\\b"', "bad_escape"),
        ('"\\f"', "bad_escape"),
        ('"\\0"', "bad_escape"),
        ('"\\ "', "bad_escape"),
        ('"literal\ttab"', "control_character"),
        ('"literal\x7f"', "control_character"),
        ('"unterminated', "unterminated_string"),
        ('"', "unterminated_string"),
        ('"ends\\\\\\"', "unterminated_string"),  # three backslashes: last one escapes the quote
        ('"nul\x00"', "control_character"),
        ('"esc\x1f"', "control_character"),
        ('"lf\n"', "control_character"),
        ('"ends\\"', "unterminated_string"),
        ('"a" "b"', "trailing_garbage"),
        ("bare", "unquoted_value"),
        ("", "empty_value"),
    ],
)
def test_decoder_rejects_non_canonical_and_unsupported_forms(literal: str, construct: str) -> None:
    with pytest.raises(YamlSyntaxError) as info:
        decode_yaml_scalar(literal)
    assert info.value.construct == construct


def test_record_with_control_chars_non_bmp_and_separators_round_trips() -> None:
    value = "tab\there\r\nline\x00nul 😀   \u0085 end\\"
    text = yaml_record_text(token="HO-ESCAPES-20261029", decision_literal=encode_yaml_scalar(value))
    parsed = parse_decision_record(text)
    assert parsed["decision"] == value
    assert parsed["token"] == "HO-ESCAPES-20261029"


def test_crlf_line_endings_parse_identically() -> None:
    lf = yaml_record_text(token="HO-ESCAPES-20261029", scope="repo")
    crlf = yaml_record_text(token="HO-ESCAPES-20261029", scope="repo", eol="\r\n")
    assert parse_decision_record(crlf) == parse_decision_record(lf)
    assert parse_decision_record(lf)["token"] == "HO-ESCAPES-20261029"
