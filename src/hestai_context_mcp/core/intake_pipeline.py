"""Stage-3 GATE: validate -> retry-once -> abort pipeline (RFC #53 Gate C, T3).

Prose mode writes a DECISION_RECORD as quoted YAML (HO-RECORDS-YAML-DEFAULT-20261031)
through the content-mode YAML seam, and every compiled record passes the prose
fidelity guard (issue #195, HO-PROSE-FIDELITY-GUARD-195-20261101) after Gate A.

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
import logging
import re
import unicodedata
from functools import partial
from pathlib import Path
from typing import Any, TypedDict

from hestai_context_mcp.core.agent_readable_governance_parser import (
    collect_topic_blocks,
    encode_yaml_scalar,
    is_yaml_front_matter,
    parse_decision_record,
    read_octave_fields,
)
from hestai_context_mcp.core.intake_compiler import (
    CompileMetrics,
    compile_prose_to_octave,
)
from hestai_context_mcp.ports.octave_validator import (
    UnavailableOctaveValidator,
    fail_closed_error_message,
    get_octave_validator,
)
from hestai_context_mcp.tools.governance.intake_context import IntakeContext
from hestai_context_mcp.tools.governance.linker import _stamp_human_adr_ref, run_linker
from hestai_context_mcp.tools.governance.type_checker import (
    ValidationResult,
    validate_octave_content,
    validate_record_content,
)

logger = logging.getLogger(__name__)


def resolve_require_real_validation(working_dir: str | None = None) -> bool:
    """Module-level seam over the adapter's fail-closed flag resolver (#108.4).

    DIP boundary (enforced by ``tests/unit/test_source_invariants.py``): this
    ``core`` module must not import ``adapters`` at module load. The adapter is
    reached via a LAZY import inside this wrapper (composition-root pattern,
    mirroring ``intake_compiler.build_default_ai_client``). Tests monkeypatch
    this symbol on the module to inject the policy; production resolves it via
    the lazy import on each call.
    """
    from hestai_context_mcp.adapters.ai_config import (
        resolve_require_real_validation as _resolve,
    )

    return _resolve(working_dir)


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
        real_validation_available: #108.4 — whether Gate B's real OCTAVE
            validator actually ran (False when the ``validation`` extra is
            absent and the pass degraded to regex-only). Surfaced so the Stage-4
            seam can apply the loud signal + opt-in fail-closed policy.
    """

    ok: bool
    octave: str | None
    validation: ValidationResult | None
    validation_errors: list[str]
    metrics: CompileMetrics
    attempts: int
    real_validation_available: bool


# --- Prose-mode fidelity guard (issue #195, HO-PROSE-FIDELITY-GUARD-195-20261101) ---
# Compares the compiled record with the SOURCE prose. Regex/scan only (North Star §4),
# stdlib only (PROD::I6), fail-loud, never auto-fix: a failure is an informed-retry
# error like any Gate A error, and aborts once the shared budget is spent.
_MIN_QUOTE_CHARS = 8
_DOUBLE_SPAN_RE = re.compile(r'"([^"\n]*)"|“([^”\n]*)”')
# stdlib ``unicodedata`` has no Script property, so a letter's script is read from the
# first word of its Unicode name ("ARABIC LETTER BEH" -> ARABIC; any name containing
# LATIN -> LATIN). Always allowed: Latin, and the name words of Common letters
# (letterlike and mathematical letters, modifier letters). Inherited characters are
# combining marks, not letters, so they are never checked.
_ALWAYS_ALLOWED_SCRIPTS = frozenset(
    {
        "LATIN",
        *("MATHEMATICAL", "MODIFIER", "DOUBLE-STRUCK", "SCRIPT", "BLACK-LETTER", "PLANCK"),
        *("TURNED", "FEMININE", "MASCULINE", "MICRO", "CARON", "EULER", "KELVIN"),
        *("ANGSTROM", "INFORMATION", "ROMAN", "VERTICAL", "ALEF", "BET", "GIMEL", "DALET"),
        "KATAKANA-HIRAGANA",
    }
)
_PROSE_YAML_ERROR = (
    "PROSE_MODE_YAML: prose mode writes a DECISION_RECORD as quoted YAML (first line ---), "
    "never OCTAVE (HO-RECORDS-YAML-DEFAULT-20261031)."
)


