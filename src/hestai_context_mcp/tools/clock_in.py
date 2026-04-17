"""Clock-in tool: Register agent session start and return context paths.

Returns the structured response per ADR-0353 interface contract.
Harvested from legacy hestai-mcp clock_in.py.
"""

import logging
from pathlib import Path
from typing import Any

from hestai_context_mcp.core.context_steward import ContextSteward
from hestai_context_mcp.core.focus import resolve_focus
from hestai_context_mcp.core.git_state import (
    check_context_freshness,
    get_current_branch,
    get_git_state,
)
from hestai_context_mcp.core.session import SessionManager

logger = logging.getLogger(__name__)


def validate_role(role: str) -> str:
    """Validate role name to prevent path traversal and injection.

    Args:
        role: Role name to validate.

    Returns:
        Validated role name (stripped).

    Raises:
        ValueError: If role is empty or contains unsafe characters.
    """
    if not role or not role.strip():
        raise ValueError("Role cannot be empty")

    if ".." in role or "/" in role or "\\" in role:
        raise ValueError("Invalid role format - path separators not allowed")

    if any(c in role for c in "\r\n\t"):
        raise ValueError("Invalid role format - control characters not allowed")

    return role.strip()


def validate_working_dir(working_dir: str) -> Path:
    """Validate working directory path.

    Args:
        working_dir: Working directory path.

    Returns:
        Resolved absolute path.

    Raises:
        ValueError: If path traversal detected.
        FileNotFoundError: If directory doesn't exist.
    """
    path = Path(working_dir).expanduser().resolve()

    if ".." in working_dir:
        raise ValueError("Path traversal attempt detected in working_dir")

    if not path.exists():
        raise FileNotFoundError(f"Working directory does not exist: {path}")

    if not path.is_dir():
        raise ValueError(f"Working directory path is not a directory: {path}")

    return path


def clock_in(
    role: str,
    working_dir: str,
    focus: str | None = None,
) -> dict[str, Any]:
    """Register agent session start and return context paths.

    Creates a session, resolves focus, discovers context files, detects
    git state, checks for focus conflicts, and returns the structured
    response per the ADR-0353 interface contract.

    Args:
        role: Agent role name (e.g., 'implementation-lead').
        working_dir: Project working directory path.
        focus: Work focus area (optional, resolved from branch if not provided).

    Returns:
        Structured context dict per interface contract:
        {
            session_id, role, focus, focus_source, branch, working_dir,
            context_paths, context: {
                product_north_star, project_context, phase_constraints,
                git_state, active_sessions
            }
        }

    Raises:
        ValueError: If role is invalid.
        FileNotFoundError: If working_dir doesn't exist.
    """
    # Validate inputs
    role = validate_role(role)
    working_dir_path = validate_working_dir(working_dir)

    # Get current branch for focus resolution
    branch = get_current_branch(working_dir_path)

    # Resolve focus: explicit > github_issue > branch > default
    focus_resolved = resolve_focus(explicit_focus=focus, branch=branch)

    # Create session
    mgr = SessionManager(str(working_dir_path))
    session_result = mgr.create_session(
        role=role,
        focus=focus_resolved["value"],
        branch=branch,
    )
    session_id = session_result["session_id"]

    # Detect focus conflicts (other sessions with same focus)
    conflicts = mgr.detect_focus_conflicts(focus_resolved["value"], session_id)
    if conflicts:
        logger.warning(f"Focus conflict detected: {conflicts}")

    # Discover context paths
    context_paths = mgr.discover_context_paths()

    # Get active session focuses
    active_sessions = mgr.get_active_session_focuses()

    # Read North Star contents
    product_north_star = None
    ns_path = mgr._find_north_star_file()
    if ns_path:
        product_north_star = mgr.read_file_contents(ns_path)

    # Read PROJECT-CONTEXT contents
    project_context_path = (
        working_dir_path / ".hestai" / "state" / "context" / "PROJECT-CONTEXT.oct.md"
    )
    project_context = mgr.read_file_contents(project_context_path)

    # Context freshness check (I4)
    if project_context_path.exists():
        freshness_warning = check_context_freshness(project_context_path, working_dir_path)
        if freshness_warning:
            logger.warning(freshness_warning)

    # Get git state
    git_state = get_git_state(working_dir_path)
    if git_state is None:
        git_state = {
            "branch": branch,
            "ahead": 0,
            "behind": 0,
            "modified_files": [],
        }

    # Phase constraints (graceful fallback)
    phase_constraints = None
    try:
        # Look for workflow files in common locations
        for workflow_candidate in [
            working_dir_path / ".hestai" / "workflow" / "OPERATIONAL-WORKFLOW.oct.md",
            working_dir_path
            / ".hestai-sys"
            / "standards"
            / "workflow"
            / "OPERATIONAL-WORKFLOW.oct.md",
        ]:
            if workflow_candidate.exists():
                steward = ContextSteward(workflow_path=workflow_candidate)
                constraints = steward.synthesize_active_state("B1")
                phase_constraints = constraints.to_dict()
                break
    except (FileNotFoundError, ValueError) as e:
        logger.debug(f"Phase constraints not available: {e}")

    return {
        "session_id": session_id,
        "role": role,
        "focus": focus_resolved["value"],
        "focus_source": focus_resolved["source"],
        "branch": branch,
        "working_dir": str(working_dir_path),
        "context_paths": context_paths,
        "context": {
            "product_north_star": product_north_star,
            "project_context": project_context,
            "phase_constraints": phase_constraints,
            "git_state": git_state,
            "active_sessions": active_sessions,
        },
    }
