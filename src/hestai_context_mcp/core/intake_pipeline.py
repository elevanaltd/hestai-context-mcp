"""Stage-3 GATE: validate -> retry-once -> abort pipeline (RFC #53 Gate C, T3).

Drives the Stage-2 prose->OCTAVE compiler through the EXISTING Stage-3 gate and
enforces the retry/abort contract:

    pass     -> return the validated OCTAVE + ValidationResult,
    fail     -> retry ONCE, re-compiling with the validation errors appended to
                the prompt so the second attempt is informed,
    fail x2  -> ABORT with structured errors.

The gate is the SAME pair already used by ``submit_governance``:
``tools.governance.type_checker.validate_octave_content`` (regex Gate A) and
``ports.octave_validator.get_octave_validator().validate`` (real Gate B). No new
validator, no in-repo OCTAVE AST (North Star §4).

HALLUCINATION-IMMUNITY INVARIANT: this module performs NO filesystem writes and
NEVER imports or calls the linker. A double-fail therefore physically cannot
reach disk or open a PR. Stage 4 (linker) runs only downstream of a *successful*
pipeline result. This is enforced structurally by a source-grep test
(``tests/unit/core/test_intake_pipeline.py``) in addition to behaviour tests.

Returns a structured dict (PROD::I4).
"""

from __future__ import annotations

import asyncio
import dataclasses
from functools import partial
from pathlib import Path
from typing import Any, TypedDict

from hestai_context_mcp.core.intake_compiler import (
    CompileMetrics,
    compile_prose_to_octave,
)
from hestai_context_mcp.ports.octave_validator import get_octave_validator
from hestai_context_mcp.tools.governance.intake_context import IntakeContext
from hestai_context_mcp.tools.governance.linker import run_linker
from hestai_context_mcp.tools.governance.type_checker import (
    ValidationResult,
    validate_octave_content,
)
from hestai_context_mcp.tools.governance.verbosity_lint import lint_verbosity

__all__ = ["PipelineResult", "run_intake_pipeline", "run_intake_to_pr"]

# Exactly one retry on validation failure (RISK-3: bounded loop).
_MAX_ATTEMPTS = 2


class PipelineResult(TypedDict):
    """Structured result of the Stage-3 pipeline (PROD::I4).

    Fields:
        ok: True when a validated OCTAVE was produced.
        octave: The validated OCTAVE string (None on abort).
        validation: The passing ValidationResult (None on abort).
        validation_errors: Flattened error strings (empty on success).
        metrics: Stage-2 metrics from the *last* compile attempt.
        attempts: Number of backend compile attempts performed (1 or 2).
    """

    ok: bool
    octave: str | None
    validation: ValidationResult | None
    validation_errors: list[str]
    metrics: CompileMetrics
    attempts: int


def _gate(working_dir: Path, octave: str) -> tuple[bool, ValidationResult, list[str]]:
    """Run the existing two-stage gate. Returns (passed, regex_result, errors).

    Regex Gate A runs first (it also extracts token/card_type/target_path for
    Stage 4). The real Gate B validator runs additively; its structured errors
    are flattened into the error list. The pass requires BOTH to be clean.
    """
    regex_result = validate_octave_content(working_dir, octave)
    if not regex_result.valid:
        return False, regex_result, list(regex_result.errors)

    octave_result = get_octave_validator().validate(octave)
    if not octave_result.ok:
        errors = [
            f"[{e.get('code', '')}] {e.get('message', '')}".strip() for e in octave_result.errors
        ]
        return False, regex_result, errors

    # Density backstop: a record can be syntactically valid (Gates A+B clean) yet
    # be uncompressed prose in OCTAVE clothing. The deterministic verbosity lint
    # closes that gap; a failure flows through the SAME informed-retry/abort path
    # as a schema failure, so a verbose second attempt aborts — no write, no PR.
    verbosity_errors = lint_verbosity(octave)
    if verbosity_errors:
        return False, regex_result, verbosity_errors

    return True, regex_result, []


def _augment_prompt_with_errors(ctx: IntakeContext, errors: list[str]) -> IntakeContext:
    """Return a new IntakeContext whose prompt appends the validation errors.

    The retry must be *informed*: the second attempt sees exactly why the first
    output was rejected so it can correct it.
    """
    error_block = "\n".join(f"- {e}" for e in errors)
    augmented = (
        f"{ctx.prompt}\n"
        "BEGIN_VALIDATION_FEEDBACK\n"
        "The previous attempt FAILED OCTAVE validation with these errors. "
        "Produce a corrected single OCTAVE block that resolves ALL of them:\n"
        f"{error_block}\n"
        "END_VALIDATION_FEEDBACK\n"
    )
    return dataclasses.replace(ctx, prompt=augmented)


