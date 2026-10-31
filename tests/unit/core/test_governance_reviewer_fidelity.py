"""RED suite — Stage-5 RULE-vs-VERBATIM fidelity review for appends (issue #203 S5, minimal).

Operator ruling (#203, design note §9 Q4): on appends the auto-SR checks each
RULE against its VERBATIM, and nothing else. ``review_ruling_fidelity``:

* sees ONLY the ``(id, RULE, VERBATIM)`` pairs -- never the rest of the record;
* asks one question: does RULE faithfully state what VERBATIM says?
* allows exactly two verdicts: APPROVED, or CONCERNS naming the pairs;
* never comments on wording style or schema;
* shares the existing reviewer plumbing (tier, cost cap, fail-soft
  ``reviewer_available=False`` on operational failure).
"""

from __future__ import annotations

from typing import Any

import pytest

import hestai_context_mcp.core.governance_reviewer as mod
from hestai_context_mcp.core.governance_reviewer import review_ruling_fidelity
from hestai_context_mcp.ports.ai_client import (
    AIClientTransportError,
    CompletionRequest,
    CompletionResult,
)

_PAIRS = [
    {
        "id": "R4",
        "rule": "Contractors get read-only access.",
        "verbatim": 'contractors, "read only"',
    },
    {"id": "R5", "rule": "Notes ship weekly.", "verbatim": "notes every week\nno skipping"},
]


class _Stub:
    def __init__(self, text: str = "", raises: BaseException | None = None) -> None:
        self.text, self.raises = text, raises
        self.request: CompletionRequest | None = None

    async def __aenter__(self) -> _Stub:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def complete_text(self, request: CompletionRequest) -> CompletionResult:
        self.request = request
        if self.raises is not None:
            raise self.raises
        return CompletionResult(content=self.text)


@pytest.fixture
def install(monkeypatch: pytest.MonkeyPatch):
    def _install(client: Any) -> dict[str, Any]:
        seen: dict[str, Any] = {}

        def factory(*, tier: str = "default", working_dir: Any = None) -> Any:
            seen["tier"] = tier
            return client

        monkeypatch.setattr(mod, "build_default_ai_client", factory)
        monkeypatch.setattr(mod, "_resolve_model_name", lambda tier, wd=None: "model-x")
        return seen

    return _install


class TestPromptScope:
    async def test_user_prompt_carries_only_the_pairs(self, install) -> None:
        stub = _Stub("VERDICT::APPROVED\nASSESSMENT::faithful\nCONCERNS::[]\n")
        install(stub)
        await review_ruling_fidelity(_PAIRS)
        assert stub.request is not None
        prompt = stub.request.user_prompt
        for pair in _PAIRS:
            assert pair["id"] in prompt
            assert pair["rule"] in prompt
            assert pair["verbatim"] in prompt
        assert "BEGIN_RECORD" not in prompt
        assert "META" not in prompt and "DECISION_RECORD" not in prompt

    async def test_system_prompt_asks_only_the_fidelity_question(self, install) -> None:
        stub = _Stub("VERDICT::APPROVED\nASSESSMENT::ok\nCONCERNS::[]\n")
        install(stub)
        await review_ruling_fidelity(_PAIRS)
        assert stub.request is not None
        system = stub.request.system_prompt
        assert "faithfully" in system
        assert "VERDICT::<APPROVED|CONCERNS>" in system
        lowered = system.lower()
        assert "do not comment on wording style" in lowered
        assert "schema" in lowered
        # The whole-record rubric is NOT reused.
        assert system != mod._REVIEW_SYSTEM_PROMPT
        assert "PRECEDENCE" not in system

    async def test_runs_at_the_analysis_tier_by_default(self, install) -> None:
        seen = install(_Stub("VERDICT::APPROVED\nASSESSMENT::ok\nCONCERNS::[]\n"))
        await review_ruling_fidelity(_PAIRS)
        assert seen["tier"] == "analysis"


