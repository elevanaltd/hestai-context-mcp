"""Focus resolution logic.

Resolves agent session focus using priority chain:
explicit > github_issue > branch > default.

Harvested from legacy hestai-mcp clock_in.py.
"""

import re

# Issue pattern regex: matches #XX, issue-XX, issues-XX
ISSUE_PATTERN = re.compile(r"(?:issues?-|#)(\d+)", re.IGNORECASE)

# Feature prefix patterns: feat/, fix/, chore/, refactor/, docs/
FEATURE_PREFIX_PATTERN = re.compile(r"^(feat|fix|chore|refactor|docs)/(.+)$")


def resolve_focus_from_branch(branch: str) -> dict[str, str] | None:
    """Resolve focus from branch name based on patterns.

    Priority within branch patterns:
    1. Issue number pattern: #XX, issue-XX, issues-XX -> "issue-XX"
    2. Feature prefix: feat/, fix/, chore/, etc. -> "prefix: description"

    Args:
        branch: Git branch name.

    Returns:
        Dict with 'value' and 'source' keys, or None if no pattern matches.
    """
    if not branch:
        return None

    # First priority: issue number patterns
    issue_match = ISSUE_PATTERN.search(branch)
    if issue_match:
        issue_number = issue_match.group(1)
        return {
            "value": f"issue-{issue_number}",
            "source": "github_issue",
        }

    # Second priority: feature prefix patterns
    prefix_match = FEATURE_PREFIX_PATTERN.match(branch)
    if prefix_match:
        prefix = prefix_match.group(1)
        description = prefix_match.group(2)
        return {
            "value": f"{prefix}: {description}",
            "source": "branch",
        }

    # No recognizable pattern
    return None


def resolve_focus(
    explicit_focus: str | None = None,
    branch: str | None = None,
) -> dict[str, str]:
    """Resolve focus with priority chain.

    Priority order:
    1. Explicit focus (if provided and non-empty)
    2. GitHub issue from branch name (if matches issue pattern)
    3. Branch inference (if matches feature prefix pattern)
    4. Default: "general"

    Args:
        explicit_focus: Explicitly provided focus (highest priority).
        branch: Git branch name to infer focus from.

    Returns:
        Dict with 'value' and 'source' keys.
    """
    # Priority 1: Explicit focus
    if explicit_focus is not None and explicit_focus.strip():
        return {
            "value": explicit_focus.strip(),
            "source": "explicit",
        }

    # Priority 2-3: Infer from branch
    if branch:
        branch_result = resolve_focus_from_branch(branch)
        if branch_result:
            return branch_result

    # Priority 4: Default
    return {
        "value": "general",
        "source": "default",
    }
