"""submit_governance × OctaveValidator wiring tests (RFC #53 Gate B).

Verifies that the real OctaveValidator port is wired at the run_in_executor seam
in submit_governance, ADDITIVE to the regex Gate A:

* valid OCTAVE -> regex passes AND real validator passes -> proceed (dry_run
  success), with a structured ``octave_validation`` field present (PROD I4);
* invalid AST that the regex Gate A cannot see (unbalanced bracket) -> real
  validator fails -> structured failure, NO PR / NO write, regex-derived fields
  still present;
* fail-soft -> when the real validator reports ``available=False`` (the
  ``validation`` extra is absent), the tool does NOT crash and does NOT block:
  the regex Gate A still gates, and the structured "real-validation unavailable"
  signal is surfaced;
* public input contract is unchanged (still ``octave_content``).

These tests inject the validator by monkeypatching the port factory used inside
submit_governance, so they are deterministic regardless of whether octave-mcp is
installed in the running environment.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from hestai_context_mcp.ports.octave_validator import OctaveValidationResult


@pytest.fixture()
def decision_record_octave() -> str:
    """A well-formed DECISION_RECORD that passes the regex Gate A."""
    return (
        "===DECISION_RECORD===\n"
        "META:\n"
        "  TYPE::DECISION_RECORD\n"
        '  TOKEN::"HO-CONTEXT-MCP-GATEB-DECISION-20260601"\n'
        "  STATUS::PROPOSED\n"
        "===END===\n"
    )


class _StubValidator:
    """Records the content it was asked to validate and returns a canned result."""

    def __init__(self, result: OctaveValidationResult) -> None:
        self._result = result
        self.seen: list[str] = []

    def validate(self, content: str) -> OctaveValidationResult:
        self.seen.append(content)
        return self._result


def _run(working_dir: Path, content: str):
    from hestai_context_mcp.tools.submit_governance import submit_governance

    return asyncio.run(
        submit_governance(
            working_dir=str(working_dir),
            octave_content=content,
            dry_run=True,
        )
    )


class TestRealValidatorPassProceeds:
    @pytest.mark.unit
    def test_valid_passes_and_surfaces_structured_octave_validation(
        self, tmp_path: Path, decision_record_octave: str, monkeypatch
    ) -> None:
        import hestai_context_mcp.tools.submit_governance as mod

        stub = _StubValidator(
            OctaveValidationResult(ok=True, errors=[], warnings=[], available=True)
        )
        monkeypatch.setattr(mod, "get_octave_validator", lambda: stub)

        result = _run(tmp_path, decision_record_octave)

        assert result["success"] is True
        assert result["validation_errors"] == []
        # Additive structured field (PROD I4), all sub-fields present.
        assert "octave_validation" in result
        ov = result["octave_validation"]
        assert set(ov) == {"ok", "errors", "warnings", "available"}
        assert ov["ok"] is True
        assert ov["available"] is True
        # The REAL validator saw the operator's content (in-process, real wiring).
        assert stub.seen == [decision_record_octave]


class TestRealValidatorFailBlocks:
    @pytest.mark.unit
    def test_invalid_ast_fails_with_structured_error_no_pr(
        self, tmp_path: Path, decision_record_octave: str, monkeypatch
    ) -> None:
        import hestai_context_mcp.tools.submit_governance as mod

        # The regex Gate A passes (well-formed token/type) but the REAL validator
        # reports an AST defect the regex is blind to.
        stub = _StubValidator(
            OctaveValidationResult(
                ok=False,
                errors=[
                    {
                        "code": "E_UNBALANCED_BRACKET",
                        "message": "opening '[' has no matching ']'",
                        "field_path": "",
                        "line": 3,
                    }
                ],
                warnings=[],
                available=True,
            )
        )
        monkeypatch.setattr(mod, "get_octave_validator", lambda: stub)

        # Linker must never run on a real-validation failure.
        def _boom(*args, **kwargs):  # pragma: no cover - must not be called
            raise AssertionError("run_linker must not be called when real validation fails")

        monkeypatch.setattr(mod, "run_linker", _boom)

        result = _run(tmp_path, decision_record_octave)

        assert result["success"] is False
        assert result["pr_url"] is None
        # The structured octave-mcp error is merged into validation_errors.
        assert any(
            "E_UNBALANCED_BRACKET" in e or "bracket" in e.lower()
            for e in result["validation_errors"]
        )
        # Structured detail preserved (PROD I4).
        assert result["octave_validation"]["ok"] is False
        assert result["octave_validation"]["errors"][0]["code"] == "E_UNBALANCED_BRACKET"
        # Regex-derived fields still present even on real-validation failure.
        assert "token" in result
        assert "card_type" in result


class TestFailSoftDoesNotBlock:
    @pytest.mark.unit
    def test_unavailable_extra_degrades_and_proceeds(
        self, tmp_path: Path, decision_record_octave: str, monkeypatch
    ) -> None:
        import hestai_context_mcp.tools.submit_governance as mod

        # Simulate the 'validation' extra being absent: ok=True, available=False.
        stub = _StubValidator(
            OctaveValidationResult(
                ok=True,
                errors=[],
                warnings=[
                    {
                        "code": "REAL_VALIDATION_UNAVAILABLE",
                        "message": "octave-mcp not installed; regex Gate A still applied",
                        "field_path": "",
                        "line": 0,
                    }
                ],
                available=False,
            )
        )
        monkeypatch.setattr(mod, "get_octave_validator", lambda: stub)

        result = _run(tmp_path, decision_record_octave)

        # Fail-soft: the regex Gate A still gated, so a valid doc proceeds.
        assert result["success"] is True
        ov = result["octave_validation"]
        assert ov["available"] is False
        # The degrade is surfaced, not silent.
        assert any(w.get("code") == "REAL_VALIDATION_UNAVAILABLE" for w in ov["warnings"])

    @pytest.mark.unit
    def test_regex_gate_a_still_blocks_when_extra_absent(self, tmp_path: Path, monkeypatch) -> None:
        import hestai_context_mcp.tools.submit_governance as mod

        # Even with the real validator degraded, the regex Gate A must still
        # reject obviously-malformed content (no OCTAVE sentinel).
        stub = _StubValidator(
            OctaveValidationResult(ok=True, errors=[], warnings=[], available=False)
        )
        monkeypatch.setattr(mod, "get_octave_validator", lambda: stub)

        result = _run(tmp_path, "plain prose, no octave sentinel at all")

        assert result["success"] is False
        assert result["validation_errors"]


class TestPublicContractUnchanged:
    @pytest.mark.unit
    def test_input_signature_still_octave_content(self) -> None:
        import inspect

        from hestai_context_mcp.tools.submit_governance import submit_governance

        params = inspect.signature(submit_governance).parameters
        # The Gate C prose intake is NOT part of this task.
        assert set(params) == {"working_dir", "octave_content", "dry_run"}
