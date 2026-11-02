"""Compiler date + record-version context (issue #253, HC standards ruling).

With no date in the prose the compiler cannot build the TOKEN ``-YYYYMMDD`` suffix, so
live runs omitted it or copied an old corpus date, and Gate A (§1.3 / §4.1 #3) rejected
the mismatch against the stamped ``authored_at``. The pipeline now hands the compiler the
call-time UTC date as deterministic context, taken from the SAME single clock read as the
``authored_at`` stamp, and the contract states that a quoted-YAML DECISION_RECORD declares
version "1.4" (ADR-RFC-ARCH-004 §1.1: the YAML form is a v1.4 feature).

Conditions pinned here:

  (a) the compile prompt carries the stamped date line (and the version fact); a record
      whose TOKEN uses that date files, with the TOKEN suffix equal to the stamped date.
  (b) an operator-supplied TOKEN with a different date still fails loudly at Gate A and
      is NOT rewritten.
  (c) the prompt date and the authored_at stamp come from ONE clock read, also across a
      retry.
  (d) the version fact is in the prompt and a "1.4" YAML record passes; a "1.1" record
      is never rewritten to "1.4".
  Guard: the date context is not quoted operator words and does not trip the fidelity
  guard.

No live model call: the AIClient is a scripted in-process stub.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

import hestai_context_mcp.core.intake_pipeline as mod
from hestai_context_mcp.core.agent_readable_governance_parser import emit_yaml_record
from hestai_context_mcp.core.intake_pipeline import run_intake_pipeline
from hestai_context_mcp.tools.governance.intake_context import (
    IntakeContext,
    assemble_intake_context,
)
from tests.unit.core.test_intake_authored_at_stamp import (  # noqa: F401
    _CORE,
    RECORD_ID,
    _ctx,
    clock,
    scripted,
)

pytestmark = pytest.mark.unit

# The injected clock's UTC date differs from the fixture TOKEN's date (20260601), so a
# passing run proves the date came from the clock, not from the corpus-style fixture.
_NOW = datetime(2026, 11, 2, 0, 50, 7, tzinfo=UTC)
_NOW_STAMP = "2026-11-02T00:50:07Z"
_DATE_LINE = "Today's UTC date is 2026-11-02"
_TOKEN_SUFFIX = "20261102"
# Same prefix as the existing fixture TOKEN, re-dated to the injected clock's date.
_TODAY_TOKEN = f"{RECORD_ID[:-8]}{_TOKEN_SUFFIX}"
_VERSION_FACT = 'version "1.4"'


def _compiled(**extra: str) -> str:
    """A compiled quoted-YAML record WITHOUT ``authored_at``, declaring version 1.4."""
    full = emit_yaml_record({**_CORE, "VERSION": "1.4", **extra})
    return "\n".join(ln for ln in full.split("\n") if not ln.startswith("authored_at:"))


def _real_ctx(tmp_path: Path, prose: str = "Keep the review gate strict.") -> IntakeContext:
    return assemble_intake_context(tmp_path, prose)


class TestPromptCarriesTheStampedDate:
    async def test_prompt_has_date_line_and_record_with_that_date_files(
        self, tmp_path: Path, scripted, clock  # noqa: F811
    ) -> None:
        clock(_NOW)
        client = scripted(_compiled(TOKEN=_TODAY_TOKEN))
        result = await run_intake_pipeline(tmp_path, _ctx())
        assert result["ok"] is True, result["validation_errors"]
        prompt = client.requests[0].system_prompt
        assert _DATE_LINE in prompt, prompt
        assert f"-{_TOKEN_SUFFIX}" in prompt, prompt
        octave = result["octave"] or ""
        assert f'token: "{_TODAY_TOKEN}"' in octave
        assert f'authored_at: "{_NOW_STAMP}"' in octave
        # Token suffix == the stamped authored_at date, as YYYYMMDD.
        assert _TODAY_TOKEN.endswith(_NOW_STAMP[:10].replace("-", ""))


class TestOperatorTokenIsNeverRewritten:
    async def test_operator_token_with_other_date_fails_gate_a_and_is_kept(
        self, tmp_path: Path, scripted, clock  # noqa: F811
    ) -> None:
        clock(_NOW)
        client = scripted(_compiled(TOKEN=RECORD_ID), _compiled(TOKEN=RECORD_ID))
        result = await run_intake_pipeline(tmp_path, _ctx())
        assert _DATE_LINE in client.requests[0].system_prompt
        assert result["ok"] is False
        assert result["octave"] is None
        joined = "\n".join(result["validation_errors"])
        assert "TOKEN date suffix '20260601'" in joined, joined
        assert _TOKEN_SUFFIX in joined, joined
        assert _TODAY_TOKEN not in joined


class TestOneClockReadFeedsPromptAndStamp:
    async def test_one_read_same_date_in_prompt_on_retry_and_in_stamp(
        self, tmp_path: Path, scripted, clock  # noqa: F811
    ) -> None:
        # A second/third read would land on a different day; there must be only one.
        reads = clock(_NOW, datetime(2026, 12, 25, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC))
        client = scripted(_compiled(TOKEN=RECORD_ID), _compiled(TOKEN=_TODAY_TOKEN))
        result = await run_intake_pipeline(tmp_path, _ctx())
        assert result["ok"] is True, result["validation_errors"]
        assert result["attempts"] == 2
        assert len(reads) == 1
        assert len(client.requests) == 2
        for request in client.requests:
            assert _DATE_LINE in request.system_prompt
            assert "2026-12-25" not in request.system_prompt
        assert "BEGIN_VALIDATION_FEEDBACK" in client.requests[1].system_prompt
        assert f'authored_at: "{_NOW_STAMP}"' in (result["octave"] or "")


class TestYamlRecordVersionFact:
    def test_contract_states_the_yaml_record_declares_version_1_4(self, tmp_path: Path) -> None:
        assert _VERSION_FACT in _real_ctx(tmp_path).prompt

    async def test_prompt_the_compiler_receives_carries_the_version_fact(
        self, tmp_path: Path, scripted, clock  # noqa: F811
    ) -> None:
        clock(_NOW)
        client = scripted(_compiled(TOKEN=_TODAY_TOKEN))
        result = await run_intake_pipeline(tmp_path, _real_ctx(tmp_path))
        assert result["ok"] is True, result["validation_errors"]
        assert _VERSION_FACT in client.requests[0].system_prompt
        assert 'version: "1.4"' in (result["octave"] or "")

    async def test_a_version_1_1_record_is_never_rewritten_to_1_4(
        self, tmp_path: Path, scripted, clock  # noqa: F811
    ) -> None:
        clock(_NOW)
        scripted(_compiled(TOKEN=_TODAY_TOKEN, VERSION="1.1"))
        result = await run_intake_pipeline(tmp_path, _ctx())
        assert 'version: "1.4"' not in (result["octave"] or "")


class TestDateContextIsNotOperatorWords:
    async def test_guard_clean_with_quotes_and_dated_token(
        self, tmp_path: Path, scripted, clock  # noqa: F811
    ) -> None:
        prose = 'The operator ruled "keep the review gate strict" for every governance record.'
        ruling = 'Operator said "keep the review gate strict" about governance records.'
        clock(_NOW)
        client = scripted(_compiled(TOKEN=_TODAY_TOKEN, OPERATOR_RULING=ruling))
        result = await run_intake_pipeline(tmp_path, _real_ctx(tmp_path, prose))
        assert result["ok"] is True, result["validation_errors"]
        assert _DATE_LINE in client.requests[0].system_prompt
        final = result["octave"] or ""
        assert mod._fidelity_errors(final, prose) == []
        # The date line is context for the compiler, never part of the operator's words.
        assert "UTC date" not in final
        assert result["attempts"] == 1
