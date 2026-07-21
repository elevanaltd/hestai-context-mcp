"""
Shared review format constants and pattern matching utilities.

Single source of truth for review comment formats used by both:
- scripts/validate_review.py (CI gate validation)
- submit_review MCP tool (programmatic review submission)

Extracted from validate_review.py to prevent format drift (I2 tension).
"""

import json
import re

# --- Review tier constants ---
TIER_0_EXEMPT = "TIER_0_EXEMPT"
TIER_1_SELF = "TIER_1_SELF"
TIER_2_STANDARD = "TIER_2_STANDARD"
TIER_3_STRICT = "TIER_3_STRICT"  # Deprecated: use TIER_3_CRITICAL
TIER_3_CRITICAL = "TIER_3_CRITICAL"
TIER_4_STRATEGIC = "TIER_4_STRATEGIC"

# --- Valid roles and verdicts ---
VALID_ROLES: frozenset[str] = frozenset({"CRS", "CE", "SR", "IL", "HO", "TMG", "CIV", "PE"})
VALID_VERDICTS: frozenset[str] = frozenset({"APPROVED", "BLOCKED", "CONDITIONAL"})

# --- IL uses SELF-REVIEWED keyword instead of APPROVED ---
_IL_APPROVED_KEYWORD = "SELF-REVIEWED"

# --- HO uses REVIEWED keyword instead of APPROVED ---
_HO_APPROVED_KEYWORD = "REVIEWED"

# --- Negation / hedge guard (trust-model defect fix) ---
# A role-anchored verdict only clears the gate when the span BETWEEN the role
# prefix and the verdict verb is free of negation/conditional intent. Without
# this guard the matcher accepted idiomatic NON-approvals -- e.g.
# "CRS does not approve" or "CRS: I would approve if the tests passed" -- so a
# blocking reviewer's own words wrongly cleared the gate (fail-open inversion).
#
# The guard inspects ONLY the gap between the role prefix and the verdict verb,
# so benign trailing assessment text ("APPROVED: would have blocked if ...") is
# unaffected, and the legitimate model-in-its-own-pipe-cell table formats
# ("| CRS | Gemini | **APPROVED** |") still clear because a model name / tick /
# pipe is not a negation token.
#
# NOTE: a denylist is inherently incomplete -- it cannot catch every phrasing of
# refusal. It is chosen deliberately for its correctness/complexity trade-off:
# it removes the verified false-clears while preserving every legitimate format.
# The deliberately-strict anti-spoof path has_crs_model_approval() does NOT use
# this matcher and is intentionally unchanged.
_NEGATION_HEDGE_RE = re.compile(
    r"\b(?:"
    r"not|n't|cannot|can't|won't|wouldn't|shouldn't|couldn't|don't|doesn't|didn't|"
    r"will\s+not|do\s+not|does\s+not|did\s+not|"
    r"never|unable|unless|until|pending|blocked|reject|fail|"
    r"if|would|should"
    r")\b",
    re.IGNORECASE,
)

# --- Unicode dash normalisation (match-only, never mutates stored/emitted text) ---
# Several Unicode dash and hyphen codepoints are visually indistinguishable from
# ASCII '-' (U+002D) but bypass the ASCII-only hyphen guards in the GO compound
# detector and the separator class.  Normalising them to '-' before any pattern
# match lets the existing guards handle them uniformly.
# Codepoints folded: U+2010 (‐), U+2011 (‑ non-breaking), U+2012 (‒ figure),
# U+2013 (– en-dash), U+2014 (— em-dash), U+2015 (― horizontal bar), U+2212 (− minus).
_UNICODE_DASH_RE = re.compile(r"[‐‑‒–—―−]")


def _normalize_dashes(text: str) -> str:
    """Fold Unicode dash/hyphen variants to ASCII '-' for match-only normalisation.

    This is a pure read-time transformation: it is applied only to text being
    inspected by the approval matchers.  It never mutates stored data, emitted
    verdicts, or the comment text returned by format_review_comment().
    """
    return _UNICODE_DASH_RE.sub("-", text)


