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
import logging
import re
from functools import partial
from typing import Any

from hestai_context_mcp.adapters.ai_config import resolve_require_real_validation
from hestai_context_mcp.core.governance_reviewer import review_governance
from hestai_context_mcp.core.intake_pipeline import run_intake_to_pr
from hestai_context_mcp.ports.octave_validator import (
    OctaveValidationResult,
    fail_closed_error_message,
    get_octave_validator,
)
from hestai_context_mcp.tools.clock_in import validate_working_dir
from hestai_context_mcp.tools.governance.intake_context import assemble_intake_context
from hestai_context_mcp.tools.governance.linker import run_linker
from hestai_context_mcp.tools.governance.type_checker import validate_octave_content
from hestai_context_mcp.tools.submit_review import submit_review

logger = logging.getLogger(__name__)

# review_governance and submit_review are imported as module globals (not via
# attribute paths) so the Stage-5 seam is monkeypatchable in tests, mirroring
# the run_intake_to_pr patch point used by the prose-mode tests. The Stage-5
# integration NEVER auto-merges — it posts an advisory/assistive SR verdict and
# the human owns the merge (Human Primacy, PROD::I3).

# review_governance verdict -> review-gate verdict. Only a clean APPROVED clears
# the gate; CONCERNS and BLOCKED both route the record to the human as BLOCKED.
_GATE_VERDICT_MAP = {"APPROVED": "APPROVED", "CONCERNS": "BLOCKED", "BLOCKED": "BLOCKED"}

# Parse "owner/name" + pr_number from a GitHub PR URL
# (e.g. https://github.com/owner/name/pull/123).
_PR_URL_RE = re.compile(r"github\.com/(?P<owner>[^/]+)/(?P<name>[^/]+)/pull/(?P<number>\d+)")


