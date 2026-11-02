"""Seeded planted-secret property test for the RedactionEngine (#261, #264).

The property (HC condition 1, #264): no planted fake secret of ANY kind
survives ANY path (two-pass helper, whole-text redact_content,
copy_and_redact), and the two-pass helper and a whole-text call agree on
every case. The five #264 anchor-consumption classes are pinned below as
plain tests (they were strict xfails on #261).

Full-size run by hand: ``.venv/bin/python -m tests.unit.core.fuzz_redaction 261 20000``

SYNTHETIC DATA ONLY: every secret is FAKE and assembled at runtime from parts.
"""

from __future__ import annotations

import random
import re
import time
from pathlib import Path

import pytest

from hestai_context_mcp.core.redaction import RedactionEngine
from hestai_context_mcp.tools.clock_out import _redact_text
from tests.unit.core.fuzz_redaction import (
    EXPECTED_TOKEN_FAMILIES,
    PATHS,
    PRIVATE_KEY_KINDS,
    absorbs_own_anchors,
    build_pair,
    classify_patterns,
    feasible_pair_kinds,
    pair_label,
    run,
    single_line_patterns,
    survives,
)

pytestmark = [pytest.mark.unit, pytest.mark.security]

FUZZ_SEED = 261
FUZZ_CASES_PER_MODE = 1000


@pytest.mark.parametrize("mode", ["A", "B"], ids=["abutting", "separated"])
def test_no_planted_secret_survives_any_path_and_paths_agree(tmp_path: Path, mode: str) -> None:
    report = run(FUZZ_SEED, FUZZ_CASES_PER_MODE, mode, tmp_path)
    assert report.cases == FUZZ_CASES_PER_MODE
    for path in PATHS:
        assert report.leak_total(path, PRIVATE_KEY_KINDS) == 0, f"key body leaked via {path}"
        assert report.leak_total(path) == 0, f"a planted secret leaked via {path}"
    assert report.differ == 0, "two-pass helper and whole-text call disagree"


# ---------------------------------------------------------------------------
# #264 anchor-consumption classes: pre-existing (also on the v2 engine)
# ---------------------------------------------------------------------------


def _password() -> str:
    return "fkPw" + "264" + "x9"


def _bearer_value() -> str:
    return "FAKEbearer" + "264"


def _sk_token() -> str:
    return "sk-" + "TESTONLY" + "0" * 20


def _db_uri() -> str:
    return "postgresql://svcuser:" + _password() + "@db.example.test/app"


_RESIDUAL_264 = {
    # B1: bearer_token eats the URI scheme, so db_password cannot anchor.
    "B1_bearer_word_then_db_uri": "Bearer " + _db_uri(),
    # B2: the first match takes "Bearer" as the value; the real token survives.
    "B2_bearer_twice_then_token": "Bearer Bearer " + _bearer_value(),
    # A1: ai_api_key eats the abutting scheme word.
    "A1_sk_token_abutting_db_uri": _sk_token() + _db_uri(),
    # A2: bearer_token's value eats the abutting scheme word.
    "A2_bearer_value_abutting_db_uri": "Bearer " + _bearer_value() + _db_uri(),
    # A3: ai_api_key eats the abutting "Bearer" keyword.
    "A3_sk_token_abutting_bearer": _sk_token() + "Bearer " + _bearer_value(),
    # B3: a bearer value abutting a second "Bearer " eats its keyword (#265 design).
    "B3_bearer_value_abutting_bearer": "Bearer " + "FAKEfirst" + "Bearer " + _bearer_value(),
}


@pytest.mark.parametrize("text", _RESIDUAL_264.values(), ids=_RESIDUAL_264.keys())
def test_residual_264_secret_does_not_survive(text: str) -> None:
    out = RedactionEngine.redact_content(text)
    assert _password() not in out, "db password survived"
    assert _bearer_value() not in out, "bearer token survived"


# ---------------------------------------------------------------------------
# S2 span-union contract (HC ruling on #265, conditions 1-4)
# ---------------------------------------------------------------------------


