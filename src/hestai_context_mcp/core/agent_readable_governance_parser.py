"""Agent-Readable Governance Record (AGR) structured extraction.

RFC #40 / ADR-RFC-ARCH-004 §1.2: turn one DECISION_RECORD ``.oct.md`` document's
TEXT into a structured dict (PROD I4) so the read tools (lookup_decision /
list_decisions / trace_supersedure) and the Payload Compiler can extract fields
programmatically without re-implementing parsing at each consumer.

Design invariants (mirrors ``core.north_star_parser`` exactly)
--------------------------------------------------------------
* **Pure function** (PROD I5) — text in, dict out. No filesystem access, no
  side effects, DEBUG logging only on malformed input; never raises.
* **Provider-agnostic** (PROD I3) — parses the OCTAVE DECISION_RECORD shape,
  not any provider-specific representation; identical results across providers.
* **Regex-only** (North Star §4 / PROD I3) — no OCTAVE AST parsing, no ``ast``
  import, no octave-mcp invocation, no LLM. Deterministic for identical text.

Format understood
-----------------
The canonical DECISION_RECORD envelope (§1.1)::

    ===DECISION_RECORD===
    META:
      TYPE::DECISION_RECORD
      VERSION::"1.0"
      TOKEN::<TOKEN>            # bare canonical, OR legacy quoted TOKEN::"<TOKEN>"
      STATUS::RATIFIED
      TIER::STRATEGIC
      AUTHORED_AT::"<ISO-8601>"
      DECISION::"<sentence>"
      BECAUSE::"<sentence>"
      ...optional fields...
    ===END===

Quote-optionality (§1.1): values may be bare or double-quoted; the parser strips
a single surrounding pair of double quotes from extracted values.

Quoted-YAML front matter (PR-4 slice A)
---------------------------------------
A record whose FIRST line is ``---`` is read as a quoted-YAML front-matter
record instead (regex-only; PyYAML is never imported)::

    ---
    type: "DECISION_RECORD"
    token: "HO-EXAMPLE-20261029"
    ...
    ---
    (markdown body — ignored)

Every fenced line is ``lowercase_key: "one-line double-quoted value"`` where the
only escapes are ``\\"`` and ``\\\\``. Keys are uppercase-mapped into the same
:class:`DecisionRecord` shape the OCTAVE path yields. The adapter FAILS CLOSED:
any other construct inside the fences (unquoted value, other escape, block or
multi-line scalar, flow collection, anchor, comment, duplicate key, indentation,
a missing closing fence, or the reserved ``current`` / ``rulings`` topic-block
keys until the YAML topic-block slice lands) yields the empty (unparseable)
record, never a half-read one.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from typing import TypedDict

logger = logging.getLogger(__name__)


class DecisionRecord(TypedDict):
    """Structured extraction of one DECISION_RECORD AGR document.

    The eight core fields map to the §1.2 required fields (plus TYPE/VERSION).
    ``fields`` carries every OTHER present ``KEY::value`` META pair (core fields
    are NOT duplicated into it; ``SUPERSEDED_BY`` IS surfaced there so the read
    tools can build the resolution chain). Core fields are ``None`` when absent
    so the shape is stable (PROD I4) and the tools can detect parse failures.
    """

    token: str | None
    type: str | None
    version: str | None
    status: str | None
    tier: str | None
    decision: str | None
    because: str | None
    authored_at: str | None
    fields: dict[str, str]


# The §1.2 core fields that are surfaced as top-level keys. Everything else
# present in the META block lands in ``fields`` (including SUPERSEDED_BY).
_CORE_FIELDS = (
    "TYPE",
    "VERSION",
    "TOKEN",
    "STATUS",
    "TIER",
    "DECISION",
    "BECAUSE",
    "AUTHORED_AT",
)

# A single ``KEY::value`` OCTAVE assignment at line start (whitespace-tolerant —
# OCTAVE bodies are indented). KEY is an uppercase OCTAVE identifier; the value
# is the rest of the line. List-valued fields (e.g. AMENDS::[A, B]) are captured
# raw and left to the caller; the read tools only need scalar core fields plus
# SUPERSEDED_BY (scalar). This is regex-only — no structural OCTAVE parsing.
_FIELD_LINE_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)::(.*?)\s*$")


# Topic-record blocks (ADR-RFC-ARCH-004 v1.3 §1.7). ``CURRENT:`` / ``RULINGS:``
# open a block; the block runs while following lines are blank or indented
# deeper than the header. Regex + indent only — no structural OCTAVE parsing.
# Only a header at the record's top-level indentation (column 0) opens a block;
# a header-shaped line deeper than that is just a line of the enclosing block
# (or of META) and can neither open nor reset a block.
_BLOCK_HEADER_RE = re.compile(r"^()(CURRENT|RULINGS):\s*$")
_RULING_ENTRY_RE = re.compile(r"^\s*(R\d+):\s*$")
_CURRENT_ENTRY_RE = re.compile(r"^\s*(R\d+)::(.*?)\s*$")
_RULING_FIELDS = ("rule", "verbatim", "ruled", "replaces")
# YAML spellings (lowercase headers/keys, one-line quoted scalars) of the same blocks.
_YAML_BLOCK_HEADER_RE = re.compile(r"^()(current|rulings):\s*$")
_YAML_CURRENT_ENTRY_RE = re.compile(r"^\s*(R\d+):[ ]+(.*?)\s*$")
_YAML_RULING_FIELD_RE = re.compile(r"^\s*(rule|verbatim|ruled|replaces):[ ]+(.*?)\s*$")


class CurrentEntry(TypedDict):
    """One in-force rule from the ``CURRENT`` block."""

    id: str
    rule: str


class RulingEntry(TypedDict):
    """One ``RULINGS`` entry: the rule, the operator's words, provenance."""

    id: str
    rule: str | None
    verbatim: str | None
    ruled: str | None
    replaces: str | None


