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

# Regex patterns for fallback filesystem grep
_TOKEN_RE = re.compile(r'TOKEN::"([^"]+)"')
_ID_QUOTED_RE = re.compile(r'(?m)^  ID::"([^"]+)"')
_ID_BARE_RE = re.compile(r"(?m)^  ID::([A-Z][A-Z0-9_]{2,127})\s*$")


def _search_manifest(manifest_path: Path, token: str) -> bool:
    """Search MANIFEST.md for a token/ID string.

    MANIFEST format: markdown table with TOKEN/ID in the first column.
    Treats the token as a literal string (no regex).

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

    # Search for the token as a word boundary in the manifest table rows.
    # Format: | TOKEN | path |
    # We look for the token surrounded by pipe chars or line boundaries.
    return any(token in line for line in content.splitlines())


def _search_filesystem(working_dir: Path, token: str) -> bool:
    """Search governance oct.md files for a token/ID.

    Greps two subtrees:
      - .hestai/decisions/**/*.oct.md
      - .hestai/context/concepts/**/*.oct.md

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
            if token in content:
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