def _quoted_spans(text: str) -> list[str]:
    """Text between double quotes (straight or curly) and between DELIMITING single quotes.

    A single quote opens a span only after whitespace, a line start or opening
    punctuation, and closes it only before whitespace, a line end or punctuation, so an
    apostrophe (``don't``, ``the team's``) never opens or closes one. Spans never cross
    a newline.
    """
    spans = [m.group(1) or m.group(2) or "" for m in _DOUBLE_SPAN_RE.finditer(text)]
    i, end = 0, len(text)
    while i < end:
        before = text[i - 1] if i else " "
        if text[i] in "'‘" and (before.isspace() or unicodedata.category(before) in ("Ps", "Pi")):
            for j in range(i + 2, end):
                if text[j] == "\n":
                    break
                after = text[j + 1] if j + 1 < end else " "
                if text[j] in "'’" and (after.isspace() or unicodedata.category(after)[0] == "P"):
                    spans.append(text[i + 1 : j])
                    i = j
                    break
        i += 1
    return spans


def _script(char: str) -> str:
    words = unicodedata.name(char, "").split()
    return "LATIN" if "LATIN" in words else (words[0] if words else "UNNAMED")


def _record_values(record: str) -> list[tuple[str, str]]:
    """Every decoded field value of a compiled record as ``(label, value)``, blocks included."""
    pairs: list[tuple[str, str]] = []
    if is_yaml_front_matter(record):
        parsed = parse_decision_record(record)
        pairs += [(k.upper(), v) for k, v in parsed.items() if isinstance(v, str)]
        pairs += list(parsed["fields"].items())
    else:
        fields, _reject = read_octave_fields(record)
        for field in fields:
            value = field.value
            quoted = len(value) >= 2 and value[0] == value[-1] == '"'
            pairs.append((field.key, value[1:-1] if quoted else value))
    blocks = collect_topic_blocks(record)
    for block, entries in (("CURRENT", blocks["current"]), ("RULINGS", blocks["rulings"])):
        for entry in entries:
            pairs += [
                (f"{block} {entry['id']} {key.upper()}", value)
                for key, value in entry.items()
                if key != "id" and isinstance(value, str)
            ]
    return pairs


def _fidelity_errors(record: str, prose: str) -> list[str]:
    """The four-rule fidelity guard's rules (1)-(3); rule (4) is the caller's retry loop."""
    errors: list[str] = []
    values = _record_values(record)
    # (1) every quoted span of 8+ characters in the prose survives byte-identical.
    for span in dict.fromkeys(_quoted_spans(prose)):
        if len(span) >= _MIN_QUOTE_CHARS and not any(span in value for _, value in values):
            errors.append(
                f'FIDELITY quote_not_preserved: the prose quotes "{span}" but no field value '
                "carries it byte-identical; copy quoted text exactly."
            )
    # (2) letters only from the prose's scripts, or Latin / Common / Inherited.
    allowed = _ALWAYS_ALLOWED_SCRIPTS | {_script(c) for c in prose if c.isalpha()}
    for number, line in enumerate(record.split("\n"), start=1):
        foreign = [c for c in line if c.isalpha() and _script(c) not in allowed]
        if foreign:
            scripts = ", ".join(sorted({_script(c) for c in foreign}))
            errors.append(
                f'FIDELITY non_source_script: line {number} has {scripts} letters "'
                f'{"".join(foreign)}" that the prose never uses; write only in its scripts.'
            )
    # (3) VERBATIM whole value; OPERATOR_RULING and *_VERBATIM quoted spans (any length).
    for label, value in values:
        name = label.rsplit(" ", 1)[-1]
        if name == "VERBATIM" and value not in prose:
            errors.append(
                f'FIDELITY verbatim_not_in_prose: {label} "{value}" is not a byte-exact '
                "substring of the prose."
            )
        elif name == "OPERATOR_RULING" or name.endswith("_VERBATIM"):
            errors += [
                f'FIDELITY quote_not_in_prose: {label} quotes "{span}", which is not a '
                "byte-exact substring of the prose."
                for span in _quoted_spans(value)
                if span not in prose
            ]
    return errors


