"""db_password matching is linear on long lines, with unchanged output (#266).

``finditer`` with the db_password regex was quadratic on one long line: every
``scheme://`` candidate scanned its password to the end of the line before
failing. 400k chars took about 70s with no '@', with an '@' first on the line,
and on ordinary ``https://host:443/p`` URLs. The engine now runs each pattern
named in ``RedactionEngine.LAST_AT_BOUNDED`` per line, with a search window
that ends just after the line's last '@' (HC ruling on #266). The regex string
is unchanged.

This module pins three things:

1. The ``re`` behaviour the equivalence argument relies on (HC points 2, 3):
   ``\\Z`` matches at ``endpos`` and a lookahead cannot see past it; ``\\b``
   at ``pos`` reads the real preceding character; no line separator is ``\\w``.
2. A permanent DIFFERENTIAL: for every name in ``LAST_AT_BOUNDED``, the live
   pattern's ``finditer`` against the bounded strategy (every group span), and
   the whole ``RedactionResult`` against an engine with the strategy turned
   off. A new ``LAST_AT_BOUNDED`` entry fails here unless its matches always
   end at the line's last '@'.
3. A timing guard at 400k chars for both URI forms: the user form (main) and
   the userless form #270 adds (an engine with replaced PATTERNS). The 1s
   bound is generous: the bounded strategy takes about 10ms; the old strategy,
   a line-'@'-prefilter only, and one whole-text window each exceed it.

SYNTHETIC DATA ONLY: every credential-like string is FAKE.
"""

from __future__ import annotations

import itertools
import random
import re
import time
from collections.abc import Iterator
from re import Match, Pattern

import pytest

from hestai_context_mcp.core.redaction import _LINE_SEPARATORS, RedactionEngine
from tests.unit.core.fuzz_redaction import anchors, make_token

pytestmark = [pytest.mark.unit, pytest.mark.security]

#: Every single line separator character, plus CRLF.
_SEPARATOR_CHARS: list[str] = re.findall(rf"[{_LINE_SEPARATORS}]", "".join(map(chr, range(0x3000))))
SEPARATORS: list[str] = [*_SEPARATOR_CHARS, "\r\n"]

_DB_LABEL = RedactionEngine.PATTERNS["db_password"][1]
_USER_SOURCE = RedactionEngine.PATTERNS["db_password"][0].pattern
#: #270's userless form: the user part may be empty. A no-op once #270 lands.
_USERLESS_SOURCE = _USER_SOURCE.replace(
    f"[^:{_LINE_SEPARATORS}]+:)", f"[^:{_LINE_SEPARATORS}]*:)", 1
)


def _variant(db_source: str, *, bounded: bool) -> type[RedactionEngine]:
    """The engine with db_password compiled from ``db_source``; ``bounded=False``
    turns the per-line strategy off for every pattern (the reference)."""
    patterns = dict(RedactionEngine.PATTERNS)
    patterns["db_password"] = (re.compile(db_source), _DB_LABEL)
    namespace: dict[str, object] = {"PATTERNS": patterns}
    if not bounded:
        namespace["LAST_AT_BOUNDED"] = frozenset()
    return type("Variant", (RedactionEngine,), namespace)


FORMS: dict[str, type[RedactionEngine]] = {
    "user": RedactionEngine,
    "userless": _variant(_USERLESS_SOURCE, bounded=True),
}
REFERENCES: dict[str, type[RedactionEngine]] = {
    "user": _variant(_USER_SOURCE, bounded=False),
    "userless": _variant(_USERLESS_SOURCE, bounded=False),
}

# ---------------------------------------------------------------------------
# 1. The re behaviour the equivalence argument relies on (HC points 2 and 3)
# ---------------------------------------------------------------------------


def test_backslash_z_matches_at_endpos_and_lookahead_stops_there() -> None:
    assert re.compile(r"a\Z").search("ab", 0, 1) is not None
    assert re.compile(r"a(?=b)").search("ab", 0, 1) is None