class TopicBlocks(TypedDict):
    """Ordered ``CURRENT`` and ``RULINGS`` content of a topic record."""

    current: list[CurrentEntry]
    rulings: list[RulingEntry]


def _text_lines(text: str, yaml: bool) -> list[str]:
    """Lines of ``text`` with line endings kept; YAML splits on LF only (see B2)."""
    if not yaml:
        return text.splitlines(keepends=True)
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def annotate_lines(text: str) -> Iterator[tuple[str | None, str]]:
    """Yield ``(block_name | None, line)`` for every line of ``text``.

    ``block_name`` is ``CURRENT`` / ``RULINGS`` for lines inside such a block
    (headers excluded) and ``None`` elsewhere. A block ends at the first
    non-blank line indented no deeper than its header. One routine serves both
    syntaxes: OCTAVE uses the uppercase ``CURRENT:`` / ``RULINGS:`` headers over
    the whole text; a YAML front-matter record (first line ``---``) uses the
    lowercase headers INSIDE its fences only, so the markdown body can never open
    a block. OCTAVE behaviour is unchanged.
    """
    yaml = is_yaml_front_matter(text)
    header_re = _YAML_BLOCK_HEADER_RE if yaml else _BLOCK_HEADER_RE
    block: str | None = None
    header_indent = 0
    in_fence = False
    for index, line in enumerate(_text_lines(text, yaml)):
        if yaml:
            if index == 0:
                in_fence = True
                yield None, line
                continue
            if in_fence and line.rstrip() == _YAML_FENCE:
                in_fence = False
                block = None
            if not in_fence:
                yield None, line
                continue
        header = header_re.match(line)
        if header:
            block = header.group(2).upper()
            header_indent = len(header.group(1))
            yield None, line
            continue
        if block is not None and line.strip() and len(line) - len(line.lstrip()) <= header_indent:
            block = None
        yield (block if line.strip() else None), line


def iter_block_lines(text: str) -> Iterator[tuple[str, str]]:
    """Yield ``(block_name, line)`` for every line inside a CURRENT/RULINGS block.

    Pure and regex-only; shared by the parser (to keep block lines out of META
    ``fields``) and by Gate A (to reject reserved top-level keys nested in a
    block).
    """
    for block, line in annotate_lines(text):
        if block is not None:
            yield block, line


def _match_current(line: str, yaml: bool) -> tuple[str, str] | None:
    """``(id, rule)`` of a CURRENT entry line in either syntax, else ``None``."""
    if not yaml:
        cur = _CURRENT_ENTRY_RE.match(line)
        return (cur.group(1), _strip_quotes(cur.group(2))) if cur else None
    ycur = _YAML_CURRENT_ENTRY_RE.match(line)
    if not ycur:
        return None
    try:
        return ycur.group(1), decode_yaml_scalar(ycur.group(2))
    except YamlSyntaxError:
        return None