def _all_paths(text: str, tmp_path: Path) -> list[str]:
    """Outputs of the three redaction paths: two-pass, whole-text, archive."""
    src, dst = tmp_path / "s2-src.txt", tmp_path / "s2-dst.txt"
    src.write_text(text, encoding="utf-8")
    RedactionEngine.copy_and_redact(src, dst)
    return [_redact_text(text), RedactionEngine.redact_content(text), dst.read_text("utf-8")]


def _gh_tail_ending_sk() -> str:
    """A FAKE 36-char GitHub-token tail whose last two chars are "sk"."""
    return "TESTONLY" + "G" * 26 + "sk"


_GH = "[REDACTED_GITHUB_" + "TOKEN]"
_API = "[REDACTED_API_" + "KEY]"
_PW = "[REDACTED_" + "PASSWORD]"
_BR = "[REDACTED_" + "BEARER]"

#: (id, input, exact expected output on every path). Built from fake parts.
_S2_CONTRACT = [
    # Cond 1: PARTIAL overlap (github 0..40, ai 38..65): the union is replaced,
    # no byte of either span survives; label = longest span (github).
    (
        "partial_overlap_github_then_sk",
        "ghp_" + _gh_tail_ending_sk() + "-" + "TESTONLY" + "0" * 16 + " end",
        _GH + " end",
    ),
    # Cond 2: a kept prefix (scheme://user:) never extends into another secret.
    (
        "kept_prefix_user_part_is_sk_token",
        "postgresql://" + _sk_token() + ":" + _password() + "@db.example.test/app",
        "postgresql://" + _API + ":" + _PW + "@db.example.test/app",
    ),
    (
        "kept_prefix_scheme_word_after_sk_token",
        _sk_token() + "postgresql://svcuser:" + _password() + "@db.example.test/app",
        _API + "://svcuser:" + _PW + "@db.example.test/app",
    ),
    # Cond 4: label tie-break on equal spans = PATTERNS order (ai before db/bearer).
    (
        "label_tie_sk_token_is_whole_password",
        "postgresql://svcuser:" + _sk_token() + "@db.example.test/app",
        "postgresql://svcuser:" + _API + "@db.example.test/app",
    ),
    (
        "label_tie_bearer_value_is_sk_token",
        "Bearer " + _sk_token(),
        "Bearer " + _API,
    ),
    # Bearer chain (B2/B3): the whole chain is one secret span.
    ("bearer_twice_exact", "Bearer Bearer " + _bearer_value(), "Bearer " + _BR),
    (
        "bearer_chain_exact",
        "Bearer " + "FAKEfirst" + "Bearer " + _bearer_value(),
        "Bearer " + _BR,
    ),
]


@pytest.mark.parametrize(
    ("text", "expected"),
    [(t, e) for _, t, e in _S2_CONTRACT],
    ids=[i for i, _, _ in _S2_CONTRACT],
)
def test_s2_contract_exact_output_on_every_path(tmp_path: Path, text: str, expected: str) -> None:
    outputs = _all_paths(text, tmp_path)
    for path, out in zip(PATHS, outputs, strict=True):
        assert out == expected, f"unexpected output via {path}"


# ---------------------------------------------------------------------------
# C1: same-pattern partial overlap of a bounded-width pattern (#265 HC ruling)
# ---------------------------------------------------------------------------

_AWS = "[REDACTED_AWS_" + "KEY]"


def _gh_classic_pair(x_alt: str, y_alt: str, k: int) -> str:
    """FAKE: a classic GitHub token whose tail ends with y_alt[:k], then Y's rest."""
    x_tail = ("TESTONLY" + "1" + "G" * 36)[: 36 - k] + y_alt[:k]
    return x_alt + x_tail + y_alt[k:] + ("TESTONLY" + "2" + "H" * 36)[:36]


