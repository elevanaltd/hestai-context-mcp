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
only escapes are the short escapes for backslash, double quote, LF, CR and TAB, and canonical ``\\uXXXX`` (see
:func:`decode_yaml_scalar`). A column-0 ``current:`` / ``rulings:`` header with no
value opens a topic block (see :func:`annotate_lines`). Keys are uppercase-mapped into the same
:class:`DecisionRecord` shape the OCTAVE path yields. The adapter FAILS CLOSED:
any other construct inside the fences (unquoted value, other escape, block or
multi-line scalar, flow collection, anchor, comment, duplicate key, indentation,
a missing closing fence, a malformed topic-block line, or a reserved key nested
in a block) yields the empty (unparseable) record, never a half-read one;
:func:`diagnose_yaml_record` reports the line and construct.
"""

from __future__ import annotations

import contextlib
import logging
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import NamedTuple, TypedDict

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
            if in_fence and _is_fence_line(line):
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


def _is_fence_line(raw: str) -> bool:
    """A fence line is exactly ``---`` plus at most ONE line ending (``\\n``, ``\\r\\n``).

    Judged on the RAW line, before any CR is stripped, so ``---\\r\\r`` is not a fence.
    The single definition for opening and closing fences.
    """
    return raw.removesuffix("\n").removesuffix("\r") == _YAML_FENCE


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
# Candidate test only: ``type: DECISION_RECORD`` in ANY quoting, optionally followed by
# whitespace and anything (a comment or trailing garbage), so a mis-written record is
# found and then rejected loudly instead of being invisible. The value must END at the
# boundary: ``DECISION_RECORD_X`` / ``DECISION_RECORDS`` are other types.
_YAML_TYPE_LINE_RE = re.compile(
    r"^type:[ ]+(?:DECISION_RECORD|'DECISION_RECORD'|\"DECISION_RECORD\")(?:[ \t].*)?$"
)
_BOM = "\ufeff"
_CRLF_RE = re.compile(r"(?<!\r)\r\n")
_YAML_TOKEN_LINE_RE = re.compile(r'^token:[ ]+"([^"\\]+)"[ \t]*$')
_YAML_BLOCK_KEYS = frozenset({"current", "rulings"})

# ADR-RFC-ARCH-004 §1.3 TOKEN format. Core must not import ``tools``; a test pins
# this string to ``type_checker._TOKEN_FORMAT_RE.pattern`` so they cannot drift.
TOKEN_FORMAT_PATTERN = r"^[A-Z][A-Z0-9_-]{1,126}[A-Z0-9_]-[0-9]{8}$"
_TOKEN_FORMAT_RE = re.compile(TOKEN_FORMAT_PATTERN)


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


class RecordText(NamedTuple):
    """Result of :func:`classify_record_text`: the one normalised view every reader uses."""

    syntax: str  # "yaml" | "octave"
    text: str
    diagnostic: YamlReject | None


def classify_record_text(raw: bytes | str) -> RecordText:
    """The single canonical entry step for record input (pure, regex-only).

    * Syntax by EXACT first line: ``---`` (optionally followed by ``\\r``, after an
      optional BOM) is a YAML candidate; anything else is OCTAVE.
    * OCTAVE: decoded with ``errors="replace"`` exactly as before PR-4, text otherwise
      untouched (a BOM is kept, so OCTAVE behaviour is identical to main).
    * YAML: decoded strictly (invalid bytes stay lone surrogates and are reported as
      ``invalid_utf8`` when inside the fences), a single CRLF folded to LF (a repeated CR is left alone, so it stays malformed), and a leading BOM
      is a loud ``invalid_key`` reject at line 1 (the BOM is kept in ``text`` so every
      downstream reader sees the same rejection). A YAML candidate is never parsed as
      OCTAVE: it is parsed as YAML or carries a ``diagnostic``.
    """
    if isinstance(raw, bytes):
        body = raw.removeprefix(_BOM.encode("utf-8"))
        if not _is_fence_line(body.partition(b"\n")[0].decode("latin-1")):
            return RecordText("octave", raw.decode("utf-8", errors="replace"), None)
        text = raw.decode("utf-8", errors="surrogateescape")
    else:
        text = raw
        if not is_yaml_front_matter(text):
            with contextlib.suppress(UnicodeEncodeError):  # already-clean str passes through
                text = text.encode("utf-8", errors="surrogateescape").decode("utf-8", "replace")
            return RecordText("octave", text, None)
    # Fold CRLF to LF, but never a repeated CR (``\r\r\n``): that would turn a malformed
    # line into a well-formed one. Diagnostics are judged on the folded text.
    text = _CRLF_RE.sub("\n", text)
    return RecordText("yaml", text, diagnose_yaml_record(text))


def read_record(path: Path) -> RecordText:
    """Read ``path`` and classify it (the one I/O entry; raises ``OSError`` like ``read_text``)."""
    record = classify_record_text(path.read_text(encoding="utf-8", errors="surrogateescape"))
    if record.syntax == "yaml":
        # ``read_text`` folds every CR/CRLF to LF (universal newlines), which would turn a
        # malformed ``---\\r\\r`` fence into a valid one: re-read the raw bytes for YAML only.
        record = classify_record_text(path.read_bytes())
    return record


def decode_record_bytes(data: bytes) -> str:
    """The normalised text of raw record bytes (see :func:`classify_record_text`)."""
    return classify_record_text(data).text


def yaml_record_is_parseable(text: str | None) -> bool:
    """True iff ``text`` is a YAML record the strict subset accepts AND §1.2-complete.

    Mirrors ``agr_read.record_is_parseable`` (VERSION is not required, as for OCTAVE);
    lives here so the lexer/manifest can gate on it without importing ``tools.agr_read``.
    """
    if not text or not is_yaml_front_matter(text):
        return False
    parsed = parse_decision_record(text)
    if parsed["type"] != "DECISION_RECORD":
        return False
    required = ("token", "status", "tier", "decision", "because", "authored_at")
    return all(parsed[k] is not None for k in required)  # type: ignore[literal-required]


def _split_yaml_lines(text: str) -> list[str]:
    """Split on LF only; exotic Unicode separators stay inside values. CR is KEPT (raw
    lines): fence judgement needs it, content consumers strip one with ``_content``."""
    return text.split("\n")


def _content(raw: str) -> str:
    """A raw line without its (single) CR."""
    return raw.removesuffix("\r")


def _yaml_opening_lines(text: str) -> list[str] | None:
    """Lines after an opening ``---`` up to the closing fence (or EOF if unclosed)."""
    if not is_yaml_front_matter(text):
        return None
    lines = _split_yaml_lines(text.removeprefix(_BOM))
    body: list[str] = []
    for line in lines[1:]:
        if _is_fence_line(line):
            break
        body.append(_content(line))
    return body


def is_yaml_front_matter(text: str | None) -> bool:
    """True iff the first line (after an optional BOM) is exactly ``---`` (+ optional CR)."""
    return bool(text) and _is_fence_line(text.removeprefix(_BOM).partition("\n")[0])  # type: ignore[union-attr]


def has_yaml_decision_header(text: str | None) -> bool:
    """True iff ``text`` opens with ``---`` and declares ``type:`` DECISION_RECORD (any quoting).

    Scoping signal only (like the OCTAVE ``TYPE::DECISION_RECORD`` check): it is
    True for a malformed YAML record too, so such a record surfaces as
    unparseable rather than being silently out of scope. Lines after the closing
    fence are never consulted. Pure, regex-only.
    """
    if not text:
        return False
    # A leading UTF-8 BOM still makes the file a candidate (it is then rejected loudly
    # by ``diagnose_yaml_record``, never silently treated as a non-record).
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


def parse_supersedes_list(value: str) -> list[str]:
    """Split a YAML ``supersedes:`` value into TOKENS, or raise ``invalid_supersedes``.

    The value is a comma-separated list (whitespace around entries is ignored; one
    token is a list of one). Every entry must match the §1.3 TOKEN pattern, empty
    entries and duplicates are rejected, so prose can never become an edge.
    """
    entries = [entry.strip() for entry in value.split(",")]
    for entry in entries:
        if not _TOKEN_FORMAT_RE.fullmatch(entry):
            raise YamlSyntaxError("invalid_supersedes", f"not a TOKEN: {entry!r}")
    if len(set(entries)) != len(entries):
        raise YamlSyntaxError("invalid_supersedes", "duplicate TOKEN")
    return entries


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
    close = next((i for i in range(1, len(lines)) if _is_fence_line(lines[i])), None)
    if close is None:
        last = max((i for i, line in enumerate(lines) if line.strip()), default=0)
        return None, {"line": last + 1, "construct": "missing_closing_fence"}

    pairs: dict[str, str] = {}
    key_lines: dict[str, int] = {}
    headers: set[str] = set()
    state = _BlockState()
    for index in range(1, close):
        line = _content(lines[index])
        if not line.strip():
            continue
        try:
            if any(0xD800 <= ord(ch) <= 0xDFFF for ch in line):
                raise YamlSyntaxError("invalid_utf8")
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
        key_lines[key] = index + 1

    if "supersedes" in pairs:
        try:
            targets = parse_supersedes_list(pairs["supersedes"])
            if pairs.get("token") in targets:
                raise YamlSyntaxError("invalid_supersedes", "a record cannot supersede itself")
        except YamlSyntaxError as exc:
            return None, {"line": key_lines["supersedes"], "construct": exc.construct}

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
    Pure; ``line`` is 1-based. A leading BOM is rejected at line 1 as ``invalid_key``.
    """
    if not text or not is_yaml_front_matter(text):
        return None
    if text.startswith(_BOM):
        return {"line": 1, "construct": "invalid_key"}
    return _parse_yaml(text)[1]


