"""Scoped SEMANTIC governance reviewer over the AIClient port (issue #77).

This is an *application-layer* capability — NOT a new port. It consumes the
existing :class:`~hestai_context_mcp.ports.ai_client.AIClient` Protocol at the
**analysis tier**, exactly mirroring the call pattern in
:mod:`hestai_context_mcp.core.intake_compiler` /
:mod:`hestai_context_mcp.core.synthesis`::

    client = build_default_ai_client(tier="analysis")
    async with client as c:
        raw = await c.complete_text(CompletionRequest(...))

**Scope (the AGR decision HO-AGR-SEMANTIC-REVIEWER-ANALYSIS-TIER-20260611).**
The reviewer assesses *only* the semantic surface of a governance record:

    * precedence / coherence,
    * contradiction,
    * scope,
    * concept-validity.

It is *explicitly instructed NOT to check schema or syntax* — the deterministic
validators (Gate A regex rails) and octave-mcp (Gate B) own that. There is no
facet-card and no schema commentary. The human retains the merge decision; this
verdict is advisory/assistive.

Provider, model, retry, and credential resolution all live *below* the port (in
``adapters/ai_config`` + the adapter). No vendor/model literal appears in this
module (PROD::I3; asserted by ``tests/unit/test_source_invariants.py``).

Cost caps (mirroring intake_compiler; operator-ratified, env-overridable):
    * ``HESTAI_REVIEW_MAX_OUTPUT_TOKENS`` — per-call output ceiling
      (default 2000). Passed as ``CompletionRequest.max_tokens``.
    * ``HESTAI_REVIEW_MAX_COST_USD`` — abort *before* the call if the projected
      cost (input + max-output tokens, priced via
      ``HESTAI_REVIEW_USD_PER_1K_TOKENS``) exceeds this cap (default 0.50).

A cap breach or any backend failure is surfaced as a structured ``BLOCKED``
result (PROD::I4) — never a fabricated APPROVED verdict (structural integrity
over velocity).

DIP boundary: this ``core/`` module imports only from ``ports`` at module load;
the adapter factory and config are reached via lazy imports inside functions
(composition-root pattern, mirroring ``core/intake_compiler``).
"""

from __future__ import annotations

import logging
import os
import re
from typing import Literal, TypedDict

from hestai_context_mcp.ports.ai_client import (
    AIClient,
    AIClientAuthError,
    AIClientError,
    AIClientTransportError,
    CompletionRequest,
)

logger = logging.getLogger(__name__)

__all__ = [
    "Verdict",
    "ReviewMetrics",
    "ReviewResult",
    "review_governance",
]

Verdict = Literal["APPROVED", "CONCERNS", "BLOCKED"]

# The analysis tier is the default for this reviewer (issue #77): a stronger,
# balanced model than the synthesis-tier default. Tier resolution itself lives
# below the port in ``ai_config`` — this is only the *tier name*, not a model.
_DEFAULT_TIER = "analysis"

# Defaults for the operator-ratified cost caps. All env-overridable. The output
# ceiling is smaller than intake_compiler's: a review verdict is short prose +
# a concern list, not a full AGR body.
_DEFAULT_MAX_OUTPUT_TOKENS = 2000
_DEFAULT_MAX_COST_USD = 0.50
# Default blended price used only for the *pre-call* cost projection. The
# guard's purpose is to abort runaway requests, not to bill; real billing is
# provider-side. Override via HESTAI_REVIEW_USD_PER_1K_TOKENS for pricier
# (analysis/critical) models.
_DEFAULT_USD_PER_1K_TOKENS = 0.01

# Rough char->token ratio for the pre-call projection (≈4 chars/token).
_CHARS_PER_TOKEN = 4
# Request timeout for the review call (seconds).
_REQUEST_TIMEOUT_SECONDS = 60


class ReviewMetrics(TypedDict):
    """Per-call metrics (PROD::I4). ``cost`` is the projected USD cost."""

    tokens: int
    cost: float
    model: str


class ReviewResult(TypedDict):
    """Structured result of a scoped semantic review (PROD::I4).

    Keys:
        verdict:    ``"APPROVED"`` | ``"CONCERNS"`` | ``"BLOCKED"``.
        assessment: One-paragraph semantic assessment (never schema).
        concerns:   Zero or more concrete concern strings.
        metrics:    ``{tokens, cost, model}``.
    """

    verdict: Verdict
    assessment: str
    concerns: list[str]
    metrics: ReviewMetrics


# --- Prompt assembly (SEMANTIC-scoped; NEVER schema) ----------------------