def _gh_pat_pair(k: int) -> str:
    """FAKE: a fine-grained token whose tail ends with "github_pat_"[:k], then the rest."""
    anchor = "github" + "_pat_"
    x_tail = ("TESTONLY" + "1" + "G" * 82)[: 82 - k] + anchor[:k]
    return anchor + x_tail + anchor[k:] + ("TESTONLY" + "2" + "H" * 82)[:82]


def _aws_pair(x_alt: str, y_alt: str, k: int) -> str:
    """FAKE: an AWS key whose 16-char tail ends with y_alt[:k], then Y's rest."""
    x_tail = ("TEST" + "1" + "Z" * 16)[: 16 - k] + y_alt[:k]
    return x_alt + x_tail + y_alt[k:] + ("TEST" + "2" + "Y" * 16)[:16]


_GH_CLASSIC = ["ghp_", "gho_", "ghu_", "ghs_", "ghr_"]
_C1_CASES = (
    [
        (f"gh_{x}>{y}:{k}", _gh_classic_pair(x, y, k), _GH)
        for x in ("ghp_",)
        for y in _GH_CLASSIC
        for k in (1, 2, 3)
    ]
    + [(f"gh_pat>pat:{k}", _gh_pat_pair(k), _GH) for k in (1, 2, 3)]
    + [
        (f"aws_{x}>{y}:{k}", _aws_pair(x, y, k), _AWS)
        for x in ("AKIA", "ASIA")
        for y in ("AKIA", "ASIA")
        for k in (1, 2, 3)
    ]
)


@pytest.mark.parametrize(
    ("text", "expected"), [(t, e) for _, t, e in _C1_CASES], ids=[i for i, _, _ in _C1_CASES]
)
def test_c1_same_pattern_partial_overlap_redacted_on_every_path(
    tmp_path: Path, text: str, expected: str
) -> None:
    for path, out in zip(PATHS, _all_paths(text, tmp_path), strict=True):
        assert out == expected, f"same-pattern overlap leaked via {path}"


# ---------------------------------------------------------------------------
# Guard (#265 HC condition 3): every bounded-width pattern is an overlapping
# matcher. Both checks are derived FROM PATTERNS, so a new pattern can't skip it.
# ---------------------------------------------------------------------------


def test_token_patterns_absorb_own_anchors_or_are_overlapping() -> None:
    """Structural C1 guard (#269 HC), derived from PATTERNS via the parse tree.

    C1 can reopen exactly when a token match can END inside its own anchor and
    the pattern is not an overlapping matcher. A whole-match token pattern must
    therefore EITHER absorb its own anchors (unbounded trailing run whose class
    holds every anchor char) OR be in OVERLAPPING. Never both: overlap on an
    absorbing run rescans the run from every start (quadratic on repeated
    anchors). No skip path: a parser change fails here, loudly.
    """
    classes = classify_patterns()  # total; fails closed on anything unclassifiable
    families = sorted(n for n, c in classes.items() if c == "token")
    assert (
        set(families) == EXPECTED_TOKEN_FAMILIES
    ), f"token families changed: found {families}, expected {sorted(EXPECTED_TOKEN_FAMILIES)}"
    wrong = []
    for name in families:
        absorbs, overlapping = absorbs_own_anchors(name), name in RedactionEngine.OVERLAPPING
        if absorbs == overlapping:
            wrong.append(f"{name}: absorbs={absorbs} overlapping={overlapping}")
    assert not wrong, "C1 guard: " + "; ".join(wrong)
    assert set(single_line_patterns()) >= RedactionEngine.OVERLAPPING


# --- The guard must FAIL CLOSED (#270 TMG round 1, issuecomment-6585628022) ---

#: TMG's probe: a whole-match token pattern whose anchor sits behind a leading
#: lookahead. Anchor discovery used to return "" for it, so the guard skipped it.
_PROBE_LOOKAHEAD_TOKEN = (re.compile(r"(?=AB_)AB_[A-Z]{16}"), "[REDACTED_PROBE]")


