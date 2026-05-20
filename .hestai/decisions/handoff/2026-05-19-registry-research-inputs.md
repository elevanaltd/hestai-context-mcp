# Decision Registry Research — Implementation Inputs (PR-F / PR-G)

**Date**: 2026-05-19
**Status**: load-bearing reference for downstream implementation PRs
**Owners**: implementer of PR-F (MCP-tool fail-fast) and PR-G (CI gate)

## What this is

Two independent literature surveys on multi-agent decision registry architecture and concurrency. They were authored by external research agents during the PR-α → PR-D drafting sequence and reach convergent recommendations that materially align with the architecture ratified in ADR-RFC-ARCH-001 through ADR-RFC-ARCH-004. They are preserved here as load-bearing implementation references — the substance has not been ratified as governance, but the schemas, audit lenses, and acceptance-criteria checklists are direct inputs the PR-F / PR-G implementer should consult.

## Sources

- [`docs/research/2026-05-19-decision-registry-architecture-research.md`](../../../docs/research/2026-05-19-decision-registry-architecture-research.md) — pattern survey (Git-native sharding, append-only events, DB-backed registries, MCP layers, PR queues, CRDT stores, structured merge), tool catalogue, candidate-architecture ranking, migration path.
- [`docs/research/2026-05-19-decision-registry-concurrency-research.md`](../../../docs/research/2026-05-19-decision-registry-concurrency-research.md) — concurrency-focused companion: stale-read detection, optimistic-concurrency tokens, GitHub merge-queue / CODEOWNERS framing as concurrency primitives, SQLite FTS5 + BM25 schemas, append-only event schema examples, acceptance criteria.

**Citation durability**: both reports use `turn*view*` / `turn*search*` citation markers that point at external sources captured at authoring time. These markers are not stable URLs and will not resolve via web fetch as written. Treat the cited claims as plausible but **non-durable** unless re-verified against primary sources at implementation time. The reports' substantive recommendations stand on their own internal logic and cross-validation with our ratified ADRs; do not treat any single cited claim as binding without independent confirmation.

## Why they're committed (non-authoritative)

Per ADR-RFC-ARCH-001 §2, any artefact referenced authoritatively MUST resolve to a committed repo-relative path. These reports are referenced from this handoff as load-bearing reference material for downstream implementation work; therefore they live at a committed path (`docs/research/`). They are **NOT** governance — they did not pass CIV/SR review and are not ratified. They are research-grade inputs whose recommendations the implementer evaluates against the already-ratified ADRs.

`docs/research/` is the standard placement for committed research material that informs but does not bind decisions. This is distinct from `.hestai/decisions/` (committed governance) and `.hestai/state/sessions/` (ephemeral / non-authoritative).

## What the reports add to the ratified architecture

Mapping the research recommendations to our shipped ADRs:

| Research recommendation | Where it lands in our architecture | Status |
|---|---|---|
| Atomic decision files per record | ADR-RFC-ARCH-004 §1 (AGR records, one per file) | Ratified |
| Generated monolith + index + SQLite projection as derived views | ADR-RFC-ARCH-002 §1 (L2 acceleration cache) + L1S facet cards | Ratified |
| Read-only MCP first, proposal broker later | ADR-RFC-ARCH-002 §3 (MCP-tool fail-fast); ADR-RFC-ARCH-004 §3 (broker scope) | Ratified |
| Git canonical; DB / MCP derived | ADR-RFC-ARCH-002 §1 (L0 canonical / L2 never authoritative) | Ratified |
| Stale-read detection via source revision or content hash | ADR-RFC-ARCH-004 §3 / §4 (`expected_record_hash` CAS primitive) | Ratified |
| MCP writes must be proposal-only (EventSourcingDB primary source) | ADR-RFC-ARCH-002 §3 + ADR-RFC-ARCH-004 §3 | Ratified |
| SQLite FTS5 + BM25 as L2 implementation | ADR-RFC-ARCH-002 §1 (L2 implementation is flexible; SQLite is one choice) | Deferrable to G6 benchmark |
| Append-only events as optional later step | Compatible; not in v1 | Deferred to RFC #40 v2 |
| CRDTs are wrong for governance | Not in our architecture; both reports confirm avoidance | Confirmed |

## What the reports provide that the implementer should consult directly

1. **Concrete schemas** for the L2 SQLite projection (`decisions`, `decision_events`, `decision_edges`, `files`, `decision_fts` virtual table with FTS5 + BM25 column weighting). See concurrency report §"Suggested schema examples".
2. **JSON event schema** for append-only decision events (`event_id`, `decision_id`, `event_type`, `actor`, `source.read_revision`, `source.read_commit`, `payload`, `recorded_at`). Useful even though events are deferred — defines the shape if/when v2 reopens.
3. **Walkthrough audit lens** — a per-decision checklist (scope global/app/domain, lifecycle state, supersedure chain, evidence, edit-vs-event classification, concurrency-hotspot likelihood). Apply when migrating any legacy monolith (e.g. elevana-studio's `DECISIONS.oct.md`) to atomic AGR records.
4. **Acceptance criteria** for Phase 1 success (one authoritative editable source per record; generated artefacts clearly marked non-authoritative; same-record proposals detectable as stale before merge; supersedure chains machine-traversable; etc.). Useful as test scenarios *within their proper scope*: PR-G owns ADR-002's placement CI gate only; CAS / stale-read merge-time enforcement is ADR-004's broker concern (PR-D′ / PR-H lane). Do not let the research's acceptance criteria expand PR-G beyond its placement-CI mandate without an explicit operator-level rescoping decision.
5. **Executive prompt for a solution-engine architect** — a self-contained brief that maps almost 1:1 to our sequencing. Useful as a sanity check when scoping any broker implementation work.

## Out of scope for these reports (filled by other artefacts)

The reports assume Markdown ADRs throughout and are silent on **intra-file format**. The Indexed Prose-Graph (IPG) kernel discussed in the 2026-05-19 debate-hall sessions (`2026-05-19-octave-canonical-rationale-standard` and `…-premium`) addresses this gap. IPG is additive on top of the reports' inter-file architecture — same atomic-record-per-file, with OCTAVE-canonical single-envelope prose-tagged-with-IDs as the intra-file format. The reports and IPG do not conflict; they operate at different levels of the stack.

## Notes for future work — explicitly deferred

- **`docs/adr/` projection target** for Backstage / Structurizr / MADR-tooling interop. Our canonical placement is `.hestai/decisions/`; a generated `docs/adr/` view would enable third-party tooling. Not now. Surface when external integration becomes a priority.
- **Audit-lens migration of elevana-studio's `DECISIONS.oct.md`** (currently ~88k tokens). Apply the walkthrough audit lens when that work begins. Not on this repo's critical path.

## Provenance

Reports authored externally; pasted into this repository under `.hestai-state/reports/` (gitignored, ephemeral) on 2026-05-19; relocated to `docs/research/` (committed, non-authoritative reference) the same day per operator instruction. Original sources are external research agents; no in-house authorship beyond placement and this handoff.