def matches_approval_pattern(text: str, prefix: str, keyword: str) -> bool:
    """Check if text matches a flexible approval pattern.

    Matches patterns like:
      - 'CRS APPROVED:' (original exact format)
      - 'CRS (Gemini): APPROVED' (parenthetical model annotation with colon)
      - 'CRS (Gemini) --- APPROVED' (parenthetical with em dash separator)
      - 'CRS (Gemini) -- APPROVED' (parenthetical with en dash separator)
      - 'CRS (Gemini) - APPROVED' (parenthetical with hyphen separator)
      - 'CRS --- APPROVED' (em dash separator, no parenthetical)
      - 'CRS: APPROVED' (colon separator, no parenthetical)
      - 'CRS  APPROVED' (extra whitespace)
      - 'IL SELF-REVIEWED:' and 'IL (Claude): SELF-REVIEWED:'
      - '| CRS | Gemini | **APPROVED** |' (markdown table with bold)
      - '## TMG APPROVED ✅' (markdown heading, stripped before matching)
      - '  ## CRS APPROVED:' (indented markdown heading)

    Uses word boundaries around both prefix and keyword to prevent false
    positives (e.g., 'XCRS' must not match 'CRS', 'APPROVEDLY' must not
    match 'APPROVED').

    Strips markdown bold/italic formatting before matching, then checks
    each line for both tokens in order with word boundaries.

    Args:
        text: The text to search for the approval pattern.
        prefix: The role prefix (e.g., 'CRS', 'CE', 'IL').
        keyword: The approval keyword (e.g., 'APPROVED', 'SELF-REVIEWED', 'GO').

    Returns:
        True if the pattern is found, False otherwise.
    """
    # Normalise Unicode dash variants to ASCII '-' before any matching so that
    # visually-identical dashes (en-dash, em-dash, non-breaking hyphen, etc.) do
    # not bypass the GO compound guard or the separator patterns.  Match-only:
    # this transformation is never reflected in any stored or emitted text.
    text = _normalize_dashes(text)
    # Strip markdown bold/italic markers so **APPROVED** matches as APPROVED
    cleaned = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)

    # Role must appear at a line-start position to prevent false positives
    # from prose like "TMG+CRS+CE+CIV+PE by tier), GO aliases".
    # Valid positions: actual start of line (with optional whitespace) or
    # after a markdown table pipe character.
    prefix_re = re.compile(rf"(?:^|(?<=\|))\s*{re.escape(prefix)}\b", re.MULTILINE | re.IGNORECASE)
    # Verdict-synonym tolerance: treat the canonical APPROVED keyword as the
    # conjugation family APPROVE(D|S)? so a table cell reading "APPROVE" or
    # "APPROVES" clears the gate exactly as "APPROVED" does (regression:
    # elevana-studio PR #1257 verdict-summary table). Word boundaries are
    # preserved (\bAPPROVE(?:D|S)?\b), so "APPROVEMENT" still does NOT match,
    # and only the APPROVED family is widened — GO/REVIEWED/SELF-REVIEWED
    # callers pass other keywords and are unaffected. The deliberately-strict
    # anti-spoof path has_crs_model_approval() is intentionally NOT widened.
    #
    # GO hyphen-compound guard (issue #138): \bGO\b matches the leading token
    # of "GO-WITH-CONDITIONS" because the hyphen is a non-word character that
    # satisfies the word boundary on both sides.
    #
    # Two-char lookbehind (?<![a-zA-Z0-9]-): the char immediately before the
    # hyphen must NOT be alphanumeric.  This correctly distinguishes:
    #   - "NO-GO"         → 'O' before '-' is alphanumeric → rejected ✓
    #   - ")-GO"          → ')' before '-' is not alphanumeric → cleared ✓
    #   - "GO-WITH-..."   → trailing (?!-) rejects ✓
    #   - "GO:", " GO", "**GO**" → no adjacent hyphen at all → cleared ✓
    #
    # A single-char lookbehind (?<!-) was tried first but incorrectly rejected
    # "ROLE (Model)-GO" where the separator hyphen is directly before GO; the
    # two-char form avoids that regression (cubic P2 / rework#2 Fix A).
    #
    # NOTE: the model-anchored path has_crs_model_approval() uses only the
    # trailing guard GO(?!-) — the leading guard is not needed there because
    # the separator class [:—–-]* consumes the chars before the keyword, so
    # NO-GO cannot reach the keyword position. DO NOT "unify" these two paths.
    if keyword == "APPROVED":
        keyword_pattern = r"APPROVE(?:D|S)?"
    elif keyword == "GO":
        keyword_pattern = r"(?<![a-zA-Z0-9]-)GO(?!-)"
    else:
        keyword_pattern = re.escape(keyword)
    keyword_re = re.compile(rf"\b{keyword_pattern}\b", re.IGNORECASE)
    # Strip markdown heading markers (##, ###, etc.) per-line so agents that
    # write '## TMG APPROVED ✅' are accepted alongside the canonical format.
    heading_re = re.compile(r"^\s*#{1,6}\s*")

    for line in cleaned.splitlines():
        stripped = heading_re.sub("", line)
        prefix_match = prefix_re.search(stripped)
        if not prefix_match:
            continue
        # Keyword must appear after the prefix on the same line. Scan EVERY
        # occurrence: a line clears only if some verdict verb has a gap (between
        # the role prefix and that verb) free of negation/hedge intent. This
        # rejects role-anchored non-approvals ("CRS does not approve") while
        # preserving model-in-its-own-cell table formats and benign assessment
        # text that follows the verdict.
        for keyword_match in keyword_re.finditer(stripped, prefix_match.end()):
            gap = stripped[prefix_match.end() : keyword_match.start()]
            if _NEGATION_HEDGE_RE.search(gap):
                continue
            return True

    return False


