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

    for raw_line in text.splitlines():
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
