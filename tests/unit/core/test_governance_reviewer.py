"""Tests for the scoped SEMANTIC governance reviewer (issue #77).

``review_governance`` is an application-layer capability that consumes the
existing ``AIClient`` port (NO new port) at the **analysis tier**. It mirrors
``core/intake_compiler.py``: ``build_default_ai_client(tier=...)`` then
``async with client as c: complete_text(...)``, with the same cost-cap +
fail-soft + structured-result discipline.

Scope (the AGR decision HO-AGR-SEMANTIC-REVIEWER-ANALYSIS-TIER-20260611):
the reviewer assesses **precedence/coherence, contradiction, scope, and
concept-validity ONLY** — it is explicitly told NOT to check schema/syntax
(the deterministic validators + octave-mcp own that). It returns a structured
``ReviewResult`` (PROD I4) of the shape
``{"verdict", "assessment", "concerns", "metrics": {tokens, cost, model}}``.

Provider-agnostic (PROD I3): no vendor literal in source (asserted in
``tests/unit/test_source_invariants.py``). Never fabricates a verdict on an
auth/transport failure (structural integrity over velocity).
"""

from __future__ import annotations

from typing import Any

import pytest

import hestai_context_mcp.core.governance_reviewer as mod
from hestai_context_mcp.core.governance_reviewer import review_governance
from hestai_context_mcp.ports.ai_client import (
    AIClientAuthError,
    AIClientError,
    AIClientProtocolError,
    AIClientTransportError,
    AIClientTruncationError,
    CompletionRequest,
    CompletionResult,
)

_SAMPLE_AGR = (
    "===DECISION_RECORD===\n"
    "META:\n"
    "  TYPE::DECISION_RECORD\n"
    '  ID::"HO-EXAMPLE-20260611"\n'
    "===END===\n"
)

# A well-formed APPROVED verdict the stub can return (the reviewer parses it).
_APPROVED_RESPONSE = (
    "VERDICT::APPROVED\n"
    "ASSESSMENT::No precedence or contradiction issues; scope is coherent.\n"
    "CONCERNS::[]\n"
)
_CONCERNS_RESPONSE = (
    "VERDICT::CONCERNS\n"
    "ASSESSMENT::Possible scope overlap with an existing record.\n"
    "CONCERNS::[overlaps prior token on routing; concept name ambiguous]\n"
)
_BLOCKED_RESPONSE = (
    "VERDICT::BLOCKED\n"
    "ASSESSMENT::Directly contradicts a ratified precedence rule.\n"
    "CONCERNS::[contradicts HO-PRIOR-20260101 precedence]\n"
)


class _StubClient:
    """Async-context AIClient stub capturing the request it received.

    Returns a ``CompletionResult`` (issue #98). Usage/cost default to ``None`` so
    a bare stub exercises the estimate-fallback path; pass them to exercise the
    real-usage path.
    """

    def __init__(
        self,
        *,
        text: str = "",
        raises: BaseException | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        cost: float | None = None,
    ) -> None:
        self._text = text
        self._raises = raises
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens
        self._total_tokens = total_tokens
        self._cost = cost
        self.request: CompletionRequest | None = None
        self.entered = False
        self.closed = False

    async def __aenter__(self) -> _StubClient:
        self.entered = True
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.closed = True

    async def complete_text(self, request: CompletionRequest) -> CompletionResult:
        self.request = request
        if self._raises is not None:
            raise self._raises
        return CompletionResult(
            content=self._text,
            prompt_tokens=self._prompt_tokens,
            completion_tokens=self._completion_tokens,
            total_tokens=self._total_tokens,
            cost=self._cost,
        )


@pytest.fixture
def patch_client(monkeypatch: pytest.MonkeyPatch):
    """Patch the module-level tier-aware AIClient factory to return a stub.

    The reviewer must resolve its client via a module attribute on each call
    (composition-root seam) so this monkeypatch is honoured.
    """

    def _install(client_or_none: Any) -> Any:
        captured: dict[str, Any] = {}

        def _factory(*, tier: str = "default") -> Any:
            captured["tier"] = tier
            return client_or_none

        monkeypatch.setattr(mod, "build_default_ai_client", _factory, raising=True)
        return captured

    return _install


