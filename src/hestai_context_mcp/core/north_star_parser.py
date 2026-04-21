"""North Star structured constraint extraction.

Issue #6: Harvest ``SCOPE_BOUNDARIES`` and ``IMMUTABLES`` from the Product
North Star so the Payload Compiler can extract architectural constraints
programmatically (PROD::I4 STRUCTURED_RETURN_SHAPES) without re-implementing
parsing at each consumer.

Design invariants
-----------------
* **Pure function** (PROD::I5) — text in, dict out. No I/O beyond DEBUG
  logging on malformed input; no filesystem access; no side effects.
* **Provider-agnostic** (PROD::I3) — parses the OCTAVE North Star summary
  format, not any provider-specific representation.
* **Legacy-independent** (PROD::I6) — design-time re-derivation of the
  legacy ``_extract_north_star_constraints`` logic; no runtime import of
  ``hestai_mcp``.

Format understood
-----------------
The parser targets the OCTAVE North Star summary document shape::

    §N::IMMUTABLES
    I1::"TOKEN<PRINCIPLE::…,WHY::…,STATUS::…>"
    I2::"…"

    §N::SCOPE_BOUNDARIES
    IS::[
      "item one",
      "item two"
    ]
    IS_NOT::[
      "other"
    ]

Section numbering (``§2`` / ``§4`` / …) is irrelevant — the parser keys
off the literal ``IMMUTABLES`` and ``SCOPE_BOUNDARIES`` tokens. Immutable
lines are recognised by the ``I<digits>::`` prefix anywhere inside the
``IMMUTABLES`` block, and list items are any quoted strings within the
bracketed ``IS::[ … ]`` / ``IS_NOT::[ … ]`` blocks.
"""

from __future__ import annotations

import logging
import re
from typing import TypedDict

logger = logging.getLogger(__name__)


class NorthStarConstraints(TypedDict):
    """Structured extraction of a Product North Star summary document.

    Fields
    ------
    scope_boundaries:
        Keyed by the lowercase section label (``"is"`` / ``"is_not"``).
        Each value is an ordered list of bullet strings extracted from the
        ``§N::SCOPE_BOUNDARIES`` block. When the block is present but one
        sub-list is absent, that key is still returned with an empty list
        (PROD::I4 consistent shape). When the whole block is absent, the
        dict is empty.
    immutables:
        Ordered list of immutable declarations (``"I1::…"``, ``"I2::…"``,
        …) extracted from the ``§N::IMMUTABLES`` block. Empty list when
        the block is absent.
    """

    scope_boundaries: dict[str, list[str]]
    immutables: list[str]


# Section delimiters inside an OCTAVE North Star summary. We key off the
# literal section TOKEN rather than the numeric ``§N`` prefix so format
# drift in section numbering does not break the parser.
_SECTION_TOKENS = (
    "IMMUTABLES",
    "SCOPE_BOUNDARIES",
    "ASSUMPTIONS",
    "CONSTRAINED_VARIABLES",
    "GATES",
    "ESCALATION",
    "TRIGGERS",
    "PROTECTION",
    "IDENTITY",
)

# An immutable line: ``I1::"…"`` or ``I12::"…"`` at line start (OCTAVE
# bodies are whitespace-tolerant — we strip each line before matching).
_IMMUTABLE_LINE_RE = re.compile(r"^(I\d+::.*)$")

# A quoted list item inside an ``IS::[ … ]`` / ``IS_NOT::[ … ]`` block.
# Captures the inner content. We accept both straight ASCII quotes and
# curly typographic quotes to survive document re-serialisation.
_QUOTED_ITEM_RE = re.compile(r'"([^"\n]*)"|“([^”\n]*)”')


def extract_constraints(text: str | None) -> NorthStarConstraints:
    """Parse a North Star document into structured constraints.

    Pure function — text in, structured dict out. Graceful on empty,
    ``None``, whitespace-only, and malformed input (returns an empty
    structured result and DEBUG-logs on parse exceptions; never raises).

    Args:
        text: Raw North Star document text, or ``None``.

    Returns:
        A :class:`NorthStarConstraints` dict with ``scope_boundaries`` and
        ``immutables`` keys. Both keys are always present; values are
        empty when the corresponding sections are absent or unparseable.
    """
    empty: NorthStarConstraints = {"scope_boundaries": {}, "immutables": []}

    if not text or not text.strip():
        return empty

    try:
        immutables = _extract_immutables(text)
    except Exception as exc:  # pragma: no cover - defensive only
        logger.debug("north_star_parser: immutables parse failed: %s", exc)
        immutables = []

    try:
        scope_boundaries = _extract_scope_boundaries(text)
    except Exception as exc:  # pragma: no cover - defensive only
        logger.debug("north_star_parser: scope_boundaries parse failed: %s", exc)
        scope_boundaries = {}

    return {"scope_boundaries": scope_boundaries, "immutables": immutables}


