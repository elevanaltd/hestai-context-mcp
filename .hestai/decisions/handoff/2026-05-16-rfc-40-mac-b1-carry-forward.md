# Mac B#1 Session Carry-Forward — rfc-40/three-layer-frame-card

**Date**: 2026-05-16
**Source session**: `rfc-40/three-layer-frame-card` branch, Mac B#1
**Status**: session closed; this document preserves session outputs

## Why this exists

Multi-machine HO coordination produced three parallel sessions on `hestai-context-mcp` with no cross-visibility. Mac B#1 authored RFC #40 + PR #42 + octave-mcp #420 + several RDs of ledger across 2026-05-13 to 2026-05-16. Their session ledger lived at gitignored `.hestai/state/sessions/control-room-ledger.oct.md` (PROD::I1 SESSION_LIFECYCLE_INTEGRITY violation — session archival is incomplete when governance artifacts vanish to gitignored paths). This document is the committed summary that survives session close.

Raw ledger promotion is **deferred to PR-E ledger schema ADR** per Principal Engineer ruling — committing the raw v1.4 ledger before resolving the v1.4-vs-v2.0 schema divergence would embed structural debt.

## Session carry-forward (verbatim from Mac B#1)

```
SESSION CARRY-FORWARD FROM rfc-40/three-layer-frame-card (Mac B #1)

A. ARTIFACTS PRODUCED, ALL ON MAIN, NOT LOST:
   - PR #42 (THREE_LAYER_GOVERNANCE_FRAME facet card) — MERGED 2026-05-13.
   - PR #41 (original dogfood attempt) — CLOSED in favour of #42's clean re-do.
   - octave-mcp issue #420 — filed with 8-envelope spec + 6 reference cards + acceptance criteria.
   - Issue #40 (RFC AGR) — filed; body says "peer to RFC #38" which needs revision by umbrella
     to "subordinate-to-IA-Contract-ADR, peer-to-RFC-#38-within-its-layer".
   - Comment on issue #38 (SQL synthesis, three inputs for ADR drafting):
     https://github.com/elevanaltd/hestai-context-mcp/issues/38#issuecomment-4466784900

B. ARTIFACTS AT RISK (gitignored on Mac B #1):
   - Control-room ledger: .hestai/state/sessions/control-room-ledger.oct.md
     (19 RDs covering RD12 through RD19). Per Principal Engineer ruling, raw ledger
     promotion handled separately under PR-E ledger schema ADR; not blocking PR-A.

C. LIVE CONTINUATIONS (PAL clink, reusable):
   - ho-liaison: bf4120a1-1c7d-4d15-97ac-ce0faba66575 (39 turns remaining;
     used for relevance audit of transferred-from-hestai-mcp issues).
   - octave-secretary: 7eaaa886-9db7-4526-9e23-af89f58b8daf (39 turns;
     used for THREE_LAYER_GOVERNANCE_FRAME authoring).
   - standards-reviewer: 0a0ea933-0f15-4768-9576-7299ef5a4cb4 (39 turns;
     used for SR APPROVED on PR #42).

D. EMPIRICAL INPUTS THE UMBRELLA / LAYER ADRs SHOULD WEIGH:
   - Two reproductions of the octave_write multi-envelope schema-collapse
     bug (PR #39's 5 cards via octave-secretary, PR #42's fix via the
     same workaround). octave-mcp #420 captures the pattern.
   - The SQL synthesis (SQLite as L2 candidate alongside BM25; two new
     MCP tool ideas list_stale_decisions / explain_governance_for_path;
     append-only events as future evolution path NOT v1).
   - This session itself: 19 RDs of multi-agent orchestration ledger
     exists ONLY at gitignored path, demonstrating the placement bug.

E. KNOWN OPEN HOUSEKEEPING (pre-pause, defer to post-umbrella):
   - Issue #25 (Decision Journal Light) overlaps RFC #40 scope.
     PR-D reconciliation should address.
   - Issue #34 still OPEN despite PR #35 merge (no Closes keyword).
   - Issue #33 still OPEN, superseded by #38+#40.

F. PROD::I# IMPLICATIONS:
   - The placement bug is borderline PROD::I1 (SESSION_LIFECYCLE_INTEGRITY):
     "every_session_has_clean_create_and_archive_lifecycle". Sessions whose
     governance artifacts vanish to gitignored paths do not have clean
     archival. The IA Contract ADR (PR-B) and CI gate may want to formalise
     this as an explicit I1 violation that the rescue PR closes.
```

## Decision-record promotion candidates for PR-D (RFC #40 AGR)

Mac B#1 surfaced three RDs from their ledger that carry durable binding content. These are NOT promoted in PR-A — they are listed here as inputs for PR-D once RFC #40 ratifies. Verbatim from Mac B#1:

