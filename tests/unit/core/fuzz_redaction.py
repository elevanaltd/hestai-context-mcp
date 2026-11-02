"""Planted-secret fuzz harness for the RedactionEngine (#261, #264, #265).

Each case concatenates random noise and FAKE secrets, then checks that no
planted secret survives in the output of each path:

- ``two_pass``: ``clock_out._redact_text`` (DOTALL patterns first, then per line)
- ``whole``: ``RedactionEngine.redact_content`` on the whole text
- ``copy_and_redact``: the archive path, through a temporary file

Two fragment families:

- Hand-written kinds (``KINDS``): sk, aws, gh, bearer, db, db with '@', and
  PEM private keys (terminated, unterminated, lowercase).
- Overlap pairs BUILT FROM ``RedactionEngine.PATTERNS`` (#265 HC): every
  single-line pattern is parsed with ``re._parser``. Tokens are generated from
  the parse tree and validated with ``fullmatch``, and its anchor alternatives
  are enumerated (e.g. ghp_/gho_/ghu_/ghs_/ghr_/github_pat_, AKIA/ASIA). For
  every ordered pair of (pattern, alternative), X's secret ends with a
  k-char prefix of Y's lead for every feasible k (k = 0 is plain abutment),
  then Y continues. Two extra forms: a bare "Bearer " keyword before Y, and Y
  as the user part of a DB URI. A new pattern therefore gets these shapes
  automatically.

A planted secret "survives" if any 8-char window of its random body (or the
whole body, if shorter) appears in the output, so partial leaks count.

Modes:

- ``A``: fragments may abut with no separator (adversarial)
- ``B``: every fragment is followed by at least one separator

Not a test module (no ``test_`` prefix). Reused by
``test_redaction_fuzz_property.py``; run it by hand from the repo root with::

    .venv/bin/python -m tests.unit.core.fuzz_redaction SEED N

Exit status: 0 only when no planted secret survives any path and the two-pass
helper agrees with a whole-text call on every case; 1 otherwise. There is
deliberately no allow-list flag.

SYNTHETIC DATA ONLY: every secret is FAKE and assembled at runtime.
"""

from __future__ import annotations

import collections
import functools
import random
import string
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from re import Match, Pattern
from re import _constants as sre_c  # type: ignore[attr-defined]
from re import _parser as sre_p  # type: ignore[attr-defined]
from typing import Any

from hestai_context_mcp.core.redaction import RedactionEngine
from hestai_context_mcp.tools.clock_out import _redact_text

_DASHES = "-" * 5
SEPARATORS = ["\n", "\r\n", " ", "\t", "\u2028", "\\n", '", "', "\n\n"]
NOISE = [
    "text",
    "mail a" + "@" + "b.org",
    "https://e.test:80/x",
    "BEGIN",
    _DASHES,
    ":",
    "@",
    "{",
    "}",
    "Bearer",
]
KINDS = ["sk", "aws", "gh", "bearer", "db", "db_at", "pk_t", "pk_u", "pk_lower"]
PRIVATE_KEY_KINDS = frozenset({"pk_t", "pk_u", "pk_lower"})
PATHS = ("two_pass", "whole", "copy_and_redact")
_WINDOW = 8

# ---------------------------------------------------------------------------
# Token generation from PATTERNS (#265 HC condition 2/3)
# ---------------------------------------------------------------------------

#: Chars used for negated classes and '.'; letters and digits only, so a
#: generated token never contains a separator, quote or '@' by accident.
#: STRICT edge sentinel (#265 cubic P2): every token-family secret body starts
#: and ends with it, and nothing else in the harness ever produces it (it is
#: excluded from _SAFE and from every random class choice; noise, separators,
#: markers and hand-written values never contain it). So ANY occurrence in an
#: output means an edge character of a bounded-width body survived; this is
#: the any-prefix/any-suffix check that 8-char windows cannot give.
SENTINEL = "Q"
_SAFE = "".join(c for c in string.ascii_letters + string.digits if c != SENTINEL)
#: A class with at most this many chars counts as part of an anchor alternative.
_SMALL_CLASS = 8
_UNBOUNDED_EXTRA = 8
#: Minimum length of an unbounded repeat, so every planted secret body stays
#: distinctive (a 1-char password would "survive" by matching any output text).
_UNBOUNDED_MIN = 16


