#!/usr/bin/env python3
"""
Review validation script - enforces review requirements based on PR changes.
Called by pre-commit hooks and CI pipeline.

Version: 2.0.0 (SECURITY: Fail-closed error handling)
Source: https://github.com/elevanaltd/HestAI-MCP
Last updated: 2026-01-19
Breaking Change: Now exits non-zero on CI failures (was: fail-open)
"""

# Critical-Engineer: consulted for Review-gate fail-closed validation
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# --- Advisory bot accounts ---
# Bot comments are ADVISORY ONLY: they provide context for reviewers but NEVER
# satisfy or block review gates.  The canonical list uses GitHub's [bot] suffix
# convention; _BOT_LOGIN_SET is derived for comment filtering.
ADVISORY_BOTS: list[str] = [
    "cubic-dev-ai[bot]",
    "github-copilot[bot]",
]

# --- Known bot account logins whose comments must be excluded from approval matching ---
# Derived from ADVISORY_BOTS (strip "[bot]" suffix) plus legacy login variants
# that GitHub may use for the same accounts.
# NOTE: This set has a DIFFERENT lifecycle from ADVISORY_BOTS.  A bot removed
# from ADVISORY_BOTS (e.g., Qodo) must STAY here so its comments can never
# satisfy an approval gate — even if we no longer surface it in advisory output.
_BOT_LOGIN_SET: frozenset[str] = frozenset(
    {name.removesuffix("[bot]") for name in ADVISORY_BOTS}
    | {
        "github-actions",
        "copilot",  # Legacy login variant for github-copilot[bot]
        "Copilot",  # GitHub API returns capital-C variant
        "cubic-bot",
        "qodo-code-review",  # Removed from ADVISORY_BOTS but kept for gate exclusion
        "qodo-merge-pro",
        "qodo-merge-pro-for-open-source",
    }
)


def get_changed_files() -> list[dict[str, Any]]:
    """Get list of changed files with line counts and file status.

    Each returned dict includes:
      - path: new file path (or current path for non-renamed files)
      - added: lines added
      - deleted: lines deleted
      - total_changed: added + deleted
      - status: git status letter (A=added, M=modified, D=deleted, R=renamed)
      - previous_path: (renames only) the old file path before the rename

    For renamed files, ``previous_path`` is populated so that callers can
    fetch the BASE blob using the old path (issue #417).
    """
    try:
        # In CI, compare against base branch; locally use cached
        if "CI" in os.environ:
            # Get the base branch (usually main)
            base_ref = os.environ.get("GITHUB_BASE_REF", "origin/main")
            numstat_cmd = ["git", "diff", f"{base_ref}...HEAD", "--numstat"]
            status_cmd = ["git", "diff", f"{base_ref}...HEAD", "--name-status"]
        else:
            # Local: check staged files
            numstat_cmd = ["git", "diff", "--cached", "--numstat"]
            status_cmd = ["git", "diff", "--cached", "--name-status"]

        # Build rename map from --name-status first: old_path -> new_path.
        # For renames git emits: "R<score>\t<old_path>\t<new_path>"
        # We key by new_path to match against numstat entries, and store old_path
        # as previous_path.
        status_result = subprocess.run(status_cmd, capture_output=True, text=True, check=True)
        status_map: dict[str, str] = {}  # new_path -> status letter
        rename_map: dict[str, str] = {}  # new_path -> old_path
        for line in status_result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                # Status is first char of first field (e.g., "M", "A", "R100")
                status_letter = parts[0][0]
                if status_letter == "R" and len(parts) >= 3:
                    # Rename: parts[1]=old_path, parts[2]=new_path
                    old_path = parts[1]
                    new_path = parts[2]
                    status_map[new_path] = "R"
                    rename_map[new_path] = old_path
                else:
                    filename = parts[-1]  # Last field is the path
                    status_map[filename] = status_letter

        # Get diff stats (line counts).
        # --numstat for renamed files emits either:
        #   <added>\t<deleted>\t<old_path>\t<new_path>  (4 fields, with -M)
        # or the brace-notation form:
        #   <added>\t<deleted>\t{old => new}  (3 fields)
        # We normalise both: for the 4-field form use new_path (parts[3]); for
        # the 3-field form use rename_map to resolve the correct new_path key.
        result = subprocess.run(numstat_cmd, capture_output=True, text=True, check=True)

        files = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) == 4:
                # 4-field rename line: added, deleted, old_path, new_path
                added, deleted, _old, new_path = parts
                files.append(
                    {
                        "path": new_path,
                        "added": int(added) if added != "-" else 0,
                        "deleted": int(deleted) if deleted != "-" else 0,
                        "total_changed": (int(added) if added != "-" else 0)
                        + (int(deleted) if deleted != "-" else 0),
                    }
                )
            elif len(parts) == 3:
                added, deleted, filename = parts
                # Resolve arrow/brace rename notation that real git --numstat emits.
                # Three forms exist (all 3-field, ' => ' inside the filename field):
                #   Plain:     "old/path.md => new/path.md"
                #   Same-dir:  "dir/{old.md => new.md}"
                #   Cross-dir: "{old/dir => new/dir}/file.md"
                if " => " in filename:
                    brace_match = re.search(r"\{([^}]*) => ([^}]*)\}", filename)
                    if brace_match:
                        # Replace the entire {old => new} fragment with just the new side.
                        filename = (
                            filename[: brace_match.start()]
                            + brace_match.group(2)
                            + filename[brace_match.end() :]
                        )
                    else:
                        # Plain "old_path => new_path" — take the new (right) side.
                        filename = filename.split(" => ", 1)[1]
                files.append(
                    {
                        "path": filename,
                        "added": int(added) if added != "-" else 0,
                        "deleted": int(deleted) if deleted != "-" else 0,
                        "total_changed": (int(added) if added != "-" else 0)
                        + (int(deleted) if deleted != "-" else 0),
                    }
                )

        # Merge status (and previous_path for renames) into file dicts.
        for f in files:
            path = f["path"]
            f["status"] = status_map.get(path, "M")  # Default to M if unknown
            if path in rename_map:
                f["previous_path"] = rename_map[path]

        return files
    except subprocess.CalledProcessError as e:
        # SECURITY FIX: Fail closed in CI, permissive locally
        if "CI" in os.environ:
            print(f"❌ Git command failed in CI: {e}", file=sys.stderr)
            sys.exit(1)
        return []


def _is_generated_json(path: str) -> bool:
    """Check if a JSON file is a generated/lock file (exempt) vs hand-edited (not exempt).

    Per governance rule ``**/*.json[when:generated_file]``, JSON is exempt ONLY
    when it is a generated file. Hand-edited config files (package.json,
    tsconfig.json, .eslintrc.json, pyrightconfig.json, .vscode/*.json) are NOT
    exempt because humans maintain them and changes can introduce bugs.

    Only truly auto-generated JSON (lock files, coverage reports) qualifies.
    """
    generated_patterns = [
        r"(^|/)package-lock\.json$",
        r"(^|/)coverage/.*\.json$",
    ]
    return any(re.search(pattern, path) for pattern in generated_patterns)


