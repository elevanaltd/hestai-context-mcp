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
_BLOCK_HEADER_RE = re.compile(r"^(\s*)(CURRENT|RULINGS):\s*$")
_RULING_ENTRY_RE = re.compile(r"^\s*(R\d+):\s*$")
_CURRENT_ENTRY_RE = re.compile(r"^\s*(R\d+)::(.*?)\s*$")


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


def _annotate_lines(text: str) -> Iterator[tuple[str | None, str]]:
    """Yield ``(block_name | None, line)`` for every line of ``text``.

    ``block_name`` is ``CURRENT`` / ``RULINGS`` for lines inside such a block
    (headers excluded) and ``None`` elsewhere. A block ends at the first
    non-blank line indented no deeper than its header.
    """
    block: str | None = None
    header_indent = 0
    for line in text.splitlines():
        header = _BLOCK_HEADER_RE.match(line)
        if header:
            block = header.group(2)
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
    for block, line in _annotate_lines(text):
        if block is not None:
            yield block, line


def collect_topic_blocks(text: str | None) -> TopicBlocks:
    """Collect the ordered CURRENT and RULINGS blocks of a topic record.

    Pure, regex-only, never raises. Absent blocks yield empty lists. A RULINGS
    entry always carries all five keys; ``replaces`` is ``None`` when absent.
    """
    result: TopicBlocks = {"current": [], "rulings": []}
    if not text or not text.strip():
        return result

    entry: RulingEntry | None = None
    for block, line in iter_block_lines(text):
        if block == "CURRENT":
            cur = _CURRENT_ENTRY_RE.match(line)
            if cur:
                result["current"].append({"id": cur.group(1), "rule": _strip_quotes(cur.group(2))})
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
        field = _FIELD_LINE_RE.match(line)
        if field and entry is not None:
            key = field.group(1).lower()
            if key in ("rule", "verbatim", "ruled", "replaces"):
                entry[key] = _strip_quotes(field.group(2))  # type: ignore[literal-required]
    return result


def _strip_quotes(value: str) -> str:
    """Strip one surrounding pair of double quotes from a value (§1.1).

    ``"1.0"`` -> ``1.0``; ``bare`` -> ``bare``. Only a matched leading+trailing
    pair is removed so inner quotes (rare) survive.
    """
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


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
    empty: DecisionRecord = {
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

    if not text or not text.strip():
        return empty

    try:
        return _parse_impl(text)
    except Exception as exc:  # pragma: no cover - defensive only
        logger.debug("agent_readable_governance_parser: parse failed: %s", exc)
        return empty


def _parse_impl(text: str) -> DecisionRecord:
    """Internal regex-only extraction (raises only on truly unexpected input)."""
    core: dict[str, str] = {}
    extra: dict[str, str] = {}

    # Lines inside CURRENT/RULINGS blocks are NOT META: keep them out of
    # ``fields`` so a nested key (e.g. TOPIC, SCOPE) cannot shadow a META field.
    for block, raw_line in _annotate_lines(text):
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
