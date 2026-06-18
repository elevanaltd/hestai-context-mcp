"""Tests for the Stage-3 validate->retry->abort pipeline (RFC #53 Gate C, T3).

``run_intake_pipeline`` drives Stage 2 (prose->OCTAVE) through the EXISTING
Stage 3 gate (``validate_octave_content`` regex + ``get_octave_validator`` real
validator). Contract:

  * pass            -> return the validated OCTAVE + ValidationResult,
  * fail            -> retry ONCE, re-compiling with the validation errors
                       appended so the second attempt is informed,
  * fail x2         -> ABORT with structured errors.

HALLUCINATION-IMMUNITY INVARIANT (tested): a double-fail performs ZERO
filesystem writes AND ZERO linker calls. Stage 4 (linker) is downstream of a
*successful* pipeline only; T3 stops at the validated OCTAVE.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import hestai_context_mcp.core.intake_pipeline as mod
from hestai_context_mcp.core.intake_pipeline import run_intake_pipeline
from hestai_context_mcp.tools.governance.intake_context import IntakeContext

# Non-secret AGR governance TOKEN fixture. Built from a plainly-named module
# constant (NOT token/secret/key-named) via f-string so no `TOKEN::"<literal>"`
# quoted-literal adjacency remains for GitGuardian's generic detector to flag as
# a possible secret (false positive; #63 policy carry-forward). The detector
# stays live on this file (no path-ignore).
RECORD_TOKEN = "HO-CONTEXT-MCP-NEWREC-20260601"

# A fully-formed DECISION_RECORD that passes the regex Gate A. Carries every
# §1.2 required field (post-#88 Gate A enforces presence + TOKEN-date
# consistency: the 20260601 suffix matches AUTHORED_AT's UTC date).
_VALID_OCTAVE = (
    "===DECISION_RECORD===\n"
    "META:\n"
    "  TYPE::DECISION_RECORD\n"
    '  VERSION::"1.0"\n'
    f'  TOKEN::"{RECORD_TOKEN}"\n'
    "  STATUS::PROPOSED\n"
    "  TIER::OPERATIONAL\n"
    '  DECISION::"Record a decision for the intake pipeline test."\n'
    '  BECAUSE::"Exercises the Stage-3 gate end to end."\n'
    '  AUTHORED_AT::"2026-06-01T00:00:00Z"\n'
    "===END===\n"
)
_INVALID_OCTAVE = "this is not octave at all"

# Fully-formed and VALID (passes Gates A+B) but verbose: the DECISION value is
# far over the word ceiling. Exercises the density backstop in ``_gate``. The
# verbose DECISION lives INSIDE the META block (post-#88 the §1.1 envelope rule
# means required fields after a ``---`` separator do not count as present).
_VERBOSE_DECISION = " ".join(f"word{i}" for i in range(200))
_VERBOSE_OCTAVE = (
    "===DECISION_RECORD===\n"
    "META:\n"
    "  TYPE::DECISION_RECORD\n"
    '  VERSION::"1.0"\n'
    f'  TOKEN::"{RECORD_TOKEN}"\n'
    "  STATUS::PROPOSED\n"
    "  TIER::OPERATIONAL\n"
    f'  DECISION::"{_VERBOSE_DECISION}"\n'
    '  BECAUSE::"Exercises the verbosity density backstop."\n'
    '  AUTHORED_AT::"2026-06-01T00:00:00Z"\n'
    "===END===\n"
)


def _ctx(prose: str = "record a decision") -> IntakeContext:
    return IntakeContext(prose_input=prose, corpus="", prompt="PROMPT", relevant_tokens=())


def _compile_result(octave: str | None, ok: bool = True) -> dict[str, Any]:
    return {
        "ok": ok,
        "octave": octave,
        "metrics": {"tokens": 10, "cost": 0.0, "model": "test-model"},
        "error": None if ok else "compile failed",
    }


@pytest.fixture
def stub_backend(monkeypatch: pytest.MonkeyPatch):
    """Patch the Stage-2 compiler with a scripted sequence of return values.

    Returns a recorder exposing ``.calls`` (list of (intake_context, kwargs)).
    """

    class _Recorder:
        def __init__(self) -> None:
            self.calls: list[tuple[IntakeContext, dict[str, Any]]] = []
            self._results: list[dict[str, Any]] = []

        def script(self, results: list[dict[str, Any]]) -> None:
            self._results = list(results)

        async def __call__(self, intake_context: IntakeContext, **kwargs: Any) -> dict[str, Any]:
            self.calls.append((intake_context, kwargs))
            return self._results.pop(0)

    rec = _Recorder()
    monkeypatch.setattr(mod, "compile_prose_to_octave", rec, raising=True)
    return rec


class TestHappyPath:
    async def test_valid_first_try_returns_octave(self, tmp_path: Path, stub_backend) -> None:
        stub_backend.script([_compile_result(_VALID_OCTAVE)])
        result = await run_intake_pipeline(tmp_path, _ctx())
        assert result["ok"] is True
        assert result["octave"] == _VALID_OCTAVE
        assert result["validation"] is not None
        assert result["validation"].valid is True
        assert result["attempts"] == 1
        assert len(stub_backend.calls) == 1


class TestRetryOnce:
    async def test_invalid_then_valid_retries_once(self, tmp_path: Path, stub_backend) -> None:
        stub_backend.script([_compile_result(_INVALID_OCTAVE), _compile_result(_VALID_OCTAVE)])
        result = await run_intake_pipeline(tmp_path, _ctx())
        assert result["ok"] is True
        assert result["octave"] == _VALID_OCTAVE
        assert result["attempts"] == 2
        assert len(stub_backend.calls) == 2

    async def test_retry_prompt_includes_first_attempt_errors(
        self, tmp_path: Path, stub_backend
    ) -> None:
        stub_backend.script([_compile_result(_INVALID_OCTAVE), _compile_result(_VALID_OCTAVE)])
        await run_intake_pipeline(tmp_path, _ctx())
        # Second call's intake_context carries the validation errors in its prompt.
        first_ctx = stub_backend.calls[0][0]
        retry_ctx = stub_backend.calls[1][0]
        assert retry_ctx.prompt != first_ctx.prompt
        assert "sentinel" in retry_ctx.prompt.lower() or "octave" in retry_ctx.prompt.lower()


class TestVerbosityBackstop:
    async def test_verbose_but_valid_then_compressed_retries_once(
        self, tmp_path: Path, stub_backend
    ) -> None:
        # First attempt is valid-but-verbose -> density lint fails the gate ->
        # informed retry -> second (compressed) attempt passes.
        stub_backend.script([_compile_result(_VERBOSE_OCTAVE), _compile_result(_VALID_OCTAVE)])
        result = await run_intake_pipeline(tmp_path, _ctx())
        assert result["ok"] is True
        assert result["octave"] == _VALID_OCTAVE
        assert result["attempts"] == 2
        # The retry prompt must carry the verbosity feedback so the 2nd attempt is informed.
        retry_ctx = stub_backend.calls[1][0]
        assert "VERBOSITY" in retry_ctx.prompt

    async def test_persistently_verbose_aborts(self, tmp_path: Path, stub_backend) -> None:
        stub_backend.script([_compile_result(_VERBOSE_OCTAVE), _compile_result(_VERBOSE_OCTAVE)])
        result = await run_intake_pipeline(tmp_path, _ctx())
        assert result["ok"] is False
        assert result["octave"] is None
        assert any("VERBOSITY" in e for e in result["validation_errors"])
        assert result["attempts"] == 2


class TestAbortImmunity:
    async def test_double_fail_aborts_with_errors(self, tmp_path: Path, stub_backend) -> None:
        stub_backend.script([_compile_result(_INVALID_OCTAVE), _compile_result(_INVALID_OCTAVE)])
        result = await run_intake_pipeline(tmp_path, _ctx())
        assert result["ok"] is False
        assert result["octave"] is None
        assert result["validation_errors"]
        assert result["attempts"] == 2
        assert len(stub_backend.calls) == 2

    async def test_double_fail_writes_nothing_to_filesystem(
        self, tmp_path: Path, stub_backend
    ) -> None:
        # Snapshot the FS tree before; assert it is byte-identical after.
        before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
        stub_backend.script([_compile_result(_INVALID_OCTAVE), _compile_result(_INVALID_OCTAVE)])
        await run_intake_pipeline(tmp_path, _ctx())
        after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
        assert before == after  # ZERO filesystem writes on double-fail

    async def test_persistent_verbosity_writes_nothing_to_filesystem(
        self, tmp_path: Path, stub_backend
    ) -> None:
        # Mirror of test_double_fail_writes_nothing_to_filesystem for the
        # VERBOSITY-driven abort path: two valid-but-verbose attempts fail the
        # density gate, so the pipeline aborts. Hallucination immunity must hold
        # on this path too -> ZERO filesystem writes.
        before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
        stub_backend.script([_compile_result(_VERBOSE_OCTAVE), _compile_result(_VERBOSE_OCTAVE)])
        result = await run_intake_pipeline(tmp_path, _ctx())
        # Precondition: this really is the verbosity abort path.
        assert result["ok"] is False
        assert any("VERBOSITY" in e for e in result["validation_errors"])
        after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
        assert before == after  # ZERO filesystem writes on verbosity-driven abort

    async def test_validate_retry_abort_loop_never_invokes_linker(self) -> None:
        # Structural invariant: the Stage-3 validate->retry->abort LOOP
        # (run_intake_pipeline) must never call the linker. The Stage-4
        # composition (run_intake_to_pr) may call it, but only downstream of a
        # *passing* gate — so we scope this assertion to the loop function body.
        import inspect

        loop_src = inspect.getsource(mod.run_intake_pipeline)
        assert "run_linker(" not in loop_src
        # And the loop must not write to disk itself.
        assert "write_text" not in loop_src
        assert "open(" not in loop_src

    async def test_backend_failure_aborts_without_retry_loop_writes(
        self, tmp_path: Path, stub_backend
    ) -> None:
        # If Stage 2 itself fails (ok=False), the pipeline aborts with the
        # compile error and never reaches the validator/Stage 4.
        stub_backend.script([_compile_result(None, ok=False)])
        result = await run_intake_pipeline(tmp_path, _ctx())
        assert result["ok"] is False
        assert result["octave"] is None
        assert result["validation_errors"]
        assert len(stub_backend.calls) == 1