def _parse_impl(text: str) -> DecisionRecord:
    """Internal regex-only extraction (raises only on truly unexpected input)."""
    if is_yaml_front_matter(text):
        # A YAML candidate is parsed as YAML or rejected (BOM included); never as OCTAVE.
        yaml_parsed = None if text.startswith(_BOM) else _parse_yaml(text)[0]
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


# ---------------------------------------------------------------------------
# Canonical emitter (EPIC4 PR-5): the write-side inverse of ``_parse_yaml``.
# ---------------------------------------------------------------------------

# Fixed key order: the ADR-RFC-ARCH-004 §1.1 example order for the core fields, then
# the §1.2 optional fields in table order, then ``supersedes`` (§1.6); any other key
# follows, sorted. One order means one byte sequence per record (record_hash/CAS).
_EMIT_KEY_ORDER = (
    "type",
    "version",
    "token",
    "status",
    "tier",
    "authored_at",
    "decision",
    "because",
    "issue_ref",
    "human_adr_ref",
    "superseded_by",
    "extends",
    "amends",
    "revision",
    "topic",
    "scope",
    "effective_from",
    "effective_until",
    "origin_session",
    "origin_ledger_rd",
    "ratified_by",
    "ratified_at",
    "supersedes",
    "supersedes_note",
)
_EMIT_REQUIRED = (
    "type",
    "version",
    "token",
    "status",
    "tier",
    "authored_at",
    "decision",
    "because",
)
_EMIT_KEY_FIRST = "abcdefghijklmnopqrstuvwxyz"
_EMIT_KEY_REST = _EMIT_KEY_FIRST + "0123456789_"
_EMIT_RULING_KEYS = ("rule", "verbatim", "ruled", "replaces")
_EMIT_ENTRY_KEYS = frozenset({"id", *_EMIT_RULING_KEYS})