# The system prompt is a module constant here (unlike intake_context's JIT
# prompt) because the review rubric is fixed: it does not depend on live repo
# corpus. It explicitly excludes schema/syntax checking and names the four
# semantic axes from the AGR decision. NO vendor/model literal appears.
_REVIEW_SYSTEM_PROMPT = (
    "You are a scoped SEMANTIC reviewer for a governance decision record.\n"
    "\n"
    "Assess ONLY the following semantic axes:\n"
    "  1. PRECEDENCE / COHERENCE — does this record sit correctly relative to "
    "existing decisions; is its supersession/precedence coherent?\n"
    "  2. CONTRADICTION — does it contradict a ratified or still-active "
    "decision?\n"
    "  3. SCOPE — is the decision within an appropriate scope; does it overlap "
    "or collide with another record's scope?\n"
    "  4. CONCEPT-VALIDITY — is this the right concept; is the idea sound and "
    "well-formed as a decision?\n"
    "\n"
    "CRITICAL EXCLUSION: Do NOT check schema, syntax, field names, OCTAVE "
    "structure, or formatting. The deterministic validators own schema "
    "correctness; you must NEVER comment on schema or syntax. Do not produce a "
    "facet card. Your job is semantic judgement only.\n"
    "\n"
    "Respond in this exact line-oriented form:\n"
    "VERDICT::<APPROVED|CONCERNS|BLOCKED>\n"
    "ASSESSMENT::<one paragraph of semantic assessment>\n"
    "CONCERNS::[<concern>; <concern>; ...]   (empty list [] if none)\n"
    "\n"
    "Use APPROVED when there is no semantic problem, CONCERNS for non-blocking "
    "semantic doubts a human should weigh, and BLOCKED for a clear semantic "
    "contradiction or precedence violation. You inform the human; you do not "
    "merge."
)


def build_default_ai_client(*, tier: str = _DEFAULT_TIER) -> AIClient | None:
    """Return the tier-aware default :class:`AIClient`, or ``None``.

    Composition-root seam (lazy import of the adapter) so this ``core`` module
    depends only on ``ports`` at module-load time. Tests monkeypatch this
    symbol on the module to inject stubs; it is resolved via the module
    attribute on each call, so patches are honoured.
    """
    from hestai_context_mcp.adapters.openai_compat_ai_client import (
        build_default_ai_client as _factory,
    )

    return _factory(tier=tier)


def _resolve_model_name(tier: str) -> str:
    """Return the configured model identifier for ``tier`` (value, not literal).

    Lazy import keeps the adapter/config dependency out of module-load scope
    (DIP) and keeps any provider/model *literal* out of this file's source
    (PROD::I3) — the model name is a runtime value resolved below the port.
    """
    from hestai_context_mcp.adapters import ai_config

    return ai_config.resolve_model(tier)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using default %d", name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using default %s", name, raw, default)
        return default


def _ceil_div(numerator: int, denominator: int) -> int:
    """Ceiling integer division."""
    return (numerator + denominator - 1) // denominator


def _estimate_input_tokens(octave_content: str) -> int:
    """Estimate input tokens from the system prompt + the record under review."""
    input_chars = len(_REVIEW_SYSTEM_PROMPT) + len(octave_content)
    return _ceil_div(input_chars, _CHARS_PER_TOKEN)


def _blocked(
    model: str,
    assessment: str,
    concerns: list[str],
    *,
    tokens: int = 0,
    cost: float = 0.0,
) -> ReviewResult:
    """Build a fail-soft BLOCKED result. NEVER fabricates an APPROVED verdict."""
    return {
        "verdict": "BLOCKED",
        "assessment": assessment,
        "concerns": concerns,
        "metrics": {"tokens": tokens, "cost": cost, "model": model},
    }


_VERDICT_RE = re.compile(r"^\s*VERDICT::\s*(APPROVED|CONCERNS|BLOCKED)\b", re.MULTILINE)
_ASSESSMENT_RE = re.compile(r"^\s*ASSESSMENT::\s*(.+?)\s*$", re.MULTILINE)
_CONCERNS_RE = re.compile(r"^\s*CONCERNS::\s*\[(.*)\]\s*$", re.MULTILINE | re.DOTALL)


def _parse_concerns(raw_block: str) -> list[str]:
    """Split a ``[a; b; c]`` concern block into a clean list of strings."""
    parts = re.split(r"[;\n]+", raw_block)
    return [p.strip() for p in parts if p.strip()]


def _parse_review(raw: str, model: str, tokens: int, cost: float) -> ReviewResult:
    """Parse the model's line-oriented response into a structured result.

    An unparseable verdict degrades to ``CONCERNS`` (never silently
    ``APPROVED``) so a malformed response routes to human attention rather
    than rubber-stamping a record.
    """
    verdict_match = _VERDICT_RE.search(raw)
    assessment_match = _ASSESSMENT_RE.search(raw)
    concerns_match = _CONCERNS_RE.search(raw)

    concerns = _parse_concerns(concerns_match.group(1)) if concerns_match else []
    assessment = (
        assessment_match.group(1).strip()
        if assessment_match
        else raw.strip()[:500] or "No assessment text returned."
    )

    if verdict_match is None:
        # No recognisable verdict -> do not approve; route to a human.
        concerns = concerns or ["Reviewer response did not contain a parseable verdict."]
        return {
            "verdict": "CONCERNS",
            "assessment": assessment,
            "concerns": concerns,
            "metrics": {"tokens": tokens, "cost": cost, "model": model},
        }

    verdict: Verdict = verdict_match.group(1)  # type: ignore[assignment]
    return {
        "verdict": verdict,
        "assessment": assessment,
        "concerns": concerns,
        "metrics": {"tokens": tokens, "cost": cost, "model": model},
    }