# --- Facet → Required Reviewers mapping ---
FACET_ROLE_MAP: dict[str, set[str]] = {
    "META_CONTROL_PLANE": {"CIV", "CE", "CRS", "SR", "TMG"},  # PE excluded: T4 is manual-only
    "EXECUTABLE_SPEC": {"CE", "CRS", "SR"},
    "GOVERNANCE": {"SR"},
    "SECURITY": {"CIV", "CE", "CRS", "TMG"},
    "ROUTINE_CODE": {"CE", "CRS", "TMG"},
}

# Hardcoded paths that always trigger META_CONTROL_PLANE
_META_CONTROL_PLANE_PATHS = {
    "scripts/validate_review.py",
    ".github/workflows/review-gate.yml",
}

# Security path patterns
_SECURITY_PATTERNS = [
    r"(^|/)auth/",
    r"(^|/)session/",
    r"(^|/)config/env",
    r"(^|/)path_utils",
]

# Security-load-bearing basenames (issue #1833): leading-dot, extensionless
# files in consumer repos that gate a security invariant (pgtap quarantine
# list, RLS drift-exception ledger). Neither the .md/tests/.lock exempt
# patterns nor any extension-based rule below can match a leading-dot
# extensionless file, so these are matched by exact basename instead.
# MIP: two basenames, no configurable per-consumer-repo path list — add a
# third only when a third real consumer exists.
_SECURITY_BASENAMES = {
    ".pgtap-quarantine",
    ".drift-exceptions",
}

# OCTAVE types that classify as EXECUTABLE_SPEC
_EXECUTABLE_SPEC_TYPES = {"AGENT_DEFINITION", "SKILL"}


