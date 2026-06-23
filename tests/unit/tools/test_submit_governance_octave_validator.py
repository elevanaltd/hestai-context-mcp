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
    """A fully-formed DECISION_RECORD that passes the regex Gate A.

    Carries every §1.2 required field (post-#88 Gate A enforces presence,
    enums, and TOKEN-date consistency: the 20260601 suffix matches AUTHORED_AT).
    """
    return (
        "===DECISION_RECORD===\n"
        "META:\n"
        "  TYPE::DECISION_RECORD\n"
        '  VERSION::"1.0"\n'
        '  TOKEN::"HO-CONTEXT-MCP-GATEB-DECISION-20260601"\n'
        "  STATUS::PROPOSED\n"
        "  TIER::OPERATIONAL\n"
        '  DECISION::"A binding decision for the Gate B test."\n'
        '  BECAUSE::"Exercises the real OCTAVE validator seam."\n'
        '  AUTHORED_AT::"2026-06-01T00:00:00Z"\n'
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


class TestRealValidationTopLevelSignal:
    """#108.4 Option L: the degrade must be an EXPLICIT top-level signal.

    ``real_validation_available`` is surfaced at the TOP LEVEL of the result on
    both submission paths so a fail-soft degrade cannot hide inside
    ``octave_validation.warnings``.
    """

    @pytest.mark.unit
    def test_available_true_surfaces_top_level_true(
        self, tmp_path: Path, decision_record_octave: str, monkeypatch
    ) -> None:
        import hestai_context_mcp.tools.submit_governance as mod

        stub = _StubValidator(
            OctaveValidationResult(ok=True, errors=[], warnings=[], available=True)
        )
        monkeypatch.setattr(mod, "get_octave_validator", lambda: stub)

        result = _run(tmp_path, decision_record_octave)

        assert result["success"] is True
        # Explicit, top-level (NOT buried in octave_validation).
        assert result["real_validation_available"] is True

    @pytest.mark.unit
    def test_unavailable_surfaces_top_level_false_and_proceeds(
        self, tmp_path: Path, decision_record_octave: str, monkeypatch
    ) -> None:
        import hestai_context_mcp.tools.submit_governance as mod

        stub = _StubValidator(
            OctaveValidationResult(ok=True, errors=[], warnings=[], available=False)
        )
        monkeypatch.setattr(mod, "get_octave_validator", lambda: stub)

        result = _run(tmp_path, decision_record_octave)

        # Flag OFF (default) -> proceeds (fail-soft), but the degrade is LOUD.
        assert result["success"] is True
        assert result["real_validation_available"] is False
        # And it is a TOP-LEVEL key, not only inside octave_validation.warnings.
        assert "real_validation_available" in result


class TestFailClosedOptIn:
    """#108.4 Option C: opt-in fail-closed flag (default OFF)."""

    @pytest.mark.unit
    def test_flag_on_unavailable_hard_blocks_no_linker(
        self, tmp_path: Path, decision_record_octave: str, monkeypatch
    ) -> None:
        import hestai_context_mcp.tools.submit_governance as mod

        stub = _StubValidator(
            OctaveValidationResult(ok=True, errors=[], warnings=[], available=False)
        )
        monkeypatch.setattr(mod, "get_octave_validator", lambda: stub)
        # Force the fail-closed policy ON regardless of env/.env.
        monkeypatch.setattr(mod, "resolve_require_real_validation", lambda working_dir: True)

        def _boom(*args, **kwargs):  # pragma: no cover - must not be called
            raise AssertionError("run_linker must not run when fail-closed blocks")

        monkeypatch.setattr(mod, "run_linker", _boom)

        result = _run(tmp_path, decision_record_octave)

        assert result["success"] is False
        assert result["pr_url"] is None
        assert result["real_validation_available"] is False
        # Structured PROD-I4 error naming the missing extra + how to install.
        joined = " ".join(result["validation_errors"]).lower()
        assert "validation" in joined and ("install" in joined or "extra" in joined)

    @pytest.mark.unit
    def test_flag_on_but_available_proceeds(
        self, tmp_path: Path, decision_record_octave: str, monkeypatch
    ) -> None:
        """Flag ON but the real validator IS available -> normal proceed (no block)."""
        import hestai_context_mcp.tools.submit_governance as mod

        stub = _StubValidator(
            OctaveValidationResult(ok=True, errors=[], warnings=[], available=True)
        )
        monkeypatch.setattr(mod, "get_octave_validator", lambda: stub)
        monkeypatch.setattr(mod, "resolve_require_real_validation", lambda working_dir: True)

        result = _run(tmp_path, decision_record_octave)

        assert result["success"] is True
        assert result["real_validation_available"] is True

    @pytest.mark.unit
    def test_flag_off_unavailable_is_byte_stable_proceed(
        self, tmp_path: Path, decision_record_octave: str, monkeypatch
    ) -> None:
        """Flag OFF + unavailable -> proceeds (only the additive signal differs)."""
        import hestai_context_mcp.tools.submit_governance as mod

        stub = _StubValidator(
            OctaveValidationResult(ok=True, errors=[], warnings=[], available=False)
        )
        monkeypatch.setattr(mod, "get_octave_validator", lambda: stub)
        monkeypatch.setattr(mod, "resolve_require_real_validation", lambda working_dir: False)

        result = _run(tmp_path, decision_record_octave)

        assert result["success"] is True
        assert result["real_validation_available"] is False


class TestPublicContractUnchanged:
    @pytest.mark.unit
    def test_input_signature_adds_prose_input_back_compatibly(self) -> None:
        import inspect

        from hestai_context_mcp.tools.submit_governance import submit_governance

        params = inspect.signature(submit_governance).parameters
        # Gate C (T5) adds prose_input back-compatibly: octave_content becomes
        # optional and prose_input is the second mode. Issue #77 adds the
        # ``review`` flag back-compatibly (defaults True). The pre-existing
        # params remain so octave_content callers are unaffected.
        assert set(params) == {
            "working_dir",
            "octave_content",
            "prose_input",
            "dry_run",
            "review",
        }
        # Back-compat: octave_content is now optional (defaults to None) so the
        # EXACTLY-ONE-OF guard can distinguish the two modes.
        assert params["octave_content"].default is None
        assert params["prose_input"].default is None
        # Issue #77: review defaults True (Stage 5 active on real PRs by default).
        assert params["review"].default is True
