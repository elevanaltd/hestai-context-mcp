"""submit_governance MCP tool -- Gate A/B Rails + Gate C prose mode (RFC #53).

Two mutually-exclusive entry modes converge on ONE validate->link tail:

  * ``octave_content`` -- operator pre-authored OCTAVE (Gate A regex + Gate B
    real validator + linker). Behaviour is byte-stable vs post-#70 main.
  * ``prose_input`` -- operator intent in prose. Stage 1 (context assembler) +
    Stage 2 (prose->OCTAVE backend) author the OCTAVE, then the call REJOINS the
    same Stage-3 gate + Stage-4 linker tail (Gate C). Adds a ``metrics`` field.

EXACTLY ONE of ``octave_content`` / ``prose_input`` must be supplied.

North Star invariants enforced:
  PROD I4: Structured return shape (always a dict with defined fields).
  PROD I5: get_context is UNTOUCHED. This tool is additive.
  PROD I6: No hestai_mcp imports. No new PyPI dependencies.
  PROD I3: prose mode authors via the provider-agnostic AIClient port; output is
           gated by the Stage-3 validator + human PR review (no auto-merge).

Gate B: octave-mcp's REAL validator runs in-process as a library behind the
OctaveValidator port (hestai_context_mcp.ports.octave_validator), gated by the
optional ``validation`` extra. When the extra is absent the port degrades to a
structured "real-validation unavailable" signal and the regex Gate A still runs.
"""

import asyncio
from functools import partial
from typing import Any

from hestai_context_mcp.core.intake_pipeline import run_intake_to_pr
from hestai_context_mcp.ports.octave_validator import (
    OctaveValidationResult,
    get_octave_validator,
)
from hestai_context_mcp.tools.clock_in import validate_working_dir
from hestai_context_mcp.tools.governance.intake_context import assemble_intake_context
from hestai_context_mcp.tools.governance.linker import run_linker
from hestai_context_mcp.tools.governance.type_checker import validate_octave_content


def _empty_result(
    dry_run: bool,
    errors: list[str],
    octave_validation: dict[str, Any] | None = None,
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
        "octave_validation": octave_validation,
        "dry_run": dry_run,
    }


def _octave_errors_to_strings(result: OctaveValidationResult) -> list[str]:
    """Flatten octave-mcp's structured errors into human-readable strings.

    The structured detail is preserved verbatim under the ``octave_validation``
    return field (PROD I4); this projection only feeds the flat
    ``validation_errors`` list that callers already consume from Gate A.
    """
    messages: list[str] = []
    for err in result.errors:
        code = err.get("code", "")
        message = err.get("message", "")
        line = err.get("line", 0)
        prefix = f"[{code}] " if code else ""
        suffix = f" (line {line})" if line else ""
        messages.append(f"{prefix}{message}{suffix}".strip())
    return messages


async def submit_governance(
    working_dir: str,
    octave_content: str | None = None,
    prose_input: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Submit a governance artifact via OCTAVE content OR prose intent.

    EXACTLY ONE of ``octave_content`` / ``prose_input`` must be non-None.

    ``octave_content`` mode (Gate A/B): regex sentinel check + real
    OctaveValidator + path placement + PR creation. Byte-stable vs post-#70 main.

    ``prose_input`` mode (Gate C): Stage 1 (context assembler) + Stage 2
    (prose->OCTAVE backend over the provider-agnostic AIClient port) author the
    OCTAVE, then the call REJOINS the same Stage-3 validator + Stage-4 linker
    tail. The return dict additionally carries a ``metrics`` field
    {tokens, cost, model}. Output is gated by the validator + human PR review
    (no auto-merge); cost caps abort runaway calls with a structured error.

    Blocking I/O (filesystem reads, subprocess calls) and the CPU-bound
    in-process OCTAVE parse are offloaded to the default thread-pool
    executor via run_in_executor so that the async event loop is never
    blocked (Bug 5 fix).

    Args:
        working_dir: Absolute path to the project root directory.
        octave_content: The OCTAVE document text to validate and commit.
        prose_input: Freeform operator intent to compile into OCTAVE.
        dry_run: If True, validates and computes placement but does not
                 create branch, write files, or open PR.

    Returns:
        I4-conformant structured dict (see field docs in the module). In
        ``prose_input`` mode the dict additionally contains ``metrics``.
    """
    # --- EXACTLY-ONE-OF guard (Gate C contract ruling) ---
    if (octave_content is None) == (prose_input is None):
        return _empty_result(
            dry_run,
            [
                "Exactly one of 'octave_content' or 'prose_input' must be provided "
                "(received neither or both)."
            ],
        )

    if prose_input is not None:
        return await _submit_prose_input(working_dir, prose_input, dry_run)

    # The EXACTLY-ONE-OF guard above guarantees octave_content is non-None here.
    assert octave_content is not None
    return await _submit_octave_content(working_dir, octave_content, dry_run)


async def _submit_prose_input(
    working_dir: str,
    prose_input: str,
    dry_run: bool,
) -> dict[str, Any]:
    """Gate C prose mode: Stage 1 assemble -> Stage 2+3+4 via run_intake_to_pr.

    Validates working_dir first (PROD I4 structured failure on bad path), then
    assembles the Stage-1 context and delegates to the Stage 2->4 composition,
    which rejoins the same validate->link tail as the octave_content path.
    """
    loop = asyncio.get_running_loop()
    try:
        wd = await loop.run_in_executor(None, validate_working_dir, working_dir)
    except (ValueError, FileNotFoundError) as exc:
        return _empty_result(dry_run, [str(exc)])

    intake_context = await loop.run_in_executor(None, assemble_intake_context, wd, prose_input)
    return await run_intake_to_pr(wd, intake_context, dry_run=dry_run)


async def _submit_octave_content(
    working_dir: str,
    octave_content: str,
    dry_run: bool,
) -> dict[str, Any]:
    """Gate A/B path: operator-authored OCTAVE -> validate -> link.

    Behaviour is byte-stable vs post-#70 main (Gate A regex + Gate B real
    validator + linker; same I4 return keys, no ``metrics`` field).
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

    # --- Gate B: REAL OCTAVE validation (in-process library behind the port) ---
    # octave-mcp's real validator runs here, ADDITIVE to the regex Gate A above.
    # It catches AST/lexer defects (e.g. unbalanced brackets, structural errors)
    # that the regex checker is blind to. The call is offloaded to the executor
    # because the in-process parse is CPU-bound. The port is feature-detected and
    # fail-soft: when the optional ``validation`` extra is absent it returns
    # ok=True/available=False with a structured signal, so the tool degrades to
    # regex-only rather than crashing or blocking (PROD I6; North Star §4).
    octave_validator = get_octave_validator()
    octave_result = await loop.run_in_executor(
        None,
        octave_validator.validate,
        octave_content,
    )
    octave_validation = octave_result.to_dict()

    if not octave_result.ok:
        # Real validation failed: structured error, no PR / no write.
        return _empty_result(
            dry_run,
            _octave_errors_to_strings(octave_result),
            octave_validation=octave_validation,
        )

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
        "octave_validation": octave_validation,
        "dry_run": dry_run,
    }
