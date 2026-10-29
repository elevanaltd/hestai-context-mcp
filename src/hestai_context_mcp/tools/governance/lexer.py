"""Context Assembler (Lexer) for governance intake.

Provides deterministic token/ID lookup for:
  1. SUPERSEDES target verification (does referenced token exist?)
  2. Duplicate detection (does proposed token already exist?)

Lookup strategy:
  1. Read .hestai/MANIFEST.md if it exists (flat markdown table).
  2. Fall back to grepping .hestai/decisions/**/*.oct.md and
     .hestai/context/concepts/**/*.oct.md directly.

North Star boundary: no OCTAVE AST parsing — regex and string search only.
No LLM calls. Deterministic for identical filesystem state.
"""

import re
from pathlib import Path

from hestai_context_mcp.core.agent_readable_governance_parser import (
    annotate_lines,
    extract_yaml_token,
    has_yaml_decision_header,
    is_yaml_front_matter,
)

# Max characters assembled for the context budget (future Gate C backend).
_CONTEXT_BUDGET_CHARS = 25_000

# Exact-match pattern for TOKEN or ID field assignment (OCTAVE form),
# quote-optional per the AGR canonical-form convergence ruling.
# Matches the bare canonical form  TOKEN::<value> / ID::<value>  AND the legacy
# quoted form  TOKEN::"<value>" / ID::"<value>"  where <value> == the token.
# Compiled with re.MULTILINE; EVERY branch (quoted and bare) is LINE-ANCHORED at
# BOTH ends:
#   - line START via ``^\s*`` — admits OCTAVE indentation but forbids a
#     ``*TOKEN::`` / ``*ID::``-suffixed key (e.g. ``DOCUMENT_TOKEN::`` /
#     ``PARENT_ID::``) from substring-leaking as a clean existence hit
#     (issue #85 — the previous template had no line-start anchor), and
#   - line END via ``(?:\s*$)`` (only trailing whitespace, then end-of-line) so:
#       - a shorter token (HO-FOO-20260101) never prefix-matches a longer one, and
#       - a trailing-garbage line (TOKEN::"<value>" junk) is NOT counted as a
#         clean existence hit (cubic P2 — the quoted branches were previously
#         unanchored, and a (?=\s|$) lookahead was satisfied by the leading
#         space of the junk).
_FIELD_EXACT_RE_TEMPLATE = (
    r'(?m)(?:^\s*TOKEN::\s*(?:"{token}"|{token})\s*$' r'|^\s*ID::\s*(?:"{token}"|{token})\s*$)'
)


def declares_token(content: str, token: str) -> bool:
    """True iff ``content`` declares ``token`` in a TOP-LEVEL TOKEN/ID line.

    Lines inside a topic record's CURRENT / RULINGS blocks are not declarations
    (ADR-RFC-ARCH-004 v1.3 §1.7: block lines are not META), so they are dropped
    before the exact-match search (#203 S2 follow-up a). A quoted-YAML record
    (first line ``---``) declares ``token`` iff its top-level front-matter
    ``token: "…"`` line matches; its block lines and markdown body never count.
    Pure; regex only.
    """
    if is_yaml_front_matter(content):
        return extract_yaml_token(content) == token
    top_level = "".join(line for block, line in annotate_lines(content) if block is None)
    pattern = re.compile(_FIELD_EXACT_RE_TEMPLATE.format(token=re.escape(token)))
    return pattern.search(top_level) is not None


def _search_manifest(manifest_path: Path, token: str) -> bool:
    """Search MANIFEST.md for a token/ID string with exact first-column match.

    MANIFEST format: markdown table rows of the form ``| TOKEN | path |``.
    Splits each data row on ``|``, strips the first cell, and compares
    exactly to ``token``.  This prevents ``HO-FOO-20260101`` from matching
    a row whose first cell is ``HO-FOO-BAR-20260101``.

    Args:
        manifest_path: Path to the MANIFEST.md file.
        token: Token or ID string to search for.

    Returns:
        True if found, False otherwise.
    """
    try:
        content = manifest_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False

    for line in content.splitlines():
        # Only process table data rows (skip header, separator, blank lines)
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        parts = stripped.split("|")
        # parts[0] is empty (before leading |), parts[1] is first cell, …
        if len(parts) >= 2 and parts[1].strip() == token:
            return True
    return False