def _has_approval(texts: list[str], prefix: str, keyword: str) -> bool:
    """Check if any text in the list matches the approval pattern."""
    return any(matches_approval_pattern(t, prefix, keyword) for t in texts)


def has_crs_approval(texts: list[str]) -> bool:
    """Check if any text contains a CRS approval (APPROVED or GO).

    Args:
        texts: List of comment/body texts to search.

    Returns:
        True if CRS approval found.
    """
    return _has_approval(texts, "CRS", "APPROVED") or _has_approval(texts, "CRS", "GO")


def has_crs_model_approval(texts: list[str], model: str) -> bool:
    """Check if any text contains a CRS approval from a specific model.

    Matches patterns like 'CRS (Gemini) APPROVED:' or 'CRS (Gemini): GO'.
    The model tag must be directly followed by the approval keyword with only
    separator characters (whitespace, colon, dashes) in between. This prevents
    spoofing where a single APPROVED keyword satisfies multiple model checks,
    or where intervening tokens like BLOCKED are ignored.

    Note: this function does NOT strip markdown heading markers. It is
    intentionally stricter than matches_approval_pattern() — its purpose is
    spoofing prevention (ensuring a specific model name is present), not
    format tolerance.

    Args:
        texts: List of comment/body texts to search.
        model: The model name to match (e.g., 'Gemini', 'Codex').

    Returns:
        True if model-specific CRS approval found.
    """
    # Strict pattern: CRS(model) followed by only separator chars then APPROVED|GO.
    # Allowed separators: whitespace, colon, em dash, en dash, hyphen (0 or more).
    # No arbitrary tokens (like "and CRS (Codex)" or "BLOCKED") permitted between.
    # CRS must appear at line-start position (same rule as matches_approval_pattern).
    #
    # GO hyphen-compound guard (issue #138): trailing-only lookahead GO(?!-) is
    # sufficient here — unlike the general matches_approval_pattern path which needs
    # BOTH lookbehind AND lookahead to block NO-GO (because \bGO\b alone matches the
    # trailing GO in "NO-GO"), this anchored path is safe with trailing-only because:
    #   - The separator class [:—–-]* is consumed before GO, so "NO-GO" can never
    #     reach the keyword position (the 'N' in 'NO-' is not in the separator class).
    #   - A legitimate hyphen separator as in "CRS (Gemini)-GO" is consumed by the
    #     separator class, leaving GO with no preceding hyphen — the leading lookbehind
    #     (?<!-) would incorrectly reject this format (cubic P2 regression).
    # DO NOT "unify" this to (?<!-)GO(?!-) — that re-introduces the P2 regression.
    pattern = re.compile(
        rf"(?:^|(?<=\|))\s*CRS\s*\(\s*{re.escape(model)}\s*\)\s*[:—–\-]*\s*(?:APPROVED|GO(?!-))\b",
        re.IGNORECASE | re.MULTILINE,
    )

    for text in texts:
        # Normalise Unicode dash variants to ASCII '-' (match-only, same as
        # matches_approval_pattern) so that en-dash/em-dash compounds like
        # "GO–WITH-CONDITIONS" are rejected by the trailing GO(?!-) guard.
        text = _normalize_dashes(text)
        # Strip markdown bold/italic markers
        cleaned = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)
        for line in cleaned.splitlines():
            if pattern.search(line):
                return True
    return False


