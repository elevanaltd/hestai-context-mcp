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