async def run_intake_pipeline(
    working_dir: Path,
    intake_context: IntakeContext,
    *,
    max_output_tokens: int | None = None,
    max_cost_usd: float | None = None,
) -> PipelineResult:
    """Compile prose to OCTAVE, validate, retry once, or abort.

    Args:
        working_dir: Project root (for token lookups in the gate).
        intake_context: Stage-1 output (JIT prompt + corpus + prose).
        max_output_tokens: Forwarded to the Stage-2 compiler cost cap.
        max_cost_usd: Forwarded to the Stage-2 compiler cost cap.

    Returns:
        :class:`PipelineResult`. On success ``ok=True`` with the validated
        OCTAVE + ValidationResult. On abort ``ok=False`` with structured
        ``validation_errors`` — and, by construction, ZERO filesystem writes and
        ZERO linker calls.
    """
    ctx = intake_context
    last_metrics: CompileMetrics = {
        "tokens": 0,
        "cost": 0.0,
        "model": "",
        "cost_is_estimate": True,
    }
    last_errors: list[str] = []

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        compiled = await compile_prose_to_octave(
            ctx, max_output_tokens=max_output_tokens, max_cost_usd=max_cost_usd
        )
        last_metrics = compiled["metrics"]

        if not compiled["ok"] or not compiled["octave"]:
            # Stage-2 itself failed (auth/transport/cost-cap/empty). Surface the
            # compile error and abort without touching the validator or disk.
            err = compiled["error"] or "Stage-2 compile failed with no output."
            return {
                "ok": False,
                "octave": None,
                "validation": None,
                "validation_errors": [err],
                "metrics": last_metrics,
                "attempts": attempt,
            }

        octave = compiled["octave"]
        passed, regex_result, errors = _gate(working_dir, octave)
        if passed:
            return {
                "ok": True,
                "octave": octave,
                "validation": regex_result,
                "validation_errors": [],
                "metrics": last_metrics,
                "attempts": attempt,
            }

        last_errors = errors
        if attempt < _MAX_ATTEMPTS:
            # Informed retry: append the validation errors to the prompt.
            ctx = _augment_prompt_with_errors(ctx, errors)

    # Exhausted attempts: ABORT. No write, no linker (structural invariant).
    return {
        "ok": False,
        "octave": None,
        "validation": None,
        "validation_errors": last_errors,
        "metrics": last_metrics,
        "attempts": _MAX_ATTEMPTS,
    }


def _intake_failure_result(pipeline: PipelineResult, dry_run: bool) -> dict[str, Any]:
    """Project an aborting PipelineResult into the I4 submit_governance shape."""
    return {
        "success": False,
        "token": None,
        "card_type": None,
        "target_path": None,
        "branch": None,
        "pr_url": None,
        "validation_errors": pipeline["validation_errors"],
        "octave_validation": None,
        "metrics": pipeline["metrics"],
        "dry_run": dry_run,
    }


async def run_intake_to_pr(
    working_dir: Path,
    intake_context: IntakeContext,
    *,
    dry_run: bool = False,
    max_output_tokens: int | None = None,
    max_cost_usd: float | None = None,
) -> dict[str, Any]:
    """Stage 3 + Stage 4: validate prose->OCTAVE, then open a PR via the linker.

    Runs the validate->retry->abort pipeline (Stage 3). On success the validated
    OCTAVE + ValidationResult are passed into the EXISTING ``run_linker``
    (Stage 4: branch->write->commit->PR). On abort, returns the structured
    failure and NEVER calls the linker — re-asserting hallucination immunity at
    the integration seam.

    Human Primacy (PROD::I3): ``run_linker`` only opens a PR; it never merges and
    never commits to main. No new git code is introduced here — the blocking
    linker call is offloaded to the default executor (mirroring
    ``submit_governance``).

    Returns the I4-conformant submit_governance dict, extended with ``metrics``
    and (issue #77) an additive ``octave`` field carrying the authored OCTAVE.
    Prose mode generates the OCTAVE internally; surfacing it here lets the
    Stage-5 analysis-tier semantic reviewer read exactly the record that was
    PR'd. The field is ``None`` on the abort path (no authored OCTAVE exists).
    """
    pipeline = await run_intake_pipeline(
        working_dir,
        intake_context,
        max_output_tokens=max_output_tokens,
        max_cost_usd=max_cost_usd,
    )

    if not pipeline["ok"] or pipeline["octave"] is None or pipeline["validation"] is None:
        return _intake_failure_result(pipeline, dry_run)

    loop = asyncio.get_running_loop()
    linker_fn = partial(
        run_linker,
        working_dir=working_dir,
        validation=pipeline["validation"],
        octave_content=pipeline["octave"],
        dry_run=dry_run,
    )
    linker_output = await loop.run_in_executor(None, linker_fn)

    linker_error = linker_output.get("error")
    return {
        "success": linker_error is None,
        "token": linker_output.get("token"),
        "card_type": linker_output.get("card_type"),
        "target_path": linker_output.get("target_path"),
        "branch": linker_output.get("branch"),
        "pr_url": linker_output.get("pr_url"),
        "validation_errors": [linker_error] if linker_error else [],
        "octave_validation": None,
        # Surface the authored OCTAVE so the Stage-5 reviewer can read the exact
        # record that was PR'd (issue #77). Additive; ``None`` on the abort path.
        "octave": pipeline["octave"],
        "metrics": pipeline["metrics"],
        "dry_run": dry_run,
    }