### Candidate 1 — RD17: AGR Standard Ownership Ruling

- **Token**: `HO-CONTEXT-MCP-OWNS-AGR-STANDARD-20260513`
- **Substance**: hestai-context-mcp owns the Agent-Readable Governance Records standard. Schema must be syntactic superset of elevana-studio HO-token convention. `HUMAN_ADR_REF` field is OPTIONAL. Adoption is opt-in; non-adopters fully supported indefinitely. AGRs are L1, distinct from L0 human ADRs and L2 Facet ABI cards.
- **Cross-refs**: Issue #40, ADR-0013 (substrate ruling), THREE_LAYER_GOVERNANCE_FRAME (PR #42).
- **Status after umbrella**: framing changes from "peer to RFC #38" → "subordinate-to-IA-Contract-ADR within L3". The ruling itself is preserved.

### Candidate 2 — RD18: OCTAVE_WRITE multi-envelope workaround sanctioned (provisional)

- **Token**: `HO-OCTAVE-WRITE-MULTI-ENVELOPE-WORKAROUND-20260513`
- **Substance**: `octave_write` currently collapses multi-envelope Facet ABI cards to META-only via `TN_RECONCILE_CANONICAL`. Direct-write is the project-accepted workaround for FRAME_CARD / CONCEPT_CARD authoring until octave-mcp #420 lands. Two empirical reproductions on record (PR #39 × 5 cards, PR #42 × 2 reproductions on one card). OCTAVE_WRITE_GATE remains binding for all other `.oct.md` authoring.
- **Cross-refs**: octave-mcp #420, PR #39, PR #42.
- **Status**: provisional. Token should be `VOID`'d or `SUPERSEDED` when #420 lands.
- **v1.13.0 addendum (2026-05-28)**: octave-mcp v1.13.0 ships `format_style='preserve'` (Strategy A, GH#377) — span-aware mode that keeps clean nodes verbatim and only re-emits dirty/repaired nodes. This is the most likely path to resolving the multi-envelope collapse. **Retest required**: author a FRAME_CARD or CONCEPT_CARD with multiple envelopes using `octave_write(format_style='preserve')` and verify all envelopes survive. If confirmed fixed, VOID this token. Until confirmed, workaround remains active. See `.hestai/decisions/tooling/octave-preserve-mode-upgrade.md`.

### Candidate 3 — RD15: Decisions-as-Context is Platform-Scope (historical)

- **Token**: `HO-DECISIONS-AS-CONTEXT-PLATFORM-SCOPE-20260505`
- **Substance**: decisions are context; agent-readable governance is a platform-layer concern not a project-local one; hestai-context-mcp is the right home for the standard. Filed as discovery in issue #33, refined into RFC #40 (#33 superseded on architecture).
- **Status after umbrella**: subsumed by the IA Contract ADR direction. Preserve as historical-`RATIFIED` with `SUPERSEDED_BY` link to whatever umbrella token PR-B produces.

### Operational noise (NOT promoted as decision records)

RD12 (issue #30 dispatch), RD13 (issue #23 dispatch), RD14 (backlog grouping), RD16 (relevance audit verdicts, except the OBSOLETE-on-#23 finding which is already on issue #43), RD19 (SQL synthesis comment on #38 — already linked from §A above). These remain in ledger provenance only.

## Cross-cutting binding finding (for PR-B IA Contract ADR drafter)

Verbatim from Mac B#1:

> `ho-control-room` SKILL `§3.DIRECT_WRITE_ALLOWED` lists ledger + coordination + project_docs as allowed write paths, and `§3.ARTIFACT_PLACEMENT_EXAMPLES` instructs HO to place BUILD-PLAN / completion / arbitration / handoff under `.hestai/state/sessions/<session-id>/`. That path is gitignored under current convention (`.hestai/state` symlinks to `.hestai-state/`). **Following the SKILL faithfully produces orphaned governance.** The IA Contract ADR's CI gate should ensure this convention is fixed in lockstep with PR-B, otherwise the next HO session reproduces the loss.

This is the root cause of the placement bug. PR-B (IA Contract ADR + CI gate) MUST update `ho-control-room::ARTIFACT_PLACEMENT_EXAMPLES` and `§3.DIRECT_WRITE_ALLOWED` to point at committed paths, simultaneously with ratifying the placement invariant.

## Closing

Mac B#1 session is closed. Continuations in §C remain reusable from any session. PR-A landing this document closes the immediate loss vector for Mac B#1's work product.

Next reads after merge: PR-α (placement ADR), PR-B (IA Contract + CI gate), then PR-D (RFC #40 AGR, where candidates 1-3 above promote to formal records).
