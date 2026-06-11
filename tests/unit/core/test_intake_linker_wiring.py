"""Tests for Stage-4 linker wiring (RFC #53 Gate C, T4).

``run_intake_to_pr`` composes Stage 3 (validate->retry->abort) with Stage 4
(the EXISTING ``run_linker``). On a passing pipeline it passes the validated
OCTAVE + ValidationResult into ``run_linker`` (branch->write->commit->PR). On an
aborting pipeline it returns the structured failure and NEVER calls the linker
(hallucination immunity at the integration seam).

Human Primacy (PROD I3): no auto-merge, no direct-main commit. The linker only
opens a PR; this is asserted structurally against the linker's subprocess argv.

NO new git code is introduced by T4 — it reuses ``run_linker`` verbatim.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import hestai_context_mcp.core.intake_pipeline as mod
from hestai_context_mcp.core.intake_pipeline import run_intake_to_pr
from hestai_context_mcp.tools.governance.intake_context import IntakeContext
from hestai_context_mcp.tools.governance.type_checker import ValidationResult

_VALID_OCTAVE = (
    "===DECISION_RECORD===\n"
    "META:\n"
    "  TYPE::DECISION_RECORD\n"
    '  TOKEN::"HO-CONTEXT-MCP-NEWREC-20260601"\n'
    "===END===\n"
)


def _ctx() -> IntakeContext:
    return IntakeContext(prose_input="record a decision", corpus="", prompt="P", relevant_tokens=())


def _pipeline_ok() -> dict[str, Any]:
    return {
        "ok": True,
        "octave": _VALID_OCTAVE,
        "validation": ValidationResult(
            valid=True,
            errors=[],
            token="HO-CONTEXT-MCP-NEWREC-20260601",
            card_type="DECISION_RECORD",
            target_path=Path(".hestai/decisions/HO-CONTEXT-MCP-NEWREC-20260601.oct.md"),
        ),
        "validation_errors": [],
        "metrics": {"tokens": 10, "cost": 0.01, "model": "test-model"},
        "attempts": 1,
    }


def _pipeline_abort() -> dict[str, Any]:
    return {
        "ok": False,
        "octave": None,
        "validation": None,
        "validation_errors": ["No OCTAVE sentinel found at document start."],
        "metrics": {"tokens": 10, "cost": 0.0, "model": "test-model"},
        "attempts": 2,
    }


@pytest.fixture
def stub_pipeline(monkeypatch: pytest.MonkeyPatch):
    def _install(result: dict[str, Any]) -> None:
        async def _fake(*args: Any, **kwargs: Any) -> dict[str, Any]:
            return result

        monkeypatch.setattr(mod, "run_intake_pipeline", _fake, raising=True)

    return _install


@pytest.fixture
def spy_linker(monkeypatch: pytest.MonkeyPatch):
    class _Spy:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def __call__(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(kwargs)
            return {
                "token": kwargs["validation"].token,
                "card_type": kwargs["validation"].card_type,
                "target_path": ".hestai/decisions/HO-CONTEXT-MCP-NEWREC-20260601.oct.md",
                "branch": "governance/20260601-ho-context-mcp-newrec-20260601",
                "pr_url": None if kwargs["dry_run"] else "https://example/pr/1",
                "error": None,
                "dry_run": kwargs["dry_run"],
            }

    spy = _Spy()
    monkeypatch.setattr(mod, "run_linker", spy, raising=True)
    return spy


class TestSuccessWiresLinker:
    async def test_validated_octave_passed_to_linker(
        self, tmp_path: Path, stub_pipeline, spy_linker
    ) -> None:
        stub_pipeline(_pipeline_ok())
        result = await run_intake_to_pr(tmp_path, _ctx(), dry_run=True)
        assert result["success"] is True
        assert len(spy_linker.calls) == 1
        call = spy_linker.calls[0]
        # The EXACT validated OCTAVE + ValidationResult flow into the linker.
        assert call["octave_content"] == _VALID_OCTAVE
        assert call["validation"].token == "HO-CONTEXT-MCP-NEWREC-20260601"
        assert call["dry_run"] is True

    async def test_result_includes_metrics_and_pr_fields(
        self, tmp_path: Path, stub_pipeline, spy_linker
    ) -> None:
        stub_pipeline(_pipeline_ok())
        result = await run_intake_to_pr(tmp_path, _ctx(), dry_run=False)
        assert result["token"] == "HO-CONTEXT-MCP-NEWREC-20260601"
        assert result["card_type"] == "DECISION_RECORD"
        assert result["branch"]
        assert result["pr_url"] == "https://example/pr/1"
        assert result["metrics"]["model"] == "test-model"
        assert result["validation_errors"] == []


class TestAbortDoesNotWireLinker:
    async def test_pipeline_abort_never_calls_linker(
        self, tmp_path: Path, stub_pipeline, spy_linker
    ) -> None:
        stub_pipeline(_pipeline_abort())
        result = await run_intake_to_pr(tmp_path, _ctx(), dry_run=False)
        assert result["success"] is False
        assert result["validation_errors"]
        assert result["pr_url"] is None
        # Hallucination immunity at the seam: linker NEVER invoked on abort.
        assert spy_linker.calls == []


class TestHumanPrimacy:
    def test_linker_argv_has_no_auto_merge(self) -> None:
        # Structural Human-Primacy guard: the reused linker opens a PR and never
        # merges. Assert the linker source contains no auto-merge / merge call.
        from hestai_context_mcp.tools.governance import linker as linker_mod

        src = Path(linker_mod.__file__).read_text(encoding="utf-8")
        assert "--auto-merge" not in src
        assert "pr merge" not in src.lower()
        assert '"merge"' not in src

    async def test_no_new_git_code_in_pipeline(self) -> None:
        # T4 introduces NO new git invocation: the pipeline module must not
        # shell out to git/gh itself; it delegates to run_linker.
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "subprocess" not in src
        assert "gh pr" not in src