def _sniff_octave_type(path: str) -> str:
    """Read META.TYPE from an OCTAVE file. Max 50 lines, fail-safe.

    Args:
        path: File path to read.

    Returns:
        The TYPE value string (e.g., 'AGENT_DEFINITION', 'RULE') or empty string.
    """
    try:
        with open(path, encoding="utf-8") as f:
            for _ in range(50):
                line = f.readline()
                if not line:
                    break
                if "TYPE::" in line:
                    parts = line.split("::", 1)
                    if len(parts) == 2:
                        return parts[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _classify_file_facet(path: str) -> str | None:
    """Classify a single file path into a content facet.

    Returns:
        Facet name string, or None if the file is exempt.
    """
    # Bundled hub skill/pattern files (.md but NOT exempt — governance artifacts)
    # These define agent behavior and must be classified before exempt check
    if "/library/skills/" in path and path.endswith("/SKILL.md"):
        return "EXECUTABLE_SPEC"
    if "/library/patterns/" in path and path.endswith(".md"):
        return "EXECUTABLE_SPEC"

    # Exempt patterns
    exempt_patterns = [
        r".*(?<!\.oct)\.md$",  # Markdown exempt, but NOT .oct.md
        r"^tests/.*$",
        r".*\.lock$",
    ]

    # Check standard exempt patterns
    if any(re.match(pattern, path) for pattern in exempt_patterns):
        return None

    # Security-load-bearing extensionless dotfiles (issue #1833): checked by
    # exact basename immediately after the exempt-pattern check so it cannot
    # be shadowed by any later extension-based or path-based branch (JSON,
    # .oct.md, code-extension, or default fall-through all key off suffixes
    # or directory segments these basenames don't have).
    if path.rsplit("/", 1)[-1] in _SECURITY_BASENAMES:
        return "SECURITY"

    # JSON: only generated ones are exempt
    if path.endswith(".json"):
        if _is_generated_json(path):
            return None
        # Non-generated JSON is ROUTINE_CODE
        return "ROUTINE_CODE"

    # META_CONTROL_PLANE: hardcoded paths
    if path in _META_CONTROL_PLANE_PATHS:
        return "META_CONTROL_PLANE"
    # Also match review-requirements.oct.md
    if "review-requirements.oct.md" in path:
        return "META_CONTROL_PLANE"

    # .oct.md files: classify by path or sniff TYPE
    if path.endswith(".oct.md"):
        # Agent/skill .oct.md files are always EXECUTABLE_SPEC by path
        # (even if deleted and can't be sniffed for TYPE)
        if "/library/agents/" in path or "/library/skills/" in path:
            return "EXECUTABLE_SPEC"
        # For other .oct.md files, sniff TYPE to distinguish
        octave_type = _sniff_octave_type(path)
        if octave_type in _EXECUTABLE_SPEC_TYPES:
            return "EXECUTABLE_SPEC"
        # All other .oct.md (RULE, STANDARD, NORTH_STAR_SUMMARY, unknown) -> GOVERNANCE
        return "GOVERNANCE"

    # Security paths
    if any(re.search(pattern, path) for pattern in _SECURITY_PATTERNS):
        return "SECURITY"

    # Architecture/infrastructure paths (base classes, shared modules, hooks, tools, MCP)
    architecture_patterns = [
        r"(^|/)base\.py$",
        r"/shared/",
        r"(^|/)abstract/",
        r"(^|/)hooks/",
        r"(^|/)modules/tools/",
        r"(^|/)mcp/tools/",
        r"^clink/agents/",
    ]
    if any(re.search(pattern, path) for pattern in architecture_patterns):
        return "SECURITY"  # Architecture changes require same elevated review as security

    # SQL files -> SECURITY (high-impact data changes)
    if path.endswith(".sql"):
        return "SECURITY"

    # Code files (.py, .ts, .js, etc.) -> ROUTINE_CODE
    code_extensions = {".py", ".ts", ".js", ".tsx", ".jsx", ".sh"}
    if any(path.endswith(ext) for ext in code_extensions):
        return "ROUTINE_CODE"

    # YAML, TOML, config files -> ROUTINE_CODE
    if any(path.endswith(ext) for ext in (".yml", ".yaml", ".toml", ".cfg", ".ini")):
        return "ROUTINE_CODE"

    # Default: treat as ROUTINE_CODE (fail-safe: gets reviewed)
    return "ROUTINE_CODE"


def classify_pr_facets(
    files: list[dict[str, Any]],
    declared_roles: set[str] | None = None,
) -> tuple[set[str], set[str], str, str]:
    """Classify PR files into content facets and compute required reviewers.

    Each file is assigned a facet based on its path and content type.
    Required reviewers = union of all facets' role requirements UNION any
    ``declared_roles`` (content-aware escalation, issue #412).
    Tier label is backward-computed from the reviewer set.

    Escalation-only semantics (issue #412): ``declared_roles`` can only ADD
    required reviewers, never remove them. A non-empty ``declared_roles`` set
    suppresses BOTH the ``TIER_0_EXEMPT`` (all-exempt) and ``TIER_1_SELF``
    (small single-file) short-circuits, so a docs-only PR carrying a
    declaration still escalates to the declared chain. ``declared_roles`` is
    expected to be pre-filtered through ``ALLOWED_ESCALATION_ROLES`` by
    :func:`_collect_bitemporal_declarations`.

    Args:
        files: List of changed file dicts with 'path' and 'total_changed' keys.
        declared_roles: Optional set of escalation roles unioned in BEFORE the
            early returns. Must already be whitelist-filtered. Defaults to None
            (no declaration -> unchanged diff-shape behaviour).

    Returns:
        Tuple of (facets, required_roles, tier_label, reason):
        - facets: Set of content facets found (e.g., {'ROUTINE_CODE', 'GOVERNANCE'})
        - required_roles: Set of reviewer roles needed (e.g., {'CE', 'CRS', 'TMG', 'SR'})
        - tier_label: Backward-computed display tier (TIER_0_EXEMPT .. TIER_4_STRATEGIC)
        - reason: Human-readable explanation
    """
    declared: set[str] = set(declared_roles) if declared_roles else set()

    facets: set[str] = set()
    non_exempt_files = []

    for f in files:
        facet = _classify_file_facet(f["path"])
        if facet is not None:
            facets.add(facet)
            non_exempt_files.append(f)

    # CRITICAL ORDERING (issue #412, comment 4569387061): the declaration union
    # MUST run BEFORE both early returns. A non-empty declared set suppresses
    # the TIER_0_EXEMPT (all-exempt) and TIER_1_SELF short-circuits so that a
    # docs-only / small-single-file PR carrying a declaration still escalates.
    # If all files are exempt AND nothing was declared, no review needed.
    if not facets and not declared:
        return set(), set(), "TIER_0_EXEMPT", "No review required - only exempt files changed"

    # Compute required roles from facets, then union the escalation declaration.
    required_roles: set[str] = set()
    for facet in facets:
        required_roles |= FACET_ROLE_MAP.get(facet, set())

    # Line count escalation: >500 lines adds CIV for elevated review
    total_lines = sum(f["total_changed"] for f in non_exempt_files)
    if total_lines > 500 and "CIV" not in required_roles:
        required_roles.add("CIV")

    # Escalation-only union: declarations can only ADD roles (set-union).
    required_roles |= declared

    # Check for T1 self-review eligibility. A declaration suppresses self-review.
    has_new_test_files = any(
        f.get("status") == "A" and f["path"].startswith("tests/") for f in files
    )

    if (
        not declared
        and total_lines < 10
        and len(non_exempt_files) == 1
        and not has_new_test_files
        and "SECURITY" not in facets
        and "META_CONTROL_PLANE" not in facets
        and "EXECUTABLE_SPEC" not in facets
    ):
        return (
            facets,
            set(),  # No external reviewers needed for T1
            "TIER_1_SELF",
            f"Self-review sufficient - {total_lines} lines in single file",
        )

    # Compute tier label from role set
    if "PE" in required_roles:
        tier_label = "TIER_4_STRATEGIC"
    elif "CIV" in required_roles:
        tier_label = "TIER_3_CRITICAL"
    else:
        tier_label = "TIER_2_STANDARD"

    facet_names = ", ".join(sorted(facets)) if facets else "(none — escalated by declaration)"
    role_names = ", ".join(sorted(required_roles))
    reason = f"Facets: [{facet_names}] -> Reviewers: [{role_names}]"
    if declared:
        reason += f" (escalated: [{', '.join(sorted(declared))}])"
    return facets, required_roles, tier_label, reason


def determine_review_tier(files: list[dict[str, Any]]) -> tuple[str, str]:
    """Determine required review tier based on changed files.

    Backward-compatible wrapper around classify_pr_facets(). Returns
    (tier_label, reason) for callers that only need the tier string.
    """
    _, _, tier_label, reason = classify_pr_facets(files)
    return tier_label, reason


# Import shared review format utilities (single source of truth).
# In CI, the package may not be installed, so we use importlib to load
# the module file directly without triggering the package's __init__.py.
try:
    from hestai_context_mcp.tools.shared.review_formats import (
        VALID_ROLES as _VALID_ROLES,
    )
    from hestai_context_mcp.tools.shared.review_formats import (
        has_ce_approval as _has_ce_approval,
    )
    from hestai_context_mcp.tools.shared.review_formats import (
        has_civ_approval as _has_civ_approval,
    )
    from hestai_context_mcp.tools.shared.review_formats import (
        has_crs_approval as _has_crs_approval,
    )
    from hestai_context_mcp.tools.shared.review_formats import (
        has_crs_model_approval as _has_crs_model_approval,
    )
    from hestai_context_mcp.tools.shared.review_formats import (
        has_gr_approval as _has_gr_approval,
    )
    from hestai_context_mcp.tools.shared.review_formats import (
        has_ho_review as _has_ho_review,
    )
    from hestai_context_mcp.tools.shared.review_formats import (
        has_pe_approval as _has_pe_approval,
    )
    from hestai_context_mcp.tools.shared.review_formats import (
        has_self_review as _has_self_review,
    )
    from hestai_context_mcp.tools.shared.review_formats import (
        has_sr_approval as _has_sr_approval,
    )
    from hestai_context_mcp.tools.shared.review_formats import (
        has_tmg_approval as _has_tmg_approval,
    )
    from hestai_context_mcp.tools.shared.review_formats import (
        matches_approval_pattern as _matches_approval_pattern,
    )
    from hestai_context_mcp.tools.shared.review_formats import (
        parse_review_metadata as _parse_review_metadata,
    )
except (ImportError, ModuleNotFoundError):
    # CI fallback: load the module file directly via importlib
    import importlib.util

    _module_path = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "hestai_context_mcp"
        / "tools"
        / "shared"
        / "review_formats.py"
    )
    if not _module_path.exists():
        raise FileNotFoundError(
            f"review_formats.py not found at {_module_path}. "
            "Expected relative to scripts/ directory."
        ) from None
    _spec = importlib.util.spec_from_file_location("review_formats", _module_path)
    if _spec is None or _spec.loader is None:
        raise FileNotFoundError(
            f"review_formats.py not found at {_module_path}. "
            "Expected relative to scripts/ directory."
        ) from None
    _review_formats = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_review_formats)
    _matches_approval_pattern = _review_formats.matches_approval_pattern
    _has_crs_approval = _review_formats.has_crs_approval
    _has_crs_model_approval = _review_formats.has_crs_model_approval
    _has_ce_approval = _review_formats.has_ce_approval
    _has_ho_review = _review_formats.has_ho_review
    _has_tmg_approval = _review_formats.has_tmg_approval
    _has_civ_approval = _review_formats.has_civ_approval
    _has_pe_approval = _review_formats.has_pe_approval
    _has_self_review = _review_formats.has_self_review
    _has_sr_approval = _review_formats.has_sr_approval
    _has_gr_approval = _review_formats.has_gr_approval
    _parse_review_metadata = _review_formats.parse_review_metadata
    _VALID_ROLES = _review_formats.VALID_ROLES


