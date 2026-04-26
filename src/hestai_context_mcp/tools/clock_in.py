"""Clock-in tool: Register agent session start and return context paths.

Returns the structured response per ADR-0353 interface contract.
Harvested from legacy hestai-mcp clock_in.py.

ADR-0013 PSS extension: clock_in resolves the PSS IdentityTuple, restores
Portable Memory Artifacts via LocalFilesystemAdapter, and writes a named
session snapshot. The response is extended with a structured
``portable_state`` block. All existing top-level fields are preserved
(G2 backward compatibility).
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
from hestai_context_mcp.core.north_star_parser import (
    NorthStarConstraints,
    extract_constraints,
)
from hestai_context_mcp.core.phase import phase_prefix, resolve_phase
from hestai_context_mcp.core.session import SessionManager
from hestai_context_mcp.core.synthesis import resolve_ai_synthesis

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
                product_north_star, product_north_star_constraints,
                project_context, phase_constraints, git_state,
                active_sessions, conflicts
            }
        }

        ``product_north_star_constraints`` is a ``NorthStarConstraints``
        TypedDict with ``scope_boundaries`` (dict) and ``immutables`` (list);
        the structured sibling of the raw ``product_north_star`` blob per
        PROD::I4 STRUCTURED_RETURN_SHAPES. See
        :mod:`hestai_context_mcp.core.north_star_parser` for schema.

        ``context.conflicts`` (issue #7) is a ``list[FocusConflict]`` of
        structured entries describing other active sessions sharing the
        resolved focus; always present (empty list when no conflict, never
        null / never absent). Distinct from ``active_sessions`` (which is
        the list of all active focus strings and remains backward compat).
        See :class:`hestai_context_mcp.core.session.FocusConflict`.

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

    # Detect focus conflicts (other sessions with same focus).
    # Issue #7: the structured result is surfaced in the response
    # (context.conflicts) so the Payload Compiler can read conflicting
    # session identity directly without deriving it from active_sessions
    # (PROD::I4 STRUCTURED_RETURN_SHAPES).
    conflicts = mgr.detect_focus_conflicts(focus_resolved["value"], session_id)
    if conflicts:
        logger.warning(f"Focus conflict detected: {conflicts}")

    # Discover context paths
    context_paths = mgr.discover_context_paths()

    # Get active session focuses
    active_sessions = mgr.get_active_session_focuses()

    # Read North Star contents (raw blob for backward compatibility).
    product_north_star = None
    ns_path = mgr._find_north_star_file()
    if ns_path:
        product_north_star = mgr.read_file_contents(ns_path)

    # Issue #6: harvest structured SCOPE_BOUNDARIES / IMMUTABLES alongside
    # the raw blob so the Payload Compiler can extract architectural
    # constraints programmatically (PROD::I4 STRUCTURED_RETURN_SHAPES).
    # The parser is a pure function (PROD::I5); it returns an empty
    # structured result when product_north_star is None/empty/malformed.
    product_north_star_constraints: NorthStarConstraints = extract_constraints(product_north_star)

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

    # Resolve the declared full-form phase (e.g. "B1_FOUNDATION_COMPLETE").
    # Full form is the Payload Compiler shape-parity contract (issue #4).
    phase = resolve_phase(working_dir_path)

    # Phase constraints (graceful fallback). The workflow document uses
    # prefix markers (B1_BUILD_PLAN, etc.), so pass the prefix — not the
    # full form — to ContextSteward.
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
                constraints = steward.synthesize_active_state(phase_prefix(phase))
                phase_constraints = constraints.to_dict()
                break
    except (FileNotFoundError, ValueError) as e:
        logger.debug(f"Phase constraints not available: {e}")

    # Build AI synthesis via the provider-agnostic seam (issue #5 replaces
    # the body of synthesize_ai_context with a real provider call). The
    # ai_synthesis field is ALWAYS present per PROD::I4 STRUCTURED_RETURN_SHAPES.
    context_summary = _build_context_summary(
        product_north_star=product_north_star,
        project_context=project_context,
        git_state=git_state,
    )
    ai_synthesis = resolve_ai_synthesis(
        role=role,
        focus=focus_resolved["value"],
        phase=phase,
        context_summary=context_summary,
    )

    # ADR-0013 PSS: restore Portable Memory Artifacts and write a named
    # snapshot bound to session_id. The block is ALWAYS present (G2 +
    # PROD::I4 STRUCTURED_RETURN_SHAPES). When no identity is configured
    # the block reports restore_status="no_identity_configured" — never
    # an exception, never a network call.
    portable_state = _restore_portable_state(
        working_dir_path=working_dir_path,
        session_id=session_id,
    )

    return {
        "session_id": session_id,
        "role": role,
        "focus": focus_resolved["value"],
        "focus_source": focus_resolved["source"],
        "branch": branch,
        "working_dir": str(working_dir_path),
        "phase": phase,
        "context_paths": context_paths,
        "ai_synthesis": ai_synthesis,
        "context": {
            "product_north_star": product_north_star,
            "product_north_star_constraints": product_north_star_constraints,
            "project_context": project_context,
            "phase_constraints": phase_constraints,
            "git_state": git_state,
            "active_sessions": active_sessions,
            "conflicts": conflicts,
        },
        "portable_state": portable_state,
    }


def _empty_portable_state(
    *, restore_status: str, error: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "restore_status": restore_status,
        "identity": None,
        "artifact_count": 0,
        "tombstone_count": 0,
        "snapshot_path": None,
        "error": error,
    }


def _restore_portable_state(*, working_dir_path: Path, session_id: str) -> dict[str, Any]:
    """Restore PSS state and write a named snapshot bound to ``session_id``.

    This function is the integration boundary between ``clock_in`` and
    the storage adapter / projection / snapshot pipeline. It NEVER
    raises: every error path returns a structured ``portable_state``
    block so the caller's response shape is stable. Network calls are
    impossible by construction (LocalFilesystemAdapter only).
    """

    # Lazy imports keep PSS coupling out of module-load time and allow
    # get_context to import this module without dragging in the
    # storage subtree.
    from hestai_context_mcp.storage.identity import IdentityValidationError
    from hestai_context_mcp.storage.identity_resolver import resolve_identity
    from hestai_context_mcp.storage.local_filesystem import (
        LocalFilesystemAdapter,
        PayloadHashMismatchError,
    )
    from hestai_context_mcp.storage.projection import (
        ProjectionError,
        build_projection,
    )
    from hestai_context_mcp.storage.schema import (
        SchemaTooNewError,
        SchemaValidationError,
        validate_artifact,
    )
    from hestai_context_mcp.storage.snapshots import create_session_snapshot
    from hestai_context_mcp.storage.types import (
        ArtifactKind,
        PortableMemoryArtifact,
        PortableNamespace,
        TombstoneArtifact,
    )

    try:
        identity = resolve_identity(working_dir_path)
    except IdentityValidationError as e:
        return _empty_portable_state(
            restore_status="identity_invalid",
            error={"code": e.code, "message": e.message},
        )

    if identity is None:
        return _empty_portable_state(restore_status="no_identity_configured")

    namespace = PortableNamespace(
        project_id=identity.project_id,
        workspace_id=identity.workspace_id,
        user_id=identity.user_id,
        state_schema_version=identity.state_schema_version,
        carrier_namespace=identity.carrier_namespace,
    )

    adapter = LocalFilesystemAdapter(working_dir=working_dir_path)
    try:
        memory_refs = adapter.list_artifacts(namespace)
    except IdentityValidationError as e:
        return _empty_portable_state(
            restore_status="identity_mismatch",
            error={"code": e.code, "message": e.message},
        )

    artifacts: list[PortableMemoryArtifact] = []
    tombstones: list[TombstoneArtifact] = []
    for ref in memory_refs:
        try:
            obj = adapter.read_artifact(ref)
        except (
            PayloadHashMismatchError,
            IdentityValidationError,
            FileNotFoundError,
        ) as e:
            return _empty_portable_state(
                restore_status="restore_io_error",
                error={"code": getattr(e, "code", "io_error"), "message": str(e)},
            )
        if isinstance(obj, PortableMemoryArtifact):
            try:
                validate_artifact(obj)
            except SchemaTooNewError as e:
                return _empty_portable_state(
                    restore_status="schema_too_new",
                    error={"code": e.code, "message": e.message},
                )
            except SchemaValidationError as e:
                return _empty_portable_state(
                    restore_status="schema_invalid",
                    error={"code": e.code, "message": e.message},
                )
            artifacts.append(obj)
        elif isinstance(obj, TombstoneArtifact):
            tombstones.append(obj)

    # Tombstones live in a separate tree; list_artifacts(namespace) only
    # returned PORTABLE_MEMORY refs above. Surface tombstones explicitly.
    tomb_namespace_dir = (
        working_dir_path
        / ".hestai"
        / "state"
        / "portable"
        / "tombstones"
        / identity.carrier_namespace
        / identity.project_id
        / identity.workspace_id
        / identity.user_id
        / f"v{identity.state_schema_version}"
    )
    if tomb_namespace_dir.exists():
        from hestai_context_mcp.storage.types import ArtifactRef

        for json_path in sorted(tomb_namespace_dir.glob("*.json")):
            import json as _json

            try:
                raw = _json.loads(json_path.read_text(encoding="utf-8"))
                if raw.get("artifact_kind") != ArtifactKind.TOMBSTONE.value:
                    continue
                # Build a ref then read through the adapter so identity
                # checks apply.
                from datetime import datetime as _dt

                ref = ArtifactRef(
                    artifact_id=str(raw["artifact_id"]),
                    identity=identity,
                    artifact_kind=ArtifactKind.TOMBSTONE,
                    sequence_id=int(raw["sequence_id"]),
                    created_at=_dt.fromisoformat(raw["created_at"]),
                    payload_hash=str(raw["payload_hash"]),
                    carrier_path=str(json_path),
                )
                obj = adapter.read_artifact(ref)
                if isinstance(obj, TombstoneArtifact):
                    tombstones.append(obj)
            except (OSError, KeyError, ValueError, IdentityValidationError):
                # A bad tombstone file should not destroy a valid
                # restore; continue past it.
                continue

    try:
        projection = build_projection(
            identity=identity,
            artifacts=tuple(artifacts),
            tombstones=tuple(tombstones),
        )
    except IdentityValidationError as e:
        return _empty_portable_state(
            restore_status="identity_mismatch",
            error={"code": e.code, "message": e.message},
        )
    except ProjectionError as e:
        return _empty_portable_state(
            restore_status="projection_error",
            error={"code": e.code, "message": e.message},
        )

    # Refs included in the snapshot are the post-tombstone memory refs.
    accepted_ids = {r["artifact_id"] for r in projection["artifact_refs"]}
    accepted_refs = tuple(r for r in memory_refs if r.artifact_id in accepted_ids)

    snapshot_path = create_session_snapshot(
        working_dir=working_dir_path,
        session_id=session_id,
        identity=identity,
        artifact_refs=accepted_refs,
        projection_payload=projection,
    )

    return {
        "restore_status": "ok",
        "identity": {
            "project_id": identity.project_id,
            "workspace_id": identity.workspace_id,
            "user_id": identity.user_id,
            "state_schema_version": identity.state_schema_version,
            "carrier_namespace": identity.carrier_namespace,
        },
        "artifact_count": len(accepted_refs),
        "tombstone_count": len(tombstones),
        "snapshot_path": str(snapshot_path),
        "error": None,
    }


def _build_context_summary(
    *,
    product_north_star: str | None,
    project_context: str | None,
    git_state: dict[str, Any],
) -> str:
    """Assemble a lightweight context summary for the AI synthesis seam.

    Kept simple in this PR; issue #5 may extend with richer signals. No
    provider-specific formatting is applied here (PROD::I3).
    """
    parts: list[str] = []
    if product_north_star:
        parts.append(f"NORTH_STAR::\n{product_north_star}")
    if project_context:
        parts.append(f"PROJECT_CONTEXT::\n{project_context}")
    parts.append(f"GIT_STATE::{git_state}")
    return "\n\n".join(parts)
