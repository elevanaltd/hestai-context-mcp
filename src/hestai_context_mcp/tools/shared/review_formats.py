"""Shared review format constants and pattern matching utilities.

Single source of truth for review comment formats used by the submit_review
MCP tool. Harvested from hestai-mcp legacy with the proven pattern-matching
logic for review-gate CI compliance.

Roles: CE, CIV, CRS, HO, IL, PE, SR, TMG
Verdicts: APPROVED, BLOCKED, CONDITIONAL
"""

import json
import re

# --- Valid roles and verdicts ---
VALID_ROLES: frozenset[str] = frozenset({"CRS", "CE", "SR", "IL", "HO", "TMG", "CIV", "PE"})
VALID_VERDICTS: frozenset[str] = frozenset({"APPROVED", "BLOCKED", "CONDITIONAL"})

# --- IL uses SELF-REVIEWED keyword instead of APPROVED ---
_IL_APPROVED_KEYWORD = "SELF-REVIEWED"

# --- HO uses REVIEWED keyword instead of APPROVED ---
_HO_APPROVED_KEYWORD = "REVIEWED"


def matches_approval_pattern(text: str, prefix: str, keyword: str) -> bool:
    """Check if text matches a flexible approval pattern.

    Matches patterns like:
      - 'CRS APPROVED:' (original exact format)
      - 'CRS (Gemini): APPROVED' (parenthetical model annotation)
      - 'CRS --- APPROVED' (em dash separator)
      - 'IL SELF-REVIEWED:' and 'IL (Claude): SELF-REVIEWED:'

    Uses word boundaries around both prefix and keyword to prevent false
    positives. Strips markdown bold/italic formatting before matching.

    Args:
        text: The text to search for the approval pattern.
        prefix: The role prefix (e.g., 'CRS', 'CE', 'IL').
        keyword: The approval keyword (e.g., 'APPROVED', 'SELF-REVIEWED', 'GO').

    Returns:
        True if the pattern is found, False otherwise.
    """
    # Strip markdown bold/italic markers so **APPROVED** matches as APPROVED
    cleaned = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)

    prefix_re = re.compile(rf"(?:^|(?<=\|))\s*{re.escape(prefix)}\b", re.MULTILINE | re.IGNORECASE)
    keyword_re = re.compile(rf"\b{re.escape(keyword)}\b", re.IGNORECASE)

    for line in cleaned.splitlines():
        prefix_match = prefix_re.search(line)
        if not prefix_match:
            continue
        keyword_match = keyword_re.search(line, prefix_match.end())
        if keyword_match:
            return True

    return False


def _has_approval(texts: list[str], prefix: str, keyword: str) -> bool:
    """Check if any text in the list matches the approval pattern."""
    return any(matches_approval_pattern(t, prefix, keyword) for t in texts)


def has_crs_approval(texts: list[str]) -> bool:
    """Check if any text contains a CRS approval (APPROVED or GO)."""
    return _has_approval(texts, "CRS", "APPROVED") or _has_approval(texts, "CRS", "GO")


def has_ce_approval(texts: list[str]) -> bool:
    """Check if any text contains a CE approval (APPROVED or GO)."""
    return _has_approval(texts, "CE", "APPROVED") or _has_approval(texts, "CE", "GO")


def has_tmg_approval(texts: list[str]) -> bool:
    """Check if any text contains a TMG approval (APPROVED or GO)."""
    return _has_approval(texts, "TMG", "APPROVED") or _has_approval(texts, "TMG", "GO")


def has_civ_approval(texts: list[str]) -> bool:
    """Check if any text contains a CIV approval (APPROVED or GO)."""
    return _has_approval(texts, "CIV", "APPROVED") or _has_approval(texts, "CIV", "GO")


def has_pe_approval(texts: list[str]) -> bool:
    """Check if any text contains a PE approval (APPROVED or GO)."""
    return _has_approval(texts, "PE", "APPROVED") or _has_approval(texts, "PE", "GO")


def has_sr_approval(texts: list[str]) -> bool:
    """Check if any text contains an SR approval (APPROVED or GO)."""
    return _has_approval(texts, "SR", "APPROVED") or _has_approval(texts, "SR", "GO")


# Compiled regex for role-agnostic self-review matching.
_SELF_REVIEW_RE = re.compile(
    r"(?:^|(?<=\|))\s*" r"\w[\w-]*" r"(?:\s*\([^)]*\))?" r"[\s:—–\-]*" r"SELF-REVIEWED\b",
    re.MULTILINE | re.IGNORECASE,
)


def has_self_review(texts: list[str]) -> bool:
    """Check if any text contains a self-review from any role or person.

    Role-agnostic: matches any word/identifier followed by SELF-REVIEWED.

    Args:
        texts: List of comment/body texts to search.

    Returns:
        True if any text contains a valid self-review pattern.
    """
    for text in texts:
        cleaned = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)
        for line in cleaned.splitlines():
            if _SELF_REVIEW_RE.search(line):
                return True
    return False


def has_ho_review(texts: list[str]) -> bool:
    """Check if any text contains an HO supervisory review (REVIEWED)."""
    return _has_approval(texts, "HO", "REVIEWED")


def format_review_comment(
    role: str,
    verdict: str,
    assessment: str,
    model_annotation: str | None = None,
    commit_sha: str | None = None,
) -> str:
    """Format a review comment that will clear the review gate.

    Produces comments in the canonical format that matches_approval_pattern()
    will accept. For IL role with APPROVED verdict, the keyword is mapped to
    SELF-REVIEWED. For HO role with APPROVED verdict, the keyword is mapped
    to REVIEWED.

    Appends a machine-readable metadata HTML comment on a second line.

    Args:
        role: Reviewer role (TMG, CRS, CE, CIV, PE, IL, HO, SR).
        verdict: Review verdict (APPROVED, BLOCKED, CONDITIONAL).
        assessment: Review assessment content.
        model_annotation: Optional model name (e.g., 'Gemini') for annotation.
        commit_sha: Optional PR head SHA the reviewer verified.

    Returns:
        Formatted review comment string with metadata on line 2.
    """
    # Validate commit_sha: must be 7-40 hex characters, silently drop invalid
    if commit_sha is not None:
        clean_sha = commit_sha.strip()
        commit_sha = clean_sha if re.fullmatch(r"[0-9a-fA-F]{7,40}", clean_sha) else None

    # Map IL APPROVED to SELF-REVIEWED, HO APPROVED to REVIEWED
    if role == "IL" and verdict == "APPROVED":
        keyword = _IL_APPROVED_KEYWORD
    elif role == "HO" and verdict == "APPROVED":
        keyword = _HO_APPROVED_KEYWORD
    else:
        keyword = verdict

    # Build the prefix with optional model annotation
    prefix = f"{role} ({model_annotation})" if model_annotation else role

    human_line = f"{prefix} {keyword}: {assessment}"

    # Build metadata dict
    metadata: dict[str, str | None] = {
        "role": role,
        "provider": model_annotation.lower() if model_annotation else None,
        "verdict": keyword,
        "sha": commit_sha[:7] if commit_sha else None,
    }
    meta_json = json.dumps(metadata, separators=(",", ":"))
    meta_line = f"<!-- review: {meta_json} -->"

    return f"{human_line}\n{meta_line}"