def _gate(
    working_dir: Path, record: str, prose: str
) -> tuple[bool, ValidationResult, list[str], bool]:
    """Run Gate A, then the prose fidelity guard, then Gate B (OCTAVE only).

    Returns ``(passed, regex_result, errors, real_validation_available)``. The
    last element (#108.4) reports whether Gate B's real validator is actually
    available. A regex-fail short-circuit still reports backend availability
    accurately without running full validation.

    A quoted-YAML record (first line ``---``) is judged by the Gate A YAML branch
    through the same seam content mode uses (``validate_record_content``); Gate B is
    OCTAVE-only and is not applied to it (ADR-RFC-ARCH-004 §1.1). A DECISION_RECORD
    compiled as OCTAVE is rejected: prose mode writes decision records as quoted YAML.
    """
    # Gate A (regex) carries the §4.1 #13 reasoning-density guard (≤40 words,
    # no newline on DECISION/BECAUSE), so the verbosity rule is enforced HERE,
    # by the SAME shared invariant the octave_content path uses — one source of
    # truth across all submission paths (#108-item-2 unification). A verbose
    # record therefore fails Gate A directly; the failure flows through the same
    # informed-retry/abort path as any schema failure (no separate Gate-C lint).
    is_yaml = is_yaml_front_matter(record)
    if is_yaml:
        regex_result = validate_record_content(working_dir, record)
    else:
        regex_result = validate_octave_content(working_dir, record)
    octave_validator = get_octave_validator()
    real_validation_available = not isinstance(
        octave_validator,
        UnavailableOctaveValidator,
    )
    if not regex_result.valid:
        return False, regex_result, list(regex_result.errors), real_validation_available

    # Third check (#195): the fidelity guard, after Gate A, against the source prose.
    errors = _fidelity_errors(record, prose)
    if not is_yaml and regex_result.card_type == "DECISION_RECORD":
        errors.insert(0, _PROSE_YAML_ERROR)
    if errors or is_yaml:
        return not errors, regex_result, errors, real_validation_available

    octave_result = octave_validator.validate(record)
    if not octave_result.ok:
        errors = [
            f"[{e.get('code', '')}] {e.get('message', '')}".strip() for e in octave_result.errors
        ]
        return False, regex_result, errors, octave_result.available

    return True, regex_result, [], octave_result.available