# ---------------------------------------------------------------------------
# Content-aware review-depth escalation (issue #412)
# ---------------------------------------------------------------------------
# Escalation-declarable whitelist. Derived from the single source of truth
# (review_formats.VALID_ROLES) MINUS the self-review roles {IL, HO}: IL and HO
# review their OWN work and therefore cannot be REQUIRED reviewers via an
# escalation declaration. Declared tokens are intersected with this set;
# out-of-set tokens (typos, [GOD_MODE]) are dropped non-fatally and logged.
ALLOWED_ESCALATION_ROLES: frozenset[str] = frozenset(_VALID_ROLES) - {"IL", "HO"}

# The gate's own rules-schema doc. Its REQUIRED_REVIEWERS:: facet lines and §8
# marker examples are DESCRIPTIVE config, not a PR-level declaration, so this
# file is excluded from the declaration scan (matched by basename to cover both
# the bundled-hub source and the .hestai-sys runtime copy).
_RULES_SCHEMA_BASENAME = "review-requirements.oct.md"

# Tier -> role table for the `<!-- review-tier: TIER_X -->` marker. Mirrors the
# backward-computed tier labels in classify_pr_facets (CIV => T3, PE => T4).
_ESCALATION_TIER_ROLE_MAP: dict[str, set[str]] = {
    "TIER_2_STANDARD": {"TMG", "CRS", "CE"},
    "TIER_3_CRITICAL": {"TMG", "CRS", "CE", "CIV"},
    "TIER_3_STRICT": {"TMG", "CRS", "CE", "CIV"},  # legacy alias
    "TIER_4_STRATEGIC": {"TMG", "CRS", "CE", "CIV", "PE"},
}

# Markers (LOCKED schema, issue #412):
#   <!-- review-requirements: [TMG, CRS, CE, CIV, SR] -->
#   <!-- review-tier: TIER_3_CRITICAL: reason -->
_REVIEW_REQUIREMENTS_COMMENT_RE = re.compile(
    r"<!--\s*review-requirements:\s*\[([^\]]*)\]\s*-->", re.IGNORECASE
)
_REVIEW_TIER_COMMENT_RE = re.compile(
    # Reason is non-greedy and anchored on the comment terminator (\s*-->), so an
    # embedded '>' in the reason is preserved without over-capturing past `-->`.
    r"<!--\s*review-tier:\s*(TIER_[0-9A-Z_]+)\s*(?::\s*(.*?))?\s*-->",
    re.IGNORECASE,
)
# OCTAVE block field: REQUIRED_REVIEWERS::"{CE, CRS, SR}" (braces optional).
_OCTAVE_REQUIRED_REVIEWERS_RE = re.compile(
    r"^\s*REQUIRED_REVIEWERS\s*::\s*\"?\{?([^}\"\n]*)\}?\"?\s*$", re.MULTILINE
)
# YAML frontmatter: review-requirements: [CE, CRS] inside a leading --- block.
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)
_FRONTMATTER_REVIEWERS_RE = re.compile(
    r"^\s*review-requirements:\s*\[([^\]]*)\]\s*$", re.MULTILINE | re.IGNORECASE
)


def _split_role_tokens(raw: str) -> set[str]:
    """Split a comma/whitespace-separated role list into upper-cased tokens.

    Tolerant of empty entries and stray whitespace (malformed declarations must
    not crash — they degrade to whatever parsed cleanly).
    """
    tokens: set[str] = set()
    for piece in re.split(r"[,\s]+", raw.strip()):
        piece = piece.strip().upper()
        if piece:
            tokens.add(piece)
    return tokens


def _parse_review_declaration(text: str) -> dict[str, Any]:
    """Single extractor for review-escalation declarations (issue #412).

    Handles three declaration surfaces with ONE function (no per-surface
    duplication):
      1. OCTAVE block field ``REQUIRED_REVIEWERS::"{CE, CRS, SR}"``
      2. HTML-comment markers ``<!-- review-requirements: [...] -->`` and
         ``<!-- review-tier: TIER_X: reason -->``
      3. YAML frontmatter ``review-requirements: [...]``

    Roles from all matched surfaces are unioned. The ``review-tier`` marker is
    mapped through the tier->role table. Tokens are NOT whitelist-filtered here
    (that happens in :func:`_collect_bitemporal_declarations`) so the raw author
    intent is visible to callers/tests.

    Malformed input never raises: it degrades to an empty/partial result.

    Args:
        text: Arbitrary document or PR-body text to scan.

    Returns:
        Dict with optional keys: ``roles`` (set[str]), ``tier`` (str),
        ``reason`` (str), and ``source`` (str label).
    """
    result: dict[str, Any] = {}
    if not text:
        return result

    roles: set[str] = set()
    sources: list[str] = []

    try:
        # 1. OCTAVE block field
        for m in _OCTAVE_REQUIRED_REVIEWERS_RE.finditer(text):
            parsed = _split_role_tokens(m.group(1))
            if parsed:
                roles |= parsed
                sources.append("octave")

        # 2a. HTML-comment review-requirements
        for m in _REVIEW_REQUIREMENTS_COMMENT_RE.finditer(text):
            parsed = _split_role_tokens(m.group(1))
            if parsed:
                roles |= parsed
                sources.append("html_requirements")

        # 2b. HTML-comment review-tier
        tier_match = _REVIEW_TIER_COMMENT_RE.search(text)
        if tier_match:
            tier = tier_match.group(1).upper()
            result["tier"] = tier
            reason = (tier_match.group(2) or "").strip()
            if reason:
                result["reason"] = reason
            mapped = _ESCALATION_TIER_ROLE_MAP.get(tier)
            if mapped:
                roles |= mapped
                sources.append("html_tier")
            else:
                # Unrecognized/misspelled tier (e.g. TIER_0_EXEMPT, a typo like
                # TIER_3_CRITCAL): contributes no roles. Warn non-fatally so the
                # author gets a signal instead of a silent no-op. Never raise.
                print(
                    f"⚠️  Ignored unrecognized review-tier '{tier}' "
                    f"(non-fatal): not in the tier->role table "
                    f"{sorted(_ESCALATION_TIER_ROLE_MAP)}; no roles contributed.",
                    file=sys.stderr,
                )

        # 3. YAML frontmatter
        fm = _FRONTMATTER_RE.match(text)
        if fm:
            fm_match = _FRONTMATTER_REVIEWERS_RE.search(fm.group(1))
            if fm_match:
                parsed = _split_role_tokens(fm_match.group(1))
                if parsed:
                    roles |= parsed
                    sources.append("frontmatter")
    except Exception:
        # Malformed declaration: never crash the gate. Keep whatever parsed.
        pass

    if roles:
        result["roles"] = roles
    if sources:
        result["source"] = ",".join(sources)
    return result