def _match_ruling_field(line: str, yaml: bool) -> tuple[str, str] | None:
    """``(lowercase key, value)`` of a RULINGS field line in either syntax, else ``None``."""
    if not yaml:
        field = _FIELD_LINE_RE.match(line)
        return (field.group(1).lower(), _strip_quotes(field.group(2))) if field else None
    yfield = _YAML_RULING_FIELD_RE.match(line)
    if not yfield:
        return None
    try:
        return yfield.group(1), decode_yaml_scalar(yfield.group(2))
    except YamlSyntaxError:
        return None


def collect_topic_blocks(text: str | None) -> TopicBlocks:
    """Collect the ordered CURRENT and RULINGS blocks of a topic record.

    Pure, regex-only, never raises. Absent blocks yield empty lists. A RULINGS
    entry always carries all five keys; ``replaces`` is ``None`` when absent.
    Works on OCTAVE and YAML front-matter records alike (a YAML line that does
    not decode is skipped here; ``diagnose_yaml_record`` is what reports it).
    """
    result: TopicBlocks = {"current": [], "rulings": []}
    if not text or not text.strip():
        return result

    yaml = is_yaml_front_matter(text)
    entry: RulingEntry | None = None
    for block, line in iter_block_lines(text):
        if block == "CURRENT":
            cur = _match_current(line, yaml)
            if cur:
                result["current"].append({"id": cur[0], "rule": cur[1]})
            continue
        start = _RULING_ENTRY_RE.match(line)
        if start:
            entry = {
                "id": start.group(1),
                "rule": None,
                "verbatim": None,
                "ruled": None,
                "replaces": None,
            }
            result["rulings"].append(entry)
            continue
        field = _match_ruling_field(line, yaml)
        if field and entry is not None and field[0] in _RULING_FIELDS:
            entry[field[0]] = field[1]  # type: ignore[literal-required]
    return result


def _strip_quotes(value: str) -> str:
    """Strip one surrounding pair of double quotes from a value (§1.1).

    ``"1.0"`` -> ``1.0``; ``bare`` -> ``bare``. Only a matched leading+trailing
    pair is removed so inner quotes (rare) survive.
    """
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def _empty_record() -> DecisionRecord:
    """The stable all-``None`` record returned for empty or unparseable input."""
    return {
        "token": None,
        "type": None,
        "version": None,
        "status": None,
        "tier": None,
        "decision": None,
        "because": None,
        "authored_at": None,
        "fields": {},
    }


def parse_decision_record(text: str | None) -> DecisionRecord:
    """Parse a DECISION_RECORD AGR document into a structured dict.

    Pure function — text in, structured dict out. Graceful on empty, ``None``,
    whitespace-only, and malformed input (returns a stable empty-ish result and
    DEBUG-logs on parse exceptions; never raises).

    Args:
        text: Raw DECISION_RECORD ``.oct.md`` document text, or ``None``.

    Returns:
        A :class:`DecisionRecord`. All nine keys are always present. Core fields
        are ``None`` when absent/unparseable; ``fields`` is ``{}`` in that case.
    """
    empty = _empty_record()

    if not text or not text.strip():
        return empty

    try:
        return _parse_impl(text)
    except Exception as exc:  # pragma: no cover - defensive only
        logger.debug("agent_readable_governance_parser: parse failed: %s", exc)
        return empty


_YAML_FENCE = "---"


class YamlReject(TypedDict):
    """Where and why a YAML front-matter record was rejected (1-based ``line``)."""

    line: int
    construct: str


class YamlSyntaxError(ValueError):
    """A construct outside the strict quoted-YAML subset; ``construct`` is a stable name."""

    def __init__(self, construct: str, detail: str = "") -> None:
        super().__init__(f"{construct}: {detail}" if detail else construct)
        self.construct = construct


# ONE escape table (B2 ruling): short escapes decode from / encode to this mapping.
# ``\uXXXX`` is the canonical form ONLY for control characters with no short escape.
_YAML_SHORT_ESCAPES = {"\\": "\\", '"': '"', "n": "\n", "r": "\r", "t": "\t"}
_YAML_SHORT_ENCODE = {char: letter for letter, char in _YAML_SHORT_ESCAPES.items()}
_YAML_LOWER_HEX_RE = re.compile(r"[0-9a-f]{4}")
_YAML_ANY_HEX_RE = re.compile(r"[0-9a-fA-F]{4}")
_YAML_KEY_RE = re.compile(r"^([a-z][a-z0-9_]*):(.*)$")
_YAML_TYPE_LINE_RE = re.compile(r'^type:[ ]+"DECISION_RECORD"[ \t]*$')
_YAML_TOKEN_LINE_RE = re.compile(r'^token:[ ]+"([^"\\]+)"[ \t]*$')
_YAML_BLOCK_KEYS = frozenset({"current", "rulings"})


