"""AI synthesis seam (provider-agnostic).

This module provides the boundary at which ``clock_in`` attempts AI-backed
context synthesis. The boundary is deliberately a module-level function with
no provider SDK imports — honouring PROD::I3 (PROVIDER_AGNOSTIC_CONTEXT) and
PROD::I6 (LEGACY_INDEPENDENCE).

Issue #4 lands the seam with a *fallback-only* implementation. The real
provider wiring (AIClient port) is deferred to issue #5. Consumers obtain a
deterministic, structured fallback when no provider is available; they never
see a missing ``ai_synthesis`` field in the ``clock_in`` response
(PROD::I4 STRUCTURED_RETURN_SHAPES).
"""

from __future__ import annotations

import logging
from typing import TypedDict

logger = logging.getLogger(__name__)

# Valid values for the ``source`` discriminator. Anything else must be
# rejected by :func:`resolve_ai_synthesis` to keep the response dict shape
# stable for the Payload Compiler (PROD::I4).
_VALID_SOURCES: frozenset[str] = frozenset({"ai", "fallback"})


class AiSynthesisResult(TypedDict):
    """Structured shape of the ``ai_synthesis`` response field.

    Keys:
        source:    ``"ai"`` when a provider produced the synthesis,
                   ``"fallback"`` when the deterministic template was used.
        synthesis: OCTAVE-formatted string consumable by the Payload Compiler
                   at KVAEPH Position 3 (ADR-0353).
    """

    source: str
    synthesis: str


def synthesize_ai_context(
    *,
    role: str,
    focus: str,
    phase: str,
    context_summary: str,
) -> AiSynthesisResult | None:
    """Attempt AI-backed synthesis of the clock-in context.

    This is the provider-agnostic seam for issue #5. In this PR, the function
    intentionally returns ``None`` because no AI provider is wired. Tests that
    need the ``source == "ai"`` path monkeypatch this symbol.

    Args:
        role: Agent role name.
        focus: Resolved focus string.
        phase: Full phase identifier (e.g. ``"B1_FOUNDATION_COMPLETE"``).
        context_summary: Pre-built context summary for the AI to synthesise.

    Returns:
        :class:`AiSynthesisResult` when a provider successfully synthesises,
        otherwise ``None``. In this PR, always ``None``.
    """
    # Parameters are part of the stable seam signature consumed by issue #5.
    _ = (role, focus, phase, context_summary)
    return None


def build_fallback_synthesis(
    *,
    role: str,
    focus: str,
    phase: str,
) -> AiSynthesisResult:
    """Construct the deterministic OCTAVE fallback synthesis.

    Matches the legacy ``CLOCK_IN_SYNTHESIS_PROTOCOL`` shape so the Payload
    Compiler can read it identically to a legacy response. Returned whenever
    :func:`synthesize_ai_context` returns ``None`` or raises.

    Args:
        role: Agent role name.
        focus: Resolved focus string.
        phase: Full phase identifier.

    Returns:
        :class:`AiSynthesisResult` with ``source == "fallback"``.
    """
    synthesis = (
        "CONTEXT_FILES::[@.hestai/state/context/PROJECT-CONTEXT.oct.md, "
        "@.hestai/north-star/000-HESTAI-CONTEXT-MCP-NORTH-STAR-SUMMARY.oct.md]\n"
        f"FOCUS::{focus}\n"
        f"PHASE::{phase}\n"
        "BLOCKERS::[]\n"
        f"TASKS::[Review context for {role}, Complete {focus} objectives]\n"
        "FRESHNESS_WARNING::AI_SYNTHESIS_UNAVAILABLE"
    )
    return {"source": "fallback", "synthesis": synthesis}


def resolve_ai_synthesis(
    *,
    role: str,
    focus: str,
    phase: str,
    context_summary: str,
) -> AiSynthesisResult:
    """Return an :class:`AiSynthesisResult`; never ``None``.

    Calls :func:`synthesize_ai_context`; if it returns ``None`` or raises,
    constructs the deterministic fallback. This is the single entry point
    callers should use to guarantee PROD::I4 structured shape.

    Args:
        role: Agent role name.
        focus: Resolved focus string.
        phase: Full phase identifier.
        context_summary: Pre-built context summary (passed through to seam).

    Returns:
        Always a populated :class:`AiSynthesisResult`.
    """
    # Look up the seam via module attribute so monkeypatched replacements
    # (in tests and issue #5 wiring) are honoured.
    from hestai_context_mcp.core import synthesis as _mod

    try:
        result = _mod.synthesize_ai_context(
            role=role,
            focus=focus,
            phase=phase,
            context_summary=context_summary,
        )
    except Exception as exc:  # noqa: BLE001 — seam must be total; fall back on any failure.
        # Observable degradation — log at warning so issue #5 provider failures
        # surface in the logs rather than silently collapsing to fallback.
        logger.warning(
            "AI synthesis seam raised %s; falling back to deterministic template.",
            exc.__class__.__name__,
        )
        result = None

    if result is None:
        return build_fallback_synthesis(role=role, focus=focus, phase=phase)

    if not _is_valid_result(result):
        logger.warning(
            "AI synthesis seam returned malformed payload %r; falling back.",
            result,
        )
        return build_fallback_synthesis(role=role, focus=focus, phase=phase)

    return result


def _is_valid_result(result: object) -> bool:
    """Strict structural validation of the seam's return value.

    Guards against future provider-port bugs silently leaking malformed
    payloads (e.g. ``{"source": None, "synthesis": []}``) into the
    ``clock_in`` response. Checks presence, types, non-emptiness, and
    source-discriminator membership.
    """
    if not isinstance(result, dict):
        return False
    if "source" not in result or "synthesis" not in result:
        return False
    source = result["source"]
    synthesis = result["synthesis"]
    if not isinstance(source, str) or source not in _VALID_SOURCES:
        return False
    return isinstance(synthesis, str) and bool(synthesis.strip())


__all__: list[str] = [
    "AiSynthesisResult",
    "build_fallback_synthesis",
    "resolve_ai_synthesis",
    "synthesize_ai_context",
]