class TestReviewSuccess:
    async def test_returns_structured_verdict_and_metrics(self, patch_client) -> None:
        stub = _StubClient(text=_APPROVED_RESPONSE)
        patch_client(stub)
        result = await review_governance(_SAMPLE_AGR)
        assert result["verdict"] == "APPROVED"
        assert isinstance(result["assessment"], str) and result["assessment"]
        assert isinstance(result["concerns"], list)
        metrics = result["metrics"]
        assert set(metrics) == {"tokens", "cost", "model", "cost_is_estimate"}
        assert isinstance(metrics["tokens"], int) and metrics["tokens"] > 0
        assert isinstance(metrics["cost"], float) and metrics["cost"] >= 0.0
        assert isinstance(metrics["model"], str) and metrics["model"]
        # Bare stub → no provider cost → labelled estimate.
        assert metrics["cost_is_estimate"] is True

    async def test_real_usage_and_cost_reported(self, patch_client) -> None:
        stub = _StubClient(
            text=_APPROVED_RESPONSE,
            prompt_tokens=900,
            completion_tokens=120,
            total_tokens=1020,
            cost=0.0021,
        )
        patch_client(stub)
        result = await review_governance(_SAMPLE_AGR)
        metrics = result["metrics"]
        assert metrics["tokens"] == 1020
        assert metrics["cost"] == pytest.approx(0.0021)
        assert metrics["cost_is_estimate"] is False

    async def test_concerns_verdict_carries_concern_list(self, patch_client) -> None:
        stub = _StubClient(text=_CONCERNS_RESPONSE)
        patch_client(stub)
        result = await review_governance(_SAMPLE_AGR)
        assert result["verdict"] == "CONCERNS"
        assert len(result["concerns"]) >= 1

    async def test_blocked_verdict_parsed(self, patch_client) -> None:
        stub = _StubClient(text=_BLOCKED_RESPONSE)
        patch_client(stub)
        result = await review_governance(_SAMPLE_AGR)
        assert result["verdict"] == "BLOCKED"
        assert result["concerns"]

    async def test_octave_content_is_in_user_prompt(self, patch_client) -> None:
        stub = _StubClient(text=_APPROVED_RESPONSE)
        patch_client(stub)
        await review_governance(_SAMPLE_AGR)
        assert stub.request is not None
        assert "HO-EXAMPLE-20260611" in stub.request.user_prompt


class TestTierSelection:
    async def test_defaults_to_analysis_tier(self, patch_client) -> None:
        stub = _StubClient(text=_APPROVED_RESPONSE)
        captured = patch_client(stub)
        await review_governance(_SAMPLE_AGR)
        assert captured["tier"] == "analysis"

    async def test_tier_is_overridable(self, patch_client) -> None:
        stub = _StubClient(text=_APPROVED_RESPONSE)
        captured = patch_client(stub)
        await review_governance(_SAMPLE_AGR, tier="critical")
        assert captured["tier"] == "critical"


class TestPromptIsSemanticScoped:
    """The prompt must be SEMANTIC-scoped, NOT schema-checking.

    The deterministic validators own schema; the reviewer must be told to
    assess precedence/contradiction/scope/concept-validity and explicitly
    NOT to check schema or syntax.
    """

    async def test_prompt_names_semantic_axes(self, patch_client) -> None:
        stub = _StubClient(text=_APPROVED_RESPONSE)
        patch_client(stub)
        await review_governance(_SAMPLE_AGR)
        assert stub.request is not None
        prompt = stub.request.system_prompt.lower()
        assert "precedence" in prompt
        assert "contradict" in prompt  # contradiction / contradict
        assert "scope" in prompt
        assert "concept" in prompt

    async def test_prompt_explicitly_excludes_schema_checking(self, patch_client) -> None:
        stub = _StubClient(text=_APPROVED_RESPONSE)
        patch_client(stub)
        await review_governance(_SAMPLE_AGR)
        assert stub.request is not None
        prompt = stub.request.system_prompt.lower()
        # Must mention schema/syntax in a NEGATIVE instruction (do not check).
        assert "schema" in prompt
        assert "not" in prompt
        # A crude proximity check: the word "schema" appears alongside a
        # negation cue so the instruction is exclusionary, not additive.
        assert ("do not" in prompt) or ("never" in prompt) or ("not check" in prompt)

    async def test_prompt_does_not_request_a_facet_card(self, patch_client) -> None:
        # The reviewer must not ASK for a facet card. If "facet" appears at all
        # it must be in an exclusionary instruction (do not / no facet card).
        stub = _StubClient(text=_APPROVED_RESPONSE)
        patch_client(stub)
        await review_governance(_SAMPLE_AGR)
        assert stub.request is not None
        prompt = stub.request.system_prompt.lower()
        if "facet" in prompt:
            assert ("do not produce a facet" in prompt) or ("no facet" in prompt)


