"""submit_governance MCP tool -- Gate A Rails (RFC #53).

Accepts operator-authored OCTAVE governance content, validates it via
the Dumb Type Checker (regex-only, no AST), and creates a PR to place
the artifact at the canonical path per ADR-RFC-ARCH-001.

North Star invariants enforced:
  PROD I4: Structured return shape (always a dict with defined fields).
  PROD I5: get_context is UNTOUCHED. This tool is additive.
  PROD I6: No hestai_mcp imports. No new PyPI dependencies.

Gate B (future): wire octave-mcp validator over stdio for full OCTAVE validation.
"""

import asyncio
from functools import partial
from typing import Any

from hestai_context_mcp.tools.clock_in import validate_working_dir
from hestai_context_mcp.tools.governance.linker import run_linker
from hestai_context_mcp.tools.governance.type_checker import validate_octave_content


def _empty_result(
    dry_run: bool,
    errors: list[str],
) -> dict[str, Any]:
    """Return the I4-conformant failure shape with all fields present."""
    return {
        "success": False,
        "token": None,
        "card_type": None,
        "target_path": None,
        "branch": None,
        "pr_url": None,
        "validation_errors": errors,
        "dry_run": dry_run,
    }


async def submit_governance(
    working_dir: str,
    octave_content: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Submit an operator-authored OCTAVE governance artifact.

    Gate A Rails: regex sentinel check + path placement + PR creation.
    No LLM. No OCTAVE AST parsing. No octave-mcp invocation.

    Blocking I/O (filesystem reads, subprocess calls) is offloaded to
    the default thread-pool executor via run_in_executor so that the
    async event loop is never blocked (Bug 5 fix).

    Args:
        working_dir: Absolute path to the project root directory.
        octave_content: The OCTAVE document text to validate and commit.
        dry_run: If True, validates and computes placement but does not
                 create branch, write files, or open PR.

    Returns:
        I4-conformant structured dict:
          success: bool -- True if validation passed (and PR opened when not dry_run).
          token: str | None -- Extracted TOKEN or ID.
          card_type: str | None -- Extracted card type.
          target_path: str | None -- Computed repo-relative target path.
          branch: str | None -- Git branch name that was (or would be) created.
          pr_url: str | None -- PR URL (None for dry_run or on failure).
          validation_errors: list[str] -- Empty on success.
          dry_run: bool -- Echoes the dry_run parameter.
    """
    loop = asyncio.get_running_loop()

    # --- Validate working_dir (blocking path resolution) ---
    try:
        wd = await loop.run_in_executor(None, validate_working_dir, working_dir)
    except (ValueError, FileNotFoundError) as exc:
        return _empty_result(dry_run, [str(exc)])

    # --- Dumb Type Checker (blocking filesystem reads for token lookup) ---
    validation = await loop.run_in_executor(
        None,
        validate_octave_content,
        wd,
        octave_content,
    )

    if not validation.valid:
        return _empty_result(dry_run, validation.errors)

    # --- Linker (blocking: git subprocess + file writes) ---
    linker_fn = partial(
        run_linker,
        working_dir=wd,
        validation=validation,
        octave_content=octave_content,
        dry_run=dry_run,
    )
    linker_output = await loop.run_in_executor(None, linker_fn)

    linker_error = linker_output.get("error")
    success = linker_error is None

    errors: list[str] = [linker_error] if linker_error else []

    return {
        "success": success,
        "token": linker_output.get("token"),
        "card_type": linker_output.get("card_type"),
        "target_path": linker_output.get("target_path"),
        "branch": linker_output.get("branch"),
        "pr_url": linker_output.get("pr_url"),
        "validation_errors": errors,
        "dry_run": dry_run,
    }
