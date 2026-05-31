"""Dumb Type Checker (Gate A Validator).

Validates OCTAVE governance content using regex only. No AST parsing,
no octave-mcp invocation, no external library imports.

North Star boundary (PROD §4 IS_NOT: document format system — octave-mcp owns):
  - Sentinel detection: first line must be r'^===([A-Z_]+)===$' (document start).
  - TYPE field: r'TYPE::(WORD)' within the first ===META=== block.
  - TOKEN field: r'TOKEN::"([^"]+)"' for DECISION_RECORD.
  - ID field: r'ID::"([^"]+)"' for facet cards.

Gate B (future) will wire the REAL OCTAVE validator to octave-mcp over stdio.
This file is intentionally dumb by design.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from hestai_context_mcp.tools.governance.lexer import lookup_token_deterministic

# ---------------------------------------------------------------------------
# Regex patterns (compiled once at module load)
# ---------------------------------------------------------------------------

# OCTAVE sentinel: must be at the very start of the document (Bug 7 fix).
# Pattern: starts with ===TYPENAME=== on the very first line.
_SENTINEL_RE = re.compile(r"\A===([A-Z_]+)===\s*(?:\r?\n|$)")

# TYPE field in META block
_TYPE_RE = re.compile(r"(?m)TYPE::(\w+)")

# TOKEN field (DECISION_RECORD): quoted string
_TOKEN_RE = re.compile(r'TOKEN::"([^"]+)"')

# ID field (facet cards): quoted string
_ID_QUOTED_RE = re.compile(r'(?m)^  ID::"([^"]+)"')

# SUPERSEDED_BY field: quoted string
_SUPERSEDED_BY_RE = re.compile(r'SUPERSEDED_BY::"([^"]+)"')

# TOKEN format validation per ADR-RFC-ARCH-004 §1.3
# ^[A-Z][A-Z0-9_-]{1,126}[A-Z0-9_]-[0-9]{8}$
_TOKEN_FORMAT_RE = re.compile(r"^[A-Z][A-Z0-9_-]{1,126}[A-Z0-9_]-[0-9]{8}$")

# Facet card ID format per ADR-RFC-ARCH-005 §1.3
# ^[A-Z][A-Z0-9_]{2,127}$
_FACET_ID_FORMAT_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")

# Known card types and their placement rules
_DECISION_RECORD_TYPE = "DECISION_RECORD"
_FACET_CARD_TYPES = frozenset({"CONCEPT_CARD", "FRAME_CARD", "CLUSTER_CARD", "PHASE_CARD"})
_KNOWN_TYPES = frozenset([_DECISION_RECORD_TYPE]) | _FACET_CARD_TYPES

# REPO_ID field for facet cards
_REPO_ID_RE = re.compile(r"REPO_ID::([^\s]+)")

# Safe slug pattern for REPO_ID validation (alphanumeric, hyphens, underscores only)
_SAFE_SLUG_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


@dataclass
class ValidationResult:
    """Result of Gate A dumb type checking.

    Fields:
        valid: True if all checks passed, False otherwise.
        errors: List of human-readable error strings (empty when valid=True).
        token: Extracted TOKEN or ID value (may be None if extraction failed).
        card_type: Extracted TYPE value (may be None if extraction failed).
        target_path: Computed target path for placement (None on error).
    """

    valid: bool
    errors: list[str] = field(default_factory=list)
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
    """Extract the TOKEN field (DECISION_RECORD style)."""
    m = _TOKEN_RE.search(content)
    if m:
        return m.group(1)
    return None


def _extract_id(content: str) -> str | None:
    """Extract the ID field (facet card style)."""
    m = _ID_QUOTED_RE.search(content)
    if m:
        return m.group(1)
    return None


def _extract_superseded_by(content: str) -> str | None:
    """Extract the SUPERSEDED_BY field if present."""
    m = _SUPERSEDED_BY_RE.search(content)
    if m:
        return m.group(1)
    return None


def _extract_repo_id(content: str) -> str | None:
    """Extract the REPO_ID field for facet card placement."""
    m = _REPO_ID_RE.search(content)
    if m:
        val = m.group(1).strip()
        # Strip trailing non-alphanumeric chars (e.g. commas, whitespace)
        val = val.rstrip(",\t\r\n ")
        return val or None
    return None


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

    try:
        return _validate_impl(working_dir, content, errors)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Unexpected validation error: {exc}")
        return ValidationResult(valid=False, errors=errors)


def _validate_impl(working_dir: Path, content: str, errors: list[str]) -> ValidationResult:
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

    # --- Check 6: Token uniqueness (must NOT already exist for new records) ---
    if token is not None and lookup_token_deterministic(working_dir, token):
        errors.append(
            f"TOKEN/ID '{token}' already exists in the governance store. "
            "Duplicate tokens are not allowed for new records."
        )

    if errors:
        return ValidationResult(valid=False, errors=errors, card_type=card_type, token=token)

    # --- Check 7: Compute target path + path traversal guard (Bug 4 via caller) ---
    target_path: Path | None = None
    if token is not None:
        effective_repo_id = repo_id or ""
        target_path = _compute_target_path(working_dir, card_type, token, effective_repo_id)

    return ValidationResult(
        valid=True,
        errors=[],
        token=token,
        card_type=card_type,
        target_path=target_path,
    )