def _augment_prompt_with_errors(ctx: IntakeContext, errors: list[str]) -> IntakeContext:
    """Return a new IntakeContext whose prompt appends the validation errors.

    The retry must be *informed*: the second attempt sees exactly why the first
    output was rejected so it can correct it.
    """
    error_block = "\n".join(f"- {e}" for e in errors)
    augmented = (
        f"{ctx.prompt}\n"
        "BEGIN_VALIDATION_FEEDBACK\n"
        "The previous attempt FAILED validation with these errors. "
        "Produce a corrected single record that resolves ALL of them:\n"
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
    # #108.4: carry Gate-B availability from the last attempt that reached Gate B.
    # Defaults True (no degrade observed) for compile-fail aborts that never
    # reach the validator.
    last_available = True

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        compiled = await compile_prose_to_octave(
            ctx,
            max_output_tokens=max_output_tokens,
            max_cost_usd=max_cost_usd,
            working_dir=str(working_dir),
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
                "real_validation_available": last_available,
            }

        octave = compiled["octave"]
        passed, regex_result, errors, last_available = _gate(
            working_dir, octave, intake_context.prose_input
        )
        if passed:
            return {
                "ok": True,
                # A YAML record continues as its canonical bytes (the content-mode
                # write path, ADR-RFC-ARCH-004 §1.1); OCTAVE continues unchanged.
                "octave": regex_result.canonical_content or octave,
                "validation": regex_result,
                "validation_errors": [],
                "metrics": last_metrics,
                "attempts": attempt,
                "real_validation_available": last_available,
            }

        last_errors = errors
        if attempt < _MAX_ATTEMPTS:
            # Informed retry: append the validation errors to the prompt.
            ctx = _augment_prompt_with_errors(ctx, errors)

    # Exhausted attempts: ABORT loudly. No write, no linker (structural invariant).
    logger.warning(
        "Prose intake aborted after %d attempts; last errors: %s",
        _MAX_ATTEMPTS,
        "; ".join(last_errors),
    )
    return {
        "ok": False,
        "octave": None,
        "validation": None,
        "validation_errors": last_errors,
        "metrics": last_metrics,
        "attempts": _MAX_ATTEMPTS,
        "real_validation_available": last_available,
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
        "in_flight": None,
        "in_flight_branches": [],
        "in_flight_pr_urls": {},
        "in_flight_pr_lookup_error": None,
        "validation_errors": pipeline["validation_errors"],
        "octave_validation": None,
        "real_validation_available": pipeline["real_validation_available"],
        "metrics": pipeline["metrics"],
        "dry_run": dry_run,
    }


def _fail_closed_result(pipeline: PipelineResult, dry_run: bool) -> dict[str, Any]:
    """#108.4 Option C: hard-block shape when real validation is required but absent.

    Mirrors the abort shape (no token/branch/pr_url, NEVER calls the linker) with
    the structured fail-closed error and the loud ``real_validation_available``
    signal. The authored OCTAVE is surfaced for parity with the success path.
    """
    return {
        "success": False,
        "token": None,
        "card_type": None,
        "target_path": None,
        "branch": None,
        "pr_url": None,
        "in_flight": None,
        "in_flight_branches": [],
        "in_flight_pr_urls": {},
        "in_flight_pr_lookup_error": None,
        "validation_errors": [fail_closed_error_message()],
        "octave_validation": None,
        "real_validation_available": False,
        "octave": pipeline["octave"],
        "metrics": pipeline["metrics"],
        "dry_run": dry_run,
    }


def _stamp_yaml_human_adr_ref(record: str, token: str) -> str:
    """Return a canonical YAML ``record`` with ``human_adr_ref`` set to ``token`` (#112).

    The YAML counterpart of the linker's OCTAVE stamp: any existing top-level
    ``human_adr_ref`` line is dropped and one is inserted after the opening fence;
    the caller re-validates, and Gate A re-emits the canonical bytes (key order).
    Unchanged when there is no closing fence (Gate A then rejects it).
    """
    lines = record.split("\n")
    close = next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
    if close is None:
        return record
    kept = [line for line in lines[1:close] if not line.startswith("human_adr_ref:")]
    stamp = f"human_adr_ref: {encode_yaml_scalar(token)}"
    return "\n".join([lines[0], stamp, *kept, *lines[close:]])


async def run_intake_to_pr(
    working_dir: Path,
    intake_context: IntakeContext,
    *,
    dry_run: bool = False,
    max_output_tokens: int | None = None,
    max_cost_usd: float | None = None,
    write_adr: bool = False,
) -> dict[str, Any]:
    """Stage 3 + Stage 4: validate prose->OCTAVE, then open a PR via the linker.

    Runs the validate->retry->abort pipeline (Stage 3). On success the validated
    OCTAVE + ValidationResult are passed into the EXISTING ``run_linker``
    (Stage 4: branch->write->commit->PR). On abort, returns the structured
    failure and NEVER calls the linker — re-asserting hallucination immunity at
    the integration seam.

    Two-birds (#112): when ``write_adr`` is True, after Stage 3 succeeds (the
    TOKEN is now known) the engine DETERMINISTICALLY stamps
    ``HUMAN_ADR_REF::<token>`` into the AGR's META block, RE-VALIDATES that the
    stamped AGR still passes Gate A (token-form #11 — no fs resolution), and
    passes both the stamped OCTAVE and the VERBATIM ``intake_context.prose_input``
    to the linker, which dumb-writes ``docs/adr/<token>.md`` alongside the AGR in
    ONE branch/commit/PR. The stamp is NOT trusted to the AI (it is engine-side,
    post-validation) so the link is deterministic.

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

    # --- #108.4: Gate-B availability policy on the PROSE path (shared Gate B) ---
    # Option L (unconditional): surface ``real_validation_available`` top-level
    # (below) and log at WARNING when degraded. Option C (opt-in, default OFF):
    # when real validation is REQUIRED but Gate B was unavailable, hard-block
    # BEFORE the linker (no branch, no PR), mirroring the octave_content path.
    real_validation_available = pipeline["real_validation_available"]
    if not real_validation_available:
        logger.warning(
            "Gate B real OCTAVE validation unavailable (the 'validation' extra is "
            "not installed); proceeding on regex Gate A only unless fail-closed is "
            "required."
        )
        loop = asyncio.get_running_loop()
        require_real_validation = await loop.run_in_executor(
            None,
            partial(resolve_require_real_validation, working_dir=str(working_dir)),
        )
        if require_real_validation:
            return _fail_closed_result(pipeline, dry_run)

    # --- Two-birds (#112): deterministic HUMAN_ADR_REF stamp + ADR prose ---
    # The validated OCTAVE and TOKEN are known here. When write_adr is set we
    # stamp the AGR with HUMAN_ADR_REF::<token> (engine-side, NOT AI-echoed) and
    # RE-VALIDATE that the stamped record still passes Gate A before the linker
    # writes it — so a stamp can never smuggle an invalid record to disk. The
    # verbatim prose becomes the ADR doc the linker dumb-writes alongside.
    octave_to_link = pipeline["octave"]
    adr_prose: str | None = None
    if write_adr:
        token = pipeline["validation"].token or ""
        if pipeline["validation"].syntax == "yaml":
            stamped = _stamp_yaml_human_adr_ref(octave_to_link, token)
            restamped_validation = validate_record_content(working_dir, stamped)
            stamped = restamped_validation.canonical_content or stamped
        else:
            stamped = _stamp_human_adr_ref(octave_to_link, token)
            restamped_validation = validate_octave_content(working_dir, stamped)
        if not restamped_validation.valid:
            # The stamp broke Gate A (should be impossible for token-form #11):
            # abort BEFORE the linker — no write, no PR. Hallucination immunity.
            return {
                "success": False,
                "token": token,
                "card_type": pipeline["validation"].card_type,
                "target_path": None,
                "adr_target_path": None,
                "branch": None,
                "pr_url": None,
                "in_flight": None,
                "in_flight_branches": [],
                "in_flight_pr_urls": {},
                "in_flight_pr_lookup_error": None,
                "validation_errors": [
                    "HUMAN_ADR_REF stamp failed Gate-A re-validation: "
                    + "; ".join(restamped_validation.errors)
                ],
                "octave_validation": None,
                "real_validation_available": real_validation_available,
                "octave": stamped,
                "metrics": pipeline["metrics"],
                "dry_run": dry_run,
            }
        octave_to_link = stamped
        adr_prose = intake_context.prose_input

    loop = asyncio.get_running_loop()
    linker_fn = partial(
        run_linker,
        working_dir=working_dir,
        validation=pipeline["validation"],
        octave_content=octave_to_link,
        dry_run=dry_run,
        adr_prose=adr_prose,
    )
    linker_output = await loop.run_in_executor(None, linker_fn)

    linker_error = linker_output.get("error")
    return {
        "success": linker_error is None,
        "token": linker_output.get("token"),
        "card_type": linker_output.get("card_type"),
        "target_path": linker_output.get("target_path"),
        "adr_target_path": linker_output.get("adr_target_path"),
        "branch": linker_output.get("branch"),
        "pr_url": linker_output.get("pr_url"),
        "in_flight": linker_output.get("in_flight"),
        "in_flight_branches": linker_output.get("in_flight_branches", []),
        "in_flight_pr_urls": linker_output.get("in_flight_pr_urls", {}),
        "in_flight_pr_lookup_error": linker_output.get("in_flight_pr_lookup_error"),
        "validation_errors": [linker_error] if linker_error else [],
        "octave_validation": None,
        "real_validation_available": real_validation_available,
        # Surface the authored OCTAVE so the Stage-5 reviewer can read the exact
        # record that was PR'd (issue #77). Additive; ``None`` on the abort path.
        # When write_adr stamped the record, this is the STAMPED OCTAVE actually
        # written (so the reviewer reads exactly what was PR'd).
        "octave": octave_to_link,
        "metrics": pipeline["metrics"],
        "dry_run": dry_run,
    }