async def _run_completion(
    client: AIClient, system_prompt: str, user_prompt: str, max_tokens: int
) -> str:
    async with client as c:
        return await c.complete_text(
            CompletionRequest(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                timeout_seconds=_REQUEST_TIMEOUT_SECONDS,
            )
        )


async def review_governance(
    octave_content: str,
    *,
    tier: str = _DEFAULT_TIER,
    max_output_tokens: int | None = None,
    max_cost_usd: float | None = None,
) -> ReviewResult:
    """Run a scoped SEMANTIC review of a governance record over the AIClient port.

    Args:
        octave_content: The governance record (AGR) text to review. Reviewed
            for semantics only — precedence, contradiction, scope, concept —
            NEVER for schema.
        tier: Model tier (default ``"analysis"``). Forwarded to the tier-aware
            client factory and to model-name resolution.
        max_output_tokens: Per-call output ceiling. Defaults to
            ``HESTAI_REVIEW_MAX_OUTPUT_TOKENS`` then 2000.
        max_cost_usd: Abort threshold for projected cost. Defaults to
            ``HESTAI_REVIEW_MAX_COST_USD`` then 0.50.

    Returns:
        :class:`ReviewResult`. A semantic verdict on success; a structured
        ``BLOCKED`` result on no-client / cost-cap / auth / transport / empty
        response — never a fabricated ``APPROVED``.
    """
    out_cap = (
        max_output_tokens
        if max_output_tokens is not None
        else _env_int("HESTAI_REVIEW_MAX_OUTPUT_TOKENS", _DEFAULT_MAX_OUTPUT_TOKENS)
    )
    cost_cap = (
        max_cost_usd
        if max_cost_usd is not None
        else _env_float("HESTAI_REVIEW_MAX_COST_USD", _DEFAULT_MAX_COST_USD)
    )
    price_per_1k = _env_float("HESTAI_REVIEW_USD_PER_1K_TOKENS", _DEFAULT_USD_PER_1K_TOKENS)

    model = _resolve_model_name(tier)

    # --- Cost cap: project BEFORE the call; abort on breach (no fabrication). ---
    projected_tokens = _estimate_input_tokens(octave_content) + out_cap
    projected_cost = (projected_tokens / 1000.0) * price_per_1k
    if projected_cost > cost_cap:
        return _blocked(
            model,
            (
                f"Aborted before backend call: projected cost ${projected_cost:.4f} "
                f"exceeds cap ${cost_cap:.4f}. No review produced."
            ),
            [
                (
                    f"Projected cost ${projected_cost:.4f} over cap ${cost_cap:.4f} "
                    f"({projected_tokens} tokens at ${price_per_1k:.4f}/1k)."
                )
            ],
            tokens=projected_tokens,
        )

    client = build_default_ai_client(tier=tier)
    if client is None:
        return _blocked(
            model,
            "No AIClient available (no credential configured); cannot run semantic review.",
            ["No AI client/credential available for the semantic review."],
        )

    user_prompt = f"BEGIN_RECORD\n{octave_content}\nEND_RECORD"
    try:
        raw = await _run_completion(client, _REVIEW_SYSTEM_PROMPT, user_prompt, out_cap)
    except AIClientAuthError as exc:
        return _blocked(
            model,
            f"AIClient auth error (permanent, no retry): {exc}",
            [f"auth error: {exc}"],
        )
    except AIClientTransportError as exc:
        return _blocked(
            model,
            f"AIClient transport error (call failed): {exc}",
            [f"transport error: {exc}"],
        )
    except AIClientError as exc:
        return _blocked(
            model,
            f"AIClient error: {exc.__class__.__name__}: {exc}",
            [f"{exc.__class__.__name__}: {exc}"],
        )

    if not isinstance(raw, str) or not raw.strip():
        return _blocked(
            model,
            "Backend returned an empty response; no semantic verdict produced.",
            ["Empty reviewer response."],
        )

    # Reported metric = input estimate + ACTUAL output (NOT the output ceiling).
    actual_output_tokens = _ceil_div(len(raw), _CHARS_PER_TOKEN)
    actual_tokens = _estimate_input_tokens(octave_content) + actual_output_tokens
    cost = (actual_tokens / 1000.0) * price_per_1k
    logger.info(
        "governance review ok: model=%s actual_tokens=%d est_cost=$%.4f",
        model,
        actual_tokens,
        cost,
    )
    return _parse_review(raw, model, actual_tokens, cost)
