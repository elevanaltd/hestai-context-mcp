"""Tests for the Stage-2 prose->OCTAVE backend compiler (RFC #53 Gate C, T2).

``compile_prose_to_octave`` is an application-layer compiler that consumes the
existing ``AIClient`` port (NO new port). It mirrors ``core/synthesis.py``:
``build_default_ai_client()`` then ``async with client as c: complete_text(...)``.

It returns a structured ``CompileResult`` (PROD I4) of the shape
``{"ok": bool, "octave": str | None, "metrics": {...}, "error": str | None}``
where ``metrics`` carries ``{tokens, cost, model}``.

Cost caps (operator-ratified, env-overridable):
  * output cap of 8000 tokens (HESTAI_INTAKE_MAX_OUTPUT_TOKENS),
  * abort if projected cost > $0.50 (HESTAI_INTAKE_MAX_COST_USD).
A breach is surfaced as a structured error — never silent truncation, never a
fabricated AGR.

Provider-agnostic (PROD I3): no vendor literal in source (asserted in
``tests/unit/test_source_invariants.py``).
"""

from __future__ import annotations

from typing import Any

import pytest

import hestai_context_mcp.core.intake_compiler as mod
from hestai_context_mcp.core.intake_compiler import compile_prose_to_octave
from hestai_context_mcp.ports.ai_client import (
    AIClientAuthError,
    AIClientTransportError,
    AIClientTruncationError,
    CompletionRequest,
)
from hestai_context_mcp.tools.governance.intake_context import IntakeContext


def _ctx(prose: str = "record a provider routing decision") -> IntakeContext:
    return IntakeContext(
        prose_input=prose,
        corpus='===CONCEPT_CARD===\nID::"X"\n===END===',
        prompt="SYSTEM PROMPT with corpus",
        relevant_tokens=(),
    )


class _StubClient:
    """Async-context AIClient stub capturing the request it received."""

    def __init__(self, *, text: str = "", raises: BaseException | None = None) -> None:
        self._text = text
        self._raises = raises
        self.request: CompletionRequest | None = None
        self.entered = False
        self.closed = False

    async def __aenter__(self) -> _StubClient:
        self.entered = True
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.closed = True

    async def complete_text(self, request: CompletionRequest) -> str:
        self.request = request
        if self._raises is not None:
            raise self._raises
        return self._text


@pytest.fixture
def patch_client(monkeypatch: pytest.MonkeyPatch):
    """Patch the module-level AIClient factory to return a supplied stub."""

    def _install(client_or_none: Any) -> None:
        monkeypatch.setattr(mod, "build_default_ai_client", lambda: client_or_none, raising=True)

    return _install


class TestCompileSuccess:
    async def test_returns_octave_and_metrics(self, patch_client) -> None:
        octave = "===DECISION_RECORD===\nMETA:\n  TYPE::DECISION_RECORD\n===END==="
        stub = _StubClient(text=octave)
        patch_client(stub)
        result = await compile_prose_to_octave(_ctx())
        assert result["ok"] is True
        assert result["octave"] == octave
        assert result["error"] is None
        metrics = result["metrics"]
        assert set(metrics) == {"tokens", "cost", "model"}
        assert isinstance(metrics["tokens"], int) and metrics["tokens"] > 0
        assert isinstance(metrics["cost"], float) and metrics["cost"] >= 0.0
        assert isinstance(metrics["model"], str) and metrics["model"]

    async def test_uses_jit_prompt_from_context(self, patch_client) -> None:
        stub = _StubClient(text="===DECISION_RECORD===\n===END===")
        patch_client(stub)
        ctx = _ctx()
        await compile_prose_to_octave(ctx)
        assert stub.request is not None
        # The compiler hands the JIT-compiled prompt to the backend.
        assert stub.request.system_prompt == ctx.prompt
        # The prose is the user prompt (delimited).
        assert ctx.prose_input in stub.request.user_prompt


