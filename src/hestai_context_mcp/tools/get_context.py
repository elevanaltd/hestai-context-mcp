"""Get-context tool: Synthesize and return project context."""


def get_context(working_dir: str, scope: str = "full") -> dict[str, str]:
    """Synthesize and return project context for the current session.

    Reads project context files, synthesizes them into a coherent view,
    and returns the result for agent consumption.

    Args:
        working_dir: Project working directory path.
        scope: Context scope ('full', 'summary', 'focus').

    Returns:
        Dictionary with synthesized context.
    """
    return {"status": "not_yet_implemented", "tool": "get_context"}
