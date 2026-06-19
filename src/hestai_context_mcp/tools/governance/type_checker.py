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

from hestai_context_mcp.tools.governance.lexer import lookup_token_deterministic

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
    """

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    token: str | None = None
    card_type: str | None = None
    target_path: Path | None = None


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
    return fields


def _strip_quotes(value: str) -> str:
    """Strip one surrounding pair of double quotes (§1.1 quote-optionality)."""
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


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
        return working_dir / ".hestai" / "decisions" / f"{token}.oct.md"

    # Facet card types
    return working_dir / ".hestai" / "context" / "concepts" / repo_id / f"{token}.oct.md"


def _check_agr_invariants(
    working_dir: Path,
    content: str,
    token: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Enforce the ADR-RFC-ARCH-004 §4.1 invariants for a DECISION_RECORD (#88).

    Collect-more-errors style (mirrors the established #10 ISSUE_REF / #8
    SUPERSEDED_BY precedent): every finding is appended to ``errors`` (or
    ``warnings`` for §4.1 #12) so a single round-trip surfaces ALL problems with
    the offending field NAMED. Regex-only (North Star §4 / PROD I3); never
    raises (PROD I4). ``token`` is the already-extracted, §1.3-format-valid
    TOKEN.

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
    meta = _extract_meta_fields(content)

    # --- #2: Required fields present (the core silent-pass class) ---
    # TYPE and TOKEN are proven present by the time we get here; check the rest
    # so a record the read parser would mark unparseable is rejected on write.
    for required in REQUIRED_META_FIELDS:
        if required not in meta:
            errors.append(
                f"Required field '{required}' is missing from the META block "
                "(ADR-RFC-ARCH-004 §1.2 / §4.1 #2)."
            )

    # --- #1-residual: VERSION two-segment shape (§1.5) ---
    if "VERSION" in meta:
        version = _strip_quotes(meta["VERSION"])
        if not _VERSION_SHAPE_RE.match(version):
            errors.append(
                f"VERSION '{version}' is not a two-segment MAJOR.MINOR string "
                "(ADR-RFC-ARCH-004 §1.5 / §4.1 #1). "
                "Patch levels (e.g. '1.0.0') and non-numeric values are rejected."
            )

    # --- #5: STATUS enum ---
    status = _strip_quotes(meta["STATUS"]) if "STATUS" in meta else None
    if status is not None and status not in STATUS_VALUES:
        errors.append(
            f"STATUS '{status}' is not a valid value. "
            f"Must be one of {', '.join(sorted(STATUS_VALUES))} "
            "(ADR-RFC-ARCH-004 §1.4 / §4.1 #5)."
        )

    # --- #6: TIER enum ---
    if "TIER" in meta:
        tier = _strip_quotes(meta["TIER"])
        if tier not in TIER_VALUES:
            errors.append(
                f"TIER '{tier}' is not a valid value. "
                f"Must be one of {', '.join(sorted(TIER_VALUES))} "
                "(ADR-RFC-ARCH-004 §1.2 / §4.1 #6)."
            )

    # --- #7: Reserved names MUST NOT appear (§1.2) ---
    for reserved in sorted(RESERVED_FIELD_NAMES):
        if reserved in meta:
            errors.append(
                f"Reserved field '{reserved}' MUST NOT appear in a v1.x record "
                "(ADR-RFC-ARCH-004 §1.2 reserved-names / §4.1 #7)."
            )

    # --- #3-residual: TOKEN date suffix == UTC date of AUTHORED_AT (§1.3) ---
    # The comparison is against the UTC DATE PORTION (§1.3): an offset timestamp
    # is normalised to UTC before the date is taken (T3 CIV rework — a lexical
    # leading-date capture mis-handles offsets and silently passes a non-
    # timestamp AUTHORED_AT).
    authored_at = _strip_quotes(meta["AUTHORED_AT"]) if "AUTHORED_AT" in meta else None
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
    has_superseded_by = _extract_superseded_by(content) is not None
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

    # --- #11: HUMAN_ADR_REF resolves under the repository ---
    human_adr_m = _HUMAN_ADR_REF_RE.search(content)
    if human_adr_m is not None:
        ref = human_adr_m.group(1) if human_adr_m.group(1) is not None else human_adr_m.group(2)
        ref = (ref or "").strip()
        if not _human_adr_ref_resolves(working_dir, ref):
            errors.append(
                f"HUMAN_ADR_REF '{ref}' does not resolve to a file under the "
                "repository (ADR-RFC-ARCH-004 §1.2 / §4.1 #11)."
            )

    # --- #12: Ratification provenance (WARNING per §4.2, NOT error) ---
    has_ratified_by = _RATIFIED_BY_RE.search(content) is not None
    if status is not None and status != "PROPOSED" and not has_ratified_by:
        warnings.append(
            f"RATIFIED_BY is absent on a record whose STATUS is '{status}' "
            "(not PROPOSED); ratification provenance is recommended "
            "(ADR-RFC-ARCH-004 §4.1 #12, severity WARNING)."
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


def _validate_impl(
    working_dir: Path,
    content: str,
    errors: list[str],
    warnings: list[str],
) -> ValidationResult:
    """Internal validation implementation."""
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
    superseded_by = _extract_superseded_by(content)
    if superseded_by is not None and not lookup_token_deterministic(working_dir, superseded_by):
        errors.append(
            f"SUPERSEDED_BY target '{superseded_by}' not found in governance store. "
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
        if not raw or not _ISSUE_REF_SHAPE_RE.fullmatch(raw):
            errors.append(
                f"ISSUE_REF '{raw}' does not match a valid shape. "
                "ISSUE_REF must be a GitHub issue URL "
                "(https://github.com/<org>/<repo>/issues/<n>) or the "
                "repo:<repo-id>#<n> shorthand (ADR-RFC-ARCH-004 §4.1 #10)."
            )
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
