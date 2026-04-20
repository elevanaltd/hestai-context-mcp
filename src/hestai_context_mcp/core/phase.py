"""Phase resolver — extract the declared full phase identifier.

Reads ``PHASE::<FULL_FORM>`` from the project's North Star summary or the
``PROJECT-CONTEXT.oct.md`` file. Returns the full form (e.g.
``B1_FOUNDATION_COMPLETE``) rather than the bare prefix ``B1``. The bare
prefix is still available via :func:`phase_prefix` for callers (such as
:class:`ContextSteward`) that key off prefix markers in workflow documents.

Issue #4 acceptance criterion 2: Payload Compiler shape-parity requires the
legacy full-form phase string.
"""

from __future__ import annotations

from pathlib import Path

# Default when no declaration can be found. Matches the current repo state
# per .hestai/north-star/000-HESTAI-CONTEXT-MCP-NORTH-STAR-SUMMARY.oct.md and
# .hestai/state/context/PROJECT-CONTEXT.oct.md. Callers may override.
DEFAULT_PHASE: str = "B1_FOUNDATION_COMPLETE"


def phase_prefix(phase: str) -> str:
    """Return the leading prefix of a phase identifier.

    ``"B1_FOUNDATION_COMPLETE"`` → ``"B1"``; ``"B1"`` → ``"B1"``. Used by
    consumers that need the workflow-document marker (e.g. ``B1_BUILD_PLAN``)
    rather than the full declared phase.

    Args:
        phase: Full or bare phase identifier.

    Returns:
        Prefix up to the first underscore.
    """
    if "_" in phase:
        return phase.split("_", 1)[0]
    return phase


def _extract_phase_from_content(content: str) -> str | None:
    """Extract the first ``PHASE::<value>`` declaration from OCTAVE text.

    Args:
        content: File contents.

    Returns:
        The trimmed phase value, or ``None`` if no well-formed declaration
        exists.
    """
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line.startswith("PHASE::"):
            continue
        value = line.split("::", 1)[1].strip()
        if value:
            return value
    return None


def _read_first_north_star_phase(working_dir: Path) -> str | None:
    """Read the phase declaration from the first North Star summary file."""
    ns_dir = working_dir / ".hestai" / "north-star"
    if not ns_dir.is_dir():
        return None
    # Deterministic ordering so precedence is stable across platforms.
    for candidate in sorted(ns_dir.glob("*.oct.md")):
        try:
            content = candidate.read_text()
        except (OSError, UnicodeDecodeError):
            # UnicodeDecodeError is a ValueError subclass raised when the
            # file bytes are not valid UTF-8. Treat as absent and fall back.
            continue
        phase = _extract_phase_from_content(content)
        if phase:
            return phase
    return None


def _read_project_context_phase(working_dir: Path) -> str | None:
    """Read the phase declaration from ``PROJECT-CONTEXT.oct.md``."""
    path = working_dir / ".hestai" / "state" / "context" / "PROJECT-CONTEXT.oct.md"
    if not path.is_file():
        return None
    try:
        content = path.read_text()
    except (OSError, UnicodeDecodeError):
        return None
    return _extract_phase_from_content(content)


def resolve_phase(working_dir: Path, *, default: str = DEFAULT_PHASE) -> str:
    """Resolve the full declared phase identifier for ``working_dir``.

    Precedence:
        1. First ``.oct.md`` file under ``.hestai/north-star/`` with a
           ``PHASE::`` declaration.
        2. ``.hestai/state/context/PROJECT-CONTEXT.oct.md``.
        3. ``default``.

    The function is a pure read — no side effects — so it is safe for use
    from ``get_context`` (PROD::I5 READ_ONLY_CONTEXT_QUERY).

    Args:
        working_dir: Project root.
        default: Value to return when no declaration is found.

    Returns:
        Full-form phase identifier (never the bare ``"B1"`` abbreviation
        unless the source file declares it that way).
    """
    phase = _read_first_north_star_phase(working_dir)
    if phase:
        return phase
    phase = _read_project_context_phase(working_dir)
    if phase:
        return phase
    return default


__all__: list[str] = ["DEFAULT_PHASE", "phase_prefix", "resolve_phase"]
