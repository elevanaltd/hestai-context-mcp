"""HestAI Context MCP Server - Tool registration and stdio transport.

This MCP server provides session lifecycle and context management tools:
- clock_in: Register session start and return context paths
- clock_out: Archive session transcript and extract learnings
- get_context: Synthesize and return project context
- submit_review: Submit structured review comments

Architecture:
- Part of the three-service model (ADR-0353)
- Communicates via stdio JSON-RPC transport
- No governance/identity code (that lives in the vault)
"""

from fastmcp import FastMCP

from hestai_context_mcp.tools.clock_in import clock_in
from hestai_context_mcp.tools.clock_out import clock_out
from hestai_context_mcp.tools.get_context import get_context
from hestai_context_mcp.tools.submit_review import submit_review

mcp = FastMCP(
    name="hestai-context-mcp",
)

# Register tools
mcp.tool(clock_in)
mcp.tool(clock_out)
mcp.tool(get_context)
mcp.tool(submit_review)


def main() -> None:
    """Run the MCP server over stdio transport."""
    mcp.run()