def _emit_key(raw: str) -> str:
    """The lowercase on-disk spelling of a field key, or raise ``invalid_key``."""
    key = raw.lower() if isinstance(raw, str) else ""
    ok = bool(key) and key[0] in _EMIT_KEY_FIRST and all(ch in _EMIT_KEY_REST for ch in key)
    if not ok:
        raise YamlSyntaxError("invalid_key", repr(raw))
    return key


def _emit_scalar(value: object) -> str:
    """Canonically encode one value, refusing anything that is not an encodable ``str``."""
    if not isinstance(value, str):
        raise YamlSyntaxError("unquoted_value", f"not a string: {type(value).__name__}")
    try:
        return encode_yaml_scalar(value)
    except ValueError as exc:
        raise YamlSyntaxError("invalid_utf8", str(exc)) from exc


def _emit_supersedes(supersedes: list[str], own_token: str) -> str:
    """The ``supersedes:`` literal for a TOKEN list, with the reader's own rules."""
    if any(
        not isinstance(entry, str) or not _TOKEN_FORMAT_RE.fullmatch(entry) for entry in supersedes
    ):
        raise YamlSyntaxError("invalid_supersedes", "every entry must be a TOKEN")
    if len(set(supersedes)) != len(supersedes):
        raise YamlSyntaxError("invalid_supersedes", "duplicate TOKEN")
    if own_token in supersedes:
        raise YamlSyntaxError("invalid_supersedes", "a record cannot supersede itself")
    return _emit_scalar(", ".join(supersedes))


