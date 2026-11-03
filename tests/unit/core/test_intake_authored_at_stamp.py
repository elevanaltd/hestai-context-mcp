"""Prose-mode AUTHORED_AT stamp (issue #249, HC standards ruling 2026-11-02).

The compiler is told never to invent dates, so a prose run whose compiled record has no
``authored_at`` used to fail Gate A (``missing_required_field: authored_at``). The
pipeline now stamps it, deterministically, inside each attempt of
``run_intake_pipeline``: after the compile and BEFORE Gate A, the fidelity guard and
canonicalisation, so every check runs on the exact final bytes.

Conditions pinned here (ADR-RFC-ARCH-004 §1.2 "UTC. Set once at record creation"):

  1. ORDER: stamped on the compiled record before ``_gate``.
  2. FORMAT: ISO-8601 UTC to the second, trailing ``Z``, ONE clock read per call
     (reused across the retry attempt); the clock seam is ``_now_utc``.
  3. PRECEDENCE: an ``authored_at`` already in the compiled record is kept ONLY IF it is
     a full ISO-8601 timestamp AND that exact string appears in the operator's prose
     (#273, HC standards ruling 2026-11-02/03 narrowing #249 condition 3); anything else
     is REPLACED by the stamp.
  4. TOKEN DATE: the TOKEN is never rewritten; Gate A's existing §1.3 check rejects a
     TOKEN whose date differs from the stamped UTC date.
  5. The stamp is not operator words: a stamped record passes the fidelity guard.
  6. Nothing else is stamped.

No live model call: the AIClient is a scripted in-process stub.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

import hestai_context_mcp.core.intake_compiler as compiler_mod
import hestai_context_mcp.core.intake_pipeline as mod
from hestai_context_mcp.core.agent_readable_governance_parser import emit_yaml_record
from hestai_context_mcp.core.intake_pipeline import run_intake_pipeline
from hestai_context_mcp.ports.ai_client import CompletionRequest, CompletionResult
from hestai_context_mcp.tools.governance.intake_context import IntakeContext

pytestmark = pytest.mark.unit

# Existing non-secret fixture identifier (see test_intake_pipeline.py), held in a
# plainly-named constant so no quoted governance identifier sits next to a token key.
RECORD_ID = "HO-CONTEXT-MCP-NEWREC-20260601"

_OPERATOR_AT = "2026-06-01T00:00:00Z"
_CORE: dict[str, str] = {
    "TYPE": "DECISION_RECORD",
    "VERSION": "1.0",
    "TOKEN": RECORD_ID,
    "STATUS": "PROPOSED",
    "TIER": "OPERATIONAL",
    "AUTHORED_AT": _OPERATOR_AT,
    "DECISION": "Keep the review gate strict for governance records.",
    "BECAUSE": "Silent record corruption is worse than a slower filing.",
}

# The TOKEN's date (20260601) and the injected clock's UTC date agree.
_NOW = datetime(2026, 6, 1, 9, 30, 15, 123456, tzinfo=UTC)
_NOW_STAMP = "2026-06-01T09:30:15Z"


def _compiled(**extra: str) -> str:
    """A compiled quoted-YAML record WITHOUT ``authored_at`` (what the compiler emits)."""
    full = emit_yaml_record({**_CORE, **extra})
    return "\n".join(ln for ln in full.split("\n") if not ln.startswith("authored_at:"))


def _expected(authored_at: str, **extra: str) -> str:
    """The canonical bytes of the record the pipeline must return."""
    return emit_yaml_record({**_CORE, "AUTHORED_AT": authored_at, **extra})


class _ScriptedClient:
    """AIClient stub returning the scripted completions in order (no live model)."""

    def __init__(self, contents: list[str]) -> None:
        self._contents = list(contents)
        self.requests: list[CompletionRequest] = []

    async def __aenter__(self) -> _ScriptedClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def complete_text(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        # The last scripted completion repeats, so a retry never exhausts the stub.
        content = self._contents.pop(0) if len(self._contents) > 1 else self._contents[0]
        return CompletionResult(content=content, total_tokens=10, cost=0.0)


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> Callable[..., _ScriptedClient]:
    def _install(*contents: str) -> _ScriptedClient:
        client = _ScriptedClient(list(contents))
        monkeypatch.setattr(
            compiler_mod, "build_default_ai_client", lambda working_dir=None: client
        )
        monkeypatch.setattr(compiler_mod, "_resolve_model_name", lambda working_dir=None: "m")
        return client

    return _install


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[datetime]]:
    """Inject the pipeline clock; returns the list of reads it served."""

    def _install(*times: datetime) -> list[datetime]:
        queue = list(times)
        reads: list[datetime] = []

        def _now() -> datetime:
            reads.append(queue[len(reads)])
            return reads[-1]

        # raising=False keeps a missing seam a BEHAVIOUR failure at RED, not an AttributeError.
        monkeypatch.setattr(mod, "_now_utc", _now, raising=False)
        return reads

    return _install


def _ctx(prose: str = "Keep the review gate strict.") -> IntakeContext:
    return IntakeContext(prose_input=prose, corpus="", prompt="PROMPT", relevant_tokens=())


class TestStampWhenAbsent:
    async def test_compiled_record_without_authored_at_succeeds_with_injected_clock(
        self, tmp_path: Path, scripted, clock
    ) -> None:
        reads = clock(_NOW)
        client = scripted(_compiled())
        result = await run_intake_pipeline(tmp_path, _ctx())
        assert result["ok"] is True, result["validation_errors"]
        assert result["attempts"] == 1
        assert len(client.requests) == 1
        assert f'authored_at: "{_NOW_STAMP}"' in (result["octave"] or "")
        assert len(reads) == 1

    async def test_stamp_is_utc_to_the_second_with_trailing_z(
        self, tmp_path: Path, scripted, clock
    ) -> None:
        # A non-UTC aware clock is normalised to UTC; microseconds are dropped.
        local = datetime(2026, 6, 1, 14, 30, 15, 999999, tzinfo=timezone(timedelta(hours=5)))
        clock(local)
        scripted(_compiled())
        result = await run_intake_pipeline(tmp_path, _ctx())
        assert result["ok"] is True, result["validation_errors"]
        assert 'authored_at: "2026-06-01T09:30:15Z"' in (result["octave"] or "")


class TestOperatorValueWins:
    async def test_operator_supplied_authored_at_is_kept_never_overwritten(
        self, tmp_path: Path, scripted, clock
    ) -> None:
        clock(_NOW)
        scripted(_expected(_OPERATOR_AT))
        # #273: "operator value wins" means a value the operator actually wrote.
        prose = f"Keep the review gate strict. Authored at {_OPERATOR_AT} by the operator."
        result = await run_intake_pipeline(tmp_path, _ctx(prose))
        assert result["ok"] is True, result["validation_errors"]
        assert result["octave"] == _expected(_OPERATOR_AT)
        assert _NOW_STAMP not in (result["octave"] or "")


class TestTokenDateMismatch:
    async def test_token_date_differing_from_stamped_date_is_rejected_loudly(
        self, tmp_path: Path, scripted, clock
    ) -> None:
        # Clock is 2026-11-02; the TOKEN is dated 20260601. The TOKEN is never re-dated.
        later = datetime(2026, 11, 2, 0, 50, 0, tzinfo=UTC)
        clock(later)
        client = scripted(_compiled(), _compiled())
        result = await run_intake_pipeline(tmp_path, _ctx())
        assert result["ok"] is False
        assert result["octave"] is None
        assert result["attempts"] == 2
        assert len(client.requests) == 2
        joined = "\n".join(result["validation_errors"])
        assert "TOKEN date suffix '20260601'" in joined, joined
        assert "20261102" in joined, joined


class TestStampIsNotOperatorWords:
    async def test_stamped_record_passes_the_fidelity_guard_including_r2(
        self, tmp_path: Path, scripted, clock
    ) -> None:
        prose = 'The operator ruled "keep the review gate strict" for every governance record.'
        ruling = 'Operator said "keep the review gate strict" about governance records.'
        clock(_NOW)
        scripted(_compiled(OPERATOR_RULING=ruling))
        result = await run_intake_pipeline(tmp_path, _ctx(prose))
        assert result["ok"] is True, result["validation_errors"]
        final = result["octave"] or ""
        assert _NOW_STAMP in final
        # The guard, run directly on the final bytes: quotes, script rule and R2 all clean.
        assert mod._fidelity_errors(final, prose) == []


class TestOneClockReadPerCall:
    async def test_two_attempts_share_one_stamp_and_one_clock_read(
        self, tmp_path: Path, scripted, clock
    ) -> None:
        reads = clock(_NOW, _NOW + timedelta(hours=1), _NOW + timedelta(hours=2))
        verbose = _compiled(DECISION=" ".join(f"word{i}" for i in range(200)))
        client = scripted(verbose, _compiled())
        result = await run_intake_pipeline(tmp_path, _ctx())
        assert result["ok"] is True, result["validation_errors"]
        assert result["attempts"] == 2
        assert len(client.requests) == 2
        assert len(reads) == 1
        assert f'authored_at: "{_NOW_STAMP}"' in (result["octave"] or "")


class TestNothingElseIsStamped:
    async def test_only_authored_at_is_added_to_the_compiled_record(
        self, tmp_path: Path, scripted, clock
    ) -> None:
        clock(_NOW)
        scripted(_compiled())
        result = await run_intake_pipeline(tmp_path, _ctx())
        assert result["ok"] is True, result["validation_errors"]
        # Byte-equal to the canonical record carrying exactly the stamp: no
        # human_adr_ref, no ratification fields, no issue reference.
        assert result["octave"] == _expected(_NOW_STAMP)


class TestStampAgreesWithTheReaderOnFences:
    """cubic P2 on #250: CR line endings and a BOM are accepted by the reader, so the
    stamp must locate the closing fence by the same rule and keep the record's EOL."""

    async def test_crlf_compiled_record_is_stamped(self, tmp_path: Path, scripted, clock) -> None:
        clock(_NOW)
        scripted(_compiled().replace("\n", "\r\n"))
        result = await run_intake_pipeline(tmp_path, _ctx())
        assert result["ok"] is True, result["validation_errors"]
        assert result["octave"] == _expected(_NOW_STAMP)

    async def test_bom_prefixed_record_is_rejected_never_accepted(
        self, tmp_path: Path, scripted, clock
    ) -> None:
        # ADR-RFC-ARCH-004 §1.1: a leading BOM is "rejected at line 1 as invalid_key".
        # The stamp must never turn such a record into an accepted one.
        clock(_NOW)
        scripted("\ufeff" + _compiled())
        result = await run_intake_pipeline(tmp_path, _ctx())
        assert result["ok"] is False
        assert result["octave"] is None
        joined = "\n".join(result["validation_errors"])
        assert "rejected at line 1: invalid_key" in joined, joined

    def test_bom_prefixed_record_is_left_unstamped(self) -> None:
        bom = "\ufeff" + _compiled()
        assert mod._stamp_authored_at(bom, _NOW_STAMP) == bom

    async def test_existing_authored_at_with_cr_counts_as_present(
        self, tmp_path: Path, scripted, clock
    ) -> None:
        clock(_NOW)
        scripted(_expected(_OPERATOR_AT).replace("\n", "\r\n"))
        prose = f"Keep the review gate strict. Authored at {_OPERATOR_AT} by the operator."
        result = await run_intake_pipeline(tmp_path, _ctx(prose))
        assert result["ok"] is True, result["validation_errors"]
        assert result["octave"] == _expected(_OPERATOR_AT)

    def test_stamp_keeps_the_records_own_line_ending(self) -> None:
        crlf = _compiled().replace("\n", "\r\n")
        stamped = mod._stamp_authored_at(crlf, _NOW_STAMP)
        assert stamped.startswith(f'---\r\nauthored_at: "{_NOW_STAMP}"\r\n')
        assert "\n" not in stamped.replace("\r\n", "")


