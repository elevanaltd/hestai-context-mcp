"""Tests for the Stage-1 intake context assembler (RFC #53 Gate C, T1).

The Stage-1 LEXER upgrades the dumb ``assemble_context`` clip into a
few-shot + JIT-compiled prompt assembler. It composes:

  (a) exemplar facet cards from ``.hestai/context/concepts/**``,
  (b) prior merged AGRs from ``.hestai/decisions/**`` (the autocatalytic feed),
  (c) a deterministic relevance-grep of local L1 for prose-relevant TOKENs,
  (d) a clip to the ~25k-char budget that retains the newest/most-relevant AGRs
      (NOT naive head truncation), and
  (e) a JIT-compiled prompt built from live repo state (NEVER a hardcoded
      system-prompt constant — A9 / source-invariant).

It also integrates ``lookup_token_deterministic`` for the supersession
target-existence check.

North Star boundary: regex + string search only, no OCTAVE AST, no LLM.
Deterministic for identical filesystem state.
"""

from __future__ import annotations

from pathlib import Path

from hestai_context_mcp.tools.governance.intake_context import (
    IntakeContext,
    assemble_intake_context,
    verify_supersession_target,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _decision(token: str, body: str = "") -> str:
    return (
        f"===DECISION_RECORD===\n"
        f"META:\n"
        f"  TYPE::DECISION_RECORD\n"
        f'  TOKEN::"{token}"\n'
        f"{body}\n"
        f"===END===\n"
    )


def _concept(card_id: str, repo_id: str = "hestai-context-mcp") -> str:
    return (
        f"===CONCEPT_CARD===\n"
        f"META:\n"
        f"  TYPE::CONCEPT_CARD\n"
        f'  ID::"{card_id}"\n'
        f"  REPO_ID::{repo_id}\n"
        f"===END===\n"
    )


def _seed_repo(tmp_path: Path) -> Path:
    """Create a minimal governance repo with a concept card and two AGRs."""
    concepts = tmp_path / ".hestai" / "context" / "concepts" / "hestai-context-mcp"
    decisions = tmp_path / ".hestai" / "decisions"
    _write(concepts / "PROVIDER_AGNOSTIC.oct.md", _concept("PROVIDER_AGNOSTIC"))
    _write(
        decisions / "HO-CONTEXT-MCP-ALPHA-20260101.oct.md",
        _decision("HO-CONTEXT-MCP-ALPHA-20260101", "  RATIONALE::alpha provider routing"),
    )
    _write(
        decisions / "HO-CONTEXT-MCP-BETA-20260201.oct.md",
        _decision("HO-CONTEXT-MCP-BETA-20260201", "  RATIONALE::beta caching layer"),
    )
    return tmp_path


class TestAssembleIntakeContext:
    def test_returns_intake_context_dataclass(self, tmp_path: Path) -> None:
        _seed_repo(tmp_path)
        ctx = assemble_intake_context(tmp_path, "record a provider routing decision")
        assert isinstance(ctx, IntakeContext)
        assert ctx.prose_input == "record a provider routing decision"
        # The JIT prompt and corpus are non-empty strings.
        assert isinstance(ctx.prompt, str) and ctx.prompt.strip()
        assert isinstance(ctx.corpus, str)

    def test_corpus_contains_exemplar_card_and_merged_agr_tokens(self, tmp_path: Path) -> None:
        _seed_repo(tmp_path)
        ctx = assemble_intake_context(tmp_path, "provider routing")
        # At least one exemplar card header present (few-shot).
        assert "CONCEPT_CARD" in ctx.corpus
        # Prior merged AGR tokens present (autocatalytic feed).
        assert "HO-CONTEXT-MCP-ALPHA-20260101" in ctx.corpus
        assert "HO-CONTEXT-MCP-BETA-20260201" in ctx.corpus

    def test_deterministic_across_two_calls(self, tmp_path: Path) -> None:
        _seed_repo(tmp_path)
        a = assemble_intake_context(tmp_path, "provider routing")
        b = assemble_intake_context(tmp_path, "provider routing")
        assert a.prompt == b.prompt
        assert a.corpus == b.corpus
        assert a.relevant_tokens == b.relevant_tokens

    def test_clip_retains_newest_agrs_not_head_truncation(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # Force a tiny budget so clipping is exercised.
        import hestai_context_mcp.tools.governance.intake_context as mod

        # Budget large enough for exactly one record but not two.
        decisions = tmp_path / ".hestai" / "decisions"
        old_body = "  RATIONALE::" + ("ancient " * 30)
        new_body = "  RATIONALE::" + ("newest " * 30)
        old_rec = _decision("HO-OLD-20250101", old_body)
        new_rec = _decision("HO-NEW-20261201", new_body)
        # Set budget so one full record fits but the second cannot.
        monkeypatch.setattr(mod, "_CONTEXT_BUDGET_CHARS", len(new_rec) + 10, raising=True)
        # Oldest -> newest by date suffix.
        _write(decisions / "HO-OLD-20250101.oct.md", old_rec)
        _write(decisions / "HO-NEW-20261201.oct.md", new_rec)
        ctx = assemble_intake_context(tmp_path, "anything")
        assert len(ctx.corpus) <= len(new_rec) + 10
        # Newest AGR retained; oldest dropped under budget pressure.
        assert "HO-NEW-20261201" in ctx.corpus
        assert "HO-OLD-20250101" not in ctx.corpus

    def test_jit_prompt_contains_live_repo_tokens(self, tmp_path: Path) -> None:
        _seed_repo(tmp_path)
        ctx = assemble_intake_context(tmp_path, "provider routing")
        # The prompt is JIT-compiled from live repo state: it must reference the
        # actual exemplar corpus, not be a static constant detached from the repo.
        assert "BEGIN_EXEMPLAR_CORPUS" in ctx.prompt
        assert "CONCEPT_CARD" in ctx.prompt
        assert "CONCEPT_CARD" in ctx.corpus

    def test_system_prompt_does_not_embed_prose(self, tmp_path: Path) -> None:
        _seed_repo(tmp_path)
        # Use a distinctive prose marker so the absence check is unambiguous.
        marker = "ZZ_DISTINCTIVE_PROSE_MARKER_QWERTY"
        ctx = assemble_intake_context(tmp_path, f"please {marker} record a decision")
        # FIX: the prose must NOT be embedded in the SYSTEM prompt — it is sent
        # exactly once, as the user_prompt, by the Stage-2 compiler. Embedding it
        # here too would duplicate it in every call.
        assert marker not in ctx.prompt
        assert ctx.prose_input not in ctx.prompt
        # And the prose is still preserved verbatim on the context for the
        # user-prompt path.
        assert marker in ctx.prose_input

    def test_relevant_tokens_greps_prose_relevant_ids(self, tmp_path: Path) -> None:
        _seed_repo(tmp_path)
        # Prose mentions ALPHA explicitly -> its token should be flagged relevant.
        ctx = assemble_intake_context(tmp_path, "supersede HO-CONTEXT-MCP-ALPHA-20260101 please")
        assert "HO-CONTEXT-MCP-ALPHA-20260101" in ctx.relevant_tokens

    def test_empty_repo_does_not_raise(self, tmp_path: Path) -> None:
        ctx = assemble_intake_context(tmp_path, "first ever decision")
        assert isinstance(ctx, IntakeContext)
        assert ctx.corpus == "" or isinstance(ctx.corpus, str)


class TestCompressionContract:
    """The JIT prompt must carry an explicit compression contract, not delegate
    density entirely to the exemplar corpus (the root cause of verbose output).
    """

    def test_prompt_states_compression_tier(self, tmp_path: Path) -> None:
        _seed_repo(tmp_path)
        ctx = assemble_intake_context(tmp_path, "record a decision")
        assert "CONSERVATIVE" in ctx.prompt

    def test_prompt_mandates_loss_accounting_meta(self, tmp_path: Path) -> None:
        _seed_repo(tmp_path)
        ctx = assemble_intake_context(tmp_path, "record a decision")
        assert "COMPRESSION_TIER" in ctx.prompt
        assert "LOSS_PROFILE" in ctx.prompt

    def test_prompt_mandates_plain_words_value_form(self, tmp_path: Path) -> None:
        # HO-AGR-PLAIN-WORDS-REASONING-20261031 FOLLOW_UP: relations in plain words.
        _seed_repo(tmp_path)
        ctx = assemble_intake_context(tmp_path, "record a decision")
        lower = ctx.prompt.lower()
        assert "plain words" in lower
        assert "never arrows or symbols" in lower
        # The flat-string limits stay.
        assert "flat" in lower and "40" in ctx.prompt and "newline" in lower

    def test_prompt_bans_prose_paragraph_values(self, tmp_path: Path) -> None:
        _seed_repo(tmp_path)
        ctx = assemble_intake_context(tmp_path, "record a decision")
        lower = ctx.prompt.lower()
        # It must reframe the task as COMPRESS, not faithfully transcribe prose.
        assert "compress" in lower
        # And forbid the enumerated mega-string / prose paragraph anti-pattern.
        assert "paragraph" in lower or "prose" in lower

    def test_prompt_still_carries_corpus_and_no_prose(self, tmp_path: Path) -> None:
        # The compression contract is ADDED; the exemplar corpus contract and the
        # no-prose-embedding invariant must remain intact.
        _seed_repo(tmp_path)
        marker = "ZZ_PROSE_MARKER_QWERTY"
        ctx = assemble_intake_context(tmp_path, f"{marker} record a decision")
        assert "BEGIN_EXEMPLAR_CORPUS" in ctx.prompt
        assert "CONCEPT_CARD" in ctx.prompt
        assert marker not in ctx.prompt


class TestBytecodeFewShotAndOperators:
    """#111 residual, amended by HO-AGR-PLAIN-WORDS-REASONING-20261031 FOLLOW_UP: the
    contract carries a verbose to flat-string worked example and NO operator glyphs.

    GAP-A: the ``∴`` (therefore) operator was missing from the contract's
    operator list while the Gate-A guard's own remediation text already cites it
    (type_checker.py) — a contract/guard inconsistency.
    GAP-B: the issue asked for a worked BEFORE (verbose prose) → AFTER (flat
    ≤40-word compressed-OCTAVE) one-shot; the contract described the rules but
    shipped no example. Both poles are test-verified against the real Gate-A
    guard: the BEFORE DECISION genuinely FAILS the ≤40-word guard (the "REJECTED"
    label is literally true), and the AFTER DECISION/BECAUSE genuinely PASS.
    """

    def test_drop_line_keeps_the_plain_relation_words(self) -> None:
        # HO-AGR-PLAIN-WORDS-REASONING-20261031: the DROP line must not tell the model to
        # drop connectives while the same contract tells it to write relations in words.
        from hestai_context_mcp.tools.governance.intake_context import _COMPRESSION_CONTRACT

        drop = next(ln for ln in _COMPRESSION_CONTRACT.splitlines() if ln.startswith("- DROP"))
        assert "connectives" not in drop
        assert "filler" in drop and "KEEP" in drop
        for word in ("because", "so", "and", "or", "but", "while"):
            assert word in drop, word

    def test_contract_carries_no_operator_glyphs(self) -> None:
        # The ruling replaced the compressed-OCTAVE operator clause with plain words.
        from hestai_context_mcp.tools.governance.intake_context import _COMPRESSION_CONTRACT

        found = [g for g in "→⇌∴⊕∧∨" if g in _COMPRESSION_CONTRACT]
        assert found == [], f"contract still carries operator glyphs: {found}"

    def test_prompt_carries_verbose_to_bytecode_fewshot(self, tmp_path: Path) -> None:
        # GAP-B: a stable, distinctive few-shot marker must be present so the
        # model sees a worked verbose→bytecode transformation, not just rules.
        _seed_repo(tmp_path)
        ctx = assemble_intake_context(tmp_path, "record a decision")
        # The example label (the JIT prompt is deterministic; this is a pure
        # prompt-contains assertion, no AI call).
        assert "EXAMPLE (verbose prose to flat string)" in ctx.prompt
        # And both poles of the worked transform are present.
        assert "BEFORE" in ctx.prompt and "AFTER" in ctx.prompt

    @staticmethod
    def _pole_field_value(prompt: str, pole: str, field_name: str) -> str | None:
        """Return the decoded value of the ``field_name: "..."`` line in one few-shot pole.

        The prompt carries both poles; each quoted-YAML ``decision:``/``because:``
        line is a single physical line (prose mode writes decision records as quoted
        YAML, PR-B #195). We slice the prompt to the requested pole's segment
        (BEFORE = between the BEFORE and AFTER labels; AFTER = from the AFTER label
        on) so the BEFORE and AFTER demonstration lines are never confused, and
        decode the scalar exactly as the YAML reader does.
        """
        from hestai_context_mcp.core.agent_readable_governance_parser import (
            decode_yaml_scalar,
        )

        if pole == "BEFORE":
            segment = prompt.split("BEFORE", 1)[1].split("AFTER", 1)[0]
        else:
            segment = prompt.split("AFTER", 1)[1]
        prefix = f"{field_name.lower()}:"
        line = next(
            (ln.strip() for ln in segment.splitlines() if ln.lstrip().startswith(prefix)),
            None,
        )
        return None if line is None else decode_yaml_scalar(line[len(prefix) :])

    def test_fewshot_after_lines_pass_the_gate_a_guard(self, tmp_path: Path) -> None:
        # The few-shot we TEACH must itself pass the guard it teaches: extract the
        # AFTER decision:/because: values from the assembled prompt and run them
        # through the real Gate-A reasoning-density guard. Pure, no AI call.
        from hestai_context_mcp.tools.governance.type_checker import (
            REASONING_FIELDS,
            _check_density_value,
        )

        _seed_repo(tmp_path)
        ctx = assemble_intake_context(tmp_path, "record a decision")

        for field_name in REASONING_FIELDS:
            value = self._pole_field_value(ctx.prompt, "AFTER", field_name)
            assert value is not None, f"few-shot AFTER must demonstrate a {field_name} line"
            errors: list[str] = []
            _check_density_value(field_name, value, errors)
            assert errors == [], f"taught AFTER {field_name} example violates Gate-A: {errors}"

    def test_fewshot_before_decision_fails_the_gate_a_guard(self, tmp_path: Path) -> None:
        # Both poles are test-verified: the BEFORE decision value is genuinely
        # GUARD-FAILING (>40-word multi-sentence prose), so the "REJECTED" label is
        # literally true under the Gate-A ≤40-word guard — not merely a style claim.
        # Pure, no AI call.
        from hestai_context_mcp.tools.governance.type_checker import (
            MAX_REASONING_WORDS,
            _check_density_value,
        )

        _seed_repo(tmp_path)
        ctx = assemble_intake_context(tmp_path, "record a decision")

        before = self._pole_field_value(ctx.prompt, "BEFORE", "DECISION")
        assert before is not None, "few-shot BEFORE must demonstrate a decision line"
        errors: list[str] = []
        _check_density_value("DECISION", before, errors)
        # The guard must reject the BEFORE pole, and specifically on word count so
        # the REJECTED label maps to the ≤40-word rule the example teaches.
        assert errors, "few-shot BEFORE decision must FAIL the Gate-A guard (REJECTED pole)"
        assert any(
            f"max {MAX_REASONING_WORDS}" in e for e in errors
        ), f"BEFORE must fail on the ≤{MAX_REASONING_WORDS}-word rule; got: {errors}"

    def test_contract_shows_no_octave_decision_record_field_lines(self) -> None:
        # cubic P2 on PR #246: an OCTAVE example teaches the shape prose mode must
        # not emit (an OCTAVE decision record is rejected and burns the shared retry
        # budget). No ``DECISION::``/``BECAUSE::``/``STATUS::`` anywhere in the contract.
        import re

        from hestai_context_mcp.tools.governance.intake_context import _COMPRESSION_CONTRACT

        found = re.findall(r"\b(?:DECISION|BECAUSE|STATUS)::", _COMPRESSION_CONTRACT)
        assert found == [], f"contract still shows OCTAVE decision-record fields: {found}"

    def test_metadata_lines_show_the_yaml_status_form(self) -> None:
        from hestai_context_mcp.tools.governance.intake_context import _COMPRESSION_CONTRACT

        assert 'status: "PROPOSED"' in _COMPRESSION_CONTRACT
        assert 'status: "RATIFIED"' in _COMPRESSION_CONTRACT  # named only to forbid it


class TestMetadataFidelityContract:
    """The prompt must forbid fabricating governance provenance.

    Live-tool testing showed the compiler copied RATIFIED / RATIFIED_BY /
    ISSUE_REF / dates from the exemplar corpus, auto-asserting a human
    ratification that never happened. The contract must constrain metadata to
    what the prose supports and leave ratification to the human merge.
    """

    def test_prompt_defaults_status_to_proposed(self, tmp_path: Path) -> None:
        _seed_repo(tmp_path)
        ctx = assemble_intake_context(tmp_path, "record a decision")
        assert "PROPOSED" in ctx.prompt

    def test_prompt_forbids_fabricated_ratification(self, tmp_path: Path) -> None:
        _seed_repo(tmp_path)
        ctx = assemble_intake_context(tmp_path, "record a decision")
        lower = ctx.prompt.lower()
        assert "fabricate" in lower
        # The specific fabricated provenance fields are named so the model knows.
        assert "RATIFIED_BY" in ctx.prompt
        assert "ratification" in lower and "merge" in lower

    def test_prompt_treats_corpus_as_shape_not_data_to_clone(self, tmp_path: Path) -> None:
        _seed_repo(tmp_path)
        ctx = assemble_intake_context(tmp_path, "record a decision")
        lower = ctx.prompt.lower()
        # Dates / issue refs must not be copied from the exemplar corpus.
        assert "copy" in lower or "clone" in lower

    def test_prompt_suppresses_reasoning_output(self, tmp_path: Path) -> None:
        # Output discipline: emit ONLY the OCTAVE block (curbs the reasoning-token
        # spend that truncated large inputs at the output cap).
        _seed_repo(tmp_path)
        ctx = assemble_intake_context(tmp_path, "record a decision")
        assert "no reasoning" in ctx.prompt.lower()


class TestVerifySupersessionTarget:
    def test_existing_target_returns_true(self, tmp_path: Path) -> None:
        _seed_repo(tmp_path)
        assert verify_supersession_target(tmp_path, "HO-CONTEXT-MCP-ALPHA-20260101") is True

    def test_missing_target_returns_false(self, tmp_path: Path) -> None:
        _seed_repo(tmp_path)
        assert verify_supersession_target(tmp_path, "HO-DOES-NOT-EXIST-20260101") is False


class TestQuotedTextAndYamlOutputContract:
    """PR-B (#195): the contract states that quoted text is never compressed, and that
    a DECISION_RECORD is written as quoted YAML (HO-RECORDS-YAML-DEFAULT-20261031).

    The fidelity guard (intake_pipeline) enforces both; the contract asks for them so a
    first attempt usually passes without spending the retry budget.
    """

    def test_contract_says_quoted_text_is_never_compressed(self) -> None:
        from hestai_context_mcp.tools.governance.intake_context import _COMPRESSION_CONTRACT

        lower = _COMPRESSION_CONTRACT.lower()
        assert "quoted text is never compressed" in lower
        assert "byte for byte" in lower
        assert "only unquoted text is compressed" in lower

    def test_contract_names_the_verbatim_fields(self) -> None:
        from hestai_context_mcp.tools.governance.intake_context import _COMPRESSION_CONTRACT

        for name in ("VERBATIM", "OPERATOR_RULING", "_VERBATIM"):
            assert name in _COMPRESSION_CONTRACT, name

    def test_contract_asks_for_a_quoted_yaml_decision_record(self, tmp_path: Path) -> None:
        _seed_repo(tmp_path)
        ctx = assemble_intake_context(tmp_path, "record a decision")
        assert "quoted YAML" in ctx.prompt
        assert "never OCTAVE" in ctx.prompt
        assert "facet card stays one OCTAVE block" in ctx.prompt
