"""ADR-0013 PSS state classification helpers — R1 + §MIGRATION_PLAN.

Maps known ``.hestai/state/`` paths to ``StateClassification`` per the
authoritative EXISTING_STATE_CLASSIFICATION_MAP in BUILD-PLAN
§MIGRATION_PLAN. Unknown paths fail closed to ``LOCAL_MUTABLE`` (R1).

The helpers here are pure: they perform no filesystem mutation and never
require the target file to exist. They classify by *path shape*, which is
the only safe basis when the migration runner does not yet know whether a
given file has been written.
"""

from __future__ import annotations

from pathlib import Path

from hestai_context_mcp.storage.types import StateClassification


def _relative_state_path(target: Path, *, working_dir: Path) -> tuple[str, ...]:
    """Return the path components of ``target`` relative to ``working_dir/.hestai/state``.

    Returns an empty tuple when ``target`` is not inside the state tree.
    Comparison uses absolute, resolved paths and tolerates the
    ``.hestai/state`` -> ``.hestai-state`` symlink convention.
    """

    state_root = working_dir / ".hestai" / "state"
    try:
        rel = target.resolve().relative_to(state_root.resolve())
    except (FileNotFoundError, ValueError):
        try:
            rel = target.relative_to(state_root)
        except ValueError:
            return ()
    return rel.parts


def classify_state_path(target: Path, *, working_dir: Path) -> StateClassification:
    """Classify ``target`` per ADR-0013 R1.

    Args:
        target: A path *under* ``working_dir/.hestai/state``. Paths outside
            the state tree default to ``LOCAL_MUTABLE`` (R1 fail-closed).
        working_dir: Project root.

    Returns:
        ``StateClassification`` for the path shape.
    """

    parts = _relative_state_path(target, working_dir=working_dir)
    if not parts:
        return StateClassification.LOCAL_MUTABLE

    # PORTABLE_MEMORY: artifacts and tombstones carrier files.
    if parts[:1] == ("portable",) and len(parts) > 1:
        sub = parts[1]
        if sub in ("artifacts", "tombstones"):
            return StateClassification.PORTABLE_MEMORY
        if sub == "snapshots":
            return StateClassification.DERIVED_PROJECTION
        if sub in ("outbox", "tmp"):
            return StateClassification.LOCAL_MUTABLE
        # Unknown subtree under portable/ → fail-closed.
        return StateClassification.LOCAL_MUTABLE

    # All non-portable paths under .hestai/state/ default to LOCAL_MUTABLE.
    return StateClassification.LOCAL_MUTABLE


def classify_materialized_context(
    target: Path, *, derived_from_portable_memory: bool
) -> StateClassification:
    """Classify a materialized PROJECT-CONTEXT.oct.md file (MAP_008).

    The same on-disk path can be either ``DERIVED_PROJECTION`` (when
    rebuilt from Portable Memory Artifacts) or ``LOCAL_MUTABLE`` (when
    authored locally). Callers MUST signal the provenance explicitly;
    when in doubt, pass ``derived_from_portable_memory=False`` to
    fail-closed under R1.

    Args:
        target: Path to the materialized context file (e.g.,
            ``.hestai/state/context/PROJECT-CONTEXT.oct.md``). Not opened.
        derived_from_portable_memory: True iff the migration / rebuilder
            produced this file from Portable Memory Artifacts.
    """

    # ``target`` is reserved for future shape-based dispatch; current
    # behavior depends only on the explicit derivation flag (MAP_008).
    del target
    if derived_from_portable_memory:
        return StateClassification.DERIVED_PROJECTION
    return StateClassification.LOCAL_MUTABLE


__all__ = [
    "classify_materialized_context",
    "classify_state_path",
]
