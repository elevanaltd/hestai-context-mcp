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
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any, TypedDict

from hestai_context_mcp.core.agent_readable_governance_parser import (
    YamlSyntaxError,
    collect_topic_blocks,
    decode_yaml_scalar,
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
# A two-digit elision ('90s, '24) is an apostrophe, never an opening quote.
_ELISION_RE = re.compile(r"\d\d s? (?![\w'’])", re.X)
_WIDTH_WORDS = frozenset({"HALFWIDTH", "FULLWIDTH"})
_PROSE_YAML_ERROR = (
    "PROSE_MODE_YAML: prose mode writes a DECISION_RECORD as quoted YAML (first line ---), "
    "never OCTAVE (HO-RECORDS-YAML-DEFAULT-20261031)."
)


def _quoted_spans(text: str) -> list[str]:
    """Text between double quotes (straight or curly) and between DELIMITING single quotes.

    A single quote opens a span only when it does not follow a letter, digit or
    combining mark (so after whitespace, a line start, punctuation or a symbol such as
    ``:`` ``=`` ``(``), is followed by non-whitespace, and is not a two-digit elision
    (``'90s``). It closes a span only when it follows non-whitespace and is followed by
    whitespace, the end of the text, or anything but a letter, digit or mark. So an
    apostrophe (``don't``, ``the team's``, ``rock'n'roll``) never opens or closes one.
    ``''`` is an empty span. Spans nest: a quote opened inside an open span closes
    before it and never restarts it. A later plausible closer on the same line, with no
    opener in between, extends the span just closed (``'the operators' ruling must
    stand'``): every reading is guarded (HC ruling R1 on #246). Only maximal spans are
    returned, since each contains the shorter readings and inner spans. Spans never
    cross a newline. One linear pass.
    """
    spans = [m.group(1) or m.group(2) or "" for m in _DOUBLE_SPAN_RE.finditer(text)]
    stack: list[int] = []  # positions of the open single quotes, innermost last
    closed: list[tuple[int, int]] = []  # maximal closed spans, ordered by start
    extend: tuple[int, int] | None = None  # (start, depth) of the span just closed

    def _close(start: int, end: int) -> None:
        while closed and closed[-1][0] >= start:
            closed.pop()  # a shorter reading or an inner span, contained in this one
        closed.append((start, end))

    for i, char in enumerate(text):
        if char == "\n":
            stack.clear()
            extend = None
            continue
        before = text[i - 1] if i else " "
        after = text[i + 1] if i + 1 < len(text) else " "
        closes = char in "'’" and not before.isspace() and _delimits(after)
        if closes and extend is not None and extend[1] == len(stack):
            _close(extend[0], i)  # a later plausible closer of the span just closed
            if not stack:
                continue
        if closes and stack:
            start = stack.pop()
            extend = None
            if i > start + 1:  # '' is an empty span, never the opener of the next one
                _close(start, i)
                extend = (start, len(stack))
        elif (
            char in "'‘"
            and _delimits(before)
            and not after.isspace()
            and not _ELISION_RE.match(text, i + 1)
        ):
            stack.append(i)
            extend = None
    return spans + [text[start + 1 : end] for start, end in closed]


def _delimits(char: str) -> bool:
    """True unless ``char`` is a letter, digit or combining mark (part of a word)."""
    return not (char.isalnum() or unicodedata.category(char)[0] == "M")


def _script(char: str) -> str:
    """A letter's script key: its Unicode name's first word, width prefixes dropped."""
    words = [w for w in unicodedata.name(char, "").split() if w not in _WIDTH_WORDS]
    if "LATIN" in words:
        return "LATIN"
    key = words[0] if words else "UNNAMED"
    return "CJK" if key == "IDEOGRAPHIC" else key  # 々 and 〆 are Han


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
        if name == "VERBATIM" and (not value or value not in prose):
            # An empty value is a substring of any prose; it never counts as verbatim.
            errors.append(
                f'FIDELITY verbatim_not_in_prose: {label} "{value}" is empty or not a '
                "byte-exact substring of the prose."
            )
        elif name == "OPERATOR_RULING" or name.endswith("_VERBATIM"):
            spans = [span for span in _quoted_spans(value) if span]
            if not spans:  # HC ruling R2 on #246: no framing-only verbatim field
                errors.append(
                    f"FIDELITY field_lacks_quote: {label} carries no quoted span; quote "
                    "the operator's words exactly from the prose, or omit the field when "
                    "the prose has none."
                )
            errors += [
                f'FIDELITY quote_not_in_prose: {label} quotes "{span}", which is not a '
                "byte-exact substring of the prose."
                for span in spans
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
    # The YAML form is named even beside Gate A errors, so the one informed retry
    # learns it before the shared budget is spent.
    form_errors = (
        [_PROSE_YAML_ERROR] if not is_yaml and regex_result.card_type == "DECISION_RECORD" else []
    )
    if not regex_result.valid:
        errors = [*regex_result.errors, *form_errors]
        return False, regex_result, errors, real_validation_available

    # Third check (#195): the fidelity guard, after Gate A, against the source prose.
    errors = [*form_errors, *_fidelity_errors(record, prose)]
    if errors or is_yaml:
        return not errors, regex_result, errors, real_validation_available

    octave_result = octave_validator.validate(record)
    if not octave_result.ok:
        errors = [
            f"[{e.get('code', '')}] {e.get('message', '')}".strip() for e in octave_result.errors
        ]
        return False, regex_result, errors, octave_result.available

    return True, regex_result, [], octave_result.available


def _now_utc() -> datetime:
    """The pipeline clock seam (#249): tests patch this; production reads real UTC."""
    return datetime.now(UTC)


_AUTHORED_AT_KEY_RE = re.compile(r"authored_at\s*:", re.IGNORECASE)
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_full_timestamp(value: str) -> bool:
    """True when ``value`` is a full ISO-8601 timestamp (a date AND a time), not a date."""
    text = value.strip()
    if _DATE_ONLY_RE.match(text) or "T" not in text.upper():
        return False
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        datetime.fromisoformat(text)
    except ValueError:
        return False
    return True


def _operator_wrote_timestamp(line: str, prose: str) -> bool:
    """True when the ``authored_at`` ``line`` holds a full timestamp present in ``prose``.

    Literal match only (#273): a time the operator wrote in another format is not
    normalised, so it is stamped over.
    """
    try:
        value = decode_yaml_scalar(line.split(":", 1)[1].removesuffix("\r"))
    except YamlSyntaxError:
        return False
    return _is_full_timestamp(value) and value in prose


def _stamp_authored_at(record: str, authored_at: str, prose: str = "") -> str:
    """Stamp ``authored_at`` on a compiled quoted-YAML ``record`` (#249, #273).

    ADR-RFC-ARCH-004 §1.2: UTC, set once at record creation, never edited. A compiler
    cannot know the creation time, so the stamp REPLACES any ``authored_at`` it wrote;
    the one value kept is a full ISO-8601 timestamp that appears verbatim in the
    operator's ``prose`` (a value the operator actually wrote). A record with several
    ``authored_at`` keys is left alone so Gate A rejects it (no silent dedupe).
    Only a quoted-YAML record is touched, and only this one field; the TOKEN is never
    re-dated, so a TOKEN-date mismatch is left for Gate A's §1.3 check to reject. The
    caller runs Gate A on the result, which re-emits the canonical bytes (key order).
    Unchanged when there is no closing fence (Gate A then rejects it).
    """
    # A leading BOM is rejected at line 1 as invalid_key (§1.1); leave it unstamped so
    # it still fails loudly rather than being made acceptable.
    if not is_yaml_front_matter(record) or record.startswith("\ufeff"):
        return record
    lines = record.split("\n")
    # The reader's fence rule (``_is_fence_line``): ``---`` plus at most one CR.
    close = next((i for i in range(1, len(lines)) if lines[i].removesuffix("\r") == "---"), None)
    if close is None:
        return record
    eol = "\r" if lines[0].endswith("\r") else ""  # the record's own line ending
    stamp = f"authored_at: {encode_yaml_scalar(authored_at)}{eol}"
    existing = [i for i in range(1, close) if _AUTHORED_AT_KEY_RE.match(lines[i])]
    if len(existing) > 1:
        return record
    if existing:
        # Only an exact lowercase key is ours to replace; ``AUTHORED_AT:`` and other
        # spellings stay as written so Gate A rejects them (#275).
        if not lines[existing[0]].startswith("authored_at"):
            return record
        if _operator_wrote_timestamp(lines[existing[0]], prose):
            return record
        lines[existing[0]] = stamp
        return "\n".join(lines)
    return "\n".join([lines[0], stamp, *lines[1:]])


def _with_date_context(ctx: IntakeContext, now: datetime) -> IntakeContext:
    """Return ``ctx`` whose prompt tells the compiler today's UTC date (#253).

    ``now`` is the pipeline's single clock read, so the date the compiler is told and the
    ``authored_at`` stamp can never disagree. Retries extend this prompt, so they keep it.
    """
    line = (
        f"Today's UTC date is {now.strftime('%Y-%m-%d')}; a new TOKEN ends with "
        f"-{now.strftime('%Y%m%d')} (that date as YYYYMMDD).\n"
    )
    return dataclasses.replace(ctx, prompt=f"{ctx.prompt}{line}")


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
    write_adr: bool = False,
) -> PipelineResult:
    """Compile prose to a record, validate, retry once, or abort.

    ``write_adr`` (#112) stamps ``human_adr_ref`` INSIDE the guarded attempt, so the
    gate and the fidelity guard judge the exact bytes the linker writes (CE on #246).

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
    # #249: ONE clock read per call, reused by every attempt, so a retry never re-dates.
    now = _now_utc().astimezone(UTC)
    authored_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    # #253: the compiler is told the SAME instant's UTC date, as context only. A TOKEN is
    # never rewritten (#249 condition 4): a mismatch still fails loudly at Gate A.
    ctx = _with_date_context(ctx, now)

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

        # Stamped before Gate A, the fidelity guard and canonicalisation (#249), so each
        # judges the exact final bytes.
        prose = intake_context.prose_input
        octave = _stamp_authored_at(compiled["octave"], authored_at, prose)
        passed, regex_result, errors, last_available = _gate(working_dir, octave, prose)
        if passed and write_adr:
            # Critical-Engineer: consulted for fidelity and corruption risk (CE on #246).
            # The deterministic stamp can replace a field that carried a guarded quote,
            # so the stamped record goes through the whole gate again.
            octave = _stamp_record(regex_result.canonical_content or octave, regex_result)
            passed, regex_result, errors, last_available = _gate(working_dir, octave, prose)
            errors = [f"HUMAN_ADR_REF stamp failed re-validation: {e}" for e in errors]
        if passed:
            # A YAML record continues as its canonical bytes (the content-mode write
            # path, ADR-RFC-ARCH-004 §1.1); OCTAVE continues unchanged. The guard runs
            # once more on exactly these bytes, the ones the linker writes.
            octave = regex_result.canonical_content or octave
            errors = _fidelity_errors(octave, prose)
            passed = not errors
        if passed:
            return {
                "ok": True,
                "octave": octave,
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
        "adr_target_path": None,
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


def _stamp_record(record: str, validation: ValidationResult) -> str:
    """Stamp ``human_adr_ref`` with the record's own TOKEN in its own syntax (#112)."""
    token = validation.token or ""
    if validation.syntax == "yaml":
        return _stamp_yaml_human_adr_ref(record, token)
    return _stamp_human_adr_ref(record, token)


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
        write_adr=write_adr,
    )

    if not pipeline["ok"] or pipeline["octave"] is None or pipeline["validation"] is None:
        return _intake_failure_result(pipeline, dry_run)

    # --- #108.4: Gate-B availability policy on the PROSE path (shared Gate B) ---
    # Option L (unconditional): surface ``real_validation_available`` top-level
    # (below) and log at WARNING when degraded. Option C (opt-in, default OFF):
    # when real validation is REQUIRED but Gate B was unavailable, hard-block
    # BEFORE the linker (no branch, no PR), mirroring the octave_content path.
    real_validation_available = pipeline["real_validation_available"]
    # Gate B never runs on a quoted-YAML record, so its absence cannot block one; the
    # signal is still surfaced, as in content mode (ADR-RFC-ARCH-004 §1.1).
    if not real_validation_available and pipeline["validation"].syntax != "yaml":
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

    # --- Two-birds (#112): the HUMAN_ADR_REF stamp already ran inside the guarded
    # attempt (run_intake_pipeline), so the validated bytes ARE the bytes to write.
    # The verbatim prose becomes the ADR doc the linker dumb-writes alongside.
    octave_to_link = pipeline["octave"]
    adr_prose = intake_context.prose_input if write_adr else None

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
