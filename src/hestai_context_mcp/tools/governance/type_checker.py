"""Dumb Type Checker (Gate A Validator).

Validates OCTAVE governance content using regex only. No AST parsing,
no octave-mcp invocation, no external library imports.

North Star boundary (PROD §4 IS_NOT: document format system — octave-mcp owns):
  - Sentinel detection: first line must be r'^===([A-Z_]+)===$' (document start).
  - TYPE field: r'TYPE::(WORD)' within the first ===META=== block.
  - TOKEN field: r'TOKEN::"([^"]+)"' for DECISION_RECORD.
  - ID field: r'ID::"([^"]+)"' for facet cards.

Gate B wires the REAL OCTAVE validator as an in-process library behind the
OctaveValidator port (hestai_context_mcp.ports.octave_validator), gated by the
optional ``validation`` extra — not over stdio, and never an in-repo AST. This
file stays intentionally dumb (regex-only) by design; the real validator is
additive and runs alongside it at the submit_governance seam.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from hestai_context_mcp.core.agent_readable_governance_parser import (
    EDGE_FIELDS,
    RecordText,
    YamlReject,
    YamlSyntaxError,
    annotate_lines,
    canonicalize_yaml_record,
    classify_record_text,
    has_yaml_decision_header,
    iter_block_lines,
    list_items,
    parse_decision_record,
    parse_supersedes_list,
    read_octave_fields,
    read_record,
)
from hestai_context_mcp.tools.governance.lexer import declares_token, lookup_token_deterministic

# ---------------------------------------------------------------------------
# Regex patterns (compiled once at module load)
# ---------------------------------------------------------------------------

# OCTAVE sentinel: must be at the very start of the document (Bug 7 fix).
# Pattern: starts with ===TYPENAME=== on the very first line.
_SENTINEL_RE = re.compile(r"\A===([A-Z_]+)===\s*(?:\r?\n|$)")

# TYPE field in META block. LINE-ANCHORED (issue #85): the KEY must be exactly
# ``TYPE`` at line start — a leading whitespace-only indent is admitted (OCTAVE
# META bodies are indented) but NO other characters may precede it, so a
# ``*TYPE::``-suffixed key such as ``DOCUMENT_TYPE::`` / ``CONTENT_TYPE::`` no
# longer substring-leaks via ``.search()``. The trailing ``\s*$`` end-anchor
# rejects trailing garbage (``TYPE::DECISION_RECORD EXTRA``). Mirrors the
# read-side ``agr_read._TYPE_IS_DECISION_RECORD_RE`` anchored approach.
_TYPE_RE = re.compile(r"(?m)^\s*TYPE::(\w+)\s*$")

# TOKEN field (DECISION_RECORD): quote-optional (AGR canonical-form convergence).
# Accepts BOTH the bare canonical form  TOKEN::VALUE  and the legacy quoted form
# TOKEN::"VALUE".  LINE-ANCHORED at BOTH ends (issue #85): the line-START anchor
# ``^\s*`` admits OCTAVE indentation but forbids a ``*TOKEN::``-suffixed key
# (e.g. ``DOCUMENT_TOKEN::``) from substring-leaking via ``.search()``; the
# end-anchor (\s*$) lives OUTSIDE the alternation so BOTH branches reject a
# trailing-garbage line such as  TOKEN::"HO-…-20260513" EXTRA  /
# TOKEN::HO-…-20260513 EXTRA  (cubic P2 — the §1.3 _TOKEN_FORMAT_RE only checks
# the captured value, so it cannot catch trailing junk; the anchor must).
_TOKEN_RE = re.compile(r'(?m)^\s*TOKEN::(?:"([^"]+)"|([^"\s]+))\s*$')

# ID field (facet cards): quote-optional. Accepts bare  ID::VALUE  and quoted
# ID::"VALUE".  The end-anchor (\s*$) lives OUTSIDE the alternation so BOTH the
# quoted and bare branches are line-anchored — ID::"VALUE"garbage is rejected
# (cubic P2 — the quoted branch was previously unanchored).
_ID_QUOTED_RE = re.compile(r'(?m)^  ID::(?:"([^"]+)"|([^"\s]+))\s*$')

# SUPERSEDED_BY field: QUOTE-OPTIONAL (T3 CE/CIV rework — ADR-004 §13.1 ratified
# bare TOKEN edge references as canonical, so a bare ``SUPERSEDED_BY::TOKEN`` MUST
# be recognised exactly as the legacy quoted form; this mirrors
# ``lineage._SUPERSEDED_BY_RE`` so the §4.1 #9 iff check and the lineage guard
# agree). LINE-ANCHORED (issue #85): ``^\s*`` admits OCTAVE indentation but
# forbids a ``*SUPERSEDED_BY::``-suffixed key (e.g. ``PARENT_SUPERSEDED_BY::``)
# from substring-leaking a supersedure target via ``.search()`` — the
# supersedure-corruption vector the issue exists to kill. The end-anchor
# (``\s*$``) lives OUTSIDE the alternation so BOTH branches reject trailing
# garbage. Group 1 = quoted value, group 2 = bare value.
_SUPERSEDED_BY_RE = re.compile(r'(?m)^\s*SUPERSEDED_BY::(?:"([^"]+)"|([^"\s]+))\s*$')

# ISSUE_REF field: greedy line capture (horizontal whitespace anchor only —
# no ReDoS risk, no extractor/presence-detector asymmetry).
# Captures everything after ISSUE_REF:: to end-of-line; shape validation is
# done separately after quote-stripping so trailing garbage is always detected.
_ISSUE_REF_LINE_RE = re.compile(r"(?m)^[ \t]*ISSUE_REF::(.*)$")

# ISSUE_REF shape per ADR-RFC-ARCH-004 §4.1 invariant #10: accepts ONLY the two
# valid forms — the repo:<repo-id>#<n> shorthand or a GitHub issue URL.
_ISSUE_REF_SHAPE_RE = re.compile(
    r"^(?:repo:[A-Za-z0-9_-]+#[0-9]+|https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/issues/[0-9]+)$"
)

# TOKEN format validation per ADR-RFC-ARCH-004 §1.3
# ^[A-Z][A-Z0-9_-]{1,126}[A-Z0-9_]-[0-9]{8}$
_TOKEN_FORMAT_RE = re.compile(r"^[A-Z][A-Z0-9_-]{1,126}[A-Z0-9_]-[0-9]{8}$")

# --- ADR-RFC-ARCH-004 §1.2 / §4.1 shared write/read contract constants --------
# These are the SINGLE SOURCE OF TRUTH for the AGR required-field set and the
# STATUS/TIER enums. The read side (``agr_read``) derives its parse-completeness
# tuple from ``REQUIRED_META_FIELDS`` (lowercased) so the write-side Gate A and
# the read-side parser can never disagree on what a parseable record requires
# (issue #88 write/read parity; MIP one-source-of-truth).

# §1.2 required META fields (uppercase OCTAVE keys), every record / every state.
REQUIRED_META_FIELDS = (
    "TYPE",
    "VERSION",
    "TOKEN",
    "STATUS",
    "TIER",
    "DECISION",
    "BECAUSE",
    "AUTHORED_AT",
)

# §1.4 STATUS enum and §1.2 TIER enum (case-sensitive).
STATUS_VALUES = frozenset({"PROPOSED", "RATIFIED", "SUPERSEDED", "VOID"})
TIER_VALUES = frozenset({"STRATEGIC", "TACTICAL", "OPERATIONAL"})

# §1.2 reserved names — MUST NOT appear in any v1.x record (§4.1 #7).
RESERVED_FIELD_NAMES = frozenset({"DEPENDS_ON", "CONFLICTS_WITH", "ARCHIVED_AT"})

# v1.3 §1.7: top-level keys that MUST NOT appear inside a topic record's CURRENT /
# RULINGS blocks (first-match parsing would let a nested copy take over the record).
TOPIC_BLOCK_RESERVED_KEYS = frozenset(
    {
        "VERSION",
        "TOKEN",
        "ID",
        "TYPE",
        "STATUS",
        "TIER",
        "DECISION",
        "BECAUSE",
        "AUTHORED_AT",
        "SUPERSEDED_BY",
    }
)

# --- ADR-RFC-ARCH-004 v1.1 §1.2 / §4.1 #13 reasoning-density contract ---------
# HO-AGR-BYTECODE-FORMAT-TWO-BIRDS-20260620 (#101, RATIFIED) ruled AGRs are LLM
# "bytecode": the reasoning-bearing fields DECISION and BECAUSE are flat,
# compressed-OCTAVE strings of AT MOST 40 words with NO embedded newline. The
# guard is a value-level word-count/newline check ONLY — no structural parser
# change (the flat-regex parse stays as-is). These are SHARED CONSTANTS: the
# read side (``agr_read``) imports them so the write-side guard and the read
# side can never disagree on the density contract (issue #88 write/read parity).
MAX_REASONING_WORDS = 40
REASONING_FIELDS = ("DECISION", "BECAUSE")

# Reasoning value FORM check: the read-authoritative value (the first-occurrence
# value ``_extract_meta_fields`` surfaces, exactly what ``agr_read`` sees) MUST be
# a COMPLETE double-quoted flat string — a leading ``"``, an inner body of
# non-quote / escaped chars, a closing ``"``, and NOTHING before or after it. The
# ``^…$`` full-match anchors reject leading garbage, trailing garbage after the
# close quote, an unquoted value, and a partial/unbalanced quote alike. Group
# ``inner`` is the unquoted content the density checks then run on. String-only —
# no OCTAVE AST. The value is single-line by construction (``_extract_meta_fields``
# is line-anchored), so an unbalanced quote from a genuinely multi-line value
# fails this full-match — consistent with the line-anchored read parser.
_REASONING_FLAT_STRING_RE = re.compile(r'^"(?P<inner>(?:[^"\\]|\\.)*)"$')

# A single META ``KEY::value`` assignment at line start (whitespace-tolerant —
# OCTAVE bodies are indented). Mirrors the read-side parser's ``_FIELD_LINE_RE``
# (core.agent_readable_governance_parser) EXACTLY so the write-side presence /
# enum / reserved-name checks see the same field set the read parser surfaces
# (issue #88 parity). KEY is an uppercase OCTAVE identifier; the value is the
# rest of the line.  Regex-only — no structural OCTAVE parsing.
_META_FIELD_LINE_RE = re.compile(r"(?m)^\s*([A-Z][A-Z0-9_]*)::(.*?)\s*$")

# §1.5 VERSION shape: MAJOR.MINOR (two numeric segments, no patch level).
# Rejects 3-segment "1.0.0" and non-numeric "v1" (§4.1 #1 envelope clause).
_VERSION_SHAPE_RE = re.compile(r"^[0-9]+\.[0-9]+$")

# TOKEN trailing date suffix (the §1.3 YYYYMMDD), captured for #3 comparison.
_TOKEN_DATE_SUFFIX_RE = re.compile(r"-([0-9]{8})$")

# AUTHORED_AT date-only guard (cubic P2): §1.2 declares AUTHORED_AT an ISO-8601
# *timestamp* (full form, e.g. ``2026-06-11T00:00:00Z``), but
# ``datetime.fromisoformat`` also accepts a bare date (``2026-06-19`` -> midnight),
# which would silently pass the §4.1 #3 check whenever the TOKEN suffix matched.
# A value carries a time component iff a ``T`` or space separator is followed by
# at least an hour field; this regex matches the date-ONLY form (no such
# separator+time) so the #3 check can reject it before normalisation.
_AUTHORED_AT_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# RATIFIED_BY presence (§4.1 #12 warning). Quote-optional, line-anchored —
# same ``*FIELD::``-suffix-safe shape as the other anchored field regexes.
_RATIFIED_BY_RE = re.compile(r'(?m)^\s*RATIFIED_BY::(?:"([^"]*)"|(\S.*?))\s*$')

# HUMAN_ADR_REF value (§4.1 #11). Quote-optional, line-anchored; the captured
# path is resolved under the repository root separately.
_HUMAN_ADR_REF_RE = re.compile(r'(?m)^\s*HUMAN_ADR_REF::(?:"([^"]*)"|(\S.*?))\s*$')

# Facet card ID format per ADR-RFC-ARCH-005 §1.3
# ^[A-Z][A-Z0-9_]{2,127}$
_FACET_ID_FORMAT_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")

# Known card types and their placement rules
_DECISION_RECORD_TYPE = "DECISION_RECORD"
_FACET_CARD_TYPES = frozenset({"CONCEPT_CARD", "FRAME_CARD", "CLUSTER_CARD", "PHASE_CARD"})
_KNOWN_TYPES = frozenset([_DECISION_RECORD_TYPE]) | _FACET_CARD_TYPES

# REPO_ID field for facet cards. LINE-ANCHORED (issue #85, same *FIELD:: class):
# ``^\s*`` admits OCTAVE indentation but forbids a ``*REPO_ID::``-suffixed key
# (e.g. ``SOURCE_REPO_ID::``) from substring-leaking via ``.search()``. The
# trailing ``\s*$`` rejects a trailing-garbage line; the captured value's own
# comma/whitespace cleanup still happens in ``_extract_repo_id``.
_REPO_ID_RE = re.compile(r"(?m)^\s*REPO_ID::([^\s]+)\s*$")

# Safe slug pattern for REPO_ID validation (alphanumeric, hyphens, underscores only)
_SAFE_SLUG_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


@dataclass
class ValidationResult:
    """Result of Gate A dumb type checking.

    Fields:
        valid: True if all ERROR-severity checks passed, False otherwise.
            (Per ADR-RFC-ARCH-004 §4.2, WARNING-severity findings do NOT flip
            ``valid`` to False — see ``warnings``.)
        errors: List of human-readable ERROR strings (empty when valid=True).
        warnings: List of human-readable WARNING strings (§4.2 advisory; may be
            non-empty even when valid=True — e.g. §4.1 #12 ratification
            provenance). Additive field; defaults to empty.
        token: Extracted TOKEN or ID value (may be None if extraction failed).
        card_type: Extracted TYPE value (may be None if extraction failed).
        target_path: Computed target path for placement (None on error).
        syntax: ``"octave"`` (default) or ``"yaml"`` -- which Gate A branch judged the
            content (EPIC4 PR-5). Decides the target extension and the downstream
            Gate B / Stage-5 treatment.
        reject: For a rejected YAML record, the PR-4 reader's structured
            ``{line, construct}``; otherwise None.
        canonical_content: For a valid YAML record, the canonical bytes to write (front
            matter re-emitted, markdown body verbatim); None for OCTAVE or on error.
    """

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    token: str | None = None
    card_type: str | None = None
    target_path: Path | None = None
    syntax: str = "octave"
    reject: YamlReject | None = None
    canonical_content: str | None = None


def _extract_sentinel(content: str) -> str | None:
    """Extract the OCTAVE envelope name anchored to document start.

    The sentinel must be the very first thing in the document.
    Returns None if the document does not start with ===TYPE_NAME===.
    """
    m = _SENTINEL_RE.match(content)
    if m:
        return m.group(1)
    return None


def _extract_type(content: str) -> str | None:
    """Extract the TYPE field value from the META block."""
    m = _TYPE_RE.search(content)
    if m:
        return m.group(1)
    return None


def _extract_token(content: str) -> str | None:
    """Extract the TOKEN field (DECISION_RECORD style), quote-optional.

    Group 1 holds the quoted value, group 2 the bare value; exactly one is set.
    """
    m = _TOKEN_RE.search(content)
    if m:
        return m.group(1) if m.group(1) is not None else m.group(2)
    return None


def _extract_id(content: str) -> str | None:
    """Extract the ID field (facet card style), quote-optional.

    Group 1 holds the quoted value, group 2 the bare value; exactly one is set.
    """
    m = _ID_QUOTED_RE.search(content)
    if m:
        return m.group(1) if m.group(1) is not None else m.group(2)
    return None


def _extract_superseded_by(content: str) -> str | None:
    """Extract the SUPERSEDED_BY field if present, quote-optional.

    Group 1 holds the quoted value, group 2 the bare value; exactly one is set.
    """
    m = _SUPERSEDED_BY_RE.search(content)
    if m:
        return m.group(1) if m.group(1) is not None else m.group(2)
    return None


def _superseded_by_value(content: str) -> str | None:
    """The raw SUPERSEDED_BY value: a list (any spacing, one or several lines) or a TOKEN.

    A closed bracket list is read through ``_extract_meta_fields`` (which overlays a
    wrapped list's full compact form); anything else keeps the legacy single-token regex.
    """
    listed = _extract_meta_fields(content).get("SUPERSEDED_BY")
    # A LIST only when it is a closed one-line ``[...]`` or a wrapped list opened by an
    # exact ``KEY::[`` (read as the compact ``[...]``, or a bare ``[`` if never closed).
    # Any other value starting ``[`` keeps its pre-#229 behaviour (the regex below).
    # Whitespace-tolerant exactly as the reader is (``:: [X]``, a tab, a space before ``]``).
    if listed is not None and listed.strip().startswith("[") and listed.strip().endswith("]"):
        return listed
    if listed is not None and listed.strip() == "[":
        return listed
    return _extract_superseded_by(content)


def _extract_issue_ref(content: str) -> str | None:
    """Extract and normalise the ISSUE_REF value if exactly one line is present.

    Uses the greedy _ISSUE_REF_LINE_RE so trailing garbage is captured (not
    silently dropped).  Returns the quote-stripped value, or None when no
    ISSUE_REF line exists.  Callers that need the raw line count should use
    _ISSUE_REF_LINE_RE.findall() directly.
    """
    matches = _ISSUE_REF_LINE_RE.findall(content)
    if len(matches) != 1:
        return None
    raw = matches[0].strip()
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        raw = raw[1:-1]
    return raw or None


def _extract_repo_id(content: str) -> str | None:
    """Extract the REPO_ID field for facet card placement."""
    m = _REPO_ID_RE.search(content)
    if m:
        val = m.group(1).strip()
        # Strip trailing non-alphanumeric chars (e.g. commas, whitespace)
        val = val.rstrip(",\t\r\n ")
        return val or None
    return None


def _extract_meta_fields(content: str) -> dict[str, str]:
    """Map every line-anchored ``KEY::value`` META assignment to its raw value.

    First occurrence wins (the META block precedes any prose echoes), matching
    the read-side parser's ``setdefault`` behaviour exactly so presence/enum
    checks agree with ``record_is_parseable`` (issue #88 parity). Quotes are NOT
    stripped here — callers that need the bare value strip them locally.
    """
    fields: dict[str, str] = {}
    for key, value in _META_FIELD_LINE_RE.findall(content):
        fields.setdefault(key, value)
    # Issue #224: a list wrapped over several lines matched above as its opener only
    # (``[``); overlay the reader's full compact value so Gate A and the read parser
    # see the same field. Every other value is exactly what the line regex gave.
    seen: set[str] = set()
    for entry in read_octave_fields(content)[0]:
        if entry.key in seen:
            continue
        seen.add(entry.key)
        if entry.wrapped and entry.key in fields:
            fields[entry.key] = entry.value
    return fields


def _strip_quotes(value: str) -> str:
    """Strip one surrounding pair of double quotes (§1.1 quote-optionality)."""
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


# The ONE place a record's syntax decides its file extension (ADR-RFC-ARCH-004 §1.1):
# an OCTAVE record is ``<token>.oct.md``, a quoted-YAML record is ``<token>.md``.
RECORD_SUFFIX = {"octave": ".oct.md", "yaml": ".md"}


def decision_record_path(working_dir: Path, token: str, syntax: str) -> Path:
    """Target path of a DECISION_RECORD of the given ``syntax`` (``octave`` or ``yaml``)."""
    return working_dir / ".hestai" / "decisions" / f"{token}{RECORD_SUFFIX[syntax]}"


def _compute_target_path(
    working_dir: Path,
    card_type: str,
    token: str,
    repo_id: str,
) -> Path:
    """Compute the canonical target path per ADR-RFC-ARCH-001 placement rules.

    DECISION_RECORD → .hestai/decisions/{token}.oct.md
    CONCEPT_CARD / FRAME_CARD / CLUSTER_CARD / PHASE_CARD →
      .hestai/context/concepts/{repo_id}/{id}.oct.md

    Args:
        working_dir: Project root directory.
        card_type: The card type string (e.g. 'DECISION_RECORD').
        token: The extracted TOKEN or ID value.
        repo_id: The REPO_ID string (only used for facet cards).

    Returns:
        Computed absolute Path.
    """
    if card_type == _DECISION_RECORD_TYPE:
        return decision_record_path(working_dir, token, "octave")

    # Facet card types
    return working_dir / ".hestai" / "context" / "concepts" / repo_id / f"{token}.oct.md"


@dataclass
class _RecordValues:
    """The syntax-independent inputs of the §4.1 invariants (#1-#12), already extracted.

    OCTAVE extracts them with line-anchored regexes, YAML from the PR-4 reader's
    decoded record; ``_check_common_invariants`` then judges both identically, so a
    rule can never drift between the two syntaxes. Values are bare (unquoted).
    """

    present: set[str]  # uppercase names of every declared top-level field
    version: str | None
    status: str | None
    tier: str | None
    authored_at: str | None
    has_superseded_by: bool
    human_adr_ref: str | None  # None when absent
    has_ratified_by: bool


def _check_agr_invariants(
    working_dir: Path,
    content: str,
    token: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Enforce the ADR-RFC-ARCH-004 §4.1 invariants for an OCTAVE DECISION_RECORD (#88).

    Extracts the OCTAVE field values, runs the syntax-independent checks
    (``_check_common_invariants``) and then the OCTAVE-form reasoning-density check
    (#13). Collect-more-errors style; regex-only (North Star §4 / PROD I3); never
    raises (PROD I4). ``token`` is the already-extracted, §1.3-format-valid TOKEN.
    """
    meta = _extract_meta_fields(content)
    human_adr_m = _HUMAN_ADR_REF_RE.search(content)
    human_adr_ref: str | None = None
    if human_adr_m is not None:
        ref = human_adr_m.group(1) if human_adr_m.group(1) is not None else human_adr_m.group(2)
        human_adr_ref = (ref or "").strip()
    values = _RecordValues(
        present=set(meta),
        version=_strip_quotes(meta["VERSION"]) if "VERSION" in meta else None,
        status=_strip_quotes(meta["STATUS"]) if "STATUS" in meta else None,
        tier=_strip_quotes(meta["TIER"]) if "TIER" in meta else None,
        authored_at=_strip_quotes(meta["AUTHORED_AT"]) if "AUTHORED_AT" in meta else None,
        has_superseded_by=_superseded_by_value(content) is not None,
        human_adr_ref=human_adr_ref,
        has_ratified_by=_RATIFIED_BY_RE.search(content) is not None,
    )
    _check_common_invariants(working_dir, token, values, errors, warnings)

    # --- #13: Reasoning-field density (ADR-RFC-ARCH-004 v1.1 §1.2) ---
    # DECISION and BECAUSE are LLM "bytecode": flat compressed-OCTAVE strings of
    # AT MOST MAX_REASONING_WORDS words with NO embedded newline (the ratified
    # GATE_A_GUARD of HO-AGR-BYTECODE-FORMAT-TWO-BIRDS-20260620 / #101). This is
    # a value-level check ONLY — the structural flat-regex parse is unchanged.
    _check_reasoning_density(content, errors)


def _check_common_invariants(
    working_dir: Path,
    token: str,
    v: _RecordValues,
    errors: list[str],
    warnings: list[str],
    container: str = "the META block",
) -> None:
    """The §4.1 invariants that do not depend on the record's syntax.

    Invariants enforced here (the residual set unenforced before #88):
      #1-residual  VERSION two-segment shape (§1.5)
      #2           Required §1.2 fields present
      #3-residual  TOKEN YYYYMMDD suffix == UTC date of AUTHORED_AT
      #5           STATUS enum
      #6           TIER enum
      #7           Reserved names absent
      #9           SUPERSEDED_BY present IFF STATUS == SUPERSEDED
      #11          HUMAN_ADR_REF resolves under the repository
      #12          Ratification provenance (WARNING per §4.2)
    """
    # --- #2: Required fields present (the core silent-pass class) ---
    # TYPE and TOKEN are proven present by the time we get here; check the rest
    # so a record the read parser would mark unparseable is rejected on write.
    for required in REQUIRED_META_FIELDS:
        if required not in v.present:
            errors.append(
                f"Required field '{required}' is missing from {container} "
                "(ADR-RFC-ARCH-004 §1.2 / §4.1 #2)."
            )

    # --- #1-residual: VERSION two-segment shape (§1.5) ---
    if v.version is not None:
        version = v.version
        if not _VERSION_SHAPE_RE.match(version):
            errors.append(
                f"VERSION '{version}' is not a two-segment MAJOR.MINOR string "
                "(ADR-RFC-ARCH-004 §1.5 / §4.1 #1). "
                "Patch levels (e.g. '1.0.0') and non-numeric values are rejected."
            )

    # --- #5: STATUS enum ---
    status = v.status
    if status is not None and status not in STATUS_VALUES:
        errors.append(
            f"STATUS '{status}' is not a valid value. "
            f"Must be one of {', '.join(sorted(STATUS_VALUES))} "
            "(ADR-RFC-ARCH-004 §1.4 / §4.1 #5)."
        )

    # --- #6: TIER enum ---
    if v.tier is not None:
        tier = v.tier
        if tier not in TIER_VALUES:
            errors.append(
                f"TIER '{tier}' is not a valid value. "
                f"Must be one of {', '.join(sorted(TIER_VALUES))} "
                "(ADR-RFC-ARCH-004 §1.2 / §4.1 #6)."
            )

    # --- #7: Reserved names MUST NOT appear (§1.2) ---
    for reserved in sorted(RESERVED_FIELD_NAMES):
        if reserved in v.present:
            errors.append(
                f"Reserved field '{reserved}' MUST NOT appear in a v1.x record "
                "(ADR-RFC-ARCH-004 §1.2 reserved-names / §4.1 #7)."
            )

    # --- #3-residual: TOKEN date suffix == UTC date of AUTHORED_AT (§1.3) ---
    # The comparison is against the UTC DATE PORTION (§1.3): an offset timestamp
    # is normalised to UTC before the date is taken (T3 CIV rework — a lexical
    # leading-date capture mis-handles offsets and silently passes a non-
    # timestamp AUTHORED_AT).
    authored_at = v.authored_at
    token_date_m = _TOKEN_DATE_SUFFIX_RE.search(token)
    if authored_at is not None and token_date_m is not None:
        token_yyyymmdd = token_date_m.group(1)
        if _AUTHORED_AT_DATE_ONLY_RE.match(authored_at.strip()):
            # §1.2: AUTHORED_AT is an ISO-8601 *timestamp*, not a bare date.
            # ``datetime.fromisoformat`` would accept the date-only form (midnight)
            # and silently pass #3 — reject it explicitly (cubic P2).
            errors.append(
                f"AUTHORED_AT '{authored_at}' must be a full ISO-8601 timestamp, "
                "not a date (e.g. '2026-06-19T00:00:00Z'); the §1.3 TOKEN-date "
                "consistency check (§4.1 #3) requires a time component."
            )
        else:
            authored_yyyymmdd = _authored_at_utc_date(authored_at)
            if authored_yyyymmdd is None:
                errors.append(
                    f"AUTHORED_AT '{authored_at}' is not a parseable ISO-8601 "
                    "timestamp; the §1.3 TOKEN-date consistency check (§4.1 #3) "
                    "cannot be evaluated."
                )
            elif authored_yyyymmdd != token_yyyymmdd:
                errors.append(
                    f"TOKEN date suffix '{token_yyyymmdd}' does not equal the UTC "
                    f"date of AUTHORED_AT ('{authored_yyyymmdd}' from "
                    f"'{authored_at}') (ADR-RFC-ARCH-004 §1.3 / §4.1 #3)."
                )

    # --- #9: SUPERSEDED_BY present IFF STATUS == SUPERSEDED ---
    has_superseded_by = v.has_superseded_by
    if status == "SUPERSEDED" and not has_superseded_by:
        errors.append(
            "STATUS is SUPERSEDED but SUPERSEDED_BY is absent; a superseded "
            "record MUST name its successor "
            "(ADR-RFC-ARCH-004 §1.2 / §4.1 #9)."
        )
    elif has_superseded_by and status is not None and status != "SUPERSEDED":
        errors.append(
            f"SUPERSEDED_BY is present but STATUS is '{status}', not SUPERSEDED; "
            "SUPERSEDED_BY is required iff STATUS == SUPERSEDED "
            "(ADR-RFC-ARCH-004 §1.2 / §4.1 #9)."
        )

    # --- #11: HUMAN_ADR_REF — token-form (v1.1) OR resolvable path (v1.0) ---
    # ADR-RFC-ARCH-004 v1.1 (per #101 ADR_REF_FORM::greppable_TOKEN) admits two
    # canonical forms. DISCRIMINATION RULE (deterministic, regex-only): a ref
    # that matches the §1.3 TOKEN regex (``_TOKEN_FORMAT_RE``) is TOKEN-form; the
    # §1.3 pattern admits no ``/`` and no ``.``, so a path (which carries a
    # separator or ``.md``) can never match it — the two classes are mutually
    # exclusive by construction (no separate path detector invented).
    #   * TOKEN-form  -> well-formed greppable token; NO path resolution
    #                    (cross-repo survivable — the target may live elsewhere).
    #   * otherwise   -> v1.0 path-form; resolve under the repo exactly as before
    #                    (back-compat; the 5 existing path-form records still pass).
    if v.human_adr_ref is not None:
        ref = v.human_adr_ref
        if _TOKEN_FORMAT_RE.match(ref):
            # Token-form: well-formed greppable token, no filesystem resolution.
            pass
        elif not _human_adr_ref_resolves(working_dir, ref):
            errors.append(
                f"HUMAN_ADR_REF '{ref}' is neither a well-formed greppable TOKEN "
                "(ADR-RFC-ARCH-004 §1.3 form) nor a path that resolves to a file "
                "under the repository (ADR-RFC-ARCH-004 §1.2 / §4.1 #11)."
            )

    # --- #12: Ratification provenance (WARNING per §4.2, NOT error) ---
    if status is not None and status != "PROPOSED" and not v.has_ratified_by:
        warnings.append(
            f"RATIFIED_BY is absent on a record whose STATUS is '{status}' "
            "(not PROPOSED); ratification provenance is recommended "
            "(ADR-RFC-ARCH-004 §4.1 #12, severity WARNING)."
        )


_META_HEADER_RE = re.compile(r"^META:\s*$")


def _check_core_key_placement(content: str, errors: list[str]) -> None:
    """Reject a top-level core key placed BEFORE the ``META:`` header.

    The read parser and Gate A keep the FIRST match of each core key over the
    whole text, so a copy placed ahead of META would override the real value.
    Placement is otherwise NOT restricted to META: some records legitimately
    declare e.g. STATUS/TIER/DECISION after the META block, and later (nested)
    repeats can never win first-match. Lines inside CURRENT / RULINGS are
    handled by #14. A no-op when the record has no ``META:`` header.
    """
    for block, line in annotate_lines(content):
        if _META_HEADER_RE.match(line):
            return
        if block is not None:
            continue
        m = _META_FIELD_LINE_RE.match(line)
        if m is not None and m.group(1) in TOPIC_BLOCK_RESERVED_KEYS:
            errors.append(
                f"Core key '{m.group(1)}' appears before the META block "
                "(ADR-RFC-ARCH-004 v1.3 §4.1 #15); first-match parsing would let "
                "this misplaced copy override the value declared in META."
            )


def _check_list_fields(raw_content: str, errors: list[str], warnings: list[str]) -> None:
    """Issue #224: a list that never closes is an ERROR; a multi-line EDGE list is a WARNING.

    The reader reads a wrapped list in full (one grammar for every list field), so a
    record ``octave_write`` wrapped stays valid and amendable. An unterminated list
    would make the record unreadable (``RECORD_PARSE_FAILED``), so it is rejected here
    with the line where the list opens. Reads the raw text so the line numbers match
    the file; regex-only.
    """
    fields, reject = read_octave_fields(raw_content)
    if reject is not None:
        errors.append(
            f"List field is malformed at line {reject['line']}: {reject['construct']}. "
            "A multi-line list must close with ] before the next field, with nothing "
            "after the ] (ADR-RFC-ARCH-004 §1.1)."
        )
    for entry in fields:
        if entry.wrapped and entry.key in EDGE_FIELDS:
            warnings.append(
                f"{entry.key} is a multi-line list (line {entry.line}). The reader reads it in "
                "full, but a lineage edge is easier to audit on one line "
                "(ADR-RFC-ARCH-004 §1.1)."
            )


def _check_topic_block_keys(content: str, errors: list[str]) -> None:
    """Reject a top-level reserved key nested inside a CURRENT / RULINGS block.

    The read parser keeps the FIRST match of each key, so a nested ``STATUS::``
    (etc.) inside a topic-record block could take over the record. Every
    offending line is reported with the key and the block named (collect-more-
    errors). Regex-only; no-op for records without these blocks.
    """
    for block, line in iter_block_lines(content):
        m = _META_FIELD_LINE_RE.match(line)
        if m is None or m.group(1) not in TOPIC_BLOCK_RESERVED_KEYS:
            continue
        errors.append(
            f"Key '{m.group(1)}' is a top-level reserved key and MUST NOT appear "
            f"inside the {block} block (ADR-RFC-ARCH-004 v1.3 §1.7 / §4.1 #14); "
            "it would shadow the record's META field under first-match parsing."
        )


def _check_reasoning_density(content: str, errors: list[str]) -> None:
    """Enforce the §4.1 #13 form + word-count / no-newline guard on the reasoning fields.

    DECISION and BECAUSE MUST each be a well-formed double-quoted flat string of
    AT MOST ``MAX_REASONING_WORDS`` words with NO embedded newline (the ratified
    ``FORMAT_RULE`` flat strings of #101, relations in plain words per
    HO-AGR-PLAIN-WORDS-REASONING-20261031). The check is purely
    value-level (no structural OCTAVE re-parse) and validates the SAME value the
    read layer surfaces, so the guard and ``agr_read`` cannot diverge (#88 parity
    strengthened):

      1. READ-AUTHORITATIVE VALUE — the value is the FIRST-occurrence value from
         the parity-shared ``_extract_meta_fields`` (``_META_FIELD_LINE_RE``),
         i.e. exactly what the read parser surfaces. The guard never scans a
         separate (later/quoted) occurrence — that two-source split was the
         divergence bypass (cubic P1): a malformed first occurrence with a clean
         later quoted one would otherwise escape.
      2. FORM — that value must FULL-MATCH ``_REASONING_FLAT_STRING_RE``
         (``^"…"$``). This rejects unquoted values, leading garbage, trailing
         garbage after the close quote, and partial/unbalanced quotes in one
         check.
      3. DENSITY — on the inner (unquoted) content, reject an embedded newline
         (any of ``\\n``, ``\\r``, ``\\r\\n``) and reject > ``MAX_REASONING_WORDS``
         words.

    Pure; appends actionable, field-named errors. Shared
    ``MAX_REASONING_WORDS`` / ``REASONING_FIELDS`` keep this in lockstep with the
    read side (issue #88 parity).
    """
    # Read-authoritative first-occurrence values (the field set the read parser
    # surfaces). Validating THESE — not a separately-scanned quoted occurrence —
    # is what keeps the guard and agr_read from diverging.
    present = _extract_meta_fields(content)

    for key in REASONING_FIELDS:
        if key not in present:
            # Absence is handled by the §4.1 #2 required-field check, not here.
            continue

        raw = present[key]
        form_match = _REASONING_FLAT_STRING_RE.match(raw)
        if form_match is None:
            # Not a clean double-quoted flat string (unquoted, leading/trailing
            # garbage, or unbalanced quote) — a #13 violation regardless of the
            # inner length, with no bypass window.
            errors.append(
                f"{key} value must be a double-quoted flat string "
                f'({key}::"…") with no leading or trailing content; an unquoted, '
                "multi-line, or garbage-padded value is rejected — "
                "ADR-RFC-ARCH-004 v1.1 §1.2 / §4.1 #13 "
                "(DECISION and BECAUSE are flat strings; write relations in plain words)."
            )
            continue

        _check_density_value(key, form_match.group("inner"), errors)


def _check_density_value(key: str, value: str, errors: list[str]) -> None:
    """The syntax-independent half of §4.1 #13: no newline, at most MAX_REASONING_WORDS words.

    ``value`` is the bare (unquoted, and for YAML unescaped) reasoning text.
    """
    if "\n" in value or "\r" in value:
        errors.append(
            f"{key} value contains an embedded newline; reasoning fields MUST "
            "be a single flat line (no newline) — ADR-RFC-ARCH-004 v1.1 §1.2 / "
            "§4.1 #13. Write one flat line, with relations in plain words "
            "(because, so, and, or), never arrows or symbols."
        )

    word_count = len(value.split())
    if word_count > MAX_REASONING_WORDS:
        errors.append(
            f"{key} value is {word_count} words (max {MAX_REASONING_WORDS}); "
            "reasoning fields MUST be short flat strings, not prose — "
            "ADR-RFC-ARCH-004 v1.1 §1.2 / §4.1 #13. Drop filler words and write "
            "relations in plain words, never arrows or symbols."
        )


def _authored_at_utc_date(value: str) -> str | None:
    """Return the UTC date of an ISO-8601 ``AUTHORED_AT`` as ``YYYYMMDD``.

    Per §1.3 the TOKEN suffix equals the **UTC date portion** of AUTHORED_AT, so
    an offset timestamp (e.g. ``2026-06-18T23:30:00-02:00``) is normalised to UTC
    (date ``20260619``) BEFORE the date is taken. A naive timestamp (no offset)
    is treated as already-UTC. Returns ``None`` when ``value`` is not a parseable
    ISO-8601 timestamp so the caller can flag it rather than silently pass.

    Regex-only boundary preserved: this uses ``datetime`` parsing of a scalar
    timestamp value (stdlib, deterministic), NOT OCTAVE AST parsing — North Star
    §4 governs OCTAVE structure, which this does not touch.
    """
    text = value.strip()
    # ``datetime.fromisoformat`` accepts a trailing ``Z`` only from Python 3.11+;
    # normalise it to ``+00:00`` for portability/clarity.
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    # Naive timestamp: spec treats AUTHORED_AT as UTC, so the date is taken
    # as-is. Offset-aware timestamp: normalise to UTC before taking the date.
    utc = parsed if parsed.tzinfo is None else parsed.astimezone(UTC)
    return f"{utc.year:04d}{utc.month:02d}{utc.day:02d}"


def _human_adr_ref_resolves(working_dir: Path, ref: str) -> bool:
    """True iff ``ref`` resolves to an existing file UNDER ``working_dir`` (#11).

    Path-traversal safe: the resolved candidate MUST stay within the repository
    root, so a ``../../../etc/passwd`` style ref is rejected even if such a file
    exists on the host. Pure read; never raises.
    """
    if not ref:
        return False
    try:
        root = working_dir.resolve()
        candidate = (working_dir / ref).resolve()
    except (OSError, ValueError, RuntimeError):
        return False
    if root != candidate and root not in candidate.parents:
        return False
    return candidate.is_file()


def validate_octave_content(working_dir: Path, content: str) -> ValidationResult:
    """Validate OCTAVE governance content using regex-only checks.

    Performs these checks in order (early return on fundamental failures):
      1. OCTAVE sentinel at document start (===TYPE===).
      2. TYPE field extraction and known-type check.
      2a. Sentinel↔TYPE consistency (sentinel name must equal TYPE value).
      3. TOKEN (DECISION_RECORD) or ID (facet cards) extraction.
      4. TOKEN/ID format validation.
      4a. REPO_ID required for facet cards.
      5. SUPERSEDED_BY target existence check (if present).
      6. Token uniqueness check (must NOT already exist for new records).
      7. Path traversal guard + target path computation.

    Never raises on bad input. Always returns a ValidationResult.

    Args:
        working_dir: Project root directory for token lookup.
        content: Raw OCTAVE document text.

    Returns:
        ValidationResult with valid=True on success or errors populated on failure.
    """
    errors: list[str] = []
    warnings: list[str] = []

    try:
        return _validate_impl(working_dir, content, errors, warnings)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Unexpected validation error: {exc}")
        return ValidationResult(valid=False, errors=errors, warnings=warnings)


def _strip_block_lines(content: str) -> str:
    """Drop every line inside a CURRENT / RULINGS block (headers are kept).

    The read parser excludes these lines from record fields; Gate A extracts
    every invariant input from the same block-excluded text so the write side
    and the read side agree on what the record declares (#203 S1).
    """
    return "".join(line for block, line in annotate_lines(content) if block is None)


def _check_issue_ref_shape(raw: str, errors: list[str]) -> None:
    """§4.1 #10: a present ISSUE_REF is a GitHub issue URL or ``repo:<repo-id>#<n>``."""
    if not raw or not _ISSUE_REF_SHAPE_RE.fullmatch(raw):
        errors.append(
            f"ISSUE_REF '{raw}' does not match a valid shape. "
            "ISSUE_REF must be a GitHub issue URL "
            "(https://github.com/<org>/<repo>/issues/<n>) or the "
            "repo:<repo-id>#<n> shorthand (ADR-RFC-ARCH-004 §4.1 #10)."
        )


def _validate_impl(
    working_dir: Path,
    raw_content: str,
    errors: list[str],
    warnings: list[str],
) -> ValidationResult:
    """Internal validation implementation."""
    content = _strip_block_lines(raw_content)
    # --- Check 1: OCTAVE sentinel at document start (Bug 7) ---
    sentinel = _extract_sentinel(content)
    if sentinel is None:
        errors.append(
            "No OCTAVE sentinel found at document start. "
            "Content must begin with ===TYPE_NAME=== on the very first line."
        )
        return ValidationResult(valid=False, errors=errors)

    # --- Check 2: TYPE field extraction ---
    card_type = _extract_type(content)
    if card_type is None:
        errors.append("No TYPE field found in META block.")
        return ValidationResult(valid=False, errors=errors)

    if card_type not in _KNOWN_TYPES:
        errors.append(
            f"Unknown TYPE '{card_type}'. " f"Known types: {', '.join(sorted(_KNOWN_TYPES))}"
        )
        return ValidationResult(valid=False, errors=errors, card_type=card_type)

    # --- Check 2a: Sentinel↔TYPE consistency (Bug 3) ---
    if sentinel != card_type:
        errors.append(
            f"Sentinel '==={sentinel}===' does not match TYPE field '{card_type}'. "
            "The opening envelope name and the META TYPE field must be identical."
        )
        return ValidationResult(valid=False, errors=errors, card_type=card_type)

    # --- Check 3: TOKEN / ID extraction ---
    token: str | None = None
    repo_id: str | None = None

    if card_type == _DECISION_RECORD_TYPE:
        token = _extract_token(content)
        if token is None:
            errors.append('DECISION_RECORD requires a TOKEN field: TOKEN::"<value>"')
            return ValidationResult(valid=False, errors=errors, card_type=card_type)

        # --- Check 4: TOKEN format ---
        if not _TOKEN_FORMAT_RE.match(token):
            errors.append(
                f"TOKEN '{token}' does not match required format "
                r"^[A-Z][A-Z0-9_-]{1,126}[A-Z0-9_]-[0-9]{8}$ "
                "(ADR-RFC-ARCH-004 §1.3)"
            )
            return ValidationResult(valid=False, errors=errors, card_type=card_type, token=token)

        # --- Check 4c: ADR-RFC-ARCH-004 §4.1 invariants (#88) ---
        # Required-field presence (#2), VERSION shape (#1-residual), TOKEN-date
        # consistency (#3-residual), STATUS/TIER enums (#5/#6), reserved names
        # (#7), SUPERSEDED_BY iff (#9), HUMAN_ADR_REF resolution (#11), and the
        # ratification-provenance WARNING (#12). Collect-more-errors; the
        # offending field is named in each message for operator UX.
        _check_agr_invariants(working_dir, content, token, errors, warnings)
        # #14/#15 need the block lines, so they read the raw (unstripped) text.
        _check_topic_block_keys(raw_content, errors)
        _check_core_key_placement(raw_content, errors)
        _check_list_fields(raw_content, errors, warnings)

    elif card_type in _FACET_CARD_TYPES:
        token = _extract_id(content)
        if token is None:
            errors.append(f'{card_type} requires an ID field: ID::"<value>"')
            return ValidationResult(valid=False, errors=errors, card_type=card_type)

        # --- Check 4: ID format ---
        if not _FACET_ID_FORMAT_RE.match(token):
            errors.append(
                f"ID '{token}' does not match required format "
                r"^[A-Z][A-Z0-9_]{2,127}$ "
                "(ADR-RFC-ARCH-005 §1.3)"
            )
            return ValidationResult(valid=False, errors=errors, card_type=card_type, token=token)

        # --- Check 4a: REPO_ID required for facet cards (Bug 8) ---
        repo_id = _extract_repo_id(content)
        if not repo_id:
            errors.append(
                f"REPO_ID field is required for {card_type} but was not found. "
                "Add REPO_ID::<repo-slug> to the META block."
            )
            return ValidationResult(valid=False, errors=errors, card_type=card_type, token=token)

        # --- Check 4b: REPO_ID slug safety (P1 cubic finding) ---
        if not _SAFE_SLUG_RE.match(repo_id):
            errors.append(
                f"REPO_ID must be a safe slug (alphanumeric, hyphens, underscores only): {repo_id}"
            )
            return ValidationResult(valid=False, errors=errors, card_type=card_type, token=token)

    # --- Check 5: SUPERSEDED_BY target existence ---
    superseded_by = _superseded_by_value(content)
    if superseded_by is not None:
        listed = superseded_by.strip() == "[" or (
            superseded_by.strip().startswith("[") and superseded_by.strip().endswith("]")
        )
        # A bare ``[`` is a list the reader could not close: ``_check_list_fields`` has
        # already reported it, so there is no target to look up.
        targets: list[str] | None = None
        if not listed:
            targets = [superseded_by]
        elif superseded_by.strip() != "[":
            targets = list_items(superseded_by)
        if targets is not None and not targets:
            errors.append(
                "SUPERSEDED_BY is an empty list; it must name the superseding TOKEN "
                "(ADR-RFC-ARCH-004 §4.1 #9)."
            )
        if targets and len(set(targets)) > 1:
            errors.append(
                f"SUPERSEDED_BY names {len(set(targets))} distinct TOKENs "
                f"({', '.join(sorted(set(targets)))}); a record has exactly one successor "
                "(ADR-RFC-ARCH-004 §4.1 #8). Duplicates of one TOKEN are accepted."
            )
        for target in targets or []:
            if not lookup_token_deterministic(working_dir, target):
                errors.append(
                    f"SUPERSEDED_BY target '{target}' not found in governance store. "
                    "The referenced TOKEN must exist before it can be superseded."
                )
        # Continue to collect more errors

    # --- Check 5a: ISSUE_REF shape (ADR-RFC-ARCH-004 §4.1 invariant #10) ---
    # ISSUE_REF is OPTIONAL: absence (zero matching lines) is valid.
    # _ISSUE_REF_LINE_RE is greedy — it always captures the full raw value
    # including trailing garbage, so shape validation catches every malformed
    # form without a separate presence detector.
    issue_ref_raw_lines = _ISSUE_REF_LINE_RE.findall(content)
    if len(issue_ref_raw_lines) > 1:
        errors.append(
            "ISSUE_REF field appears multiple times; expected at most one "
            "(ADR-RFC-ARCH-004 §4.1 #10)."
        )
        # Continue to collect more errors
    elif len(issue_ref_raw_lines) == 1:
        raw = issue_ref_raw_lines[0].strip()
        if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
            raw = raw[1:-1]
        _check_issue_ref_shape(raw, errors)
        # Continue to collect more errors

    # --- Check 6: Token uniqueness (must NOT already exist for new records) ---
    if token is not None and lookup_token_deterministic(working_dir, token):
        errors.append(
            f"TOKEN/ID '{token}' already exists in the governance store. "
            "Duplicate tokens are not allowed for new records."
        )

    if errors:
        return ValidationResult(
            valid=False,
            errors=errors,
            warnings=warnings,
            card_type=card_type,
            token=token,
        )

    # --- Check 7: Compute target path + path traversal guard (Bug 4 via caller) ---
    target_path: Path | None = None
    if token is not None:
        effective_repo_id = repo_id or ""
        target_path = _compute_target_path(working_dir, card_type, token, effective_repo_id)

    # warnings (§4.2) may be non-empty even on a valid record — e.g. §4.1 #12
    # ratification provenance. They are advisory and do NOT flip ``valid``.
    return ValidationResult(
        valid=True,
        errors=[],
        warnings=warnings,
        token=token,
        card_type=card_type,
        target_path=target_path,
    )


# ---------------------------------------------------------------------------
# EPIC4 PR-5: the quoted-YAML Gate A branch and the ONE syntax seam.
# ---------------------------------------------------------------------------


def validate_record_content(
    working_dir: Path, content: str, *, existing_record: Path | None = None
) -> ValidationResult:
    """The syntax seam: classify ``content`` once, then run the matching Gate A branch.

    A quoted-YAML record (first line ``---``, ADR-RFC-ARCH-004 §1.1) is judged by
    ``_validate_yaml_impl`` and targets ``{token}.md``; any other content goes,
    byte-for-byte unchanged, to :func:`validate_octave_content` and targets
    ``{token}.oct.md``. The dispatch is by ``classify_record_text`` on the content
    alone. ``submit_governance`` also checks the first line itself before choosing which
    validator to call (existing callers patch ``validate_octave_content`` there), so this
    function is the Gate A dispatch, not the only syntax decision in the tool. A later
    prose-mode-emits-YAML change can reuse :func:`decision_record_path` and
    ``ValidationResult.syntax``.

    ``existing_record`` (#203 S2) is for the append_ruling path ONLY: the path of the
    YAML ``.md`` record being rewritten. The YAML branch's §4.1 #4 uniqueness check then
    accepts that one file as the TOKEN's match, and nothing else: any other record file
    (``.md`` or ``.oct.md``) under ``.hestai/decisions`` or ``.hestai/context/concepts``
    that declares the TOKEN or is named for it (an ``.oct.md`` twin, a second ``.md``)
    still raises the duplicate error. Non-record files (e.g. ``.txt``) never count. The OCTAVE branch ignores it. Content mode never passes
    it, so a new record still needs an unused TOKEN.

    Never raises on bad input. Always returns a ValidationResult.
    """
    record = classify_record_text(content)
    if record.syntax != "yaml":
        return validate_octave_content(working_dir, content)
    errors: list[str] = []
    warnings: list[str] = []
    try:
        return _validate_yaml_impl(
            working_dir, record, content, errors, warnings, existing_record=existing_record
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Unexpected validation error: {exc}")
        return ValidationResult(valid=False, errors=errors, warnings=warnings, syntax="yaml")


def _existing_record_files(working_dir: Path, token: str) -> list[Path]:
    """Files named ``<token>.oct.md`` or ``<token>.md`` anywhere under ``.hestai/decisions``.

    Catches a file lookup cannot see (an unparseable record, a stray file), so a write
    can never silently replace one. ``token`` is §1.3-valid, so it is glob-safe.
    """
    root = working_dir / ".hestai" / "decisions"
    if not root.is_dir():
        return []
    found = {*root.rglob(f"{token}.md"), *root.rglob(f"{token}.oct.md")}
    return sorted(path for path in found if path.is_file())


def _token_record_paths(working_dir: Path, token: str) -> set[Path]:
    """Every record file (``.md`` / ``.oct.md``) under ``.hestai/decisions`` or
    ``.hestai/context/concepts`` that declares ``token`` or is named for it (resolved).

    The readers' pairing applies: an ``.oct.md`` declares only as OCTAVE, a plain
    ``.md`` under ``.hestai/decisions`` only as a YAML record with the DECISION_RECORD
    header. Unlike the lexer's boolean lookup, a YAML file that declares the TOKEN but
    does not parse still counts, and same-name files (decisions or concepts) count
    whatever they hold. Non-record files and MANIFEST rows are not consulted. This is
    the LOCAL second line; the authority is the broader main-OID check in
    ``linker.read_append_base``.
    """
    found = set(_existing_record_files(working_dir, token))
    hestai = working_dir / ".hestai"
    for root in (hestai / "decisions", hestai / "context" / "concepts"):
        if not root.is_dir():
            continue
        for path in root.rglob("*.md"):
            if not path.is_file():
                continue
            try:
                record = read_record(path)
            except OSError:
                continue
            if path.name in (f"{token}.md", f"{token}.oct.md"):
                hit = True
            elif path.name.endswith(".oct.md"):
                hit = record.syntax == "octave" and declares_token(record.text, token)
            else:
                hit = (
                    root.name == "decisions"
                    and record.syntax == "yaml"
                    and has_yaml_decision_header(record.text)
                    and declares_token(record.text, token)
                )
            if hit:
                found.add(path)
    return {path.resolve() for path in found}


def _display_path(working_dir: Path, path: Path) -> str:
    try:
        return path.relative_to(working_dir.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _check_rewrite_is_sole_match(
    working_dir: Path, token: str, rewritten: Path, errors: list[str]
) -> None:
    """§4.1 #4 for an append_ruling rewrite: ``rewritten`` may be the TOKEN's only match.

    This judges the caller's checkout. Zero local matches (a checkout behind main) are
    accepted ONLY because the append path has already enforced the same sole-match rule
    at the pinned main OID the branch is cut from (``linker.read_append_base``, CE
    6538573589); this local check is the second line, not the authority.
    """
    target = rewritten if rewritten.is_absolute() else working_dir / rewritten
    if not target.name.endswith(".md") or target.name.endswith(".oct.md"):
        errors.append(
            f"existing_record must name the YAML .md record being rewritten "
            f"(got {target.name!r})."
        )
        return
    target = target.resolve()
    for other in sorted(_token_record_paths(working_dir, token) - {target}):
        errors.append(
            f"TOKEN/ID '{token}' already exists in the governance store: '{other.name}' "
            f"at {_display_path(working_dir, other)} also declares or is named for it, so "
            f"rewriting {_display_path(working_dir, target)} would leave a duplicate."
        )


def _validate_yaml_impl(
    working_dir: Path,
    record: RecordText,
    raw_content: str,
    errors: list[str],
    warnings: list[str],
    *,
    existing_record: Path | None = None,
) -> ValidationResult:
    """Gate A for a quoted-YAML DECISION_RECORD (reader errors + the shared invariants)."""
    if record.diagnostic is not None:
        reject = record.diagnostic
        errors.append(
            f"YAML record rejected at line {reject['line']}: {reject['construct']} "
            "(ADR-RFC-ARCH-004 §1.1 strict quoted-YAML subset)."
        )
        return ValidationResult(valid=False, errors=errors, syntax="yaml", reject=reject)

    parsed = parse_decision_record(record.text)
    fields = parsed["fields"]
    card_type = parsed["type"]
    token = parsed["token"]

    def fail(**kwargs: str | None) -> ValidationResult:
        return ValidationResult(
            valid=False, errors=errors, warnings=warnings, syntax="yaml", **kwargs  # type: ignore[arg-type]
        )

    if card_type != _DECISION_RECORD_TYPE:
        errors.append(
            f'A YAML record must declare type: "{_DECISION_RECORD_TYPE}" '
            f"(found {card_type!r}); only DECISION_RECORDs are written as quoted YAML."
        )
        return fail(card_type=card_type)
    if token is None:
        errors.append('DECISION_RECORD requires a token field: token: "<value>"')
        return fail(card_type=card_type)
    if not _TOKEN_FORMAT_RE.fullmatch(token):
        errors.append(
            f"TOKEN '{token}' does not match required format "
            r"^[A-Z][A-Z0-9_-]{1,126}[A-Z0-9_]-[0-9]{8}$ "
            "(ADR-RFC-ARCH-004 §1.3)"
        )
        return fail(card_type=card_type, token=token)

    present = {key.upper() for key in ("type", "token") if parsed[key] is not None}  # type: ignore[literal-required]
    present |= {
        key.upper()
        for key in ("version", "status", "tier", "decision", "because", "authored_at")
        if parsed[key] is not None  # type: ignore[literal-required]
    }
    present |= set(fields)
    values = _RecordValues(
        present=present,
        version=parsed["version"],
        status=parsed["status"],
        tier=parsed["tier"],
        authored_at=parsed["authored_at"],
        has_superseded_by=bool(fields.get("SUPERSEDED_BY")),
        human_adr_ref=fields.get("HUMAN_ADR_REF"),  # as written: the bytes persisted are unstripped
        has_ratified_by="RATIFIED_BY" in fields,
    )
    _check_common_invariants(working_dir, token, values, errors, warnings, "the front matter")
    for key in REASONING_FIELDS:
        value = parsed[key.lower()]  # type: ignore[literal-required]
        if value is not None:
            _check_density_value(key, value, errors)

    # --- SUPERSEDED_BY / supersedes targets must exist ---
    superseded_by = fields.get("SUPERSEDED_BY")
    if superseded_by and not lookup_token_deterministic(working_dir, superseded_by):
        errors.append(
            f"SUPERSEDED_BY target '{superseded_by}' not found in governance store. "
            "The referenced TOKEN must exist before it can be superseded."
        )
    if "SUPERSEDES" in fields:
        for target in parse_supersedes_list(fields["SUPERSEDES"]):
            if not lookup_token_deterministic(working_dir, target):
                errors.append(
                    f"supersedes target '{target}' not found in governance store. "
                    "The referenced TOKEN must exist before it can be superseded."
                )

    # --- ISSUE_REF shape (§4.1 #10) ---
    if "ISSUE_REF" in fields:
        _check_issue_ref_shape(fields["ISSUE_REF"], errors)

    # --- TOKEN uniqueness ACROSS .oct.md and .md (§4.1 #4) ---
    # An append_ruling rewrite may match its OWN file and nothing else.
    if existing_record is not None:
        _check_rewrite_is_sole_match(working_dir, token, existing_record, errors)
    elif lookup_token_deterministic(working_dir, token):
        errors.append(
            f"TOKEN/ID '{token}' already exists in the governance store. "
            "Duplicate tokens are not allowed for new records."
        )
    else:
        for existing in _existing_record_files(working_dir, token):
            errors.append(
                f"TOKEN/ID '{token}' already exists in the governance store: a file "
                f"named '{existing.name}' is present at "
                f"{existing.relative_to(working_dir).as_posix()} and would be replaced."
            )

    # --- canonical bytes + round-trip gate (write-mode ruling C) ---
    canonical: str | None = None
    try:
        canonical = canonicalize_yaml_record(raw_content)
    except YamlSyntaxError as exc:
        errors.append(f"YAML record cannot be canonicalised: {exc}")

    if errors:
        return fail(card_type=card_type, token=token)

    return ValidationResult(
        valid=True,
        warnings=warnings,
        token=token,
        card_type=card_type,
        target_path=decision_record_path(working_dir, token, "yaml"),
        syntax="yaml",
        canonical_content=canonical,
    )