def _is_control(codepoint: int) -> bool:
    """C0 controls and DEL: the characters a quoted scalar may never carry literally."""
    return codepoint < 0x20 or codepoint == 0x7F


def _needs_unicode_escape(char: str) -> bool:
    """True for controls with NO short escape: the only chars ``\\uXXXX`` may spell."""
    return _is_control(ord(char)) and char not in _YAML_SHORT_ENCODE


def encode_yaml_scalar(value: str) -> str:
    """Canonically encode ``value`` as a one-line double-quoted YAML scalar.

    Pure. Short escapes for ``\\ " LF CR TAB``; ``\\uXXXX`` (four lowercase hex
    digits) for the remaining C0 controls and DEL; every other character
    (including non-BMP text) is written literally as UTF-8. Raises ``ValueError``
    for a lone surrogate, which has no UTF-8 form. ``decode_yaml_scalar`` inverts
    it exactly, and ``encode(decode(encode(x))) == encode(x)``.
    """
    out = ['"']
    for char in value:
        if char in _YAML_SHORT_ENCODE:
            out.append("\\" + _YAML_SHORT_ENCODE[char])
        elif _needs_unicode_escape(char):
            out.append(f"\\u{ord(char):04x}")
        elif 0xD800 <= ord(char) <= 0xDFFF:
            raise ValueError("lone surrogate cannot be encoded; use literal UTF-8 text")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def decode_yaml_scalar(literal: str) -> str:
    """Decode one strict double-quoted scalar literal, or raise :class:`YamlSyntaxError`.

    Accepts EXACTLY the :data:`_YAML_SHORT_ESCAPES` plus canonical ``\\uXXXX``;
    everything else raises with a stable ``construct`` name. Pure, regex/scan only.
    """
    text = literal.lstrip(" ")
    if not text:
        raise YamlSyntaxError("empty_value")
    first = text[0]
    indicators = {
        "|": "block_scalar",
        ">": "block_scalar",
        "[": "flow_collection",
        "{": "flow_collection",
        "&": "anchor",
        "*": "alias",
        "!": "tag",
        "#": "comment",
    }
    if first in indicators:
        raise YamlSyntaxError(indicators[first])
    if first != '"':
        raise YamlSyntaxError("unquoted_value")

    out: list[str] = []
    i = 1
    while True:
        if i >= len(text):
            raise YamlSyntaxError("unterminated_string")
        char = text[i]
        if char == '"':
            break
        if char == "\\":
            i = _decode_escape(text, i, out)
            continue
        if _is_control(ord(char)):
            raise YamlSyntaxError("control_character", f"U+{ord(char):04X}")
        out.append(char)
        i += 1
    rest = text[i + 1 :].strip()
    if rest.startswith("#"):
        raise YamlSyntaxError("comment")
    if rest:
        raise YamlSyntaxError("trailing_garbage")
    return "".join(out)


def _decode_escape(text: str, i: int, out: list[str]) -> int:
    """Decode the escape starting at ``text[i] == '\\'``; return the next index."""
    if i + 1 >= len(text):
        raise YamlSyntaxError("unterminated_string")
    letter = text[i + 1]
    if letter in _YAML_SHORT_ESCAPES:
        out.append(_YAML_SHORT_ESCAPES[letter])
        return i + 2
    if letter != "u":
        raise YamlSyntaxError("bad_escape", f"\\{letter}")
    digits = text[i + 2 : i + 6]
    if not _YAML_ANY_HEX_RE.fullmatch(digits):
        raise YamlSyntaxError("bad_escape", "\\u needs four hex digits")
    codepoint = int(digits, 16)
    if 0xD800 <= codepoint <= 0xDFFF:
        raise YamlSyntaxError("surrogate_escape", f"\\u{digits}")
    if not _YAML_LOWER_HEX_RE.fullmatch(digits) or not _needs_unicode_escape(chr(codepoint)):
        raise YamlSyntaxError("noncanonical_escape", f"\\u{digits}")
    out.append(chr(codepoint))
    return i + 6


def _split_yaml_lines(text: str) -> list[str]:
    """Split on LF only (tolerating CRLF); exotic Unicode separators stay inside values."""
    return [line[:-1] if line.endswith("\r") else line for line in text.split("\n")]