class TestNoClientAvailable:
    async def test_returns_structured_failure_when_no_client(self, patch_client) -> None:
        patch_client(None)
        result = await compile_prose_to_octave(_ctx())
        assert result["ok"] is False
        assert result["octave"] is None
        assert result["error"]
        assert result["metrics"]["tokens"] == 0


class TestErrorPaths:
    async def test_auth_error_is_permanent_structured_failure(self, patch_client) -> None:
        stub = _StubClient(raises=AIClientAuthError("no key"))
        patch_client(stub)
        result = await compile_prose_to_octave(_ctx())
        assert result["ok"] is False
        assert result["octave"] is None
        assert "auth" in result["error"].lower()

    async def test_transport_error_surfaced_not_fabricated(self, patch_client) -> None:
        stub = _StubClient(raises=AIClientTransportError("timeout"))
        patch_client(stub)
        result = await compile_prose_to_octave(_ctx())
        assert result["ok"] is False
        # Never a silently fabricated AGR.
        assert result["octave"] is None
        assert result["error"]

    async def test_empty_response_is_failure(self, patch_client) -> None:
        stub = _StubClient(text="   ")
        patch_client(stub)
        result = await compile_prose_to_octave(_ctx())
        assert result["ok"] is False
        assert result["octave"] is None


class _CountingStub:
    """AIClient stub that counts how many times complete_text is invoked."""

    def __init__(self, *, raises: BaseException) -> None:
        self._raises = raises
        self.calls = 0

    async def __aenter__(self) -> _CountingStub:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    async def complete_text(self, request: CompletionRequest) -> str:
        self.calls += 1
        raise self._raises


class TestTruncationAccounting:
    """Issue #96: truncation records REAL cost and is never retried.

    The adapter raises ``AIClientTruncationError`` (finish_reason='length')
    carrying the tokens the provider actually billed. The compiler must:
      * return a structured failure (PROD::I4) — never a fabricated AGR,
      * record the REAL consumed tokens and a NON-zero cost (closing the
        ``tokens:0 / cost:0`` accounting leak), and
      * NOT retry (an identical re-issue would re-truncate and burn budget).
    """

    async def test_truncation_is_structured_failure(self, patch_client) -> None:
        stub = _StubClient(raises=AIClientTruncationError("truncated", consumed_tokens=8000))
        patch_client(stub)
        result = await compile_prose_to_octave(_ctx())
        assert result["ok"] is False
        assert result["octave"] is None
        assert result["error"]
        assert "truncat" in result["error"].lower()

    async def test_truncation_records_real_tokens_and_cost(self, patch_client, monkeypatch) -> None:
        # Deterministic pricing so cost is exactly tokens/1000 * price.
        monkeypatch.setenv("HESTAI_INTAKE_USD_PER_1K_TOKENS", "1.0")
        # Raise the abort cap so the pre-call cost guard does not short-circuit;
        # we want the truncation branch (post-call) to be exercised.
        monkeypatch.setenv("HESTAI_INTAKE_MAX_COST_USD", "1000000")
        stub = _StubClient(raises=AIClientTruncationError("truncated", consumed_tokens=8000))
        patch_client(stub)
        result = await compile_prose_to_octave(_ctx())
        metrics = result["metrics"]
        # The REAL billed tokens, not 0.
        assert metrics["tokens"] == 8000
        # NON-zero cost computed from consumed tokens at the configured price.
        assert metrics["cost"] == pytest.approx(8.0)
        assert metrics["model"]

    async def test_truncation_is_not_retried(self, patch_client) -> None:
        stub = _CountingStub(raises=AIClientTruncationError("truncated", consumed_tokens=8000))
        patch_client(stub)
        result = await compile_prose_to_octave(_ctx())
        assert result["ok"] is False
        # Exactly one backend call — no retry on truncation.
        assert stub.calls == 1