def single_line_patterns() -> dict[str, Pattern[str]]:
    """Every PATTERNS entry except the stage-1 private_key pattern."""
    return {n: p for n, (p, _) in RedactionEngine.PATTERNS.items() if n != "private_key"}


#: PATTERNS entries that are NOT whole-match token families, each with its reason.
#: Classification is TOTAL (#270 TMG): every PATTERNS entry is either a token
#: family with derivable, non-empty anchors or named here; anything else fails.
NON_TOKEN_PATTERNS: dict[str, str] = {
    "private_key": "stage-1 DOTALL block pattern, redacted first by name; not single-line",
    "bearer_token": "secret is the named group after a kept keyword; chains absorb a keyword",
    "db_password": "secret is the named group before the line's last '@'; one match a line",
}
#: The token families the classifier must find, exactly: adding or removing one
#: must be a deliberate change here, not something the guard silently adapts to.
EXPECTED_TOKEN_FAMILIES: frozenset[str] = frozenset(
    {"ai_api_key", "aws_key", "github_token", "github_pat"}
)


def classify_patterns() -> dict[str, str]:
    """Total classification of PATTERNS: name -> "token" or "excluded". Fails closed.

    Raises AssertionError for a pattern that is neither in NON_TOKEN_PATTERNS
    nor a whole-match pattern whose anchors can all be derived (non-empty),
    e.g. one led by a lookahead, and for a stale NON_TOKEN_PATTERNS entry.
    """
    classes: dict[str, str] = {}
    problems: list[str] = []
    for name, (pattern, _label) in RedactionEngine.PATTERNS.items():
        if name in NON_TOKEN_PATTERNS:
            classes[name] = "excluded"
        elif "secret" in pattern.groupindex:
            problems.append(f"{name}: has a secret group but is not in NON_TOKEN_PATTERNS")
        elif not anchors(name) or not all(anchors(name)):
            problems.append(
                f"{name}: anchors cannot be derived {anchors(name)!r}; classify it explicitly"
            )
        else:
            classes[name] = "token"
    stale = sorted(set(NON_TOKEN_PATTERNS) - set(RedactionEngine.PATTERNS))
    if stale:
        problems.append(f"NON_TOKEN_PATTERNS names unknown patterns: {stale}")
    assert not problems, "unclassifiable PATTERNS (fail closed): " + "; ".join(problems)
    return classes


def is_token_family(name: str) -> bool:
    """A whole-match token pattern with a literal anchor (sk-, AKIA, gh?_, github_pat_)."""
    return classify_patterns()[name] == "token"


def run_class(name: str) -> tuple[frozenset[str], bool]:
    """(chars, unbounded) of the pattern's trailing run, from the parse tree."""
    pattern = single_line_patterns()[name]
    op, av = list(sre_p.parse(pattern.pattern, pattern.flags))[-1]
    if op not in (sre_c.MAX_REPEAT, sre_c.MIN_REPEAT, sre_c.POSSESSIVE_REPEAT):
        raise AssertionError(f"{name}: no trailing run to analyse ({op})")
    lo, hi, sub = av
    (sub_op, sub_av), *rest = list(sub)
    if rest or sub_op is not sre_c.IN:
        raise AssertionError(f"{name}: trailing run is not a single character class")
    return frozenset(_class_chars(sub_av)), hi >= sre_c.MAXREPEAT


def absorbs_own_anchors(name: str) -> bool:
    """True if the trailing run is unbounded and its class holds every anchor char."""
    chars, unbounded = run_class(name)
    return unbounded and all(set(anchor) <= chars for anchor in anchors(name))