def _git_show_file(sha: str, path: str) -> str | None:
    """Return the contents of ``path`` at commit ``sha`` via ``git show``.

    Returns None when the blob does not exist (e.g. a new file has no BASE
    blob, or a deleted file has no HEAD blob). Never raises: any git failure
    degrades to None so the bitemporal read is safe on missing blobs.
    """
    if not sha:
        return None
    try:
        result = subprocess.run(
            ["git", "show", f"{sha}:{path}"],
            capture_output=True,
            text=True,
            # A PR may change binary files (png, jpg, …). `git show` emits the
            # raw blob bytes, which need not be valid UTF-8. Decode with
            # errors="replace" so a binary blob degrades to a (garbage but
            # declaration-free) string instead of raising UnicodeDecodeError
            # and crashing the org-wide gate (I2). check=False keeps a missing
            # blob (new/deleted file) returning a non-zero rc, handled below.
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        # Missing blob (new/deleted file) or bad ref — treat as absent.
        return None
    return result.stdout


def _collect_bitemporal_declarations(
    files: list[dict[str, Any]],
    pr_body: str = "",
    base_sha: str | None = None,
    head_sha: str | None = None,
) -> tuple[set[str], dict[str, set[str]]]:
    """Collect escalation declarations across the bitemporal source set.

    Runs the single extractor against FOUR sources and unions them
    (issue #412)::

        Required_Roles = Base_Roles ∪ Head_Roles ∪ PR_Body_Roles  (∪ Diff later)

    Per the debate contribution, set-union makes escalation-only an *emergent*
    property: an author cannot relax the gate by deleting a declaration in a
    later commit because the BASE blob still contributes the role. The result is
    intersected with :data:`ALLOWED_ESCALATION_ROLES`; out-of-set tokens are
    dropped non-fatally and logged. Missing base/head blobs (new/deleted files)
    are handled gracefully — :func:`_git_show_file` returns None and that source
    contributes nothing.

    Args:
        files: Changed-file dicts (need a 'path' key).
        pr_body: The PR description text.
        base_sha: Base commit SHA (``pr.base.sha``) for BASE blob reads.
        head_sha: Head commit SHA (``pr.head.sha``) for HEAD blob reads.

    Returns:
        Tuple ``(declared_roles, provenance)`` where:
        - declared_roles: whitelist-filtered union of all declared roles.
        - provenance: maps each surviving role -> set of contributing source
          labels drawn from {"HEAD", "BASE", "PR_BODY"}.
    """
    provenance: dict[str, set[str]] = {}
    dropped: set[str] = set()

    def _ingest(text: str | None, source_label: str) -> None:
        if not text:
            return
        decl = _parse_review_declaration(text)
        declared = decl.get("roles")
        if not declared:
            return
        for role in declared:
            if role in ALLOWED_ESCALATION_ROLES:
                provenance.setdefault(role, set()).add(source_label)
            else:
                dropped.add(role)

    # PR body
    _ingest(pr_body, "PR_BODY")

    # Per-file BASE and HEAD blobs
    for f in files:
        path = f.get("path")
        if not path:
            continue
        # Exclude the gate's OWN rules-schema doc from the declaration scan.
        # review-requirements.oct.md uses REQUIRED_REVIEWERS:: DESCRIPTIVELY to
        # define per-facet reviewers (and §8 quotes the marker examples); those
        # are the gate's config, NOT a PR-level declaration. Match by basename
        # so BOTH the bundled-hub source and the .hestai-sys runtime copy are
        # skipped as declaration SOURCES. The file still routes via its facet
        # (META_CONTROL_PLANE) and the PR-body marker path is unaffected.
        if os.path.basename(path) == _RULES_SCHEMA_BASENAME:
            continue
        if base_sha:
            # For renamed files, the BASE blob lives at the OLD path (previous_path).
            # Using the new path for the BASE lookup silently misses the declaration
            # when the file was renamed — breaking the escalation-only ratchet
            # (issue #417). Fall back to path when previous_path is absent (new/
            # modified files where old path == new path).
            base_path = f.get("previous_path", path)
            _ingest(_git_show_file(base_sha, base_path), "BASE")
        if head_sha:
            _ingest(_git_show_file(head_sha, path), "HEAD")

    if dropped:
        print(
            f"⚠️  Dropped {len(dropped)} declared role(s) outside "
            f"ALLOWED_ESCALATION_ROLES (non-fatal): {', '.join(sorted(dropped))}",
            file=sys.stderr,
        )

    declared_roles = set(provenance.keys())
    return declared_roles, provenance


def _has_approval(texts: list[str], prefix: str, keyword: str) -> bool:
    """Check if any text in the list matches the approval pattern."""
    return any(_matches_approval_pattern(t, prefix, keyword) for t in texts)


def check_pr_comments(
    _tier_or_roles: set[str] | str | None = None,
    *,
    required_roles: set[str] | None = None,
    tier: str = "",
) -> tuple[bool, str, list[str]]:
    """Check if required review comments and PR body contain approval patterns.

    Supports two calling conventions for backward compatibility:
    - New: check_pr_comments(required_roles={'CE', 'CRS'}, tier='TIER_2_STANDARD')
    - Old: check_pr_comments('TIER_2_STANDARD')  (string -> uses tier->roles mapping)

    For TIER_1_SELF with empty required_roles, falls back to self-review logic.
    For all other tiers, validates that ALL required_roles have posted approvals.

    Returns:
        Tuple of (approved, message, missing_roles):
        - approved: True if all required approvals are present
        - message: Human-readable status message
        - missing_roles: List of role names that have NOT yet approved.
          Empty list when approved=True or in non-CI/error contexts.
    """
    # Handle backward compat: positional string arg is the tier (old API)
    if isinstance(_tier_or_roles, str):
        tier = _tier_or_roles
    elif isinstance(_tier_or_roles, set):
        required_roles = _tier_or_roles

    # In pre-commit context, we can't check PR comments
    # This would be called from CI with PR number
    if "CI" not in os.environ:
        return True, "Skipping comment check in local context", []

    pr_number = os.environ.get("PR_NUMBER")
    if not pr_number:
        return False, "❌ PR_NUMBER not set in environment", []

    print(f"   Checking PR #{pr_number} for review comments...")

    # Use gh CLI to get comments, PR body, and PR reviews
    try:
        result = subprocess.run(
            ["gh", "pr", "view", pr_number, "--json", "comments,body,reviews"],
            capture_output=True,
            text=True,
            check=True,
        )
        pr_data = json.loads(result.stdout)

        # Collect all searchable text: PR body + comment bodies + review bodies
        # Exclude ALL bot comments/reviews to prevent false positive approval matches.
        # Bot review prose (Copilot, Cubic, github-actions) often
        # contains "APPROVED", "GO", etc. which would falsely clear the gate.
        def _is_bot_comment(comment: dict[str, Any]) -> bool:
            """Check if a comment or review is from a bot author."""
            login = (comment.get("author") or {}).get("login", "")
            if login in _BOT_LOGIN_SET:
                return True
            # Catch any other [bot]-suffixed accounts (GitHub convention)
            if login.endswith("[bot]"):
                return True
            # Legacy marker check for review-gate status comments
            return "<!-- review-gate-status -->" in comment.get("body", "")

        searchable_texts: list[str] = []
        pr_body = pr_data.get("body")
        if pr_body:
            searchable_texts.append(pr_body)

        # Filter comments, logging any bot comments that are skipped
        skipped_bots: list[str] = []
        for c in pr_data.get("comments", []):
            if _is_bot_comment(c):
                bot_login = (c.get("author") or {}).get("login", "unknown")
                skipped_bots.append(bot_login)
            else:
                searchable_texts.append(c.get("body", ""))

        # Include PR review bodies — GitHub PR Reviews (submitted via the Review
        # button, pulls/{n}/reviews API) are a separate resource from issue-level
        # comments.  Reviewers who self-review must use state=COMMENTED (GitHub
        # forbids self-approve).  DISMISSED reviews are excluded: the reviewer
        # retracted their assessment, so it must not satisfy the gate.
        # PENDING reviews have not been submitted yet and are also excluded.
        active_review_states: frozenset[str] = frozenset({"APPROVED", "COMMENTED"})
        for r in pr_data.get("reviews", []):
            if r.get("state") not in active_review_states:
                continue
            if _is_bot_comment(r):
                bot_login = (r.get("author") or {}).get("login", "unknown")
                skipped_bots.append(bot_login)
            else:
                review_body = r.get("body", "")
                if review_body:
                    searchable_texts.append(review_body)

        if skipped_bots:
            print(
                f"   Skipped {len(skipped_bots)} bot comment(s) "
                f"(ADVISORY only, not counted for gate): "
                f"{', '.join(sorted(set(skipped_bots)))}"
            )

        # --- Metadata extraction and cross-validation ---
        # Extract structured metadata from all texts for machine-readable checks.
        # When metadata IS present, also run regex on the same comment.
        # If regex-extracted verdict contradicts metadata verdict, FAIL
        # (prevents spoofing: visible "BLOCKED" with hidden metadata "APPROVED").
        metadata_entries: list[dict[str, str | None]] = []
        for text in searchable_texts:
            meta = _parse_review_metadata(text)
            if meta is not None:
                metadata_entries.append(meta)
                # CROSS-VALIDATION: If metadata says a role gave an approval
                # verdict, the visible text in the same comment MUST also
                # match that approval via regex. Otherwise reject.
                meta_role = meta.get("role")
                meta_verdict = meta.get("verdict")
                if meta_role and meta_verdict:
                    # Only cross-validate recognized review roles.
                    # Unrecognized roles (e.g., agent names like
                    # "code-review-specialist") cannot satisfy any gate
                    # check, so mismatched metadata is irrelevant -- not
                    # a spoofing vector.
                    if meta_role not in _VALID_ROLES:
                        continue
                    # Only cross-validate approval verdicts (not BLOCKED/CONDITIONAL)
                    approval_keywords = {"APPROVED", "SELF-REVIEWED", "REVIEWED", "GO"}
                    if meta_verdict in approval_keywords:
                        # Strip metadata HTML comment lines before regex check so
                        # the hidden JSON tokens don't satisfy the pattern match.
                        visible_text = re.sub(r"<!--\s*review:.*?-->\s*", "", text)
                        # Strip fenced code blocks and inline code so that
                        # approval text inside code examples cannot spoof the
                        # cross-validation regex.
                        visible_text = re.sub(r"```.*?```", "", visible_text, flags=re.DOTALL)
                        visible_text = re.sub(r"`[^`]+`", "", visible_text)
                        regex_agrees = _matches_approval_pattern(
                            visible_text, meta_role, meta_verdict
                        )
                        if not regex_agrees:
                            return (
                                False,
                                f"❌ Cross-validation failure: metadata says "
                                f"{meta_role} {meta_verdict} but visible text "
                                f"does not match. Possible spoofing detected.",
                                [],
                            )

        def _meta_has(
            role: str,
            verdict: str,
            provider: str | None = None,
        ) -> bool:
            """Check if metadata entries contain a matching approval."""
            for entry in metadata_entries:
                if (
                    entry.get("role") == role
                    and entry.get("verdict") == verdict
                    and (provider is None or entry.get("provider") == provider.lower())
                ):
                    return True
            return False

        # --- Role-based approval checking ---
        # Role → approval checker dispatch
        _role_checkers: dict[str, Any] = {
            "TMG": lambda: _meta_has("TMG", "APPROVED") or _has_tmg_approval(searchable_texts),
            "CRS": lambda: _meta_has("CRS", "APPROVED") or _has_crs_approval(searchable_texts),
            "CE": lambda: _meta_has("CE", "APPROVED") or _has_ce_approval(searchable_texts),
            "CIV": lambda: _meta_has("CIV", "APPROVED") or _has_civ_approval(searchable_texts),
            "PE": lambda: _meta_has("PE", "APPROVED") or _has_pe_approval(searchable_texts),
            "SR": lambda: (
                _meta_has("SR", "APPROVED")
                or _has_sr_approval(searchable_texts)
                # Legacy GR visible-text check only (no _meta_has("GR") —
                # GR not in VALID_ROLES so metadata bypasses cross-validation)
                or _has_gr_approval(searchable_texts)
            ),
        }

        # TIER_1_SELF: self-review logic (no external reviewers required)
        if tier == "TIER_1_SELF" and (required_roles is None or len(required_roles) == 0):
            for entry in metadata_entries:
                if entry.get("verdict") == "SELF-REVIEWED":
                    return True, "✓ Self-review found (metadata)", []
            if _meta_has("HO", "REVIEWED"):
                return True, "✓ HO supervisory review found (metadata)", []
            if _meta_has("CRS", "APPROVED"):
                return True, "✓ CRS approval satisfies self-review (metadata)", []
            if _has_self_review(searchable_texts):
                return True, "✓ Self-review found", []
            if _has_approval(searchable_texts, "HO", "REVIEWED"):
                return True, "✓ HO supervisory review found", []
            if _has_crs_approval(searchable_texts):
                return True, "✓ CRS approval satisfies self-review requirement", []
            return False, "❌ Missing: SELF-REVIEWED or HO REVIEWED comment", []

        # Determine effective roles to check
        effective_roles = required_roles if required_roles is not None else set()

        # DEPRECATED: Tier-only API cannot distinguish code vs governance PRs.
        # Use classify_pr_facets() + required_roles for accurate routing.
        # This fallback maps tiers to code-review roles only (no SR).
        if not effective_roles and tier:
            _tier_role_map: dict[str, set[str]] = {
                "TIER_2_STANDARD": {"TMG", "CRS", "CE"},
                "TIER_3_CRITICAL": {"TMG", "CRS", "CE", "CIV"},
                "TIER_4_STRATEGIC": {"TMG", "CRS", "CE", "CIV", "PE"},
            }
            effective_roles = _tier_role_map.get(tier, set())
            if not effective_roles:
                return False, f"❌ Unrecognized tier: {tier}", []

        # Check each required role (SECURITY: fail-closed for unknown roles)
        missing_roles: list[str] = []
        missing_display: list[str] = []
        for role in sorted(effective_roles):
            checker = _role_checkers.get(role)
            if checker is None or not checker():
                missing_roles.append(role)
                missing_display.append(f"{role} APPROVED or {role} GO")

        if not missing_roles:
            role_names = ", ".join(sorted(effective_roles))
            return True, f"✓ All required approvals found ({role_names})", []

        return False, f"❌ Missing: {', '.join(missing_display)}", missing_roles

    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        # SECURITY FIX: Fail closed in CI, permissive locally
        if "CI" in os.environ:
            return False, f"❌ Error checking PR comments: {e}", []
        return True, "Unable to check PR comments (local mode)", []


def log_emergency_bypass() -> None:
    """Create audit trail for emergency bypass."""
    # Create audit directory
    audit_dir = Path.cwd() / ".hestai" / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_log = audit_dir / "bypass-log.jsonl"

    # Get metadata
    pr_number = os.environ.get("PR_NUMBER", "unknown")

    # Get git user info
    try:
        user_name = subprocess.run(
            ["git", "config", "user.name"], capture_output=True, text=True, check=True
        ).stdout.strip()
        user_email = subprocess.run(
            ["git", "config", "user.email"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except subprocess.CalledProcessError:
        user_name = "unknown"
        user_email = "unknown"

    # Get commit SHA
    try:
        commit_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except subprocess.CalledProcessError:
        commit_sha = "unknown"

    # Create audit entry
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "reason": "EMERGENCY_BYPASS",
        "pr_number": pr_number,
        "commit": commit_sha,
        "user_name": user_name,
        "user_email": user_email,
    }

    # Append to audit log
    with open(audit_log, "a") as f:
        f.write(json.dumps(entry) + "\n")


def check_emergency_bypass() -> bool:
    """Check if this is an emergency bypass commit."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--pretty=%B"], capture_output=True, text=True, check=True
        )
        return "EMERGENCY:" in result.stdout
    except subprocess.CalledProcessError:
        return False


def _get_head_sha() -> str:
    """Get the current HEAD commit SHA for tracking in JSON output.

    Returns:
        The HEAD commit SHA string, or 'unknown' if git rev-parse fails.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


def _get_pr_body() -> str:
    """Fetch the PR description text for declaration scanning (issue #412).

    Uses ``gh pr view <PR_NUMBER> --json body``. Returns an empty string outside
    CI (no PR context), when PR_NUMBER is unset, or on any gh/parse failure —
    the bitemporal union simply omits the PR_BODY source rather than crashing.
    """
    if "CI" not in os.environ:
        return ""
    pr_number = os.environ.get("PR_NUMBER")
    if not pr_number:
        return ""
    try:
        result = subprocess.run(
            ["gh", "pr", "view", pr_number, "--json", "body"],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout)
        body = data.get("body")
        return body if isinstance(body, str) else ""
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError):
        return ""


def _get_base_ref_sha() -> str:
    """Get the current tip SHA of the base branch.

    Computes ``git rev-parse origin/{base_ref}`` to obtain the same value that
    the GitHub API returns as ``pr.base.sha``.  The review-gate workflow stores
    ``pr.base.sha`` (the base branch tip) in its cached data, so the Python
    validator must resolve the identical commit to keep the fast-path SHA
    comparison aligned.

    Uses PR_BASE_REF or GITHUB_BASE_REF environment variables to determine
    the base branch.  Falls back to 'unknown' if git rev-parse fails.

    Returns:
        The base branch tip SHA string, or 'unknown' on failure.
    """
    base_ref = os.environ.get("PR_BASE_REF") or os.environ.get("GITHUB_BASE_REF", "main")
    # Ensure we have the origin/ prefix for remote comparison
    if not base_ref.startswith("origin/"):
        base_ref = f"origin/{base_ref}"
    try:
        result = subprocess.run(
            ["git", "rev-parse", base_ref],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


def _emit_json_summary(
    tier: str,
    reason: str,
    reviewers: list[str],
    status: str,
    required_count: int,
    found_count: int,
    sha: str = "unknown",
    provenance: dict[str, list[str]] | None = None,
) -> None:
    """Emit a structured JSON summary as an HTML comment for machine parsing.

    The JSON is wrapped in an HTML comment so it doesn't appear in human-readable
    output but IS captured in the output variable by the CI workflow. The JS parser
    in review-gate.yml can extract this for structured data instead of relying on
    fragile regex patterns.

    Format: <!-- REVIEW_GATE_JSON:{"tier":"...","reason":"...","sha":"...",...} -->

    The ``sha`` field tracks which commit the review gate evaluated. Downstream
    consumers can compare this against the PR head SHA to detect stale approvals
    when new commits are pushed after approval.

    The ``provenance`` field (issue #412) maps each required role to the list of
    sources that contributed it — drawn from {"DIFF", "HEAD", "BASE", "PR_BODY"} —
    so the status comment can render a per-role audit trail. A role present in
    BASE but absent from HEAD shows ``BASE`` only (visible attempted reduction).
    """
    summary = {
        "tier": tier,
        "reason": reason,
        "reviewers": reviewers,
        "status": status,
        "required_count": required_count,
        "found_count": found_count,
        "sha": sha,
        "provenance": provenance or {},
    }
    print(f"<!-- REVIEW_GATE_JSON:{json.dumps(summary)} -->")


def main() -> int:
    """Main validation logic."""

    # Get HEAD SHA early for inclusion in all JSON output paths
    head_sha = _get_head_sha()

    # Check for emergency bypass
    if check_emergency_bypass():
        print("⚠️  EMERGENCY BYPASS - Review required post-merge")
        log_emergency_bypass()
        return 0

    # --- Comment-event fast path ---
    # When CACHED_GATE_DATA is set (by the workflow on issue_comment events with
    # matching SHA), skip file classification and use cached tier/reviewers.
    # The diff hasn't changed — only approvals may have changed.
    cached_gate_json = os.environ.get("CACHED_GATE_DATA", "")
    cached_gate: dict[str, Any] | None = None
    if cached_gate_json:
        try:
            cached_gate = json.loads(cached_gate_json)
            # SHA comparison guard: verify cached data matches current HEAD
            # before trusting it. Stale data (workflow bug, manual run) must
            # not silently apply incorrect tier/roles.
            # Guard against 'unknown' matching 'unknown' when git fails —
            # both sides returning a placeholder must not enable the fast path.
            cached_sha_val = cached_gate.get("sha")
            if cached_sha_val == head_sha and head_sha != "unknown" and cached_sha_val != "unknown":
                # Base-ref guard: if the base branch moved while the PR head
                # stayed the same, the diff (and thus file classification) has
                # changed. Validate base branch tip SHA to detect this.
                cached_base_sha = cached_gate.get("base_sha")
                if cached_base_sha is None:
                    # Backward compatibility: old status comments without base_sha
                    # must be treated as cache miss to ensure correctness.
                    print(
                        "⚠️  Cached data missing base_sha (old format), "
                        "falling back to normal classification"
                    )
                    cached_gate = None
                else:
                    base_ref_sha = _get_base_ref_sha()
                    if base_ref_sha == "unknown" or str(cached_base_sha) != base_ref_sha:
                        print(
                            f"⚠️  Base ref SHA {str(cached_base_sha)[:7]} != "
                            f"current {base_ref_sha[:7]}, "
                            f"falling back to normal classification"
                        )
                        cached_gate = None
                    else:
                        print(
                            f"⚡ Comment-event fast path: cached SHA "
                            f"{head_sha[:7]} matches HEAD, "
                            f"base ref {base_ref_sha[:7]} matches"
                        )
            else:
                cached_sha = str(cached_gate.get("sha", "none"))
                print(
                    f"⚠️  Cached SHA {cached_sha[:7]} != HEAD {head_sha[:7]}, "
                    f"falling back to normal classification"
                )
                cached_gate = None
        except (json.JSONDecodeError, TypeError):
            cached_gate = None

    # Per-role provenance map (issue #412): role -> sorted list of contributing
    # sources from {"DIFF", "HEAD", "BASE", "PR_BODY"}. Rendered by review-gate.yml.
    provenance: dict[str, list[str]] = {}

    if cached_gate is not None:
        tier = str(cached_gate.get("tier", "UNKNOWN"))
        reason = str(cached_gate.get("reason", ""))
        required_roles = set(cached_gate.get("roles", []))
        # Reuse cached provenance when present (display-only; diff unchanged).
        cached_prov = cached_gate.get("provenance")
        if isinstance(cached_prov, dict):
            provenance = {k: list(v) for k, v in cached_prov.items()}
    else:
        # Get changed files
        files = get_changed_files()
        if not files:
            print("✓ No files changed")
            return 0

        # Show changed files summary
        total_lines = sum(int(f["total_changed"]) for f in files)
        print(f"📊 Changed Files: {len(files)} files, {total_lines} lines")
        for f in files[:5]:  # Show first 5
            print(f"   - {f['path']} (+{f['added']}/-{f['deleted']})")
        if len(files) > 5:
            print(f"   ... and {len(files) - 5} more")

        # --- Content-aware escalation: bitemporal declaration union (issue #412) ---
        # Collect declarations from PR body + BASE blob + HEAD blob per changed
        # file, intersect with ALLOWED_ESCALATION_ROLES, then union into the
        # diff-computed floor. Reads are safe on missing blobs (new/deleted files).
        base_sha = _get_base_ref_sha()
        pr_body = _get_pr_body()
        declared_roles, decl_provenance = _collect_bitemporal_declarations(
            files=files,
            pr_body=pr_body,
            base_sha=None if base_sha == "unknown" else base_sha,
            head_sha=None if head_sha == "unknown" else head_sha,
        )

        # Classify PR content into facets and compute required reviewers,
        # unioning the (whitelist-filtered) declared roles BEFORE early returns.
        _facets, required_roles, tier, reason = classify_pr_facets(
            files, declared_roles=declared_roles
        )

        # Compute the diff/facet-only role floor (no declaration) so provenance
        # can attribute DIFF independently of any declared source. A role that is
        # BOTH diff-required AND declared must show ALL its sources.
        _df, diff_roles, _dt, _dr = classify_pr_facets(files)

        # Build the provenance map: every required role gets a source list. A
        # role's sources are the UNION of its declaration origins (HEAD/BASE/
        # PR_BODY) and DIFF when it is in the diff/facet floor — a role from
        # multiple sources shows all of them.
        for role in sorted(required_roles):
            sources = set(decl_provenance.get(role, set()))
            if role in diff_roles:
                sources.add("DIFF")
            if not sources:
                # Defensive: a required role with no traced source (should not
                # happen) is attributed to DIFF so provenance is never empty.
                sources.add("DIFF")
            provenance[role] = sorted(sources)

    print(f"\n📋 Review Tier: {tier}")
    print(f"   Reason: {reason}")

    # Check if tier is exempt
    if tier == "TIER_0_EXEMPT":
        print("✓ Review not required")
        _emit_json_summary(
            tier=tier,
            reason=reason,
            reviewers=[],
            status="pass",
            required_count=0,
            found_count=0,
            sha=head_sha,
        )
        return 0

    # Check for required approvals
    approved, message, missing_roles = check_pr_comments(required_roles=required_roles, tier=tier)
    print(f"   {message}")

    reviewers_list = sorted(required_roles)

    if not approved:
        # Compute found_count from structured missing_roles data.
        found_count = len(required_roles) - len(missing_roles)

        print("\n⚠️  Review Requirements:")
        if tier == "TIER_1_SELF":
            print("   Add comment: '{your-role} SELF-REVIEWED: [your rationale]'")
            print("   Any role or name accepted (e.g., IL, skills-expert, Shaun)")
            print("   -- or --")
            print("   Add comment: 'HO REVIEWED: [rationale after delegated work]'")
            print("   Example: 'skills-expert SELF-REVIEWED: Updated GATES section'")
        else:
            print("   Need comments:")
            for role in sorted(required_roles):
                print(f"   - '{role} APPROVED: [assessment]' (or {role} GO:)")

        _emit_json_summary(
            tier=tier,
            reason=reason,
            reviewers=reviewers_list,
            status="fail",
            required_count=len(required_roles),
            found_count=found_count,
            sha=head_sha,
            provenance=provenance,
        )

        # Only block in CI context
        if "CI" in os.environ:
            print("\n❌ Blocking merge - reviews required")
            return 1
        else:
            print("\n   ℹ️  Local check only - not blocking")
            return 0

    _emit_json_summary(
        tier=tier,
        reason=reason,
        reviewers=reviewers_list,
        status="pass",
        required_count=len(required_roles),
        found_count=len(required_roles),
        sha=head_sha,
        provenance=provenance,
    )
    print("\n✓ Review requirements satisfied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