def _empty_result(
    dry_run: bool,
    errors: list[str],
    octave_validation: dict[str, Any] | None = None,
    *,
    real_validation_available: bool = True,
    adr_target_path: str | None = None,
) -> dict[str, Any]:
    """Return the I4-conformant failure shape with all fields present.

    ``real_validation_available`` (#108.4 Option L) is an EXPLICIT top-level
    signal so a fail-soft Gate-B degrade is never hidden inside
    ``octave_validation.warnings``. It defaults True because most failures are
    unrelated to Gate-B availability; the Gate-B paths pass it explicitly.
    """
    return {
        "success": False,
        "token": None,
        "card_type": None,
        "target_path": None,
        "adr_target_path": adr_target_path,
        "branch": None,
        "pr_url": None,
        "validation_errors": errors,
        "octave_validation": octave_validation,
        "real_validation_available": real_validation_available,
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


def _compose_sr_assessment(assessment: str, concerns: list[str]) -> str:
    """Build the SR comment body: the semantic assessment plus any concerns."""
    body = assessment.strip() or "No assessment text returned."
    if concerns:
        joined = "; ".join(c.strip() for c in concerns if c.strip())
        if joined:
            body = f"{body}\n\nConcerns: {joined}"
    return body


async def _run_semantic_review(
    octave_content: str, pr_url: str, working_dir: str | None = None
) -> dict[str, Any]:
    """Stage 5: analysis-tier scoped-semantic review + SR post (issue #77).

    Runs ``review_governance(octave_content, tier="analysis")`` over the authored
    OCTAVE (a different tier — and therefore a different model — from the
    default-tier author, giving reviewer independence), maps the verdict onto
    the review gate (APPROVED clears; CONCERNS|BLOCKED route to the human as
    BLOCKED), and posts an ``SR`` verdict on ``pr_url`` via the EXISTING
    ``submit_review`` post path (no gh/format logic is duplicated here).

    FAIL-SOFT + NON-DESTRUCTIVE: every failure mode (no analysis key, transport,
    unparseable verdict, unparseable PR URL, posting error) is caught and
    surfaced under ``error``; the PR is left open and successful and is NEVER
    undone. The verdict is advisory/assistive — this function NEVER merges.

    Returns the structured ``semantic_review`` block (PROD::I4).
    """
    try:
        review = await review_governance(octave_content, tier="analysis", working_dir=working_dir)
    except Exception as exc:  # noqa: BLE001 — fail-soft: any reviewer error is recorded.
        return {"posted": False, "error": f"semantic review failed: {exc}"}

    review_verdict = review.get("verdict", "")
    gate_verdict = _GATE_VERDICT_MAP.get(review_verdict, "BLOCKED")
    reviewer_model = review.get("metrics", {}).get("model", "")
    concerns = review.get("concerns", []) or []

    base: dict[str, Any] = {
        "review_verdict": review_verdict,
        "gate_verdict": gate_verdict,
        "reviewer_model": reviewer_model,
        "tier": "analysis",
        "concerns": concerns,
    }

    match = _PR_URL_RE.search(pr_url or "")
    if match is None:
        return {**base, "posted": False, "error": f"could not parse PR URL: {pr_url!r}"}

    repo = f"{match.group('owner')}/{match.group('name')}"
    pr_number = int(match.group("number"))
    assessment = _compose_sr_assessment(review.get("assessment", ""), concerns)

    try:
        post = submit_review(
            repo=repo,
            pr_number=pr_number,
            role="SR",
            verdict=gate_verdict,
            assessment=assessment,
            model_annotation=reviewer_model,
        )
    except Exception as exc:  # noqa: BLE001 — fail-soft: posting must not undo the PR.
        return {**base, "posted": False, "error": f"posting SR verdict failed: {exc}"}

    if post.get("status") != "ok":
        error = post.get("validation", {}).get("error", "submit_review returned an error status")
        return {**base, "posted": False, "error": error, "post_status": post.get("status")}

    return {**base, "posted": True, "comment_url": post.get("comment_url")}


async def submit_governance(
    working_dir: str,
    octave_content: str | None = None,
    prose_input: str | None = None,
    dry_run: bool = False,
    review: bool = True,
    write_adr: bool = False,
) -> dict[str, Any]:
    """Submit a governance artifact via OCTAVE content OR prose intent.

    EXACTLY ONE of ``octave_content`` / ``prose_input`` must be non-None.

    ``write_adr`` (two-birds, #112) is PROSE-ONLY. When True (with
    ``prose_input``) the natural-language prose IS the ADR source: the linker
    dumb-writes the VERBATIM prose to ``docs/adr/<token>.md`` and the condensed
    AGR carries a deterministically-stamped ``HUMAN_ADR_REF::<token>`` — depth +
    condensed AGR in ONE call, ONE PR. ``write_adr`` with ``octave_content`` (or
    no ``prose_input``) is a structured error: there is no natural prose to dump,
    so ``octave_content`` stays AGR-only. Default False = AGR-only, byte-stable.

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
        review: If True (default), run the Stage-5 analysis-tier scoped-semantic
                review and post an ``SR`` verdict — but ONLY when a real PR was
                opened (``pr_url`` present and NOT ``dry_run``). Set False to
                skip Stage 5. The Stage-5 step is additive, fail-soft, and never
                auto-merges (Human Primacy, PROD::I3).

    Returns:
        I4-conformant structured dict (see field docs in the module). In
        ``prose_input`` mode the dict additionally contains ``metrics``. When
        Stage 5 runs (real PR + ``review=True``) the dict additionally contains
        an additive ``semantic_review`` block; the octave_content return is
        byte-stable vs post-#70 main beyond that single additive field, and
        Stage 5 is skipped (no ``semantic_review`` key) on dry_run / review=False
        / no-PR paths.
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

    # --- write_adr is PROSE-ONLY (#112) ---
    # Exactly-one is satisfied here; prose_input is None ⇒ octave_content mode,
    # which has no natural prose to dump verbatim into an ADR doc. Reject loudly
    # rather than silently ignore the flag.
    if write_adr and prose_input is None:
        return _empty_result(
            dry_run,
            [
                "ADR+AGR (write_adr=True) requires prose_input; octave_content is "
                "AGR-only. Re-submit the decision as prose_input to author both the "
                "verbatim ADR doc and the condensed AGR in one call."
            ],
        )

    if prose_input is not None:
        return await _submit_prose_input(working_dir, prose_input, dry_run, review, write_adr)

    # The EXACTLY-ONE-OF guard above guarantees octave_content is non-None here.
    assert octave_content is not None
    return await _submit_octave_content(working_dir, octave_content, dry_run, review)


async def _maybe_review(
    result: dict[str, Any],
    octave_content: str | None,
    dry_run: bool,
    review: bool,
    working_dir: str | None = None,
) -> dict[str, Any]:
    """Run Stage 5 over a successful real PR, attaching ``semantic_review``.

    Guard (active ONLY when a real PR was opened): ``review`` is True, NOT a
    ``dry_run``, the call ``success``, a ``pr_url`` is present, and an authored
    OCTAVE is available. Otherwise the result is returned unchanged (no
    ``semantic_review`` key) — preserving the byte-stable shape on skip paths.

    Mutates and returns ``result`` (additive ``semantic_review`` field only).
    """
    if not review or dry_run:
        return result
    pr_url = result.get("pr_url")
    if not result.get("success") or not pr_url or not octave_content:
        return result

    result["semantic_review"] = await _run_semantic_review(
        octave_content, pr_url, working_dir=working_dir
    )
    return result


async def _submit_prose_input(
    working_dir: str,
    prose_input: str,
    dry_run: bool,
    review: bool,
    write_adr: bool = False,
) -> dict[str, Any]:
    """Gate C prose mode: Stage 1 assemble -> Stage 2+3+4 via run_intake_to_pr.

    Validates working_dir first (PROD I4 structured failure on bad path), then
    assembles the Stage-1 context and delegates to the Stage 2->4 composition,
    which rejoins the same validate->link tail as the octave_content path. On a
    successful real PR, Stage 5 reviews the GENERATED OCTAVE threaded out of
    ``run_intake_to_pr`` (issue #77).

    ``write_adr`` (#112) is forwarded to ``run_intake_to_pr`` so the two-birds
    path dumb-writes the verbatim ADR doc + stamps the AGR's HUMAN_ADR_REF.
    """
    loop = asyncio.get_running_loop()
    try:
        wd = await loop.run_in_executor(None, validate_working_dir, working_dir)
    except (ValueError, FileNotFoundError) as exc:
        return _empty_result(dry_run, [str(exc)])

    intake_context = await loop.run_in_executor(None, assemble_intake_context, wd, prose_input)
    result = await run_intake_to_pr(wd, intake_context, dry_run=dry_run, write_adr=write_adr)
    return await _maybe_review(result, result.get("octave"), dry_run, review, working_dir=str(wd))


async def _submit_octave_content(
    working_dir: str,
    octave_content: str,
    dry_run: bool,
    review: bool,
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
    real_validation_available = octave_result.available

    if not octave_result.ok:
        # Real validation failed: structured error, no PR / no write.
        return _empty_result(
            dry_run,
            _octave_errors_to_strings(octave_result),
            octave_validation=octave_validation,
            real_validation_available=real_validation_available,
        )

    # --- #108.4: Gate-B availability policy (Option L loud + Option C opt-in) ---
    # Option L (unconditional): the degrade is surfaced as the top-level
    # ``real_validation_available`` signal below, and logged at WARNING here, so
    # it can never hide inside ``octave_validation.warnings``.
    # Option C (opt-in, default OFF): when the deployment REQUIRES real validation
    # and it is unavailable, hard-block (no linker / no PR) with a structured
    # PROD-I4 error naming the missing extra. Default OFF keeps the octave_content
    # path byte-stable apart from the additive signal.
    if not real_validation_available:
        logger.warning(
            "Gate B real OCTAVE validation unavailable (the 'validation' extra is "
            "not installed); proceeding on regex Gate A only unless fail-closed is "
            "required."
        )
        require_real_validation = await loop.run_in_executor(
            None,
            partial(resolve_require_real_validation, working_dir=str(wd)),
        )
        if require_real_validation:
            return _empty_result(
                dry_run,
                [fail_closed_error_message()],
                octave_validation=octave_validation,
                real_validation_available=False,
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

    result = {
        "success": success,
        "token": linker_output.get("token"),
        "card_type": linker_output.get("card_type"),
        "target_path": linker_output.get("target_path"),
        "branch": linker_output.get("branch"),
        "pr_url": linker_output.get("pr_url"),
        "validation_errors": errors,
        "octave_validation": octave_validation,
        "real_validation_available": real_validation_available,
        "dry_run": dry_run,
    }
    return await _maybe_review(result, octave_content, dry_run, review, working_dir=str(wd))
