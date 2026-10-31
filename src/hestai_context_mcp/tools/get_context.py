"""Get-context tool: Read-only context synthesis without session creation.

Returns the same context object as clock_in but without any side effects:
- No session directory creation
- No session.json writing
- No FAST layer file mutations
- Zero file system writes

Use cases:
- Payload Compiler preview ("what would an agent see?")
- CI pipeline context injection
- Lightweight reads without session overhead

PURITY_GUARD::G3 — DO NOT ADD STORAGE IMPORTS.
================================================

Per CE RISK_003 OPTION_C ratified in the B1->B2 arbitration record,
this module's public contract is **frozen** at
``get_context(working_dir: str)``. Session-bound snapshots are exposed
exclusively via ``clock_in.portable_state.snapshot``; ``get_context``
MUST NOT import any adapter module, MUST NOT reference adapter or
outbox symbols, MUST NOT create portable subdirectories, MUST NOT
mutate snapshot/outbox mtimes, MUST NOT drain or enqueue outbox
entries, and MUST NOT surface hydration as a successful response key.

Behavioral invariants are enforced by
``tests/integration/test_get_context_purity.py`` and the source-level
guard is enforced by ``tests/storage/test_source_invariants_pss.py``
(PROD::I5 + R10 INVARIANT_001).
"""

import logging
from pathlib import Path
from typing import Any

from hestai_context_mcp.core.context_steward import ContextSteward, WorkflowParseError
from hestai_context_mcp.core.git_state import get_git_state
from hestai_context_mcp.core.session import SessionManager

logger = logging.getLogger(__name__)


def _validate_working_dir(working_dir: str) -> Path:
    """Validate working directory path.

    Args:
        working_dir: Working directory path.

    Returns:
        Resolved absolute path.

    Raises:
        ValueError: If path traversal detected.
        FileNotFoundError: If directory doesn't exist.
    """
    if ".." in working_dir:
        raise ValueError("Path traversal attempt detected in working_dir")

    path = Path(working_dir).expanduser().resolve()

    if not path.exists():
        raise FileNotFoundError(f"Working directory does not exist: {path}")

    if not path.is_dir():
        raise ValueError(f"Working directory path is not a directory: {path}")

    return path


def get_context(working_dir: str) -> dict[str, Any]:
    """Read-only context query. Returns context without creating a session.

    Synthesizes the same context object as clock_in but with zero side effects.
    No session directories, no session.json, no FAST layer files are created.

    Args:
        working_dir: Absolute path to project directory.

    Returns:
        Structured context dict:
        {
            working_dir: str,
            context: {
                product_north_star: str | None,
                project_context: str | None,
                phase_constraints: dict | None,
                git_state: {branch, ahead, behind, modified_files},
                active_sessions: [str],
                phase_constraints_error: {code, file, line, construct}  # optional: only
                    # when the workflow document has a malformed list (phase_constraints
                    # is then None); file is relative to working_dir
            }
        }

    Raises:
        ValueError: If working_dir contains path traversal.
        FileNotFoundError: If working_dir doesn't exist.
    """
    working_dir_path = _validate_working_dir(working_dir)

    # Use SessionManager for read-only operations only
    mgr = SessionManager(str(working_dir_path))

    # Read North Star contents (read-only)
    product_north_star = None
    ns_path = mgr._find_north_star_file()
    if ns_path:
        product_north_star = mgr.read_file_contents(ns_path)

    # Read PROJECT-CONTEXT contents (read-only)
    project_context_path = (
        working_dir_path / ".hestai" / "state" / "context" / "PROJECT-CONTEXT.oct.md"
    )
    project_context = mgr.read_file_contents(project_context_path)

    # Get git state (read-only subprocess calls)
    git_state = get_git_state(working_dir_path)
    if git_state is None:
        git_state = {
            "branch": "unknown",
            "ahead": 0,
            "behind": 0,
            "modified_files": [],
        }

    # Get active session focuses (read-only directory scan)
    active_sessions = mgr.get_active_session_focuses()

    # Phase constraints (read-only, graceful fallback)
    phase_constraints, phase_constraints_error = _get_phase_constraints(working_dir_path)

    context: dict[str, Any] = {
        "product_north_star": product_north_star,
        "project_context": project_context,
        "phase_constraints": phase_constraints,
        "git_state": git_state,
        "active_sessions": active_sessions,
    }
    if phase_constraints_error is not None:
        # Optional key: present ONLY when the workflow document is malformed (#196).
        context["phase_constraints_error"] = phase_constraints_error

    return {"working_dir": str(working_dir_path), "context": context}


def _get_phase_constraints(
    working_dir_path: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Attempt to read phase constraints from workflow files.

    Args:
        working_dir_path: Resolved project directory path.

    Returns:
        ``(phase_constraints, error)``. ``phase_constraints`` is the dict or None if not
        available; ``error`` is the structured ``WORKFLOW_PARSE_FAILED`` dict (repo-relative
        file) when the workflow document has a malformed list, else None.
    """
    try:
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
                return constraints.to_dict(), None
    except WorkflowParseError as e:
        logger.warning(f"Workflow document malformed: {e}")
        return None, e.to_error(working_dir_path)
    except (FileNotFoundError, ValueError) as e:
        logger.debug(f"Phase constraints not available: {e}")

    return None, None
