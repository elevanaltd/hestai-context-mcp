"""Stage-2 BACKEND: prose->OCTAVE compiler over the AIClient port (RFC #53 T2).

This is an *application-layer* compiler — NOT a new port. It consumes the
existing :class:`~hestai_context_mcp.ports.ai_client.AIClient` Protocol, exactly
mirroring the call pattern in :mod:`hestai_context_mcp.core.synthesis`:

    client = build_default_ai_client()
    async with client as c:
        raw = await c.complete_text(CompletionRequest(...))

Provider, model, retry, and credential resolution all live *below* the port (in
``adapters/ai_config`` + the adapter). No vendor literal appears in this module
(PROD::I3; asserted by ``tests/unit/test_source_invariants.py``). The compiler
returns a *raw* OCTAVE string + metrics; it does NOT validate OCTAVE — that is
Stage 3.

Cost caps (operator-ratified, env-overridable):
    * ``HESTAI_INTAKE_MAX_OUTPUT_TOKENS`` — per-call output ceiling
      (default 8000). Passed as ``CompletionRequest.max_tokens``.
    * ``HESTAI_INTAKE_MAX_COST_USD`` — abort *before* the call if the projected
      cost (input + max-output tokens, priced via
      ``HESTAI_INTAKE_USD_PER_1K_TOKENS``) exceeds this cap (default 0.50).

A cap breach or any backend failure is surfaced as a structured error
(PROD::I4) — never a silent truncation, never a fabricated AGR.

DIP boundary: this ``core/`` module imports only from ``ports`` at module load;
the adapter factory and config are reached via lazy imports inside functions
(composition-root pattern, mirroring ``core/synthesis``).
"""

from __future__ import annotations

import logging
import os
from typing import TypedDict

from hestai_context_mcp.ports.ai_client import (
    AIClient,
    AIClientAuthError,
    AIClientError,
    AIClientTransportError,
    AIClientTruncationError,
    CompletionRequest,
    CompletionResult,
)
from hestai_context_mcp.tools.governance.intake_context import IntakeContext

logger = logging.getLogger(__name__)

__all__ = [
    "CompileMetrics",
    "CompileResult",
    "compile_prose_to_octave",
]

# Defaults for the operator-ratified cost caps. All env-overridable.
_DEFAULT_MAX_OUTPUT_TOKENS = 8000
_DEFAULT_MAX_COST_USD = 0.50
# Default blended price used only for the *pre-call* cost projection. Sized so
# the default 8000-token ceiling stays comfortably under the $0.50 abort cap for
# typical low-cost models; the guard's purpose is to abort runaway requests, not
# to bill. Override via HESTAI_INTAKE_USD_PER_1K_TOKENS for pricier models. Real
# billing is provider-side.
_DEFAULT_USD_PER_1K_TOKENS = 0.01

# Rough char->token ratio for the pre-call projection (≈4 chars/token).
_CHARS_PER_TOKEN = 4
# Request timeout for the prose->OCTAVE call (seconds).
_REQUEST_TIMEOUT_SECONDS = 60


class CompileMetrics(TypedDict):
    """Per-call metrics (PROD::I4).

    ``tokens`` / ``cost`` are the provider's REAL figures when available
    (issue #98). ``cost_is_estimate`` is ``True`` when the provider reported no
    cost and the value is a flat-rate local estimate rather than an actual — so
    consumers never mistake an estimate for a billed figure.
    """

    tokens: int
    cost: float
    model: str
    cost_is_estimate: bool


class CompileResult(TypedDict):
    """Structured result of a prose->OCTAVE compile (PROD::I4)."""

    ok: bool
    octave: str | None
    metrics: CompileMetrics
    error: str | None


def build_default_ai_client() -> AIClient | None:
    """Return the default :class:`AIClient`, or ``None`` if none available.

    Composition-root seam (lazy import of the adapter) so this ``core`` module
    depends only on ``ports`` at module-load time. Tests monkeypatch this symbol
    on the module to inject stubs; it is resolved via the module attribute on
    each call, so patches are honoured.
    """
    from hestai_context_mcp.core.synthesis import (
        build_default_ai_client as _factory,
    )

    return _factory()


