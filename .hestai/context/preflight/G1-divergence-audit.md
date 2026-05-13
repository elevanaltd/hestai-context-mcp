# G1 — Divergence Audit (RFC #38 pre-flight gate)

**Executor**: ho-liaison via pal_clink(goose, ho-liaison)
**Date**: 2026-05-08
**Inputs**:
- `/Volumes/HestAI-Projects/hestai-context-mcp/.hestai-state/context/PROJECT-CONTEXT.oct.md` (mac A, 73 lines)
- `/Volumes/HestAI-Projects/hestai-context-mcp/.hestai-state/context/PROJECT-CONTEXT-other-mac.oct.md` (mac B, 88 lines)

## Question

For each delta between the two files, classify as SEMANTIC_FACT (governance-grade; should promote to committed git) or SESSION_EPHEMERA (transient working state; correctly belongs in local-only PROJECT-CONTEXT).

## Delta table

| # | Section/Line range | Mac A content | Mac B content | Classification | Promotion target |
|---|---|---|---|---|---|
| 1 | META | VERSION 1.0.0, LAST_UPDATED 2026-04-22 | VERSION 1.2.0, ADR_0013_B1_MERGED, LAST_UPDATED 2026-05-02 | SEMANTIC_FACT | DECISIONS.oct.md |
| 2 | §1::CURRENT_STATE | pytest<604_tests>, COVERAGE: 91% | pytest<853_tests>, COVERAGE: 91.20% | SESSION_EPHEMERA | (keep local) |
| 3 | §2::ARCHITECTURE | Base internal components | Added StorageAdapter, LocalFilesystemAdapter, Outbox_status_only_queue, etc. | SEMANTIC_FACT | day-one-seed |
| 4 | §2::ARCHITECTURE | N/A | Added PORTABLE_ARTIFACT_VARIANTS, ON_DISK_LAYOUT constraints | SEMANTIC_FACT | ADR / DECISIONS.oct.md |
| 5 | §3::HARVEST_PHASES | Phase 2 pending | Added PHASE_PSS_B1 complete, Phase 2 updated with SHIPPED facts | SEMANTIC_FACT | DECISIONS.oct.md |
| 6 | §4::KNOWN_GAPS | basic workbench integration tracking | Added workbench issue #161, ADR_0013_FOLLOWUPS, TYPEGUARD_HELPERS | SEMANTIC_FACT | DECISIONS.oct.md |

## Summary

- TOTAL_DELTAS: 6
- SEMANTIC_FACT_COUNT: 5
- SESSION_EPHEMERA_COUNT: 1

## Promotion list

- Version bump, release dates, and ADR tracking → DECISIONS.oct.md
- System architecture components and service inventory → day-one-seed
- Storage layout paths and discriminated union architecture constraints → ADR / DECISIONS.oct.md
- Phase completion statuses and milestone boundaries → DECISIONS.oct.md
- Known gaps mapping and deferred tracking issues → DECISIONS.oct.md

## Observed pattern

The vast majority of the deltas are governance-grade semantic facts (architecture components, phase boundaries, layout constraints, architectural decisions), not transient ephemera. This indicates that `.hestai-state/context/PROJECT-CONTEXT.oct.md` is being fundamentally misused as a mixed substrate — permanent architectural knowledge is actively being written into a local, gitignored directory, causing permanent configuration drift and loss of system coherency across machines.

## Recommendation

The file must be split into strictly enforced committed-semantic and local-ephemera halves. All governance facts (phases, architecture, layout boundaries, decisions) should be promoted out of `.hestai-state` and committed to git (e.g., within `DECISIONS.oct.md` or a globally tracked `.hestai-sys/PROJECT-CONTEXT.oct.md`), leaving `.hestai-state/context/PROJECT-CONTEXT.oct.md` as the pure, transient substrate for machine-local working state measurements (like test coverage, active session notes, and current branch state). This completely resolves the root cause of the divergence.

## Implication for RFC #38 architecture

This audit empirically confirms one of the merged-synthesis assumptions: **the divergence problem is structural, not synchronisation**. The fix is not a remote PSS adapter or a network-based sync mechanism. The fix is to stop writing semantic facts into local-only state and route them to L1 (committed git) or — once the architecture lands — L1S facet cards. The mac-to-mac divergence resolves automatically once that discipline is enforced because git already distributes L1.

This is a **pre-flight architectural validation** of RFC #38: if 5 of 6 observed deltas are misclassified writes, then the L1 + L1S design is the right shape for v1.