def has_ce_approval(texts: list[str]) -> bool:
    """Check if any text contains a CE approval (APPROVED or GO).

    Args:
        texts: List of comment/body texts to search.

    Returns:
        True if CE approval found.
    """
    return _has_approval(texts, "CE", "APPROVED") or _has_approval(texts, "CE", "GO")


# Compiled regex for role-agnostic self-review matching.
# Matches any word (including hyphenated identifiers like "skills-expert")
# at line-start position (consistent with matches_approval_pattern),
# optionally followed by a parenthetical model annotation and separators,
# then SELF-REVIEWED with word boundary.
_SELF_REVIEW_RE = re.compile(
    r"(?:^|(?<=\|))\s*"  # Line-start or after pipe (consistent with approval matcher)
    r"\w[\w-]*"  # Role/name word (e.g., IL, skills-expert, Shaun)
    r"(?:\s*\([^)]*\))?"  # Optional parenthetical (e.g., (Claude))
    r"[\s:—–\-]*"  # Separators (whitespace, colon, dashes)
    r"SELF-REVIEWED\b",  # Keyword with word boundary
    re.MULTILINE | re.IGNORECASE,
)


def has_self_review(texts: list[str]) -> bool:
    """Check if any text contains a self-review from any role or person.

    Role-agnostic: matches any word/identifier followed by SELF-REVIEWED.

    Matches patterns like:
      - 'IL SELF-REVIEWED: fixed typo'
      - 'skills-expert SELF-REVIEWED: updated GATES'
      - 'Shaun SELF-REVIEWED: quick config change'
      - 'IL (Claude): SELF-REVIEWED: quick fix' (via flexible matching)

    A bare 'SELF-REVIEWED' without a preceding role/name does NOT match.

    Args:
        texts: List of comment/body texts to search.

    Returns:
        True if any text contains a valid self-review pattern.
    """
    for text in texts:
        # Strip markdown bold/italic markers for consistency
        cleaned = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)
        for line in cleaned.splitlines():
            if _SELF_REVIEW_RE.search(line):
                return True
    return False


def has_il_self_review(texts: list[str]) -> bool:
    """Check if any text contains an IL self-review.

    Deprecated: Use has_self_review() for role-agnostic matching.
    Kept for backward compatibility.

    Args:
        texts: List of comment/body texts to search.

    Returns:
        True if IL SELF-REVIEWED found.
    """
    return has_self_review(texts)


def has_ho_review(texts: list[str]) -> bool:
    """Check if any text contains an HO supervisory review.

    When HO delegates to IL and then reviews the work, this constitutes
    a supervisory review (higher authority than self-review) and satisfies T1.

    Matches patterns like:
      - 'HO REVIEWED: delegated to IL, verified output'
      - 'HO (Claude): REVIEWED: verified'

    Args:
        texts: List of comment/body texts to search.

    Returns:
        True if HO REVIEWED found.
    """
    return _has_approval(texts, "HO", "REVIEWED")


def has_tmg_approval(texts: list[str]) -> bool:
    """Check if any text contains a TMG approval (APPROVED or GO).

    TMG (Test Methodology Guardian) validates test coverage and quality.

    Args:
        texts: List of comment/body texts to search.

    Returns:
        True if TMG approval found.
    """
    return _has_approval(texts, "TMG", "APPROVED") or _has_approval(texts, "TMG", "GO")