def _search_filesystem(working_dir: Path, token: str) -> bool:
    """Search governance oct.md files for a token/ID using exact field match.

    Greps two subtrees:
      - .hestai/decisions/**/*.oct.md plus quoted-YAML ``*.md`` decision records
      - .hestai/context/concepts/**/*.oct.md

    Uses a regex that matches the OCTAVE field-assignment form
    ``TOKEN::"<token>"`` or ``ID::"<token>"`` exactly, preventing
    prefix-match false positives (e.g. ``HO-FOO`` matching ``HO-FOO-BAR``).
    Only top-level declarations count (``declares_token``): a TOKEN line nested
    in a CURRENT / RULINGS block does not make a token exist.

    Args:
        working_dir: Project root directory.
        token: Token or ID string to search for.

    Returns:
        True if found in any file, False otherwise.
    """
    hestai = working_dir / ".hestai"
    decisions_root = hestai / "decisions"
    concepts_root = hestai / "context" / "concepts"

    for root in (decisions_root, concepts_root):
        if not root.exists():
            continue
        for oct_file in root.rglob("*.oct.md"):
            try:
                content = oct_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if declares_token(content, token):
                return True
        if root != decisions_root:
            continue
        for md_file in root.rglob("*.md"):
            if md_file.name.endswith(".oct.md"):
                continue
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if has_yaml_decision_header(content) and declares_token(content, token):
                return True

    return False


def lookup_token_deterministic(working_dir: Path, token: str) -> bool:
    """Check whether a TOKEN or ID exists in the governance store.

    Lookup order:
      1. MANIFEST.md (fast path — O(lines)).
      2. Filesystem grep of .hestai/decisions/ and .hestai/context/concepts/
         (fallback when no MANIFEST or MANIFEST is stale).

    This function is deterministic and read-only. It does NOT invoke any LLM,
    does NOT parse OCTAVE AST, and does NOT modify any file.

    Args:
        working_dir: Project root directory.
        token: The TOKEN (for DECISION_RECORDs) or ID (for facet cards) to look up.

    Returns:
        True if the token exists in the governance store, False otherwise.
    """
    manifest_path = working_dir / ".hestai" / "MANIFEST.md"

    if manifest_path.exists():
        found = _search_manifest(manifest_path, token)
        if found:
            return True
        # If MANIFEST exists but token not found, still fall through to
        # filesystem in case MANIFEST is stale (e.g. recent commit not reflected).

    return _search_filesystem(working_dir, token)


def assemble_context(working_dir: Path) -> str:
    """Assemble governance context clipped to the token budget.

    Reads all governance oct.md files and concatenates their content,
    clipped to _CONTEXT_BUDGET_CHARS characters. Intended for future
    Gate C backend consumption.

    Args:
        working_dir: Project root directory.

    Returns:
        Concatenated governance content string, max ~25k chars.
    """
    hestai = working_dir / ".hestai"
    decisions_root = hestai / "decisions"
    concepts_root = hestai / "context" / "concepts"

    parts: list[str] = []
    total = 0

    for root in (decisions_root, concepts_root):
        if not root.exists():
            continue
        for oct_file in sorted(root.rglob("*.oct.md")):
            if total >= _CONTEXT_BUDGET_CHARS:
                break
            try:
                content = oct_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            remaining = _CONTEXT_BUDGET_CHARS - total
            chunk = content[:remaining]
            parts.append(chunk)
            total += len(chunk)

    return "\n".join(parts)