class TestVerdicts:
    async def test_approved(self, install) -> None:
        install(_Stub("VERDICT::APPROVED\nASSESSMENT::Both rules match.\nCONCERNS::[]\n"))
        result = await review_ruling_fidelity(_PAIRS)
        assert result["verdict"] == "APPROVED"
        assert result["concerns"] == []
        assert result["reviewer_available"] is True
        assert result.get("fidelity_pairs") == []

    async def test_concerns_name_the_pairs(self, install) -> None:
        install(
            _Stub(
                "VERDICT::CONCERNS\nASSESSMENT::R5 overstates.\n"
                "CONCERNS::[R5: verbatim says every week, rule adds shipping]\n"
            )
        )
        result = await review_ruling_fidelity(_PAIRS)
        assert result["verdict"] == "CONCERNS"
        assert result["fidelity_pairs"] == ["R5"]
        assert any("R5" in c for c in result["concerns"])

    async def test_concerns_without_a_named_pair_flag_every_pair(self, install) -> None:
        install(_Stub("VERDICT::CONCERNS\nASSESSMENT::unclear\nCONCERNS::[something is off]\n"))
        result = await review_ruling_fidelity(_PAIRS)
        assert result["verdict"] == "CONCERNS"
        assert result["fidelity_pairs"] == ["R4", "R5"]

    async def test_unknown_pair_ids_are_ignored(self, install) -> None:
        install(_Stub("VERDICT::CONCERNS\nASSESSMENT::x\nCONCERNS::[R9: not a pair; R4: drifts]\n"))
        result = await review_ruling_fidelity(_PAIRS)
        assert result["fidelity_pairs"] == ["R4"]

    @pytest.mark.parametrize("verdict", ["BLOCKED", "WORDING"])
    async def test_other_verdicts_are_never_passed_through(self, install, verdict: str) -> None:
        install(_Stub(f"VERDICT::{verdict}\nASSESSMENT::x\nWORDING_FIXES::[tidy]\nCONCERNS::[]\n"))
        result = await review_ruling_fidelity(_PAIRS)
        assert result["verdict"] == "CONCERNS"
        assert result["fidelity_pairs"] == ["R4", "R5"]
        assert "wording_fixes" not in result

    async def test_approved_with_listed_concerns_is_not_approved(self, install) -> None:
        install(_Stub("VERDICT::APPROVED\nASSESSMENT::x\nCONCERNS::[R4: drifts]\n"))
        result = await review_ruling_fidelity(_PAIRS)
        assert result["verdict"] == "CONCERNS"
        assert result["fidelity_pairs"] == ["R4"]

    async def test_approved_without_a_concerns_line_fails_closed(self, install) -> None:
        install(_Stub("VERDICT::APPROVED\nASSESSMENT::looks fine\n"))
        result = await review_ruling_fidelity(_PAIRS)
        assert result["verdict"] == "CONCERNS"
        assert result["fidelity_pairs"] == ["R4", "R5"]
        assert any("CONCERNS::[]" in c for c in result["concerns"])

    @pytest.mark.parametrize("block", ["[;]", "[ ; ]", "[\n;\n]"])
    async def test_approved_with_a_separator_only_concerns_block_fails_closed(
        self, install, block: str
    ) -> None:
        install(_Stub(f"VERDICT::APPROVED\nASSESSMENT::x\nCONCERNS::{block}\n"))
        result = await review_ruling_fidelity(_PAIRS)
        assert result["verdict"] == "CONCERNS"
        assert result["fidelity_pairs"] == ["R4", "R5"]

    @pytest.mark.parametrize("block", ["[]", "[   ]", "[\n]"])
    async def test_approved_with_a_whitespace_only_concerns_block_is_approved(
        self, install, block: str
    ) -> None:
        install(_Stub(f"VERDICT::APPROVED\nASSESSMENT::x\nCONCERNS::{block}\n"))
        result = await review_ruling_fidelity(_PAIRS)
        assert result["verdict"] == "APPROVED"
        assert result["fidelity_pairs"] == []

    async def test_unparseable_response_is_concerns(self, install) -> None:
        install(_Stub("I think it is fine."))
        result = await review_ruling_fidelity(_PAIRS)
        assert result["verdict"] == "CONCERNS"
        assert result["reviewer_available"] is True


class TestOperationalFailures:
    async def test_no_client_is_unavailable(self, install) -> None:
        install(None)
        result = await review_ruling_fidelity(_PAIRS)
        assert result["reviewer_available"] is False
        assert result["verdict"] != "APPROVED"

    async def test_transport_error_is_unavailable(self, install) -> None:
        install(_Stub(raises=AIClientTransportError("down")))
        result = await review_ruling_fidelity(_PAIRS)
        assert result["reviewer_available"] is False

    async def test_empty_response_is_unavailable(self, install) -> None:
        install(_Stub("   "))
        result = await review_ruling_fidelity(_PAIRS)
        assert result["reviewer_available"] is False

    async def test_cost_cap_aborts_before_the_call(self, install) -> None:
        stub = _Stub("VERDICT::APPROVED\nASSESSMENT::x\nCONCERNS::[]\n")
        install(stub)
        result = await review_ruling_fidelity(_PAIRS, max_cost_usd=0.0)
        assert result["reviewer_available"] is False
        assert stub.request is None

    async def test_no_pairs_is_refused_without_a_call(self, install) -> None:
        stub = _Stub("VERDICT::APPROVED\nASSESSMENT::x\nCONCERNS::[]\n")
        install(stub)
        result = await review_ruling_fidelity([])
        assert result["reviewer_available"] is False
        assert stub.request is None