def has_civ_approval(texts: list[str]) -> bool:
    """Check if any text contains a CIV approval (APPROVED or GO).

    CIV (Critical Implementation Validator) validates implementation
    correctness against specifications.

    Args:
        texts: List of comment/body texts to search.

    Returns:
        True if CIV approval found.
    """
    return _has_approval(texts, "CIV", "APPROVED") or _has_approval(texts, "CIV", "GO")


def has_pe_approval(texts: list[str]) -> bool:
    """Check if any text contains a PE approval (APPROVED or GO).

    PE (Principal Engineer) validates long-term architectural sustainability.

    Args:
        texts: List of comment/body texts to search.

    Returns:
        True if PE approval found.
    """
    return _has_approval(texts, "PE", "APPROVED") or _has_approval(texts, "PE", "GO")


def has_sr_approval(texts: list[str]) -> bool:
    """Check if any text contains an SR approval (APPROVED or GO).

    SR (Standards Reviewer) validates system standards documentation for
    alignment, contradiction detection, completeness, and structural integrity.

    Args:
        texts: List of comment/body texts to search.

    Returns:
        True if SR approval found.
    """
    return _has_approval(texts, "SR", "APPROVED") or _has_approval(texts, "SR", "GO")


def has_gr_approval(texts: list[str]) -> bool:
    """Check if any text contains a GR or SR approval (APPROVED or GO).

    Deprecated: Use has_sr_approval(). GR was renamed to SR (Standards Reviewer).
    Kept for backward compatibility -- matches both GR and SR prefixes so
    legacy "GR APPROVED" comments still clear the gate.
    """
    return (
        has_sr_approval(texts)
        or _has_approval(texts, "GR", "APPROVED")
        or _has_approval(texts, "GR", "GO")
    )


def format_review_comment(
    role: str,
    verdict: str,
    assessment: str,
    model_annotation: str | None = None,
    commit_sha: str | None = None,
) -> str:
    """Format a review comment that will clear the review gate.

    Produces comments in the canonical format that matches_approval_pattern()
    will accept. This ensures submit_review produces gate-clearing comments.

    For IL role with APPROVED verdict, the keyword is mapped to SELF-REVIEWED.
    For HO role with APPROVED verdict, the keyword is mapped to REVIEWED.
    For BLOCKED/CONDITIONAL verdicts, the comment uses the verdict directly
    (these don't clear the gate but are valid review comments).

    Appends a machine-readable metadata HTML comment on a second line for
    structured audit trail parsing.

    Args:
        role: Reviewer role (TMG, CRS, CE, CIV, PE, IL, HO).
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


# --- Metadata regex for parsing structured review metadata ---
_METADATA_RE = re.compile(r"<!-- review: (\{.*?\}) -->")


def parse_review_metadata(text: str) -> dict[str, str | None] | None:
    """Extract structured metadata from a review comment.

    Looks for ``<!-- review: {...} -->`` HTML comment and parses the JSON.

    Args:
        text: Review comment text to parse.

    Returns:
        Parsed metadata dict or None if not found or invalid.
    """
    # Strip markdown code blocks and inline code to avoid matching
    # example metadata in documentation (e.g., PR body with backtick-quoted examples).
    stripped = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    stripped = re.sub(r"`[^`]+`", "", stripped)
    match = _METADATA_RE.search(stripped)
    if not match:
        return None
    try:
        return json.loads(match.group(1))  # type: ignore[no-any-return]
    except (json.JSONDecodeError, ValueError):
        return None


def extract_review_metadata(texts: list[str]) -> list[dict[str, str | None]]:
    """Batch extraction of metadata from multiple comments.

    Args:
        texts: List of comment texts to scan.

    Returns:
        List of parsed metadata dicts (only for comments that have metadata).
    """
    results: list[dict[str, str | None]] = []
    for text in texts:
        meta = parse_review_metadata(text)
        if meta is not None:
            results.append(meta)
    return results