def _class_chars(items: list[tuple[Any, Any]]) -> list[str]:
    negate, chars = False, set()
    for op, av in items:
        if op is sre_c.NEGATE:
            negate = True
        elif op is sre_c.LITERAL:
            chars.add(chr(av))
        elif op is sre_c.RANGE:
            chars.update(chr(c) for c in range(av[0], av[1] + 1))
        elif op is sre_c.CATEGORY:
            if av is sre_c.CATEGORY_WORD:
                chars.update(_SAFE + "_")
            elif av is sre_c.CATEGORY_DIGIT:
                chars.update(string.digits)
            elif av is sre_c.CATEGORY_SPACE:
                chars.add(" ")
            else:  # pragma: no cover - not used by PATTERNS today
                raise ValueError(av)
        else:  # pragma: no cover
            raise ValueError(op)
    if negate:
        return [c for c in _SAFE if c not in chars]
    return sorted(chars)


def _has_assert(items: Any) -> bool:
    for op, av in items:
        if op in (sre_c.ASSERT, sre_c.ASSERT_NOT):
            return True
        if op in (sre_c.MAX_REPEAT, sre_c.MIN_REPEAT, sre_c.POSSESSIVE_REPEAT) and _has_assert(
            av[2]
        ):
            return True
        if op is sre_c.SUBPATTERN and _has_assert(av[3]):
            return True
        if op is sre_c.BRANCH and any(_has_assert(alt) for alt in av[1]):
            return True
        if op is sre_c.ATOMIC_GROUP and _has_assert(av):
            return True
    return False


def _emit(items: Any, rng: random.Random, out: list[str]) -> None:
    for op, av in items:
        if op is sre_c.LITERAL:
            out.append(chr(av))
        elif op is sre_c.NOT_LITERAL:
            out.append(rng.choice([c for c in _SAFE if ord(c) != av]))
        elif op is sre_c.ANY:
            out.append(rng.choice(_SAFE))
        elif op is sre_c.IN:
            out.append(rng.choice([c for c in _class_chars(av) if c != SENTINEL]))
        elif op in (sre_c.MAX_REPEAT, sre_c.MIN_REPEAT, sre_c.POSSESSIVE_REPEAT):
            lo, hi, sub = av
            if _has_assert(sub):
                count = lo
            elif hi < sre_c.MAXREPEAT:
                count = rng.randint(lo, hi)
            elif len(sub) == 1 and sub[0][0] is sre_c.LITERAL:
                # A repeated single literal (e.g. '=' padding) carries no entropy:
                # keep it short so its windows never stand in for a secret body.
                count = rng.randint(lo, lo + 2)
            else:
                floor = max(lo, _UNBOUNDED_MIN)
                count = rng.randint(floor, floor + _UNBOUNDED_EXTRA)
            for _ in range(count):
                _emit(sub, rng, out)
        elif op is sre_c.BRANCH:
            _emit(rng.choice(av[1]), rng, out)
        elif op is sre_c.SUBPATTERN:
            _emit(av[3], rng, out)
        elif op is sre_c.ATOMIC_GROUP:
            _emit(av, rng, out)
        elif op in (sre_c.AT, sre_c.ASSERT, sre_c.ASSERT_NOT):
            continue
        else:  # pragma: no cover
            raise ValueError(op)


def _prefixes(items: Any) -> list[str]:
    """Enumerate the literal lead strings (anchor alternatives) of ``items``."""
    results = [""]
    for op, av in items:
        if op is sre_c.LITERAL:
            results = [r + chr(av) for r in results]
        elif op is sre_c.IN and len(_class_chars(av)) <= _SMALL_CLASS:
            results = [r + c for r in results for c in _class_chars(av)]
        elif op is sre_c.BRANCH:
            return [r + a for r in results for alt in av[1] for a in _prefixes(alt)]
        elif op is sre_c.SUBPATTERN:
            inner = _prefixes(av[3])
            return [r + a for r in results for a in inner]
        elif op is sre_c.AT:
            continue
        else:
            break
    return results


@functools.cache
def anchors(name: str) -> tuple[str, ...]:
    """Anchor alternatives of a single-line pattern, derived from PATTERNS."""
    pattern = single_line_patterns()[name]
    return tuple(sorted(set(_prefixes(sre_p.parse(pattern.pattern, pattern.flags)))))


