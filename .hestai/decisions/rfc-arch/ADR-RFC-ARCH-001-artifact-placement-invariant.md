# ADR-RFC-ARCH-001 — Artifact Placement Invariant for Committed Governance

- **Status**: PROPOSED (awaiting CIV + SR review)
- **Date**: 2026-05-16
- **Scope**: hestai-context-mcp repository (LOCAL repo-relative paths only)
- **Sequence**: PR-α (this ADR); supersedes by PR-B IA Contract ADR when it lands
- **Related**: PR-A rescue (commits `2af70f3`, `385757a`, `bcbef4c` / PR #45), Mac B#1 carry-forward (`.hestai/decisions/handoff/2026-05-16-rfc-40-mac-b1-carry-forward.md`), RFC #38 (Facet ABI), RFC #40 (AGR)
- **Authority**: HOLISTIC_ORCHESTRATOR drafting; operator-pre-ratified convergent architecture (debate-hall 2026-05-16, premium "Executable Skeleton with Bounded Peers" + standard "Ratchet Kernel Governance"); Principal Engineer amendments folded in
- **Invariants invoked**: PROD::I1 (SESSION_LIFECYCLE_INTEGRITY), PROD::I3 (PROVIDER_AGNOSTIC_CONTEXT), PROD::I4 (STRUCTURED_RETURN_SHAPES), SYS::I1 (CONTEXT_INTEGRITY)

## 1. Context

Multi-machine HO coordination on `hestai-context-mcp` produced parallel sessions whose governance work product (BUILD-PLANs, arbitration records, control-room ledger, phase handoffs) was authored to paths under `.hestai/state/sessions/…`. That subtree is gitignored on this repository (`.hestai/state` is a symlink to `.hestai-state/`), so authoritative artifacts referenced from open issues, RFC bodies, and committed facet cards silently failed to resolve for any other session, machine, or reviewer.

The root cause is not a per-session author error. It is a SKILL-encoded convention: `ho-control-room` SKILL §3.DIRECT_WRITE_ALLOWED and §3.ARTIFACT_PLACEMENT_EXAMPLES (file `.hestai-sys/library/skills/ho-control-room/SKILL.md`, lines 96–112) instruct every HO session to place phase BUILD-PLAN, completion ledger, arbitration records, and handoff artifacts under `.hestai/state/sessions/…`. Following the SKILL faithfully produces orphaned governance — the cross-cutting binding finding recorded verbatim in §"Cross-cutting binding finding" of the Mac B#1 carry-forward.

PR-A (PR #45) physically rescued the orphaned artifacts to committed paths under `.hestai/decisions/`. PR-A is a symptom fix: it preserves Mac B#1's outputs but does not bind the rule that prevents recurrence and does not correct the SKILL. PR-α is the minimum binding rule that closes both gaps while the broader PR-B IA Contract ADR is sequenced.

The convergent architecture ratified 2026-05-16 establishes a layered governance topology — L0 canonical git (DECISIONS, North Stars, ADRs), L1 phase governance (BUILD-PLANs, arbitrations, now committed), L1S facet ABI (RFC #38), L2 optional acceleration cache (gitignored, content-hash keyed), L3 retrieval (RFC #38 internals), L4 session-local (session.json, FAST tier, ledger). PR-α scopes the placement invariant to L0/L1/L1S (committed governance) versus L4 (session-local) versus L2 (optional cache). Routing rules between L1S #38 and L3 #40 are PR-B scope.

## 2. Decision

The following placement invariant is binding for hestai-context-mcp:

> **Any artifact referenced by an open issue, ADR, RFC, PR body, or committed facet card as authoritative MUST resolve to a committed repo-relative path OR be explicitly marked ephemeral/non-authoritative at the reference site.**

Scope is **LOCAL repo-relative paths only**. External URIs, cross-repo references, opaque tokens, and content-addressed identifiers are out of scope; PR-B's IA Contract ADR will address cross-repo cases.

Four placement categories are defined for this repository:

| Category | Path root | Git status | Purpose |
|---|---|---|---|
| `committed_governance` | `.hestai/decisions/` | committed | ADRs, BUILD-PLANs, arbitration records, phase handoffs, security design docs — any artifact a reader is entitled to expect resolves identically across machines and sessions |
| `committed_context_cards` | `.hestai/context/` | committed | Concept / Frame / Cluster / Phase facet cards (RFC #38 L1S substrate) and any other reviewable structured context |
| `ephemeral_session_state` | `.hestai/state/sessions/` | gitignored | Per-session scratch: in-flight checkpoints, FAST-tier session state, run-local artifacts that intentionally do not survive session close |
| `optional_cache` | `.hestai/state/cache/` | gitignored | Content-hash-keyed retrieval acceleration (L2). Never authoritative; rebuildable; consulted only after a stable canonical source resolves |

A reference site that points into `ephemeral_session_state` or `optional_cache` MUST be explicitly marked `EPHEMERAL` or `NON_AUTHORITATIVE` adjacent to the reference, otherwise the reference is treated as a violation of this invariant.

## 3. Consequences

**Immediate (this ADR):**

- The binding placement rule above is in force from ratification. PR reviewers cite this ADR to reject any new authoritative reference into a gitignored path.
- **`ho-control-room` SKILL §3 correction (root cause — LANDED upstream)**: the SKILL at `.hestai-sys/library/skills/ho-control-room/SKILL.md` previously directed HO sessions to place BUILD-PLAN / completion / arbitration / handoff artifacts under `.hestai/state/sessions/…` (§3.DIRECT_WRITE_ALLOWED, §3.ARTIFACT_PLACEMENT_EXAMPLES, §5 ANCHOR_KERNEL `place_phase_artifacts_in_sessions_zone`). That convention was the proximate cause of the Mac B#1 governance leak. **The corrective Vault PR has landed**: §3.DIRECT_WRITE_ALLOWED now lists `committed_governance` (`.hestai/decisions/`) and `committed_context_cards` (`.hestai/context/`) as primary write paths with ledger/coordination marked ephemeral; §3.ARTIFACT_PLACEMENT_EXAMPLES routes phase BUILD-PLAN / completion / arbitration / handoff / ADR to `.hestai/decisions/…` and facet cards to `.hestai/context/…`; §5 ANCHOR_KERNEL `MUST::` adds `place_committed_governance_in_decisions_zone` + `keep_only_ephemeral_state_in_sessions_zone`, and `NEVER::` adds `place_authoritative_artifact_in_gitignored_path_without_explicit_EPHEMERAL_marker`. The upstream SKILL cites ADR-RFC-ARCH-001 in its DIRECT_WRITE_ALLOWED REFS. The verbatim text §6 below is the historical ratified record. The cross-cutting binding finding in `.hestai/decisions/handoff/2026-05-16-rfc-40-mac-b1-carry-forward.md` is closed.

**Sequenced (NOT in this ADR):**

- **PR-B (IA Contract ADR + CI gate spec + MCP-tool fail-fast requirement)** owns the fuller information-architecture contract, including query-routing rules between RFC #38 (`lookup_concept`) and RFC #40 (`lookup_decision`), the stable-vs-temporal boundary, and the CI gate that enforces this placement invariant at review time. PR-B SUPERSEDES this ADR's binding rule into a broader contract; this ADR's category list is intended to be carried forward verbatim or refined under PR-B.
- **PR-F (MCP-tool-level fail-fast)** is the strongest defense: `clock_out` / `octave_write` reject governance-class writes to gitignored paths at the tool boundary. CI is the review-time backstop.
- **PR-G (CI gate implementation)** lands the local repo-relative path scanner — explicitly scoped to repo-relative paths only per PE amendment, to avoid false positives on URIs, opaque tokens, and cross-repo refs.

**Out of scope here (do not infer):**

- Cross-repo placement rules (PR-B).
- Query-routing between #38 and #40 (PR-B).
- Decision Journal Light scope reconciliation with RFC #40 (PR-D).
- Ledger schema resolution v1.4 vs v2.0 (PR-E).
- Any enforcement implementation (PR-F, PR-G).
- Re-debate of umbrella-vs-peers architecture (settled 2026-05-16).

## 4. Invariant chain

This ADR is a direct instantiation of:

- **PROD::I1 SESSION_LIFECYCLE_INTEGRITY** — "every_session_has_clean_create_and_archive_lifecycle". A session whose governance artifacts vanish to gitignored paths does not have clean archival. The placement invariant makes archival mechanically verifiable.
- **PROD::I3 PROVIDER_AGNOSTIC_CONTEXT** — "context_synthesis_identical_regardless_of_AI_provider_or_CLI". This requires authoritative artifact references to resolve identically across providers, which requires stable committed paths.
- **PROD::I4 STRUCTURED_RETURN_SHAPES** — Programmatic extraction of governance artifact references requires those references to resolve at predictable, version-controlled paths.
- **SYS::I1 CONTEXT_INTEGRITY** — "Agent MUST declare ROLE and PHASE before action" generalises at the artifact layer to: an artifact MUST resolve to a committed path before it is treated as authoritative.

## 5. Verification

The minimum verification for this ADR is review-only (TIER_3, facets [GOVERNANCE]) via CIV + SR per `/review` skill. No code is added by this ADR. Machine enforcement is intentionally deferred:

- Tool-level fail-fast → PR-F (first defense).
- CI gate scanning → PR-G (review-time backstop, repo-relative only).

Until PR-F and PR-G land, enforcement is by review discipline: any PR touching `.hestai/state/sessions/…` or `.hestai/state/cache/…` that does not also carry an explicit `EPHEMERAL` / `NON_AUTHORITATIVE` marker at the reference site is rejected on placement grounds, citing this ADR.

## 6. Ratified `ho-control-room` SKILL amendment (verbatim — LANDED upstream)

The upstream `.hestai-sys/library/skills/ho-control-room/SKILL.md` has been amended with the following substance (Vault PR landed; the SKILL cites this ADR in its DIRECT_WRITE_ALLOWED REFS). Preserved here as the historical ratified record:

**§3.DIRECT_WRITE_ALLOWED — replace current placement keys:**

```
committed_governance::.hestai/decisions/**/*.{md,oct.md}
committed_context_cards::.hestai/context/**/*.oct.md
ledger::.hestai/state/sessions/control-room-ledger.oct.md          # ephemeral; not authoritative
coordination::.hestai/state/sessions/**/*                          # ephemeral; not authoritative
optional_cache::.hestai/state/cache/**/*                           # gitignored; never authoritative
medium_context_BLOCKED::.hestai/state/context/*.oct.md→octave-secretary_via_oa-router
fast_context_BLOCKED::.hestai/state/context/state/*.oct.md→owned_by_session_lifecycle_tools_only
project_docs::[README.md, CLAUDE.md]
```

**§3.ARTIFACT_PLACEMENT_EXAMPLES — replace existing entries:**

```
phase_BUILD_PLAN::.hestai/decisions/phase-<id>/BUILD-PLAN.oct.md
phase_completion_ledger::.hestai/decisions/phase-<id>/completion.oct.md
arbitration_record::.hestai/decisions/phase-<id>/arbitration-<n>.oct.md
phase_handoff::.hestai/decisions/handoff/<YYYY-MM-DD>-<topic>.md
ADR::.hestai/decisions/<group>/ADR-<id>-<slug>.md
facet_card::.hestai/context/concepts/<repo-id>/<CARD_ID>.oct.md
control_room_ledger::.hestai/state/sessions/control-room-ledger.oct.md   # ephemeral
delegation_log::control-room-ledger.oct.md_§2_DELEGATION_LOG             # ephemeral
medium_PROJECT_CONTEXT_delta::BLOCKED→delegate_to_octave-secretary
fast_current-focus_update::BLOCKED→owned_by_session_lifecycle_tools
fast_checklist_update::BLOCKED→owned_by_session_lifecycle_tools
fast_blockers_update::BLOCKED→owned_by_session_lifecycle_tools
```

**§5 ANCHOR_KERNEL — replace clause `place_phase_artifacts_in_sessions_zone<.hestai/state/sessions/phase-<id>/>` with:**

```
place_committed_governance_in_decisions_zone<.hestai/decisions/{phase-<id>|handoff|<group>}/>,
keep_only_ephemeral_state_in_sessions_zone<.hestai/state/sessions/>
```

**§5 ANCHOR_KERNEL — add to `NEVER::`:**

```
place_authoritative_artifact_in_gitignored_path_without_explicit_EPHEMERAL_marker
```

## 7. Supersession

This ADR is **expected to be superseded** by PR-B's IA Contract ADR. Supersession is the normal path, not a failure mode. The intent is that PR-B's broader contract subsumes the four categories defined here without altering their semantics; if PR-B narrows or widens a category, the change must be explicit and traceable to this ADR's identifier.