def test_word_boundary_at_pos_reads_the_real_preceding_char() -> None:
    assert re.compile(r"\bb").search("ab", 1) is None
    assert re.compile(r"\bb").search("-b", 1) is not None


def test_no_line_separator_is_a_word_char() -> None:
    assert len(_SEPARATOR_CHARS) == 10
    assert [c for c in _SEPARATOR_CHARS if re.match(r"\w", c)] == []


# ---------------------------------------------------------------------------
# 2. Differential: bounded strategy == finditer, byte for byte
# ---------------------------------------------------------------------------

_PW = "fkPw9x"
HAND: list[str] = [
    f"postgresql://svc:{_PW}@db.test/app",
    f"postgresql://svc:fk@{_PW}@db.test/app",  # password contains '@'
    f"postgresql://svc:a@b@c@{_PW}@db.test/app",
    f"a://u:{_PW}@h b://v:{_PW}2@h2",  # two URIs on one line
    f"a://u:{_PW}@h b://v:{_PW}2@h2 tail",
    f"@ a://u:{_PW}@h",  # '@' before
    f"a://u:{_PW} @ b://v:{_PW}2",  # '@' between
    f"a://u:{_PW} b://v:{_PW}2 @",  # '@' after
    f"a://u:{_PW} b://v:{_PW}2@",
    f"@a://u:{_PW}",
    "a://u:@h",
    "a://:p@h",
    "a://:@h",
    "a://u:p",
    "a://u@h",
    "a://u:p@",
    "xa://u:p@h",
    "-a://u:p@h",
    "\u00e9://\u00fc:p@h",
    "a://u:p@h a://u:p@h a://u:p@h",
    "a:/u:p@h a://u:p@h",
    "a://u:p:q:r@h@",
    "https://host:443/p https://host:443/p @",
    "https://host:443/p @ https://host:443/p",
    "@ https://host:443/p https://host:443/p",
    "",
    "@",
    "@@@",
    "://u:p@h",
    "a://:",
    "a://u:@",
]
for _sep in SEPARATORS:  # every separator, in every position around the URI and the '@'
    HAND += [
        f"a://u:{_PW}{_sep}@h",
        f"a://u:{_PW}@h{_sep}@",
        f"@{_sep}a://u:{_PW}@h",
        f"a://u:{_PW}@h{_sep}b://v:{_PW}2@h2",
        f"a://u{_sep}:{_PW}@h",
        f"a://{_sep}u:{_PW}@h",
        f"a:{_sep}//u:{_PW}@h",
        f"a://u:{_PW}@{_sep}",
        f"{_sep}a://u:{_PW}@h{_sep}",
        f"a://u:{_PW}@h{_sep}{_sep}a://:{_PW}@h",
        f"a://u:p@q{_sep}r@s",
    ]

_TOKENS = [
    "a://",
    "u",
    ":",
    "p",
    "@",
    " ",
    "\u00e9",
    "://",
    "a://u:",
    "https://h:443/p",
    *SEPARATORS,
]
_ALPHABET = [
    *"au:p@/ x_\u00e9-.",
    "://",
    "a://",
    "a://u:",
    "a://:",
    "https://h:443/p",
    "@h",
    *SEPARATORS,
]
DIFFERENTIAL_SEEDS = (261, 7, 99)
_RANDOM_CASES_PER_SEED = 3000


def _inputs(names: frozenset[str]) -> Iterator[str]:
    """Hand-written cases, every token sequence up to 3, seeded random text,
    and generated tokens of every bounded pattern embedded in hostile noise."""
    yield from HAND
    for k in range(4):
        for seq in itertools.product(_TOKENS, repeat=k):
            yield "".join(seq)
    for seed in DIFFERENTIAL_SEEDS:
        rng = random.Random(f"266-{seed}")
        for _ in range(_RANDOM_CASES_PER_SEED):
            yield "".join(rng.choice(_ALPHABET) for _ in range(rng.randint(0, 40)))
        for name in sorted(names):
            for _ in range(200):
                parts = [make_token(name, rng.choice(anchors(name)), rng).text for _ in range(2)]
                noise = [rng.choice(_ALPHABET) for _ in range(4)]
                pieces = parts + noise
                rng.shuffle(pieces)
                yield "".join(pieces)


