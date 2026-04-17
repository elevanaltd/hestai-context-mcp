"""Git state detection module.

Provides git branch detection, status, ahead/behind tracking,
and context freshness checking for I4 compliance.

Harvested from legacy hestai-mcp clock_in.py and fast_layer.py.
"""

import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def get_current_branch(working_dir: Path) -> str:
    """Get the current git branch name.

    Args:
        working_dir: Project working directory.

    Returns:
        Branch name or 'unknown' if git unavailable.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(working_dir),
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return "unknown"


def get_git_state(working_dir: Path) -> dict[str, Any] | None:
    """Get full git state: branch, ahead/behind, modified files.

    Args:
        working_dir: Project working directory.

    Returns:
        Dict with branch, ahead, behind, modified_files or None on total failure.
    """
    try:
        # Get current branch
        branch = get_current_branch(working_dir)
        if branch == "unknown":
            # If we can't even get the branch, git is likely not available
            # Try one more time to confirm
            try:
                test_result = subprocess.run(
                    ["git", "status"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    cwd=str(working_dir),
                )
                if test_result.returncode != 0:
                    return None
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                return None

        # Get ahead/behind counts
        ahead = 0
        behind = 0
        try:
            rev_result = subprocess.run(
                ["git", "rev-list", "--left-right", "--count", "HEAD...@{upstream}"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=str(working_dir),
            )
            if rev_result.returncode == 0 and rev_result.stdout.strip():
                parts = rev_result.stdout.strip().split("\t")
                if len(parts) == 2:
                    ahead = int(parts[0])
                    behind = int(parts[1])
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
            pass

        # Get modified files
        modified_files: list[str] = []
        try:
            status_result = subprocess.run(
                ["git", "status", "--short"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=str(working_dir),
            )
            if status_result.returncode == 0 and status_result.stdout.strip():
                for line in status_result.stdout.strip().split("\n"):
                    if line.strip():
                        # git status --short format: "XY filename"
                        # Split on whitespace and take the remaining parts as filename
                        parts = line.strip().split(None, 1)
                        if len(parts) >= 2:
                            modified_files.append(parts[1])
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

        return {
            "branch": branch,
            "ahead": ahead,
            "behind": behind,
            "modified_files": modified_files,
        }

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug(f"Could not get git state: {e}")
        return None


def check_context_freshness(
    context_path: Path,
    working_dir: Path,
    max_age_hours: int = 24,
) -> str | None:
    """Check if a context file is stale per I4 freshness verification.

    Stale = last git commit modifying the file > max_age_hours ago,
    or file exists but has never been committed (no git history).

    Args:
        context_path: Path to context file.
        working_dir: Project root for git commands.
        max_age_hours: Maximum age in hours before considered stale.

    Returns:
        Warning message if stale, None if fresh.
    """
    try:
        # Get the last commit date for this specific file
        try:
            rel_path = context_path.relative_to(working_dir)
        except ValueError:
            rel_path = context_path

        result = subprocess.run(
            [
                "git",
                "log",
                "-1",
                "--format=%ct",  # Unix timestamp
                "--",
                str(rel_path),
            ],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(working_dir),
        )

        if result.returncode != 0 or not result.stdout.strip():
            return (
                "I4 WARNING: PROJECT-CONTEXT.oct.md has never been committed "
                "to git (freshness unknown)"
            )

        # Parse timestamp and check age
        commit_timestamp = int(result.stdout.strip())
        commit_time = datetime.fromtimestamp(commit_timestamp, tz=UTC)
        now = datetime.now(UTC)
        age_hours = (now - commit_time).total_seconds() / 3600

        if age_hours > max_age_hours:
            return (
                f"I4 WARNING: PROJECT-CONTEXT.oct.md is stale "
                f"({age_hours:.1f}h since last commit, threshold: {max_age_hours}h)"
            )

        return None  # Fresh

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError) as e:
        logger.debug(f"Could not check context freshness: {e}")
        return "I4 WARNING: Could not verify PROJECT-CONTEXT.oct.md freshness " "(git unavailable)"