class TestCostIsEstimateSemantics:
    """Issue #99 (Finding 3): cost_is_estimate must be False on zero-cost paths.

    Mirrors Finding 2 in intake_compiler: auth errors and no-credential failures
    cost definitively $0. Transport errors remain ``True`` (unknown billing).
    """

    async def test_no_credential_blocked_has_cost_is_estimate_false(self, patch_client) -> None:
        """No AIClient → definitively $0; cost_is_estimate must be False."""
        patch_client(None)
        result = await review_governance(_SAMPLE_AGR)
        assert result["verdict"] == "BLOCKED"
        assert result["metrics"]["cost_is_estimate"] is False, (
            "No-credential BLOCKED is definitively $0 (provider never called); "
            "cost_is_estimate must be False, not True"
        )

    async def test_auth_error_blocked_has_cost_is_estimate_false(self, patch_client) -> None:
        """Auth error → provider rejected before billing; cost_is_estimate must be False."""
        stub = _StubClient(raises=AIClientAuthError("no key"))
        patch_client(stub)
        result = await review_governance(_SAMPLE_AGR)
        assert result["verdict"] == "BLOCKED"
        assert result["metrics"]["cost_is_estimate"] is False, (
            "Auth error is a pre-billing rejection; cost is definitively $0; "
            "cost_is_estimate must be False"
        )

    async def test_transport_error_blocked_retains_cost_is_estimate_true(
        self, patch_client
    ) -> None:
        """Transport error → unknown whether provider billed; cost_is_estimate stays True."""
        stub = _StubClient(raises=AIClientTransportError("timeout"))
        patch_client(stub)
        result = await review_governance(_SAMPLE_AGR)
        assert result["verdict"] == "BLOCKED"
        assert result["metrics"]["cost_is_estimate"] is True


class TestNoClientAvailable:
    async def test_returns_structured_failure_when_no_client(self, patch_client) -> None:
        patch_client(None)
        result = await review_governance(_SAMPLE_AGR)
        assert result["verdict"] == "BLOCKED"
        assert result["concerns"]
        assert result["metrics"]["tokens"] == 0


class TestFailSoftErrorPaths:
    """Auth/transport/protocol failures NEVER fabricate a verdict."""

    async def test_auth_error_is_blocked_not_approved(self, patch_client) -> None:
        stub = _StubClient(raises=AIClientAuthError("no key"))
        patch_client(stub)
        result = await review_governance(_SAMPLE_AGR)
        assert result["verdict"] == "BLOCKED"
        assert "auth" in result["assessment"].lower() or any(
            "auth" in c.lower() for c in result["concerns"]
        )

    async def test_transport_error_surfaced_not_fabricated(self, patch_client) -> None:
        stub = _StubClient(raises=AIClientTransportError("timeout"))
        patch_client(stub)
        result = await review_governance(_SAMPLE_AGR)
        assert result["verdict"] == "BLOCKED"
        # No fabricated APPROVED verdict from a transport failure.
        assert result["verdict"] != "APPROVED"

    async def test_protocol_error_surfaced(self, patch_client) -> None:
        stub = _StubClient(raises=AIClientProtocolError("bad body"))
        patch_client(stub)
        result = await review_governance(_SAMPLE_AGR)
        assert result["verdict"] == "BLOCKED"

    async def test_generic_ai_client_error_surfaced(self, patch_client) -> None:
        # The catch-all AIClientError branch (not auth/transport) also degrades
        # to a structured BLOCKED result, never a fabricated verdict.
        stub = _StubClient(raises=AIClientError("weird"))
        patch_client(stub)
        result = await review_governance(_SAMPLE_AGR)
        assert result["verdict"] == "BLOCKED"
        assert result["concerns"]

    async def test_empty_response_is_not_approved(self, patch_client) -> None:
        stub = _StubClient(text="   ")
        patch_client(stub)
        result = await review_governance(_SAMPLE_AGR)
        assert result["verdict"] == "BLOCKED"

    async def test_truncation_records_real_cost_and_is_blocked(
        self, patch_client, monkeypatch
    ) -> None:
        """Issue #96: a truncated review records REAL tokens/cost, never APPROVED.

        Mirrors the intake_compiler accounting fix so the shared AIClient path
        is handled consistently: finish_reason=length is billed, so the metrics
        must reflect the real spend instead of collapsing to 0/0.
        """
        monkeypatch.setenv("HESTAI_REVIEW_USD_PER_1K_TOKENS", "1.0")
        monkeypatch.setenv("HESTAI_REVIEW_MAX_COST_USD", "1000000")  # never abort pre-call
        stub = _StubClient(raises=AIClientTruncationError("truncated", consumed_tokens=2000))
        patch_client(stub)
        result = await review_governance(_SAMPLE_AGR)
        assert result["verdict"] == "BLOCKED"
        assert result["verdict"] != "APPROVED"
        assert result["metrics"]["tokens"] == 2000
        # No provider cost on the error → labelled flat-rate estimate.
        assert result["metrics"]["cost"] == pytest.approx(2.0)
        assert result["metrics"]["cost_is_estimate"] is True

    async def test_truncation_records_real_cost_when_available(
        self, patch_client, monkeypatch
    ) -> None:
        monkeypatch.setenv("HESTAI_REVIEW_MAX_COST_USD", "1000000")
        stub = _StubClient(
            raises=AIClientTruncationError("truncated", consumed_tokens=2000, cost=0.0031)
        )
        patch_client(stub)
        result = await review_governance(_SAMPLE_AGR)
        assert result["verdict"] == "BLOCKED"
        assert result["metrics"]["tokens"] == 2000
        assert result["metrics"]["cost"] == pytest.approx(0.0031)
        assert result["metrics"]["cost_is_estimate"] is False