# --- #273: provenance of an authored_at the compiler wrote ------------------------------
# Live evidence (deployed main 36c3c243, 3 no-date dry runs): the compiler, told today's
# date (#253), wrote a date-only ``authored_at: "2026-11-03"`` where the canonical order
# places it (after ``tier``), and #250's stamp kept it -> Gate A: "AUTHORED_AT
# '2026-11-03' must be a full ISO-8601 timestamp". The fixtures reproduce that shape
# faithfully (not a captured live transcript: no secrets needed, shape only).


def _compiled_with(authored_at: str) -> str:
    """A compiled record carrying ``authored_at`` where the live compiler placed it."""
    return emit_yaml_record({**_CORE, "AUTHORED_AT": authored_at})


class TestCompilerWrittenAuthoredAtIsReplaced:
    async def test_date_only_value_not_in_prose_is_stamped(
        self, tmp_path: Path, scripted, clock
    ) -> None:
        clock(_NOW)
        scripted(_compiled_with("2026-11-03"))
        result = await run_intake_pipeline(tmp_path, _ctx())
        assert result["ok"] is True, result["validation_errors"]
        assert result["octave"] == _expected(_NOW_STAMP)

    async def test_date_only_value_present_in_prose_is_still_stamped(
        self, tmp_path: Path, scripted, clock
    ) -> None:
        # Writing a DATE in the prose is not writing a full timestamp.
        clock(_NOW)
        scripted(_compiled_with("2026-11-03"))
        result = await run_intake_pipeline(
            tmp_path, _ctx("Keep the gate strict, filed on 2026-11-03.")
        )
        assert result["ok"] is True, result["validation_errors"]
        assert result["octave"] == _expected(_NOW_STAMP)

    async def test_invented_full_timestamp_not_in_prose_is_replaced(
        self, tmp_path: Path, scripted, clock
    ) -> None:
        clock(_NOW)
        scripted(_compiled_with("2026-06-01T08:00:00Z"))
        result = await run_intake_pipeline(tmp_path, _ctx())
        assert result["ok"] is True, result["validation_errors"]
        assert result["octave"] == _expected(_NOW_STAMP)

    async def test_full_timestamp_written_in_prose_is_kept_verbatim(
        self, tmp_path: Path, scripted, clock
    ) -> None:
        clock(_NOW)
        scripted(_compiled_with(_OPERATOR_AT))
        prose = f"Keep the review gate strict, authored {_OPERATOR_AT}."
        result = await run_intake_pipeline(tmp_path, _ctx(prose))
        assert result["ok"] is True, result["validation_errors"]
        # TOKEN date (20260601) agrees with the kept value.
        assert result["octave"] == _expected(_OPERATOR_AT)

    async def test_timestamp_in_another_format_is_stamped_not_normalised(
        self, tmp_path: Path, scripted, clock
    ) -> None:
        # Literal match only: the prose says 09:30 local-style text, the value is ISO.
        clock(_NOW)
        scripted(_compiled_with("2026-06-01T09:30:00+00:00"))
        result = await run_intake_pipeline(tmp_path, _ctx("Authored 2026-06-01 09:30 UTC."))
        assert result["ok"] is True, result["validation_errors"]
        assert result["octave"] == _expected(_NOW_STAMP)

    async def test_key_absent_is_stamped(self, tmp_path: Path, scripted, clock) -> None:
        clock(_NOW)
        scripted(_compiled())
        result = await run_intake_pipeline(tmp_path, _ctx())
        assert result["ok"] is True, result["validation_errors"]
        assert result["octave"] == _expected(_NOW_STAMP)

    async def test_duplicate_authored_at_is_still_rejected_by_gate_a(
        self, tmp_path: Path, scripted, clock
    ) -> None:
        # No silent dedupe: two keys is a malformed record, left for Gate A to reject.
        clock(_NOW)
        dup = _compiled_with("2026-11-03").replace(
            'authored_at: "2026-11-03"', 'authored_at: "2026-11-03"\nauthored_at: "2026-11-04"'
        )
        scripted(dup)
        result = await run_intake_pipeline(tmp_path, _ctx())
        assert result["ok"] is False
        assert result["octave"] is None
        assert "duplicate_key" in "\n".join(result["validation_errors"])

    def test_duplicate_authored_at_is_left_untouched_by_the_stamp(self) -> None:
        dup = _compiled_with("2026-11-03").replace(
            'authored_at: "2026-11-03"', 'authored_at: "2026-11-03"\nauthored_at: "2026-11-04"'
        )
        assert mod._stamp_authored_at(dup, _NOW_STAMP, "") == dup

    async def test_retries_share_one_clock_read_and_one_stamp(
        self, tmp_path: Path, scripted, clock
    ) -> None:
        reads = clock(_NOW, _NOW + timedelta(hours=1))
        verbose = emit_yaml_record(
            {
                **_CORE,
                "AUTHORED_AT": "2026-11-03",
                "DECISION": " ".join(f"w{i}" for i in range(200)),
            }
        )
        client = scripted(verbose, _compiled_with("2026-11-03"))
        result = await run_intake_pipeline(tmp_path, _ctx())
        assert result["ok"] is True, result["validation_errors"]
        assert result["attempts"] == 2
        assert len(client.requests) == 2
        assert len(reads) == 1
        assert result["octave"] == _expected(_NOW_STAMP)

    async def test_crlf_record_has_its_authored_at_line_replaced_in_place(
        self, tmp_path: Path, scripted, clock
    ) -> None:
        clock(_NOW)
        scripted(_compiled_with("2026-11-03").replace("\n", "\r\n"))
        result = await run_intake_pipeline(tmp_path, _ctx())
        assert result["ok"] is True, result["validation_errors"]
        assert result["octave"] == _expected(_NOW_STAMP)

    def test_replace_keeps_the_records_own_line_ending(self) -> None:
        crlf = _compiled_with("2026-11-03").replace("\n", "\r\n")
        stamped = mod._stamp_authored_at(crlf, _NOW_STAMP, "")
        assert stamped.count("authored_at:") == 1
        assert f'authored_at: "{_NOW_STAMP}"\r\n' in stamped
        assert "\n" not in stamped.replace("\r\n", "")

    def test_bom_record_is_still_left_unstamped_when_it_carries_a_date_only_value(self) -> None:
        bom = "\ufeff" + _compiled_with("2026-11-03")
        assert mod._stamp_authored_at(bom, _NOW_STAMP, "") == bom

    def test_indented_authored_at_line_is_not_treated_as_the_key(self) -> None:
        # Unchanged behaviour: only a column-0 ``authored_at:`` is the key; an indented
        # line is left alone (Gate A rejects it) and the stamp is still added.
        rec = _compiled().replace("---\n", '---\n  authored_at: "2026-11-03"\n', 1)
        out = mod._stamp_authored_at(rec, _NOW_STAMP, "")
        assert '  authored_at: "2026-11-03"' in out
        assert f'authored_at: "{_NOW_STAMP}"' in out

    def test_quoted_key_line_is_not_treated_as_the_key(self) -> None:
        rec = _compiled().replace("---\n", '---\n"authored_at": "2026-11-03"\n', 1)
        out = mod._stamp_authored_at(rec, _NOW_STAMP, "")
        assert '"authored_at": "2026-11-03"' in out
        assert f'authored_at: "{_NOW_STAMP}"' in out


class TestContractTellsTheCompilerToOmitAuthoredAt:
    def test_contract_says_to_omit_authored_at_and_does_not_list_it_as_a_field(self) -> None:
        import re

        from hestai_context_mcp.tools.governance.intake_context import _COMPRESSION_CONTRACT

        text = " ".join(_COMPRESSION_CONTRACT.split())
        assert re.search(r"(?i)\b(omit|do not (write|emit|include))\b[^.]*authored_at", text)
        assert "tier, authored_at, decision" not in text
        # The existing instruction not to invent dates stays.
        assert "do NOT copy its dates" in text