def _resolve_model_name() -> str:
    """Return the configured model identifier (value, not a source literal).

    Lazy import keeps the adapter/config dependency out of module-load scope
    (DIP) and keeps any provider/model *literal* out of this file's source
    (PROD::I3) — the model name is a runtime value resolved below the port.
    """
    from hestai_context_mcp.adapters import ai_config

    return ai_config.resolve_model()


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


def _estimate_input_tokens(intake_context: IntakeContext) -> int:
    """Estimate input tokens from the system prompt + the prose user prompt.

    After the prose-duplication fix the system prompt no longer embeds the
    prose, so ``len(prompt) + len(prose_input)`` is the correct, non-duplicative
    input size: the system prompt (instructions + corpus) plus the prose carried
    by the user prompt.
    """
    input_chars = len(intake_context.prompt) + len(intake_context.prose_input)
    return _ceil_div(input_chars, _CHARS_PER_TOKEN)


def _project_tokens(intake_context: IntakeContext, max_output_tokens: int) -> int:
    """Pre-call cost projection: input estimate + max output CEILING.

    Used only by the pre-call cost guard (worst case = full output budget).
    Unchanged by the metrics fix.
    """
    return _estimate_input_tokens(intake_context) + max_output_tokens


def _resolve_cost(
    provider_cost: float | None, tokens: int, price_per_1k: float
) -> tuple[float, bool]:
    """Return ``(cost, is_estimate)`` preferring the provider's real cost.

    Issue #98: when the provider reports a real cost, use it verbatim and mark
    it as actual. Otherwise fall back to the flat-rate projection
    (``tokens / 1000 * price_per_1k``) and mark it as an estimate so consumers
    never mistake the local approximation for a billed figure.
    """
    if provider_cost is not None:
        return provider_cost, False
    return (tokens / 1000.0) * price_per_1k, True


def _failure(
    model: str,
    error: str,
    tokens: int = 0,
    cost: float = 0.0,
    *,
    cost_is_estimate: bool = True,
) -> CompileResult:
    return {
        "ok": False,
        "octave": None,
        "metrics": {
            "tokens": tokens,
            "cost": cost,
            "model": model,
            "cost_is_estimate": cost_is_estimate,
        },
        "error": error,
    }


async def _run_completion(
    client: AIClient, prompt: str, user_prompt: str, max_tokens: int
) -> CompletionResult:
    async with client as c:
        return await c.complete_text(
            CompletionRequest(
                system_prompt=prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
                timeout_seconds=_REQUEST_TIMEOUT_SECONDS,
            )
        )


