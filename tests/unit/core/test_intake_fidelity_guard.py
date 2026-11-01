"""Prose-mode fidelity guard and prose mode emitting quoted YAML (issue #195, PR-B).

Ratified design (HO-PROSE-FIDELITY-GUARD-195-20261101, confirmed_design): the guard is
a third check in ``intake_pipeline._gate`` after Gate A, compared against the source
prose, regex-only, fail-loud, never auto-fix.

  (1) Every double-quoted span of 8 or more characters, straight or curly, survives
      byte-identical; single-quoted spans count only when the quote marks delimit,
      never apostrophes.
  (2) Letters come only from scripts in the source, or Latin, Common or Inherited.
  (3) VERBATIM is a whole-value byte-exact substring of the prose; in OPERATOR_RULING
      and fields ending _VERBATIM every quoted span is byte-exact, compiler framing
      exempt, compared after decode.
  (4) A guard failure shares the existing informed-retry budget, then aborts loudly.

The same pull request switches prose mode to quoted YAML (HO-RECORDS-YAML-DEFAULT-
20261031): a compiled DECISION_RECORD is quoted YAML, judged by the Gate A YAML branch
and written as its canonical bytes; a facet card stays OCTAVE.

The three defect classes reproduced here come from issue #195: letters from a script
the prose does not use (the Arabic HISTORY line), misquoted evidence ("(consult Test
Guardian)" emitted as "(consult TMG)"), and free text where the author's words had to
stay exact (a paraphrased SCOPE the prose quoted; a VERBATIM that is not in the prose).

No live model call: the AIClient is a scripted in-process stub.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import hestai_context_mcp.core.intake_compiler as compiler_mod
import hestai_context_mcp.core.intake_pipeline as mod
from hestai_context_mcp.core.agent_readable_governance_parser import (
    emit_yaml_record,
    read_record,
)
from hestai_context_mcp.core.intake_pipeline import run_intake_pipeline, run_intake_to_pr
from hestai_context_mcp.ports.ai_client import CompletionRequest, CompletionResult
from hestai_context_mcp.tools.governance.intake_context import IntakeContext

pytestmark = pytest.mark.unit

# Existing non-secret fixture identifier (see test_intake_pipeline.py), held in a
# plainly-named constant so no quoted governance identifier sits next to a token key.
RECORD_ID = "HO-CONTEXT-MCP-NEWREC-20260601"

_CORE: dict[str, str] = {
    "TYPE": "DECISION_RECORD",
    "VERSION": "1.0",
    "TOKEN": RECORD_ID,
    "STATUS": "PROPOSED",
    "TIER": "OPERATIONAL",
    "AUTHORED_AT": "2026-06-01T00:00:00Z",
    "DECISION": "Keep the review gate strict for governance records.",
    "BECAUSE": "Silent record corruption is worse than a slower filing.",
}


def _yaml(blocks: Any = None, **extra: str) -> str:
    """A canonical, Gate-A-valid quoted-YAML DECISION_RECORD with ``extra`` fields."""
    return emit_yaml_record({**_CORE, **extra}, blocks)


def _gate(record: str, prose: str, tmp_path: Path) -> tuple[bool, list[str]]:
    passed, _result, errors, _available = mod._gate(tmp_path, record, prose)
    return passed, errors


def _has(errors: list[str], *needles: str) -> bool:
    return any(all(n in e for n in needles) for e in errors)


# ---------------------------------------------------------------------------
# Rule (1): quoted spans in the prose survive byte-identical
# ---------------------------------------------------------------------------


class TestRuleOneQuotedSpans:
    _PROSE = 'Before any merge the reviewer must act "(consult Test Guardian)" and record it.'

    def test_misquoted_evidence_fails_loudly(self, tmp_path: Path) -> None:
        # Defect class 2 from #195: "(consult TMG)" emitted for "(consult Test Guardian)".
        record = _yaml(EVIDENCE="The reviewer must act (consult TMG) before merge.")
        passed, errors = _gate(record, self._PROSE, tmp_path)
        assert passed is False
        assert _has(errors, "quote_not_preserved", "(consult Test Guardian)"), errors

    def test_faithful_quote_passes(self, tmp_path: Path) -> None:
        record = _yaml(EVIDENCE="The reviewer must act (consult Test Guardian) before merge.")
        passed, errors = _gate(record, self._PROSE, tmp_path)
        assert passed is True, errors

    def test_curly_double_quoted_span_altered_fails(self, tmp_path: Path) -> None:
        prose = "The operator said “keep the archive read only” in the session."
        record = _yaml(EVIDENCE="keep the archive read-only")
        passed, errors = _gate(record, prose, tmp_path)
        assert passed is False
        assert _has(errors, "quote_not_preserved", "keep the archive read only"), errors

    def test_curly_double_quoted_span_preserved_passes(self, tmp_path: Path) -> None:
        prose = "The operator said “keep the archive read only” in the session."
        record = _yaml(EVIDENCE="Operator: keep the archive read only")
        passed, errors = _gate(record, prose, tmp_path)
        assert passed is True, errors

    def test_spans_under_eight_characters_are_ignored(self, tmp_path: Path) -> None:
        # "go" (2) and "1234567" (7) are short incidental quotes: not guarded.
        prose = 'Set the flag to "go" and the build id to "1234567" then file it.'
        passed, errors = _gate(_yaml(), prose, tmp_path)
        assert passed is True, errors

    def test_a_span_of_exactly_eight_characters_is_guarded(self, tmp_path: Path) -> None:
        prose = 'The release tag is "12345678" for this decision.'
        passed, errors = _gate(_yaml(), prose, tmp_path)
        assert passed is False
        assert _has(errors, "quote_not_preserved", "12345678"), errors

    def test_delimited_single_quoted_span_is_guarded(self, tmp_path: Path) -> None:
        prose = "The standing rule is 'never auto-fix a quote' for every record."
        passed, errors = _gate(_yaml(), prose, tmp_path)
        assert passed is False
        assert _has(errors, "quote_not_preserved", "never auto-fix a quote"), errors

    def test_apostrophe_heavy_prose_passes(self, tmp_path: Path) -> None:
        # Positive control (HC ruling 1): apostrophes never open or close a span.
        prose = (
            "The operator's ruling isn't final yet, and we don't want the team's or the "
            "reviewers' notes treated as quotes; it's the users' call and they'll decide "
            "what's kept, so don't block on Shaun's or the HC room's wording."
        )
        passed, errors = _gate(_yaml(), prose, tmp_path)
        assert passed is True, errors

    def test_apostrophes_inside_a_delimited_single_quoted_span(self, tmp_path: Path) -> None:
        prose = "He wrote 'the operator's call isn't ours' and left it there."
        kept = _yaml(EVIDENCE="Quote: the operator's call isn't ours")
        dropped = _yaml(EVIDENCE="Quote: the operator decides")
        assert _gate(kept, prose, tmp_path)[0] is True
        passed, errors = _gate(dropped, prose, tmp_path)
        assert passed is False
        assert _has(errors, "quote_not_preserved", "the operator's call isn't ours"), errors

    def test_span_is_compared_after_yaml_decode(self, tmp_path: Path) -> None:
        # The record stores the backslashes escaped (\\); decoded, they are byte-exact.
        prose = 'Logs live under "C:\\temp\\logs dir" on the build host.'
        record = _yaml(EVIDENCE="Logs: C:\\temp\\logs dir")
        assert "C:\\\\temp\\\\logs dir" in record  # escaped on disk
        passed, errors = _gate(record, prose, tmp_path)
        assert passed is True, errors

    def test_free_text_scope_replacing_a_quoted_scope_fails(self, tmp_path: Path) -> None:
        # Defect class 3 from #195, within the ratified rules: the author quoted the
        # scope, so a free-text paraphrase of it fails rule (1).
        prose = 'This applies with scope "hestai-context-mcp prose mode" only.'
        record = _yaml(SCOPE="the context server")
        passed, errors = _gate(record, prose, tmp_path)
        assert passed is False
        assert _has(errors, "quote_not_preserved", "hestai-context-mcp prose mode"), errors


# ---------------------------------------------------------------------------
# Rule (2): letters only from source scripts, or Latin / Common / Inherited
# ---------------------------------------------------------------------------


class TestRuleTwoScripts:
    def test_non_source_script_letters_fail_loudly(self, tmp_path: Path) -> None:
        # Defect class 1 from #195: Arabic "because of" inside an English record.
        prose = "Record that the operator parked the work at 7/21 because of resource limits."
        record = _yaml(HISTORY="2026-09-09 operator parked at 7/21 بسبب resource constraint")
        passed, errors = _gate(record, prose, tmp_path)
        assert passed is False
        assert _has(errors, "non_source_script", "ARABIC", "بسبب"), errors

    def test_a_script_the_prose_uses_is_allowed(self, tmp_path: Path) -> None:
        prose = 'The office is named "مكتب الرياض الرئيسي" in the contract.'
        record = _yaml(OFFICE="مكتب الرياض الرئيسي")
        passed, errors = _gate(record, prose, tmp_path)
        assert passed is True, errors

    def test_latin_common_and_inherited_are_always_allowed(self, tmp_path: Path) -> None:
        prose = "plain ascii request"
        # Latin with diacritics, a combining mark (Inherited), digits, dashes, curly
        # punctuation, a Latin modifier letter and Common letters (double-struck N,
        # mathematical bold A, micro sign).
        record = _yaml(
            NOTE="caf\u00e9 na\u00efve e\u0301 \u2014 42 \u201cok\u201d "
            "\u02b0 \u2115 \U0001d400 \u00b5"
        )
        passed, errors = _gate(record, prose, tmp_path)
        assert passed is True, errors

    @pytest.mark.parametrize(
        ("text", "script"),
        [("Привет мир", "CYRILLIC"), ("審查通過", "CJK"), ("αβγ", "GREEK")],
    )
    def test_other_non_source_scripts_fail(self, tmp_path: Path, text: str, script: str) -> None:
        passed, errors = _gate(_yaml(NOTE=text), "plain ascii request", tmp_path)
        assert passed is False
        assert _has(errors, "non_source_script", script), errors


# ---------------------------------------------------------------------------
# Rule (3): VERBATIM / OPERATOR_RULING / *_VERBATIM byte-exact against the prose
# ---------------------------------------------------------------------------


def _rulings(verbatim: str) -> dict[str, list[dict[str, Any]]]:
    return {
        "current": [{"id": "R1", "rule": "Keep the gate strict."}],
        "rulings": [
            {
                "id": "R1",
                "rule": "Keep the gate strict.",
                "verbatim": verbatim,
                "ruled": "2026-06-01",
                "replaces": None,
            }
        ],
    }


class TestRuleThreeVerbatimFields:
    _PROSE = (
        "Shaun ruled in the HC room today: I confirm this, keep the gate strict and "
        "proceed. He then answered the follow-up with 3. Yes and moved on."
    )

    def test_verbatim_not_a_byte_exact_substring_fails(self, tmp_path: Path) -> None:
        # Defect class 3: a VERBATIM that paraphrases instead of copying the prose.
        record = _yaml(_rulings("I confirm this and keep the gate strict."), TOPIC="gate")
        passed, errors = _gate(record, self._PROSE, tmp_path)
        assert passed is False
        assert _has(errors, "verbatim_not_in_prose", "VERBATIM"), errors

    def test_verbatim_byte_exact_substring_passes(self, tmp_path: Path) -> None:
        record = _yaml(_rulings("I confirm this, keep the gate strict and proceed."), TOPIC="gate")
        passed, errors = _gate(record, self._PROSE, tmp_path)
        assert passed is True, errors

    def test_operator_ruling_quoted_span_altered_fails(self, tmp_path: Path) -> None:
        record = _yaml(
            OPERATOR_RULING="Shaun Buswell, first-party, verbatim: 'I confirm this and proceed'"
        )
        passed, errors = _gate(record, self._PROSE, tmp_path)
        assert passed is False
        assert _has(errors, "quote_not_in_prose", "OPERATOR_RULING"), errors

    def test_operator_ruling_framing_is_exempt(self, tmp_path: Path) -> None:
        # Who/when/which-session framing is compiler-written and never checked; only
        # the quoted span must be byte-exact.
        record = _yaml(
            OPERATOR_RULING=(
                "Shaun Buswell, 2026-06-01, HC control room session, first-party, "
                "answering whether to proceed, verbatim: 'I confirm this, keep the gate "
                "strict and proceed.'"
            )
        )
        passed, errors = _gate(record, self._PROSE, tmp_path)
        assert passed is True, errors

    def test_short_quotes_in_operator_ruling_are_checked(self, tmp_path: Path) -> None:
        # Rule (3) says EVERY quoted span: no 8-character floor ('3. Yes' is 6).
        ok = _yaml(OPERATOR_RULING="Shaun answered verbatim: '3. Yes'")
        bad = _yaml(OPERATOR_RULING="Shaun answered verbatim: '3. No'")
        assert _gate(ok, self._PROSE, tmp_path)[0] is True
        passed, errors = _gate(bad, self._PROSE, tmp_path)
        assert passed is False
        assert _has(errors, "quote_not_in_prose", "3. No"), errors

    def test_a_field_ending_verbatim_is_checked_after_decode(self, tmp_path: Path) -> None:
        # The double quotes are escaped (\") on disk and compared decoded.
        ok = _yaml(RULING_VERBATIM='He said "keep the gate strict" twice.')
        bad = _yaml(RULING_VERBATIM='He said "keep every gate strict" twice.')
        assert '\\"keep the gate strict\\"' in ok
        assert _gate(ok, self._PROSE, tmp_path)[0] is True
        passed, errors = _gate(bad, self._PROSE, tmp_path)
        assert passed is False
        assert _has(errors, "quote_not_in_prose", "RULING_VERBATIM"), errors


# ---------------------------------------------------------------------------
# Prose mode emits quoted YAML (gate level)
# ---------------------------------------------------------------------------

_OCTAVE_RECORD = (
    "===DECISION_RECORD===\n"
    "META:\n"
    "  TYPE::DECISION_RECORD\n"
    '  VERSION::"1.0"\n'
    f"  TOKEN::{RECORD_ID}\n"
    "  STATUS::PROPOSED\n"
    "  TIER::OPERATIONAL\n"
    '  DECISION::"Keep the review gate strict for governance records."\n'
    '  BECAUSE::"Silent record corruption is worse than a slower filing."\n'
    '  AUTHORED_AT::"2026-06-01T00:00:00Z"\n'
    "===END===\n"
)

_CONCEPT_CARD = (
    "===CONCEPT_CARD===\n"
    "META:\n"
    "  TYPE::CONCEPT_CARD\n"
    "  REPO_ID::hestai-context-mcp\n"
    '  ID::"GATE_A_TEST_CONCEPT"\n'
    "  STATUS::proposed\n"
    "  CARD_SCHEMA_VERSION::1\n"
    '  GENERATED_AT_COMMIT::"N/A"\n'
    '  SOURCE_HASH::"N/A"\n'
    "===END===\n"
)


class TestProseModeYamlGate:
    def test_an_octave_decision_record_is_rejected_in_prose_mode(self, tmp_path: Path) -> None:
        passed, errors = _gate(_OCTAVE_RECORD, "record a decision", tmp_path)
        assert passed is False
        assert _has(errors, "quoted YAML"), errors

    def test_a_yaml_decision_record_passes_and_never_reaches_gate_b(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _NoGateB:
            def validate(self, content: str) -> Any:
                raise AssertionError("Gate B ran on a YAML record")

        monkeypatch.setattr(mod, "get_octave_validator", lambda: _NoGateB(), raising=True)
        passed, result, errors, available = mod._gate(tmp_path, _yaml(), "record a decision")
        assert passed is True, errors
        assert result.syntax == "yaml"
        assert available is True

    def test_a_facet_card_stays_octave(self, tmp_path: Path) -> None:
        passed, errors = _gate(_CONCEPT_CARD, "record a concept", tmp_path)
        assert passed is True, errors


# ---------------------------------------------------------------------------
# Pipeline level: a scripted AIClient through the REAL compiler and gate
# ---------------------------------------------------------------------------


class _ScriptedClient:
    """AIClient stub returning one scripted completion per call (no live model)."""

    def __init__(self, contents: list[str]) -> None:
        self._contents = list(contents)
        self.requests: list[CompletionRequest] = []

    async def __aenter__(self) -> _ScriptedClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def complete_text(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        return CompletionResult(content=self._contents.pop(0), total_tokens=10, cost=0.0)


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch):
    def _install(*contents: str) -> _ScriptedClient:
        client = _ScriptedClient(list(contents))
        monkeypatch.setattr(
            compiler_mod, "build_default_ai_client", lambda working_dir=None: client
        )
        monkeypatch.setattr(compiler_mod, "_resolve_model_name", lambda working_dir=None: "m")
        return client

    return _install


def _ctx(prose: str) -> IntakeContext:
    return IntakeContext(prose_input=prose, corpus="", prompt="PROMPT", relevant_tokens=())


_MISQUOTED = _yaml(EVIDENCE="The reviewer must act (consult TMG) before merge.")
_FAITHFUL = _yaml(EVIDENCE="The reviewer must act (consult Test Guardian) before merge.")
_PROSE = TestRuleOneQuotedSpans._PROSE


class TestRuleFourSharedRetryBudget:
    async def test_guard_failure_gets_an_informed_retry(self, tmp_path: Path, scripted) -> None:
        client = scripted(_MISQUOTED, _FAITHFUL)
        result = await run_intake_pipeline(tmp_path, _ctx(_PROSE))
        assert result["ok"] is True, result["validation_errors"]
        assert result["attempts"] == 2
        retry_prompt = client.requests[1].system_prompt
        assert "quote_not_preserved" in retry_prompt
        assert "(consult Test Guardian)" in retry_prompt

    async def test_repeated_guard_failure_aborts_loudly(
        self, tmp_path: Path, scripted, caplog: pytest.LogCaptureFixture
    ) -> None:
        client = scripted(_MISQUOTED, _MISQUOTED)
        with caplog.at_level("WARNING"):
            result = await run_intake_pipeline(tmp_path, _ctx(_PROSE))
        assert result["ok"] is False
        assert result["octave"] is None
        assert result["attempts"] == 2
        assert len(client.requests) == 2  # shared budget: no extra fidelity retries
        assert _has(result["validation_errors"], "quote_not_preserved")
        assert "quote_not_preserved" in caplog.text  # loud: the abort is logged

    async def test_gate_a_and_guard_failures_share_one_budget(
        self, tmp_path: Path, scripted
    ) -> None:
        client = scripted("not a record at all", _MISQUOTED)
        result = await run_intake_pipeline(tmp_path, _ctx(_PROSE))
        assert result["ok"] is False
        assert len(client.requests) == 2
        assert _has(result["validation_errors"], "quote_not_preserved")

    async def test_guard_abort_never_reaches_the_linker_or_disk(
        self, tmp_path: Path, scripted, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(**kwargs: Any) -> dict[str, Any]:
            raise AssertionError("linker reached after a fidelity abort")

        monkeypatch.setattr(mod, "run_linker", _boom, raising=True)
        scripted(_MISQUOTED, _MISQUOTED)
        result = await run_intake_to_pr(tmp_path, _ctx(_PROSE), dry_run=False)
        assert result["success"] is False
        assert _has(result["validation_errors"], "quote_not_preserved")
        assert not (tmp_path / ".hestai").exists()


# ---------------------------------------------------------------------------
# Prose mode writes a quoted-YAML record the strict reader accepts
# ---------------------------------------------------------------------------


@pytest.fixture
def writing_linker(monkeypatch: pytest.MonkeyPatch):
    """Spy linker that dumb-writes the handed bytes to the validated target path."""
    calls: list[dict[str, Any]] = []

    def _link(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        target: Path = kwargs["validation"].target_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(kwargs["octave_content"].encode("utf-8"))
        return {
            "token": kwargs["validation"].token,
            "card_type": kwargs["validation"].card_type,
            "target_path": str(target.relative_to(kwargs["working_dir"])),
            "branch": "governance/test",
            "pr_url": "https://example/pr/1",
            "error": None,
        }

    monkeypatch.setattr(mod, "run_linker", _link, raising=True)
    monkeypatch.setattr(mod, "resolve_require_real_validation", lambda **kw: False)
    return calls


class TestProseModeWritesYaml:
    async def test_prose_mode_writes_a_yaml_record_the_reader_accepts(
        self, tmp_path: Path, scripted, writing_linker
    ) -> None:
        # Non-canonical model output (key order, CRLF) plus trailing chatter after the
        # closing fence: the record written is the canonical front matter only.
        compiled = (
            "---\r\n"
            f'token: "{RECORD_ID}"\r\n'
            'type: "DECISION_RECORD"\r\n'
            'version: "1.0"\r\n'
            'status: "PROPOSED"\r\n'
            'tier: "OPERATIONAL"\r\n'
            'authored_at: "2026-06-01T00:00:00Z"\r\n'
            'decision: "Keep the review gate strict for governance records."\r\n'
            'because: "Silent record corruption is worse than a slower filing."\r\n'
            "---\r\n"
            "Here is the record you asked for.\n"
        )
        scripted(compiled)
        result = await run_intake_to_pr(tmp_path, _ctx("keep the gate strict"), dry_run=False)
        assert result["success"] is True, result["validation_errors"]
        assert result["target_path"] == f".hestai/decisions/{RECORD_ID}.md"
        path = tmp_path / ".hestai" / "decisions" / f"{RECORD_ID}.md"
        data = path.read_bytes()
        assert data.split(b"\n", 1)[0] == b"---"
        assert b"Here is the record" not in data
        record = read_record(path)
        assert record.syntax == "yaml"
        assert record.diagnostic is None
        assert data.decode("utf-8") == _yaml()  # canonical bytes
        assert result["octave"] == _yaml()  # Stage 5 reviews what was written

    async def test_an_octave_decision_record_is_retried_into_yaml(
        self, tmp_path: Path, scripted, writing_linker
    ) -> None:
        client = scripted(_OCTAVE_RECORD, _yaml())
        result = await run_intake_to_pr(tmp_path, _ctx("keep the gate strict"), dry_run=False)
        assert result["success"] is True, result["validation_errors"]
        assert len(client.requests) == 2
        assert "quoted YAML" in client.requests[1].system_prompt
        assert result["target_path"].endswith(f"{RECORD_ID}.md")

    async def test_write_adr_stamps_human_adr_ref_into_the_yaml_record(
        self, tmp_path: Path, scripted, writing_linker
    ) -> None:
        prose = "keep the gate strict"
        scripted(_yaml())
        result = await run_intake_to_pr(tmp_path, _ctx(prose), dry_run=False, write_adr=True)
        assert result["success"] is True, result["validation_errors"]
        call = writing_linker[0]
        written = call["octave_content"]
        assert written == emit_yaml_record({**_CORE, "HUMAN_ADR_REF": RECORD_ID})
        assert call["adr_prose"] == prose


# ---------------------------------------------------------------------------
# Pre-review fixes
# ---------------------------------------------------------------------------


class TestPreReviewFixes:
    def test_a_gate_a_failure_on_an_octave_decision_record_also_names_the_yaml_form(
        self, tmp_path: Path
    ) -> None:
        # The retry must learn about the YAML form even when Gate A already failed,
        # or a 2-attempt budget can be spent before the model is told.
        verbose = _OCTAVE_RECORD.replace(
            "Keep the review gate strict for governance records.",
            " ".join(f"word{i}" for i in range(60)),
        )
        passed, errors = _gate(verbose, "record a decision", tmp_path)
        assert passed is False
        assert _has(errors, "40"), errors
        assert _has(errors, "quoted YAML"), errors

    def test_a_word_initial_apostrophe_does_not_hijack_a_real_span(self, tmp_path: Path) -> None:
        prose = "Back in the '90s the team's 'fast path plan' won."
        assert mod._quoted_spans(prose) == ["fast path plan"]
        kept = _yaml(EVIDENCE="Plan: fast path plan")
        assert _gate(kept, prose, tmp_path)[0] is True

    def test_span_scan_is_linear_on_a_long_line_of_unclosed_openers(self) -> None:
        import time

        line = " 'x" * 60_000
        start = time.perf_counter()
        assert mod._quoted_spans(line) == []
        assert time.perf_counter() - start < 2.0

    @pytest.mark.parametrize("letters", ["時々", "ｱｲｳ"])
    def test_iteration_mark_and_halfwidth_kana_match_their_scripts(
        self, tmp_path: Path, letters: str
    ) -> None:
        prose = "時間 アイウ について"
        passed, errors = _gate(_yaml(NOTE=letters), prose, tmp_path)
        assert passed is True, errors


class TestYamlProseSkipsGateBFailClosed:
    async def test_yaml_record_links_when_real_validation_is_required_but_absent(
        self, tmp_path: Path, scripted, writing_linker, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Gate B never runs on YAML, so the fail-closed policy for a missing Gate B
        # does not apply to it, as in content mode.
        from hestai_context_mcp.ports.octave_validator import UnavailableOctaveValidator

        monkeypatch.setattr(mod, "get_octave_validator", lambda: UnavailableOctaveValidator())
        monkeypatch.setattr(mod, "resolve_require_real_validation", lambda **kw: True)
        scripted(_yaml())
        result = await run_intake_to_pr(tmp_path, _ctx("keep the gate strict"), dry_run=False)
        assert result["success"] is True, result["validation_errors"]
        assert result["real_validation_available"] is False
        assert len(writing_linker) == 1


class TestSingleQuoteOpenerAfterPunctuation:
    """cubic P2 on PR #246: a single quote after non-letter, non-digit punctuation
    delimits (``scope:'x'``, ``key='x'``); after a letter or digit it is an
    apostrophe. HC ruling 1: spans count only when the marks delimit."""

    @pytest.mark.parametrize(
        ("prose", "span"),
        [
            ("Set scope:'sensitive data' for this record.", "sensitive data"),
            ("Use key='quoted value here' in the config.", "quoted value here"),
            ("Call key=('quoted value here') once.", "quoted value here"),
            ("Tags ['restricted scope'] apply.", "restricted scope"),
        ],
    )
    def test_a_span_after_punctuation_is_guarded(
        self, tmp_path: Path, prose: str, span: str
    ) -> None:
        assert mod._quoted_spans(prose) == [span]
        passed, errors = _gate(_yaml(), prose, tmp_path)
        assert passed is False
        assert _has(errors, "quote_not_preserved", span), errors

    @pytest.mark.parametrize(
        "prose",
        [
            "They played rock'n'roll all night long at the venue.",
            "We said don't' and then left the meeting for the day.",
            "He is 5'11 tall and the 90's records were archived.",
        ],
    )
    def test_a_quote_after_a_letter_or_digit_is_an_apostrophe(self, prose: str) -> None:
        assert mod._quoted_spans(prose) == []
