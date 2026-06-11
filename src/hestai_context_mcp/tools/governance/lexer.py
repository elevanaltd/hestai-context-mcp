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

# Max characters assembled for the context budget (future Gate C backend).
_CONTEXT_BUDGET_CHARS = 25_000

# Exact-match pattern for TOKEN or ID field assignment (OCTAVE form),
# quote-optional per the AGR canonical-form convergence ruling.
# Matches the bare canonical form  TOKEN::<value> / ID::<value>  AND the legacy
# quoted form  TOKEN::"<value>" / ID::"<value>"  where <value> == the token.
# Compiled with re.MULTILINE; EVERY branch (quoted and bare) ends with a
# (?:\s*$) line-end anchor (only trailing whitespace, then end-of-line) so that:
#   - a shorter token (HO-FOO-20260101) never prefix-matches a longer one, and
#   - a trailing-garbage line (TOKEN::"<value>" junk) is NOT counted as a clean
#     existence hit (cubic P2 — the quoted branches were previously unanchored,
#     and a (?=\s|$) lookahead was satisfied by the leading space of the junk).
_FIELD_EXACT_RE_TEMPLATE = (
    r'(?m)(?:TOKEN::\s*(?:"{token}"|{token})\s*$' r'|ID::\s*(?:"{token}"|{token})\s*$)'
)


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
      - .hestai/decisions/**/*.oct.md
      - .hestai/context/concepts/**/*.oct.md

    Uses a regex that matches the OCTAVE field-assignment form
    ``TOKEN::"<token>"`` or ``ID::"<token>"`` exactly, preventing
    prefix-match false positives (e.g. ``HO-FOO`` matching ``HO-FOO-BAR``).

    Args:
        working_dir: Project root directory.
        token: Token or ID string to search for.

    Returns:
        True if found in any file, False otherwise.
    """
    hestai = working_dir / ".hestai"
    decisions_root = hestai / "decisions"
    concepts_root = hestai / "context" / "concepts"

    pattern = re.compile(_FIELD_EXACT_RE_TEMPLATE.format(token=re.escape(token)))

    for root in (decisions_root, concepts_root):
        if not root.exists():
            continue
        for oct_file in root.rglob("*.oct.md"):
            try:
                content = oct_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if pattern.search(content):
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