def _guard_with_patterns(monkeypatch: pytest.MonkeyPatch, **changes: object) -> None:
    """Run the structural guard against PATTERNS with ``changes`` (None removes)."""
    for name, value in changes.items():
        if value is None:
            monkeypatch.delitem(RedactionEngine.PATTERNS, name)
        else:
            monkeypatch.setitem(RedactionEngine.PATTERNS, name, value)
    test_token_patterns_absorb_own_anchors_or_are_overlapping()


def test_guard_fails_on_a_lookahead_led_token_pattern(monkeypatch: pytest.MonkeyPatch) -> None:
    # The stakes, reproduced: this pattern really does leak a second token's tail.
    probe = RedactionEngine.PATTERNS.copy()
    probe["probe_token"] = _PROBE_LOOKAHEAD_TOKEN
    variant = type("Probe", (RedactionEngine,), {"PATTERNS": probe})
    out = variant.redact_content("AB_" + "C" * 14 + "AB_" + "Y" * 16)
    assert "Y" * 16 in out, "probe no longer leaks; the fixture no longer shows the risk"
    with pytest.raises(AssertionError, match="anchors cannot be derived"):
        _guard_with_patterns(monkeypatch, probe_token=_PROBE_LOOKAHEAD_TOKEN)


def test_guard_fails_on_an_unclassified_pattern(monkeypatch: pytest.MonkeyPatch) -> None:
    unknown = (re.compile(r"probe=(?P<secret>[A-Z]{12,})"), "[REDACTED_PROBE]")
    with pytest.raises(AssertionError, match="not in NON_TOKEN_PATTERNS"):
        _guard_with_patterns(monkeypatch, probe_secret_group=unknown)


def test_guard_fails_on_an_unexpected_extra_token_family(monkeypatch: pytest.MonkeyPatch) -> None:
    extra = (re.compile(r"xk-[A-Za-z0-9\-]{20,}"), "[REDACTED_PROBE]")
    with pytest.raises(
        AssertionError, match=r"token families changed: found .*'probe_extra_family'"
    ):
        _guard_with_patterns(monkeypatch, probe_extra_family=extra)


def test_guard_fails_when_a_token_family_is_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(
        AssertionError,
        match=r"token families changed: found \['ai_api_key', 'aws_key', 'github_token'\],",
    ):
        _guard_with_patterns(monkeypatch, github_pat=None)


def test_every_same_pattern_overlap_kind_redacted_on_every_path(tmp_path: Path) -> None:
    """Every feasible X>Y kind where X and Y are the same pattern, built from PATTERNS."""
    rng = random.Random("same-pattern-overlap")
    same = [kind for kind in feasible_pair_kinds() if kind[0] == kind[2]]
    assert same
    leaked = []
    for kind in same:
        for _ in range(3):
            made = None
            while made is None:
                made = build_pair(kind, rng)
            text, cores = made
            for path, out in zip(PATHS, _all_paths(text, tmp_path), strict=True):
                if any(survives(core, out) for core in cores):
                    leaked.append((pair_label(kind), path))
    assert not leaked, f"{len(leaked)} same-pattern overlap leaks, e.g. {leaked[:3]}"


# ---------------------------------------------------------------------------
# ReDoS regression guard (#265 TMG condition): these inputs were quadratic on
# the v3 engine (db_password's plain "\w+://" rescanned a long word from every
# start: about 1s at 40k chars, about 20s at 160k). The final engine handles
# each in milliseconds. The 1s bound at 120k chars is deliberately generous so
# a slow CI machine cannot flake it, yet the old pattern exceeds it by about 10x.
# ---------------------------------------------------------------------------