async def compile_prose_to_octave(
    intake_context: IntakeContext,
    *,
    max_output_tokens: int | None = None,
    max_cost_usd: float | None = None,
) -> CompileResult:
    """Transduce prose into a raw OCTAVE string over the AIClient port.

    Args:
        intake_context: Stage-1 output (JIT prompt + corpus + prose).
        max_output_tokens: Per-call output ceiling. Defaults to
            ``HESTAI_INTAKE_MAX_OUTPUT_TOKENS`` then 8000.
        max_cost_usd: Abort threshold for projected cost. Defaults to
            ``HESTAI_INTAKE_MAX_COST_USD`` then 0.50.

    Returns:
        :class:`CompileResult`. ``ok=True`` carries the raw OCTAVE string and
        populated metrics; ``ok=False`` carries a structured ``error`` and never
        a fabricated OCTAVE body.
    """
    out_cap = (
        max_output_tokens
        if max_output_tokens is not None
        else _env_int("HESTAI_INTAKE_MAX_OUTPUT_TOKENS", _DEFAULT_MAX_OUTPUT_TOKENS)
    )
    cost_cap = (
        max_cost_usd
        if max_cost_usd is not None
        else _env_float("HESTAI_INTAKE_MAX_COST_USD", _DEFAULT_MAX_COST_USD)
    )
    price_per_1k = _env_float("HESTAI_INTAKE_USD_PER_1K_TOKENS", _DEFAULT_USD_PER_1K_TOKENS)

    model = _resolve_model_name()

    # --- Cost cap: project BEFORE the call; abort on breach (no truncation). ---
    projected_tokens = _project_tokens(intake_context, out_cap)
    projected_cost = (projected_tokens / 1000.0) * price_per_1k
    if projected_cost > cost_cap:
        return _failure(
            model,
            (
                f"Projected cost ${projected_cost:.4f} exceeds cap ${cost_cap:.4f} "
                f"(projected {projected_tokens} tokens at ${price_per_1k:.4f}/1k). "
                "Aborted before backend call; no output produced."
            ),
            tokens=projected_tokens,
        )

    client = build_default_ai_client()
    if client is None:
        # Issue #99 (Finding 2): no credential → definitively $0; the provider
        # was never called so cost_is_estimate=False (not an approximation).
        return _failure(
            model, "No AIClient available (no credential configured).", cost_is_estimate=False
        )

    user_prompt = f"BEGIN_REQUEST\n{intake_context.prose_input}\nEND_REQUEST"
    try:
        result = await _run_completion(client, intake_context.prompt, user_prompt, out_cap)
    except AIClientAuthError as exc:
        # Issue #99 (Finding 2): auth rejection is pre-billing; definitively $0.
        return _failure(
            model, f"AIClient auth error (permanent, no retry): {exc}", cost_is_estimate=False
        )
    except AIClientTransportError as exc:
        return _failure(model, f"AIClient transport error (call failed): {exc}")
    except AIClientTruncationError as exc:
        # Issue #96: the provider hit the output-token cap (budget exhausted)
        # and BILLED for the truncated call. Record the REAL tokens so the
        # metrics stop under-reporting as 0/0. Do NOT retry: an identical
        # re-issue would re-truncate and burn budget for the same outcome.
        # Issue #98: price with the provider's REAL cost when reported; else
        # fall back to a labelled flat-rate estimate.
        consumed = exc.consumed_tokens
        billed_cost, cost_is_estimate = _resolve_cost(exc.cost, consumed, price_per_1k)
        logger.warning(
            "intake compile truncated: model=%s consumed_tokens=%d cost=$%.4f estimate=%s "
            "(output cap hit; not retried)",
            model,
            consumed,
            billed_cost,
            cost_is_estimate,
        )
        return _failure(
            model,
            (
                "AIClient truncation error (output hit the token cap; not retried): "
                f"{exc}. Consumed {consumed} tokens."
            ),
            tokens=consumed,
            cost=billed_cost,
            cost_is_estimate=cost_is_estimate,
        )
    except AIClientError as exc:
        return _failure(model, f"AIClient error: {exc.__class__.__name__}: {exc}")

    raw = result.content
    if not raw.strip():
        return _failure(model, "Backend returned empty response; no OCTAVE produced.")

    # Issue #98: report the provider's REAL usage and cost. The pre-call guard
    # used out_cap as a worst case; the post-call metric reflects reality.
    # Tokens: prefer the provider total; fall back to a char-based estimate only
    # when the provider reports no usage. Cost: prefer the provider's real cost;
    # fall back to a labelled flat-rate estimate when None.
    if result.total_tokens is not None:
        actual_tokens = result.total_tokens
    else:
        actual_output_tokens = _ceil_div(len(raw), _CHARS_PER_TOKEN)
        actual_tokens = _estimate_input_tokens(intake_context) + actual_output_tokens
    cost, cost_is_estimate = _resolve_cost(result.cost, actual_tokens, price_per_1k)
    logger.info(
        "intake compile ok: model=%s tokens=%d cost=$%.4f estimate=%s",
        model,
        actual_tokens,
        cost,
        cost_is_estimate,
    )
    return {
        "ok": True,
        "octave": raw,
        "metrics": {
            "tokens": actual_tokens,
            "cost": cost,
            "model": model,
            "cost_is_estimate": cost_is_estimate,
        },
        "error": None,
    }