@dataclass(frozen=True)
class Token:
    """A generated token that fullmatches its pattern."""

    name: str
    anchor: str
    text: str
    secret: tuple[int, int]

    @property
    def lead(self) -> str:
        """Text before the secret body: the anchor, or the kept prefix."""
        start = self.secret[0] if self.secret[0] > 0 else len(self.anchor)
        return self.text[:start]


def _secret_span(name: str, match: Match[str]) -> tuple[int, int]:
    pattern = single_line_patterns()[name]
    return match.span("secret") if "secret" in pattern.groupindex else match.span(0)


_POOL_SIZE = 64


def _with_sentinel_edges(token: Token) -> Token:
    """Replace the first and last char of the token's secret body with SENTINEL."""
    start, end = max(token.secret[0], len(token.lead)), token.secret[1]
    if end - start < 2:  # pragma: no cover - bounded bodies are 16+ chars
        return token
    text = token.text[:start] + SENTINEL + token.text[start + 1 : end - 1] + SENTINEL
    return Token(token.name, token.anchor, text + token.text[end:], token.secret)


@functools.cache
def _token_pool(name: str, anchor: str, salt: str = "") -> tuple[Token, ...]:
    """A deterministic pool of tokens of ``name`` starting with ``anchor``.

    ``salt`` selects an independent pool (variants use their own, so a variant
    body never coincides with a pair body and leak attribution stays exact).
    """
    pattern = single_line_patterns()[name]
    parsed = sre_p.parse(pattern.pattern, pattern.flags)
    rng = random.Random(f"pool-{name}-{anchor}-{salt}")
    pool: list[Token] = []
    for _ in range(_POOL_SIZE * 400):
        out: list[str] = []
        _emit(parsed, rng, out)
        text = "".join(out)
        match = pattern.fullmatch(text)
        if match and text.startswith(anchor):
            token = Token(name, anchor, text, _secret_span(name, match))
            if is_token_family(name):
                token = _with_sentinel_edges(token)
                if not pattern.fullmatch(token.text):
                    continue
            pool.append(token)
            if len(pool) == _POOL_SIZE:
                return tuple(pool)
    raise RuntimeError(f"cannot generate {name!r} with anchor {anchor!r}")


def make_token(name: str, anchor: str, rng: random.Random, salt: str = "") -> Token:
    """A token of pattern ``name`` that starts with ``anchor`` (validated by fullmatch)."""
    return rng.choice(_token_pool(name, anchor, salt))


def body(token: Token, cut_tail: int = 0) -> str:
    """The token's random secret body (lead excluded), minus ``cut_tail`` chars."""
    start = max(token.secret[0], len(token.lead))
    return token.text[start : token.secret[1] - cut_tail]


def survives(core: str, out: str) -> bool:
    """True if ``core`` (or any _WINDOW-char window of it) appears in ``out``."""
    if len(core) <= _WINDOW:
        return bool(core) and core in out
    return any(core[i : i + _WINDOW] in out for i in range(len(core) - _WINDOW + 1))


def overlap_fragment(x: Token, y: Token, k: int) -> tuple[str, list[str]] | None:
    """X's secret ends with y.lead[:k], then Y continues; None if infeasible."""
    if k and x.secret[1] != len(x.text):
        return None
    if len(body(x, cut_tail=k)) < _WINDOW:  # X must keep a distinctive body
        return None
    x_text = x.text[: len(x.text) - k] + y.lead[:k]
    pattern = single_line_patterns()[x.name]
    if not pattern.fullmatch(x_text):
        return None
    return x_text + y.text[k:], [body(x, cut_tail=k), body(y)]


def _alternatives() -> list[tuple[str, str]]:
    return [(n, a) for n in single_line_patterns() for a in anchors(n)]


#: (X form, X alternative, Y pattern, Y alternative, k). X form is a pattern
#: name, or "bearer_kw" (a bare "Bearer " before Y) or "db_user" (Y as the
#: user part of a DB URI); those two have no X alternative and k = 0.
PairKind = tuple[str, str, str, str, int]