_REDOS_CHARS = 120_000
_REDOS_BOUND_SECONDS = 1.0
_REDOS_FAMILIES = {
    "long_word": lambda n: "a" * n,
    "long_word_then_scheme": lambda n: "a" * n + "://x",
    "aws_anchor_then_uppercase_run": lambda n: "AKIA" + "Z" * n,
    "aws_anchor_run": lambda n: "AKIA" * (n // 4),
    "ghp_anchor_then_alnum_run": lambda n: "ghp_" + "A" * n,
    "ghp_anchor_run": lambda n: ("ghp_" + "A" * 33 + "ghp") * (n // 40),
    "github_pat_underscore_run": lambda n: "github" + "_pat_" * (n // 5),
}


@pytest.mark.parametrize("family", _REDOS_FAMILIES, ids=list(_REDOS_FAMILIES))
def test_redos_guard_adversarial_input_is_linear(family: str) -> None:
    text = _REDOS_FAMILIES[family](_REDOS_CHARS)
    start = time.perf_counter()
    RedactionEngine.redact_content(text)
    elapsed = time.perf_counter() - start
    assert elapsed < _REDOS_BOUND_SECONDS, f"{family}: {elapsed:.2f}s for {len(text)} chars"


def test_db_password_scheme_is_word_bounded_and_possessive() -> None:
    """Structural guard: plain "\\w+://" retries every start inside one word."""
    source = RedactionEngine.PATTERNS["db_password"][0].pattern
    assert source.startswith("(" + "\\b\\w++://"), "db_password scheme must be \\b\\w++://"


# ---------------------------------------------------------------------------
# #269 unrecognised credential forms (HC ruling issuecomment-6582850613).
# Exact kept text is not pinned here; that is part of the design ruling.
# ---------------------------------------------------------------------------


def _pw269() -> str:
    return "fkPw" + "269" + "zzK"


def _tok269() -> str:
    return "FAKEbearer" + "269" + "val"


_U1_CASES = {
    "redis_userless": "redis://:" + _pw269() + "@cache.example.test:6379/0",
    "postgresql_userless": "postgresql://:" + _pw269() + "@db.example.test/app",
}
_U2_CASES = {
    "lower": "bearer " + _tok269(),
    "upper": "BEARER " + _tok269(),
    "mixed": "bEaReR " + _tok269(),
    "authorization_header_lower": "Authorization: bearer " + _tok269(),
    "chain_lower": "bearer bearer " + _tok269(),
    "chain_mixed": "BEARER Bearer " + _tok269(),
}
#: (input, excess that must not survive, marker). ghp_ + 40 and AKIA + 20.
_U3_CASES = {
    "ghp_plus_40": (
        "ghp_" + ("TESTONLY" + "269" + "G" * 40)[:36] + "x9X8",
        "x9X8",
        "[REDACTED_GITHUB_" + "TOKEN]",
    ),
    "akia_plus_20": (
        "AKIA" + ("TEST" + "269" + "Z" * 20)[:16] + "W7V6",
        "W7V6",
        "[REDACTED_AWS_" + "KEY]",
    ),
}


@pytest.mark.parametrize("text", _U1_CASES.values(), ids=list(_U1_CASES))
def test_u1_userless_db_uri_password_redacted_on_every_path(tmp_path: Path, text: str) -> None:
    for path, out in zip(PATHS, _all_paths(text, tmp_path), strict=True):
        assert _pw269() not in out, f"userless-URI password survived via {path}"
        assert _PW in out, f"no password marker via {path}"


@pytest.mark.parametrize("text", _U2_CASES.values(), ids=list(_U2_CASES))
def test_u2_bearer_keyword_any_case_redacted_on_every_path(tmp_path: Path, text: str) -> None:
    for path, out in zip(PATHS, _all_paths(text, tmp_path), strict=True):
        assert _tok269() not in out, f"bearer value survived via {path}"
        assert _BR in out, f"no bearer marker via {path}"


@pytest.mark.parametrize(("text", "excess", "marker"), _U3_CASES.values(), ids=list(_U3_CASES))
def test_u3_overwidth_run_redacted_whole_on_every_path(
    tmp_path: Path, text: str, excess: str, marker: str
) -> None:
    for path, out in zip(PATHS, _all_paths(text, tmp_path), strict=True):
        assert excess not in out, f"over-width excess survived via {path}"
        assert marker in out, f"no marker via {path}"
