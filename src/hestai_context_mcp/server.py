"""HestAI Context MCP Server - Tool registration and stdio transport.

This MCP server provides session lifecycle and context management tools:
- clock_in: Register session start and return context paths
- clock_out: Archive session transcript and extract learnings
- get_context: Synthesize and return project context
- submit_review: Submit structured review comments
- submit_governance: Gate A Rails intake for OCTAVE governance artifacts (RFC #53)

Architecture:
- Part of the three-service model (ADR-0353)
- Communicates via stdio JSON-RPC transport
- No governance/identity code (that lives in the vault)

Startup .env loading:
- ``main()`` calls :func:`_load_env` before ``mcp.run()`` so that Gate C prose
  mode (``submit_governance(prose_input=...)``) can resolve ``OPENROUTER_API_KEY``
  / ``HESTAI_AI_MODEL`` when the server is launched by an MCP client whose CWD is
  unrelated to the repo. Mirrors the sibling MCP servers (hestai-mcp,
  debate-hall-mcp).
- ``override=False`` (PROD I2): explicit process env vars and the ai_config
  keyring lookup always win over a ``.env`` file value. No secret value is logged.
"""

from pathlib import Path

from fastmcp import FastMCP

from hestai_context_mcp.tools.clock_in import clock_in
from hestai_context_mcp.tools.clock_out import clock_out
from hestai_context_mcp.tools.get_context import get_context
from hestai_context_mcp.tools.submit_governance import submit_governance
from hestai_context_mcp.tools.submit_review import submit_review

mcp = FastMCP(
    name="hestai-context-mcp",
)


def _project_root_env() -> Path:
    """Return the expected repo-root ``.env`` path, anchored to this file.

    ``server.py`` lives at ``src/hestai_context_mcp/server.py``; walking three
    parents reaches the repo root regardless of the process CWD at spawn time.
    """
    return Path(__file__).resolve().parents[2] / ".env"


def _load_env(dotenv_path: Path | None = None) -> bool:
    """Load a ``.env`` file into ``os.environ`` at server startup.

    Resolution order (first existing file wins):
        1. ``dotenv_path`` if explicitly provided.
        2. ``<repo-root>/.env`` (anchored to this module, CWD-independent).
        3. ``<cwd>/.env`` fallback.

    Uses ``override=False`` so explicit process env vars and the ai_config
    keyring lookup are never clobbered by a file value (PROD I2). The import of
    ``python-dotenv`` is kept import-safe; no secret value is ever logged.

    Returns:
        ``True`` if a ``.env`` file was found and loaded, ``False`` otherwise.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - dotenv is a declared dependency
        return False

    candidates = (
        [dotenv_path] if dotenv_path is not None else [_project_root_env(), Path.cwd() / ".env"]
    )
    for candidate in candidates:
        if candidate is not None and candidate.exists():
            load_dotenv(dotenv_path=candidate, override=False)
            return True
    return False


# Register tools
mcp.tool(clock_in)
mcp.tool(clock_out)
mcp.tool(get_context)
mcp.tool(submit_review)
mcp.tool(submit_governance)


def main() -> None:
    """Run the MCP server over stdio transport."""
    _load_env()
    mcp.run()


if __name__ == "__main__":
    main()