def _yaml_opening_lines(text: str) -> list[str] | None:
    """Lines after an opening ``---`` up to the closing fence (or EOF if unclosed)."""
    lines = _split_yaml_lines(text)
    if lines[0].rstrip() != _YAML_FENCE:
        return None
    body: list[str] = []
    for line in lines[1:]:
        if line.rstrip() == _YAML_FENCE:
            break
        body.append(line)
    return body


def is_yaml_front_matter(text: str | None) -> bool:
    """True iff ``text`` opens with a ``---`` fence line (YAML-syntax record)."""
    return bool(text) and _split_yaml_lines(text or "")[0].rstrip() == _YAML_FENCE


def has_yaml_decision_header(text: str | None) -> bool:
    """True iff ``text`` opens with ``---`` and declares ``type: "DECISION_RECORD"``.

    Scoping signal only (like the OCTAVE ``TYPE::DECISION_RECORD`` check): it is
    True for a malformed YAML record too, so such a record surfaces as
    unparseable rather than being silently out of scope. Lines after the closing
    fence are never consulted. Pure, regex-only.
    """
    if not text:
        return False
    fenced = _yaml_opening_lines(text)
    return fenced is not None and any(_YAML_TYPE_LINE_RE.match(line) for line in fenced)


def extract_yaml_token(text: str | None) -> str | None:
    """Return the fenced ``token: "…"`` value of a YAML record, else ``None``.

    Independent of whole-record parseability so a malformed record can still be
    located by TOKEN and reported as RECORD_PARSE_FAILED. Body is ignored.
    """
    if not text:
        return None
    fenced = _yaml_opening_lines(text)
    if fenced is None:
        return None
    for line in fenced:
        match = _YAML_TOKEN_LINE_RE.match(line)
        if match:
            return match.group(1)
    return None


def _split_yaml_pair(line: str) -> tuple[str, str]:
    """Split a top-level fenced line into ``(key, rest-after-colon)`` or raise."""
    if line[:1] in (" ", "\t"):
        raise YamlSyntaxError("comment" if line.strip().startswith("#") else "indentation")
    if line.startswith("#"):
        raise YamlSyntaxError("comment")
    if line == "-" or line.startswith("- "):
        raise YamlSyntaxError("sequence_item")
    match = _YAML_KEY_RE.match(line)
    if not match or (match.group(2) and not match.group(2).startswith(" ")):
        raise YamlSyntaxError("invalid_key")
    return match.group(1), match.group(2)


# Keys that must never appear inside a topic block (lowercase twins of Gate A's
# TOPIC_BLOCK_RESERVED_KEYS): a nested copy could otherwise shadow a META field.
_YAML_RESERVED_BLOCK_KEYS = frozenset(
    {
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
    }
)
_YAML_BLOCK_LINE_RE = re.compile(r"^( *)([^\s:]+):(.*)$")
_YAML_ENTRY_ID_RE = re.compile(r"^R\d+$")


class _BlockState:
    """Mutable per-record state while validating YAML topic-block lines."""

    def __init__(self) -> None:
        self.name: str | None = None
        self.seen_ids: set[str] = set()
        self.entry_keys: set[str] | None = None


def _check_block_line(state: _BlockState, line: str) -> None:
    """Validate one line inside a ``current:`` / ``rulings:`` block, or raise."""
    if line.strip().startswith("#"):
        raise YamlSyntaxError("comment")
    if line[:1] == "\t":
        raise YamlSyntaxError("indentation")
    match = _YAML_BLOCK_LINE_RE.match(line)
    if not match:
        raise YamlSyntaxError("invalid_block_entry")
    indent, key, rest = len(match.group(1)), match.group(2), match.group(3)
    if key in _YAML_RESERVED_BLOCK_KEYS:
        raise YamlSyntaxError("reserved_key_in_block", key)
    if rest and not rest.startswith(" "):
        raise YamlSyntaxError("invalid_block_entry")
    if state.name == "current":
        if not _YAML_ENTRY_ID_RE.match(key):
            raise YamlSyntaxError("invalid_block_entry")
        if indent != 2:
            raise YamlSyntaxError("indentation")
        decode_yaml_scalar(rest)
        if key in state.seen_ids:
            raise YamlSyntaxError("duplicate_key", key)
        state.seen_ids.add(key)
        return
    if indent == 2:
        if not _YAML_ENTRY_ID_RE.match(key) or rest.strip():
            raise YamlSyntaxError("invalid_block_entry")
        if key in state.seen_ids:
            raise YamlSyntaxError("duplicate_key", key)
        state.seen_ids.add(key)
        state.entry_keys = set()
        return
    if indent != 4:
        raise YamlSyntaxError("indentation")
    if state.entry_keys is None:
        raise YamlSyntaxError("orphan_block_line")
    if key not in _RULING_FIELDS:
        raise YamlSyntaxError("unknown_block_key", key)
    decode_yaml_scalar(rest)
    if key in state.entry_keys:
        raise YamlSyntaxError("duplicate_key", key)
    state.entry_keys.add(key)