class TestCostCap:
    async def test_cost_cap_aborts_before_call(self, patch_client) -> None:
        stub = _StubClient(text=_APPROVED_RESPONSE)
        patch_client(stub)
        # A microscopic cost cap forces a pre-call abort.
        result = await review_governance(_SAMPLE_AGR, max_cost_usd=0.0)
        assert result["verdict"] == "BLOCKED"
        # The backend was never entered (abort before the call).
        assert stub.entered is False
        assert any("cost" in c.lower() for c in result["concerns"]) or (
            "cost" in result["assessment"].lower()
        )

    async def test_output_cap_passed_to_request(self, patch_client) -> None:
        stub = _StubClient(text=_APPROVED_RESPONSE)
        patch_client(stub)
        await review_governance(_SAMPLE_AGR, max_output_tokens=123)
        assert stub.request is not None
        assert stub.request.max_tokens == 123

    async def test_env_caps_used_when_args_absent(
        self, monkeypatch: pytest.MonkeyPatch, patch_client
    ) -> None:
        stub = _StubClient(text=_APPROVED_RESPONSE)
        patch_client(stub)
        monkeypatch.setenv("HESTAI_REVIEW_MAX_OUTPUT_TOKENS", "55")
        await review_governance(_SAMPLE_AGR)
        assert stub.request is not None
        assert stub.request.max_tokens == 55

    async def test_invalid_env_caps_fall_back_to_defaults(
        self, monkeypatch: pytest.MonkeyPatch, patch_client
    ) -> None:
        # Malformed env caps must not crash; they fall back to the defaults
        # (warning logged). The call still succeeds.
        stub = _StubClient(text=_APPROVED_RESPONSE)
        patch_client(stub)
        monkeypatch.setenv("HESTAI_REVIEW_MAX_OUTPUT_TOKENS", "not-an-int")
        monkeypatch.setenv("HESTAI_REVIEW_MAX_COST_USD", "not-a-float")
        monkeypatch.setenv("HESTAI_REVIEW_USD_PER_1K_TOKENS", "nan-nan")
        result = await review_governance(_SAMPLE_AGR)
        assert result["verdict"] == "APPROVED"
        assert stub.request is not None
        # Fell back to the default 2000-token output ceiling.
        assert stub.request.max_tokens == 2000


class TestResultShape:
    async def test_unparseable_verdict_falls_back_to_concerns(self, patch_client) -> None:
        # A response with prose but no recognisable VERDICT:: line must not be
        # silently treated as APPROVED — degrade to CONCERNS for human review.
        stub = _StubClient(text="The record looks broadly fine to me.")
        patch_client(stub)
        result = await review_governance(_SAMPLE_AGR)
        assert result["verdict"] in {"CONCERNS", "BLOCKED"}
        assert result["verdict"] != "APPROVED"