class TestCostCaps:
    async def test_output_token_cap_is_passed_to_request(self, patch_client) -> None:
        stub = _StubClient(text="===DECISION_RECORD===\n===END===")
        patch_client(stub)
        await compile_prose_to_octave(_ctx(), max_output_tokens=1234)
        assert stub.request is not None
        assert stub.request.max_tokens == 1234

    async def test_default_output_cap_is_8000(self, patch_client, monkeypatch) -> None:
        monkeypatch.delenv("HESTAI_INTAKE_MAX_OUTPUT_TOKENS", raising=False)
        stub = _StubClient(text="===DECISION_RECORD===\n===END===")
        patch_client(stub)
        await compile_prose_to_octave(_ctx())
        assert stub.request is not None
        assert stub.request.max_tokens == 8000

    async def test_aborts_when_projected_cost_exceeds_cap(self, patch_client, monkeypatch) -> None:
        # Force a tiny cost cap so the projected cost trivially exceeds it; the
        # backend must NOT be called.
        monkeypatch.setenv("HESTAI_INTAKE_MAX_COST_USD", "0.00001")
        monkeypatch.setenv("HESTAI_INTAKE_USD_PER_1K_TOKENS", "1.0")
        stub = _StubClient(text="should never be returned")
        patch_client(stub)
        result = await compile_prose_to_octave(_ctx("x" * 50000))
        assert result["ok"] is False
        assert result["octave"] is None
        assert "cost" in result["error"].lower()
        # Hallucination/abort immunity: backend was never entered.
        assert stub.entered is False
        assert stub.request is None

    async def test_env_override_for_output_cap(self, patch_client, monkeypatch) -> None:
        monkeypatch.setenv("HESTAI_INTAKE_MAX_OUTPUT_TOKENS", "256")
        stub = _StubClient(text="===DECISION_RECORD===\n===END===")
        patch_client(stub)
        await compile_prose_to_octave(_ctx())
        assert stub.request is not None
        assert stub.request.max_tokens == 256


class TestMetricsAccounting:
    """The reported tokens metric = input estimate + ACTUAL output (no out_cap)."""

    async def test_actual_tokens_excludes_output_ceiling(self, patch_client, monkeypatch) -> None:
        from hestai_context_mcp.core.intake_compiler import _CHARS_PER_TOKEN

        # Deterministic pricing so cost follows tokens linearly.
        monkeypatch.setenv("HESTAI_INTAKE_USD_PER_1K_TOKENS", "1.0")
        monkeypatch.setenv("HESTAI_INTAKE_MAX_COST_USD", "1000000")  # never abort

        ctx = _ctx(prose="record a routing decision")
        raw = "===DECISION_RECORD===\nMETA:\n  TYPE::DECISION_RECORD\n===END==="
        stub = _StubClient(text=raw)
        patch_client(stub)

        out_cap = 8000
        result = await compile_prose_to_octave(ctx, max_output_tokens=out_cap)

        def _ceil(n: int) -> int:
            return (n + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN

        input_tokens = _ceil(len(ctx.prompt) + len(ctx.prose_input))
        output_tokens = _ceil(len(raw))
        expected = input_tokens + output_tokens

        assert result["ok"] is True
        # Exact: input estimate + ACTUAL output, NOT the output ceiling.
        assert result["metrics"]["tokens"] == expected
        # Regression guard: the old double-counting added out_cap on top.
        assert result["metrics"]["tokens"] < expected + out_cap
        assert result["metrics"]["tokens"] != input_tokens + out_cap + output_tokens
        # Cost tracks the (non-double-counted) token total at 1.0/1k.
        assert result["metrics"]["cost"] == pytest.approx(expected / 1000.0)

    async def test_prose_counted_once_in_input_estimate(self, patch_client, monkeypatch) -> None:
        # After the duplication fix, the system prompt does NOT contain the
        # prose, so input = len(prompt) + len(prose) with the prose counted once.
        from hestai_context_mcp.core.intake_compiler import (
            _CHARS_PER_TOKEN,
            _estimate_input_tokens,
        )

        ctx = _ctx(prose="a short prose request")
        # The helper's input estimate must equal prompt + prose exactly once.
        expected = (
            len(ctx.prompt) + len(ctx.prose_input) + _CHARS_PER_TOKEN - 1
        ) // _CHARS_PER_TOKEN
        assert _estimate_input_tokens(ctx) == expected