def pair_label(kind: PairKind) -> str:
    """Human-readable kind label, e.g. "pair:github_token[ghp_]>ai_api_key[sk-]:2"."""
    x, x_alt, y, y_alt, k = kind
    left = x if x in ("bearer_kw", "db_user") else f"{x}[{x_alt}]"
    return f"pair:{left}>{y}[{y_alt}]:{k}"


def _special(form: str, y: Token, rng: random.Random) -> tuple[str, list[str]] | None:
    if form == "bearer_kw":
        return "Bearer " + y.text, [body(y)]
    if ":" in y.text or "@" in y.text:
        return None
    password = "".join(rng.choice(_SAFE) for _ in range(12))
    text = "postgresql://" + y.text + ":" + password + "@db.example.test/app"
    match = single_line_patterns()["db_password"].search(text)
    if not match or match.group("secret") != password:
        return None
    return text, [password, body(y)]


def _draw(kind: PairKind, rng: random.Random) -> tuple[Token | None, Token]:
    x_form, x_alt, y_name, y_alt, _k = kind
    y = make_token(y_name, y_alt, rng)
    if x_form in ("bearer_kw", "db_user"):
        return None, y
    return make_token(x_form, x_alt, rng), y


def _assemble(
    kind: PairKind, x: Token | None, y: Token, rng: random.Random
) -> tuple[str, list[str]] | None:
    x_form, _x_alt, _y_name, _y_alt, k = kind
    if x is None:
        return _special(x_form, y, rng)
    if k and k >= len(y.lead):
        return None
    return overlap_fragment(x, y, k)


_PROBE_DRAWS = 48
_KEEP_SUCCESSES = 8


@functools.cache
def _feasible() -> dict[PairKind, tuple[tuple[Token | None, Token], ...]]:
    """Every feasible pair kind, with token pairs that are known to build it."""
    rng = random.Random("feasible-pair-kinds")
    found: dict[PairKind, tuple[tuple[Token | None, Token], ...]] = {}
    alts = _alternatives()
    for y_name, y_alt in alts:
        max_lead = max(len(t.lead) for t in _token_pool(y_name, y_alt))
        candidates: list[PairKind] = [
            ("bearer_kw", "", y_name, y_alt, 0),
            ("db_user", "", y_name, y_alt, 0),
        ]
        candidates += [(x, xa, y_name, y_alt, k) for x, xa in alts for k in range(max(max_lead, 1))]
        for kind in candidates:
            wins: list[tuple[Token | None, Token]] = []
            for _ in range(_PROBE_DRAWS):
                x, y = _draw(kind, rng)
                if _assemble(kind, x, y, rng):
                    wins.append((x, y))
                    if len(wins) == _KEEP_SUCCESSES:
                        break
            if wins:
                found[kind] = tuple(wins)
    return found


def feasible_pair_kinds() -> tuple[PairKind, ...]:
    """Every pair kind the generator can produce (probed deterministically)."""
    return tuple(_feasible())


def build_pair(kind: PairKind, rng: random.Random) -> tuple[str, list[str]]:
    """A fragment of a feasible ``kind``: random draws first, then a known pair."""
    for _ in range(10):
        x, y = _draw(kind, rng)
        made = _assemble(kind, x, y, rng)
        if made:
            return made
    for x, y in rng.sample(_feasible()[kind], len(_feasible()[kind])):
        made = _assemble(kind, x, y, rng)
        if made:
            return made
    raise RuntimeError(f"cannot build {pair_label(kind)}")  # pragma: no cover


def overlap_pair(rng: random.Random) -> tuple[str, list[str], str]:
    """One overlap-pair fragment of a uniformly chosen feasible kind."""
    kind = rng.choice(feasible_pair_kinds())
    text, cores = build_pair(kind, rng)
    return text, cores, pair_label(kind)


