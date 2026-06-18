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

    def test_prompt_mandates_telegraphic_value_form(self, tmp_path: Path) -> None:
        _seed_repo(tmp_path)
        ctx = assemble_intake_context(tmp_path, "record a decision")
        lower = ctx.prompt.lower()
        assert "telegraphic" in lower
        # Operators are named so the model knows what carries the connectives.
        assert "⊕" in ctx.prompt and "⇌" in ctx.prompt and "→" in ctx.prompt

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