def _emit_ids(entries: list, block: str, allowed: frozenset[str]) -> list[dict]:
    """Validate block entries (id shape, uniqueness, field names); return them as dicts."""
    seen: set[str] = set()
    checked: list[dict] = []
    for entry in entries:
        for key in entry:
            if key == "id":
                continue  # the entry's own id slot, not an on-disk key
            if key in _YAML_RESERVED_BLOCK_KEYS:
                raise YamlSyntaxError("reserved_key_in_block", key)
            if key not in allowed:
                raise YamlSyntaxError("unknown_block_key", key)
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not _YAML_ENTRY_ID_RE.fullmatch(entry_id):
            raise YamlSyntaxError("invalid_block_entry", f"{block} entry id {entry_id!r}")
        if entry_id in seen:
            raise YamlSyntaxError("duplicate_key", entry_id)
        seen.add(entry_id)
        checked.append(entry)
    return checked


def _emit_blocks(blocks: TopicBlocks) -> list[str]:
    """The ``current:`` / ``rulings:`` lines (canonical two/four-space indent)."""
    lines: list[str] = []
    current = _emit_ids(list(blocks.get("current", [])), "current", frozenset({"id", "rule"}))
    if current:
        lines.append("current:")
        for entry in current:
            if not isinstance(entry.get("rule"), str):
                raise YamlSyntaxError("invalid_block_entry", f"current {entry['id']} needs a rule")
            lines.append(f"  {entry['id']}: {_emit_scalar(entry['rule'])}")
    rulings = _emit_ids(list(blocks.get("rulings", [])), "rulings", _EMIT_ENTRY_KEYS)
    if rulings:
        lines.append("rulings:")
        for entry in rulings:
            lines.append(f"  {entry['id']}:")
            for key in _EMIT_RULING_KEYS:
                if entry.get(key) is not None:
                    lines.append(f"    {key}: {_emit_scalar(entry[key])}")
    return lines


def emit_yaml_record(
    fields: Mapping[str, str],
    blocks: TopicBlocks | None = None,
    supersedes: list[str] | None = None,
    body: str = "",
) -> str:
    """Emit one canonical quoted-YAML record (front matter plus ``body``), or raise.

    Pure and deterministic: the same logical input gives byte-identical output
    whatever the mapping order (fixed key order, LF endings, exact ``---`` fences,
    canonical block indentation, scalars via :func:`encode_yaml_scalar`). The text
    is exactly what :func:`parse_decision_record` / :func:`diagnose_yaml_record`
    accept, and ``emit(read(emit(x))) == emit(x)``.

    ``fields`` maps field names (either case) to ``str`` values and must carry the
    eight §1.2 core fields with ``type`` == ``DECISION_RECORD`` and a §1.3 ``token``.
    ``supersedes`` is the TOKEN list (§1.6) and may not also appear in ``fields``.
    Anything the reader would reject raises :class:`YamlSyntaxError` with the reader's
    own ``construct`` name, so this can never write a record the reader refuses.
    Value rules that belong to Gate A (STATUS/TIER enums, density, dates) are NOT
    checked here.

    ``body`` (the markdown after the closing fence, ADR-RFC-ARCH-004 §1.1) is appended
    VERBATIM: no newline or other normalisation, so file bytes == canonical bytes.
    """
    if not isinstance(body, str):
        raise YamlSyntaxError("invalid_body", f"not a string: {type(body).__name__}")
    pairs: dict[str, str] = {}
    for raw_key, value in fields.items():
        key = _emit_key(raw_key)
        if key in pairs:
            raise YamlSyntaxError("duplicate_key", key)
        if key in _YAML_BLOCK_KEYS:
            raise YamlSyntaxError("block_header_with_value", key)
        if key == "supersedes" and supersedes is not None:
            raise YamlSyntaxError("duplicate_key", key)
        pairs[key] = value

    for required in _EMIT_REQUIRED:
        if required not in pairs:
            raise YamlSyntaxError("missing_required_field", required)
    if pairs["type"] != "DECISION_RECORD":
        raise YamlSyntaxError("invalid_type", repr(pairs["type"]))
    if not isinstance(pairs["token"], str) or not _TOKEN_FORMAT_RE.fullmatch(pairs["token"]):
        raise YamlSyntaxError("invalid_token", repr(pairs["token"]))

    literals = {key: _emit_scalar(value) for key, value in pairs.items()}
    if supersedes:
        literals["supersedes"] = _emit_supersedes(supersedes, pairs["token"])
    if "supersedes" in pairs:
        # A ``supersedes`` given through ``fields`` must still satisfy the reader's list rules.
        literals["supersedes"] = _emit_supersedes(
            parse_supersedes_list(pairs["supersedes"]), pairs["token"]
        )

    rank = {key: index for index, key in enumerate(_EMIT_KEY_ORDER)}
    ordered = sorted(literals, key=lambda key: (rank.get(key, len(rank)), key))
    lines = [_YAML_FENCE, *(f"{key}: {literals[key]}" for key in ordered)]
    if blocks:
        lines.extend(_emit_blocks(blocks))
    lines.append(_YAML_FENCE)
    return "\n".join(lines) + "\n" + body