# ---------------------------------------------------------------------------
# Unrecognised-form variants (#269 U1/U2/U3), derived from PATTERNS tokens.
# These shapes are NOT what PATTERNS defines (that is the point of #269):
# - u1_userless_db: a generated db URI with its user part emptied ("scheme://:pw@")
# - u2_bearer_case: a generated bearer value after the keyword in another casing
#   (lower, upper or mixed, never exactly "Bearer"), sometimes chained
#   ("bearer bearer X")
# - u3_overwidth: a whole-match token (every anchored token family) followed by
#   1-8 more chars of its class, ending in SENTINEL, so a surviving excess also
#   fails the strict check
# ---------------------------------------------------------------------------

_U3_EXTRA = "".join(c for c in string.ascii_uppercase + string.digits if c != SENTINEL)
VARIANT_KINDS = ("u1_userless_db", "u2_bearer_case", "u3_overwidth")


def _case_variant(word: str, rng: random.Random) -> str:
    """``word`` in lower, upper or mixed casing, never exactly ``word``."""
    while True:
        style = rng.choice(("lower", "upper", "mixed"))
        if style == "lower":
            variant = word.lower()
        elif style == "upper":
            variant = word.upper()
        else:
            variant = "".join(c.upper() if rng.random() < 0.5 else c.lower() for c in word)
        if variant != word:
            return variant


def variant(rng: random.Random) -> tuple[str, list[str], str]:
    """One unrecognised-form fragment (#269); kind is one of VARIANT_KINDS (+ detail)."""
    form = rng.choice(VARIANT_KINDS)
    if form == "u1_userless_db":
        tok = make_token("db_password", "", rng, salt="variant")
        password = tok.text[tok.secret[0] : tok.secret[1]]
        scheme_end = tok.text.index("://") + 3
        text = tok.text[:scheme_end] + ":" + password + "@cache.example.test/0"
        return text, [password], form
    if form == "u2_bearer_case":
        tok = make_token("bearer_token", "Bearer ", rng, salt="variant")
        value = tok.text[tok.secret[0] : tok.secret[1]]
        prefix = _case_variant("Bearer", rng) + " "
        if rng.random() < 0.3:
            prefix = _case_variant("Bearer", rng) + " " + prefix
        return prefix + value, [value], form
    families = [(n, a) for n in single_line_patterns() if is_token_family(n) for a in anchors(n)]
    name, alt = rng.choice(families)
    tok = make_token(name, alt, rng, salt="variant")
    extra = "".join(rng.choice(_U3_EXTRA) for _ in range(rng.randint(1, 8))) + SENTINEL
    return tok.text + extra, [body(tok) + extra], f"{form}:{name}[{alt}]"


# ---------------------------------------------------------------------------
# Hand-written kinds
# ---------------------------------------------------------------------------


def _secret(rng: random.Random, tag: str) -> tuple[str, list[str], str]:
    """Return (fragment, planted cores that must not survive, kind)."""
    kind = rng.choice(KINDS)
    if kind == "sk":
        core = "TESTONLY" + tag + "R" * 12
        return "sk-" + core, [core], kind
    if kind == "aws":
        # EXACT width (AKIA + 16); sentinel edges (cubic P2: was AKIA + 17).
        core = "AKIA" + SENTINEL + ("TEST" + tag + "Z" * 16)[:14] + SENTINEL
        return core, [core], kind
    if kind == "gh":
        # EXACT width (ghp_ + 36); sentinel edges (cubic P2: was ghp_ + 37).
        core = SENTINEL + ("TESTONLY" + tag + "G" * 36)[:34] + SENTINEL
        return "ghp_" + core, [core], kind
    if kind == "bearer":
        core = "FAKEbearer" + tag + ".val"
        return "Bearer " + core, [core], kind
    if kind in ("db", "db_at"):
        core = "fkPw" + tag + "x9"
        password = core if kind == "db" else "fk@" + core
        return "postgresql://svcuser:" + password + "@db.example.test/app", [core], kind
    lines = ["MIIE" + "FAKE" + tag + "A" * 16, "FAKE" + tag + "B" * 20 + "="]
    lower = kind == "pk_lower"
    header = "rsa private" + " key" if lower else "RSA PRIVATE" + " KEY"
    begin = _DASHES + ("begin " if lower else "BEGIN ") + header + _DASHES
    end = _DASHES + ("end " if lower else "END ") + header + _DASHES
    text = begin + "\n" + "\n".join(lines) + ("" if kind == "pk_u" else "\n" + end)
    return text, lines, kind


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