def _find_section_header(text: str, token: str, start_pos: int = 0) -> int:
    """Return the start index of ``token`` when it appears as an OCTAVE
    section header, or ``-1`` if absent.

    A section header is strictly one of the following structural forms:

    * ``(^|\\n)§<digits>::TOKEN(\\n|$)`` — the OCTAVE ``§N::TOKEN``
      conventional form, the entire token+suffix occupying its own line.
    * ``(^|\\n)TOKEN::`` — a bare line-start ``TOKEN::`` key (the OCTAVE
      key/value shape with the token itself being the key).

    Both forms pin TOKEN to a line-start position AND require the OCTAVE
    ``::`` separator, so neither a free-text occurrence inside a bullet
    body (e.g. ``"cross-reference the IMMUTABLES section"``) nor an
    inline ``::TOKEN`` reference inside a quoted body
    (e.g. ``"depends on ::CAPABILITIES"``) nor a sentence opener
    (e.g. ``"\\nIMMUTABLES are essential ..."``) will be falsely
    anchored. This closes PR #10 cubic P2 (CRS delta verdict).
    """
    # Header anchor: TOKEN must (a) sit at file head or directly after a
    # newline (LF or the LF tail of CRLF) optionally prefixed with the
    # OCTAVE ``§N::`` numbering, and (b) be followed by either ``::`` (the
    # OCTAVE key/value separator), an EOL char, or end-of-string. The
    # ``\r`` admittance handles CRLF inputs without falsely admitting an
    # in-body inline reference.
    pattern = re.compile(r"(?:^|\n)(?:§\d+::)?" + re.escape(token) + r"(?=::|\r|\n|$)")
    match = pattern.search(text, start_pos)
    if match is None:
        return -1
    # Return the index of the TOKEN itself within the match, regardless
    # of which form (with or without the ``§N::`` prefix) was matched.
    return match.start() + match.group(0).find(token)


def _section_slice(text: str, token: str) -> str | None:
    """Return the substring starting at a properly anchored ``token`` header
    and ending at the next such header (or ``===END``), or ``None`` if the
    header is absent.

    Keyed off literal section names (see :data:`_SECTION_TOKENS`) rather
    than OCTAVE ``§N`` numbering to survive renumbering drift.
    """
    start = _find_section_header(text, token)
    if start < 0:
        return None

    scan_from = start + len(token)
    end = len(text)
    for other in _SECTION_TOKENS:
        if other == token:
            continue
        pos = _find_section_header(text, other, scan_from)
        if 0 <= pos < end:
            end = pos

    # Also honour the OCTAVE document terminator ``===END`` if present.
    end_marker = text.find("===END", scan_from)
    if 0 <= end_marker < end:
        end = end_marker

    return text[start:end]


def _extract_immutables(text: str) -> list[str]:
    """Extract ``I<n>::…`` lines from the IMMUTABLES section in order."""
    section = _section_slice(text, "IMMUTABLES")
    if section is None:
        return []

    results: list[str] = []
    for raw_line in section.splitlines():
        line = raw_line.strip()
        match = _IMMUTABLE_LINE_RE.match(line)
        if match:
            results.append(match.group(1))
    return results


def _extract_scope_boundaries(text: str) -> dict[str, list[str]]:
    """Extract ``IS::[ … ]`` and ``IS_NOT::[ … ]`` lists from SCOPE_BOUNDARIES.

    When the block is present, both keys (``is``, ``is_not``) are returned
    with list values; whichever sub-list is absent gets an empty list so
    the :class:`NorthStarConstraints` shape is stable (PROD::I4).
    """
    section = _section_slice(text, "SCOPE_BOUNDARIES")
    if section is None:
        return {}

    is_items = _parse_bracketed_list(section, "IS")
    is_not_items = _parse_bracketed_list(section, "IS_NOT")

    if is_items is None and is_not_items is None:
        # Block header present but no parseable sub-lists — still return
        # the shape so downstream consumers do not special-case absence.
        return {"is": [], "is_not": []}

    return {
        "is": is_items or [],
        "is_not": is_not_items or [],
    }


def _parse_bracketed_list(section: str, label: str) -> list[str] | None:
    """Return quoted list items inside ``{label}::[ … ]``, or ``None`` if
    the labelled block is not found. ``IS_NOT`` is matched before ``IS``
    at call time to avoid prefix collisions.
    """
    # Locate the label, then the opening bracket. We scan conservatively:
    # first ``\n{label}::`` (line-anchored) with a fallback to whitespace-
    # prefixed forms so edge-of-section lines are still caught.
    candidates = (f"\n{label}::", f" {label}::", f"\t{label}::")
    idx = -1
    for cand in candidates:
        idx = section.find(cand)
        if idx >= 0:
            idx += len(cand)
            break
    if idx < 0 and section.startswith(f"{label}::"):
        idx = len(f"{label}::")
    if idx < 0:
        return None

    # Find the opening bracket after the label.
    open_bracket = section.find("[", idx)
    if open_bracket < 0:
        return None

    # Find the matching close bracket. We do not attempt deep nesting — the
    # OCTAVE dialect does not put brackets inside these bullet strings. If
    # unterminated (malformed), read to the next section/end-of-string.
    close_bracket = section.find("]", open_bracket + 1)
    if close_bracket < 0:
        logger.debug("north_star_parser: unterminated %s bracket list; best-effort parse", label)
        body = section[open_bracket + 1 :]
    else:
        body = section[open_bracket + 1 : close_bracket]

    items: list[str] = []
    for match in _QUOTED_ITEM_RE.finditer(body):
        # Exactly one of the two capture groups is populated per match.
        item = match.group(1) if match.group(1) is not None else match.group(2)
        if item is not None:
            items.append(item)
    return items