def _raw_body(raw: bytes | str) -> str:
    """The text after the closing fence line, taken from the RAW input.

    ``classify_record_text`` folds CRLF to LF over the whole text, which would
    normalise the body; the body is therefore split from the raw decode instead.
    Only called for a record the reader accepted, so the closing fence exists.
    """
    text = raw.decode("utf-8", errors="surrogateescape") if isinstance(raw, bytes) else raw
    lines = text.split("\n")
    for index in range(1, len(lines)):
        if _is_fence_line(lines[index]):
            body = "\n".join(lines[index + 1 :])
            if any(0xD800 <= ord(ch) <= 0xDFFF for ch in body):
                raise YamlSyntaxError("invalid_utf8", "the markdown body is not valid UTF-8")
            return body
    raise YamlSyntaxError("missing_closing_fence")


def _flat_fields(record: DecisionRecord) -> dict[str, str]:
    """Every decoded field of a record by uppercase name (core fields and extras alike)."""
    flat = {k.upper(): v for k, v in record.items() if k != "fields" and isinstance(v, str)}
    flat.update(record["fields"])
    return flat


def _round_trip_mismatch(
    before: tuple[DecisionRecord, TopicBlocks], after: tuple[DecisionRecord, TopicBlocks]
) -> str | None:
    """Name of the first differing record part (a field name, ``current`` or ``rulings``)."""
    fields_a, fields_b = _flat_fields(before[0]), _flat_fields(after[0])
    for name in sorted(set(fields_a) | set(fields_b)):
        if fields_a.get(name) != fields_b.get(name):
            return name.lower()
    if before[1]["current"] != after[1]["current"]:
        return "current"
    if before[1]["rulings"] != after[1]["rulings"]:
        return "rulings"
    return None


def canonicalize_yaml_record(raw: bytes | str) -> str:
    """Parse a submitted YAML record, gate the round trip, and return its canonical text.

    The one write-path step (EPIC4 PR-5, ruling C): the front matter is re-emitted by
    :func:`emit_yaml_record` and the markdown body is copied verbatim from the RAW input.
    ``canonicalize(canonical) == canonical`` byte for byte. Raises
    :class:`YamlSyntaxError` with the reader's own ``construct`` for a record the
    reader rejects, and ``round_trip_mismatch`` (naming the field) if any decoded value
    of the re-emitted bytes differs from the submitted one.
    """
    record = classify_record_text(raw)
    if record.syntax != "yaml":
        raise YamlSyntaxError("not_yaml", "the record does not open with a --- fence")
    if record.diagnostic is not None:
        raise YamlSyntaxError(record.diagnostic["construct"], f"line {record.diagnostic['line']}")

    parsed = parse_decision_record(record.text)
    blocks = collect_topic_blocks(record.text)
    fields = _flat_fields(parsed)
    fields.pop("SUPERSEDES", None)
    supersedes_value = parsed["fields"].get("SUPERSEDES")
    supersedes = parse_supersedes_list(supersedes_value) if supersedes_value is not None else None
    body = _raw_body(raw)

    out = emit_yaml_record(fields, blocks, supersedes, body=body)

    problem = diagnose_yaml_record(out)
    if problem is not None:
        raise YamlSyntaxError(
            "round_trip_mismatch", f"re-emitted record rejected: {problem['construct']}"
        )
    again = (parse_decision_record(out), collect_topic_blocks(out))
    differing = _round_trip_mismatch((parsed, blocks), again)
    if differing is not None:
        raise YamlSyntaxError("round_trip_mismatch", f"field {differing!r} changed on re-emission")
    if not out.endswith(body):
        raise YamlSyntaxError("round_trip_mismatch", "field 'body' changed on re-emission")
    return out