def _group_spans(match: Match[str]) -> tuple[tuple[int, int], ...]:
    return tuple(match.span(g) for g in range(match.re.groups + 1))


def test_db_password_runs_last_at_bounded() -> None:
    assert "db_password" in RedactionEngine.LAST_AT_BOUNDED


def test_differential_every_bounded_pattern_matches_like_finditer() -> None:
    """Every group span of every match equals plain ``finditer``'s, for every
    pattern in LAST_AT_BOUNDED (and #270's userless db form)."""
    from hestai_context_mcp.core.redaction import _last_at_bounded

    names = RedactionEngine.LAST_AT_BOUNDED
    patterns: list[Pattern[str]] = [RedactionEngine.PATTERNS[name][0] for name in sorted(names)]
    patterns.append(re.compile(_USERLESS_SOURCE))
    matched = diffs = 0
    first: list[str] = []
    for text in _inputs(names):
        for pattern in patterns:
            expected = [_group_spans(m) for m in pattern.finditer(text)]
            actual = [_group_spans(m) for m in _last_at_bounded(pattern, text)]
            matched += bool(expected)
            if expected != actual:
                diffs += 1
                first.append(f"{pattern.pattern[:30]!r} on {text!r}: {expected} != {actual}")
    assert diffs == 0, first[:5]
    assert (
        matched > 1000
    ), f"differential is near-vacuous: {matched} (pattern, input) pairs with a match"


@pytest.mark.parametrize("form", FORMS)
def test_differential_engine_output_equals_strategy_off(form: str) -> None:
    """The whole RedactionResult is identical to an engine whose LAST_AT_BOUNDED
    is empty (plain finditer for every pattern)."""
    engine, reference = FORMS[form], REFERENCES[form]
    diffs = [
        t
        for t in _inputs(RedactionEngine.LAST_AT_BOUNDED)
        if engine._redact(t) != reference._redact(t)
    ]
    assert diffs == [], [repr(t) for t in diffs[:5]]


# ---------------------------------------------------------------------------
# 3. Timing guard: linear on every long-line family, both URI forms
# ---------------------------------------------------------------------------

_GUARD_CHARS = 400_000
_GUARD_BOUND_SECONDS = 1.0
#: Line width for the many-lines family (HC: 40k, so a whole-text window fails
#: the bound by a clear margin; 10k lines gave under 2x).
_WIDE_LINE = 40_000
UNITS = {"user": "a://u:p ", "userless": "a://:p "}
_URL = "https://host:443/p "


def _rep(unit: str, n: int) -> str:
    return unit * (n // len(unit))


def _many_lines(unit: str, n: int) -> str:
    lines: list[str] = []
    size = 0
    while size < n:
        lines.append("@" + _rep(unit, _WIDE_LINE) + SEPARATORS[len(lines) % len(SEPARATORS)])
        size += len(lines[-1])
    return "".join(lines)


SHAPES = {
    "no_at": lambda u, n: _rep(u, n),
    "at_first": lambda u, n: "@" + _rep(u, n),
    "at_last": lambda u, n: _rep(u, n) + "@",
    "at_mid": lambda u, n: _rep(u, n // 2) + "@" + _rep(u, n // 2),
    "many_wide_lines_at_first": _many_lines,
    "port_urls_no_at": lambda u, n: _rep(_URL, n),
    "port_urls_at_first": lambda u, n: "@" + _rep(_URL, n),
}


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("form", FORMS)
def test_db_password_is_linear_on_long_lines(form: str, shape: str) -> None:
    text = SHAPES[shape](UNITS[form], _GUARD_CHARS)
    start = time.perf_counter()
    FORMS[form].redact_content(text)
    elapsed = time.perf_counter() - start
    assert elapsed < _GUARD_BOUND_SECONDS, f"{form}/{shape}: {elapsed:.2f}s for {len(text)} chars"