@dataclass
class FuzzReport:
    """Counts from one seeded run."""

    seed: int
    mode: str
    cases: int = 0
    differ: int = 0
    leaks: collections.Counter[tuple[str, str]] = field(default_factory=collections.Counter)
    generated: collections.Counter[str] = field(default_factory=collections.Counter)

    def leak_total(self, path: str, kinds: frozenset[str] | None = None) -> int:
        """Leaked planted secrets on ``path``, optionally limited to ``kinds``."""
        return sum(n for (p, k), n in self.leaks.items() if p == path and (not kinds or k in kinds))


def run(seed: int, n: int, mode: str, workdir: Path) -> FuzzReport:
    """Run ``n`` seeded cases in ``mode`` ("A" or "B"); temp files go in ``workdir``."""
    rng = random.Random(f"{seed}-{mode}")
    report = FuzzReport(seed=seed, mode=mode)
    glue = SEPARATORS + ([""] * 6 if mode == "A" else [])
    src, dst = workdir / "fuzz-src.txt", workdir / "fuzz-dst.txt"
    for i in range(n):
        parts: list[str] = []
        planted: list[tuple[str, str]] = []
        for j in range(rng.randint(1, 8)):
            roll = rng.random()
            if roll < 0.2:
                fragment, cores, kind = overlap_pair(rng)
                report.generated[kind] += 1
            elif roll < 0.3:
                fragment, cores, kind = variant(rng)
                report.generated[kind] += 1
            elif roll < 0.5:
                fragment, cores, kind = _secret(rng, f"{i:05d}{j}")
            else:
                parts.append(rng.choice(NOISE))
                continue
            parts.append(fragment)
            planted += [(core, kind) for core in cores]
        text = "".join(part + rng.choice(glue) for part in parts)
        two, whole = _redact_text(text), RedactionEngine.redact_content(text)
        src.write_text(text, encoding="utf-8")
        RedactionEngine.copy_and_redact(src, dst)
        outputs = {"two_pass": two, "whole": whole, "copy_and_redact": dst.read_text("utf-8")}
        report.cases += 1
        report.differ += two != whole
        for core, kind in planted:
            for path, out in outputs.items():
                if survives(core, out):
                    report.leaks[(path, kind)] += 1
        for path, out in outputs.items():
            if SENTINEL in out:  # strict: an edge char of a bounded-width body survived
                report.leaks[(path, "strict_bounded_edge")] += out.count(SENTINEL)
    return report


def main(argv: list[str]) -> int:
    """CLI: print the per-mode table for SEED and N; exit 1 on any leak or disagreement."""
    seed, n = int(argv[1]), int(argv[2])
    failed = False
    print("anchor alternatives:", {name: list(anchors(name)) for name in single_line_patterns()})
    with tempfile.TemporaryDirectory() as tmp:
        for mode in ("A", "B"):
            r = run(seed, n, mode, Path(tmp))
            totals = " ".join(f"leak_{p}={r.leak_total(p)}" for p in PATHS)
            covered = len(set(r.generated) & {pair_label(k) for k in feasible_pair_kinds()})
            print(f"mode={mode} seed={seed} cases={r.cases} differ={r.differ} {totals}")
            print(f"   overlap-pair kinds generated: {covered}/{len(feasible_pair_kinds())}")
            for path in PATHS:
                kinds = {k: c for (p, k), c in sorted(r.leaks.items()) if p == path and c}
                print(f"   {path:16s} {kinds}")
            failed |= r.differ > 0 or any(r.leak_total(p) > 0 for p in PATHS)
    print("RESULT:", "FAIL (leak or path disagreement)" if failed else "PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