def _parse_yaml(text: str) -> tuple[DecisionRecord | None, YamlReject | None]:
    """Strictly parse a YAML front-matter record: ``(record, None)`` or ``(None, reject)``."""
    lines = _split_yaml_lines(text)
    close = next((i for i in range(1, len(lines)) if lines[i].rstrip() == _YAML_FENCE), None)
    if close is None:
        last = max((i for i, line in enumerate(lines) if line.strip()), default=0)
        return None, {"line": last + 1, "construct": "missing_closing_fence"}

    pairs: dict[str, str] = {}
    headers: set[str] = set()
    state = _BlockState()
    for index in range(1, close):
        line = lines[index]
        if not line.strip():
            continue
        try:
            if state.name is not None and line[:1] in (" ", "\t"):
                _check_block_line(state, line)
                continue
            state = _BlockState()  # column-0 line: any open block ended
            key, rest = _split_yaml_pair(line)
            if key in _YAML_BLOCK_KEYS:
                if rest.strip():
                    raise YamlSyntaxError("block_header_with_value")
                if key in headers:
                    raise YamlSyntaxError("duplicate_key", key)
                headers.add(key)
                state.name = key
                continue
            value = decode_yaml_scalar(rest)
            if key in pairs:
                raise YamlSyntaxError("duplicate_key", key)
        except YamlSyntaxError as exc:
            return None, {"line": index + 1, "construct": exc.construct}
        pairs[key] = value

    core = {k.lower(): v for k, v in pairs.items() if k.upper() in _CORE_FIELDS}
    record: DecisionRecord = {
        "token": core.get("token"),
        "type": core.get("type"),
        "version": core.get("version"),
        "status": core.get("status"),
        "tier": core.get("tier"),
        "decision": core.get("decision"),
        "because": core.get("because"),
        "authored_at": core.get("authored_at"),
        "fields": {k.upper(): v for k, v in pairs.items() if k.upper() not in _CORE_FIELDS},
    }
    return record, None


def diagnose_yaml_record(text: str | None) -> YamlReject | None:
    """Return ``{line, construct}`` for a rejected YAML front-matter record, else ``None``.

    ``None`` for OCTAVE text and for a YAML record the strict subset accepts
    (whether it is then COMPLETE is a separate §1.2 required-field question).
    Pure; ``line`` is 1-based in ``text``.
    """
    if not text or not is_yaml_front_matter(text):
        return None
    return _parse_yaml(text)[1]


def _parse_impl(text: str) -> DecisionRecord:
    """Internal regex-only extraction (raises only on truly unexpected input)."""
    if is_yaml_front_matter(text):
        yaml_parsed = _parse_yaml(text)[0]
        return yaml_parsed if yaml_parsed is not None else _empty_record()

    core: dict[str, str] = {}
    extra: dict[str, str] = {}

    # Lines inside CURRENT/RULINGS blocks are NOT META: keep them out of
    # ``fields`` so a nested key (e.g. TOPIC, SCOPE) cannot shadow a META field.
    for block, raw_line in annotate_lines(text):
        if block is not None:
            continue
        match = _FIELD_LINE_RE.match(raw_line)
        if not match:
            continue
        key = match.group(1)
        value = _strip_quotes(match.group(2))

        if key in _CORE_FIELDS:
            # First occurrence wins (META block precedes any prose echoes).
            core.setdefault(key, value)
        else:
            extra.setdefault(key, value)

    return {
        "token": core.get("TOKEN"),
        "type": core.get("TYPE"),
        "version": core.get("VERSION"),
        "status": core.get("STATUS"),
        "tier": core.get("TIER"),
        "decision": core.get("DECISION"),
        "because": core.get("BECAUSE"),
        "authored_at": core.get("AUTHORED_AT"),
        "fields": extra,
    }
