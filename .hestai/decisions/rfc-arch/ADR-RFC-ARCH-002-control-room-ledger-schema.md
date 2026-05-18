# ADR-RFC-ARCH-002 — Control-Room Ledger Schema (v1.x vs v2.x Resolution)

- **Status**: PROPOSED (awaiting CIV + SR review)
- **Date**: 2026-05-18
- **Scope**: `hestai-context-mcp` repository. Governs the FORMAT of `.hestai/state/sessions/control-room-ledger.oct.md` only. Placement category and authority elevation are out of scope (settled by PR-α).
- **Sequence**: PR-E in the RFC-arch series. Parallelizable with PR-B (IA Contract). Subordinate to ADR-RFC-ARCH-001 (placement invariant).
- **Related**: ADR-RFC-ARCH-001 (`.hestai/decisions/rfc-arch/ADR-RFC-ARCH-001-artifact-placement-invariant.md`); `ho-control-room` SKILL §3.LEDGER and §4.LEDGER_TEMPLATE (`.hestai-sys/library/skills/ho-control-room/SKILL.md`); Mac B#1 carry-forward (`.hestai/decisions/handoff/2026-05-16-rfc-40-mac-b1-carry-forward.md`); concrete v1.4 instance at `.hestai-state-1/sessions/control-room-ledger.oct.md`.
- **Authority**: HOLISTIC_ORCHESTRATOR drafting; operator-pre-ratified convergent architecture (debate-hall 2026-05-16). Format decision only; no system-standard amendment requested.
- **Invariants invoked**: PROD::I1 (SESSION_LIFECYCLE_INTEGRITY), PROD::I4 (STRUCTURED_RETURN_SHAPES, applied by analogy to a non-tool artifact).

## 1. Context

Mac B#1's session ledger (`.hestai/state/sessions/control-room-ledger.oct.md`, gitignored under PR-α's `ephemeral_session_state` category) was authored at `VERSION::"1.4"` and carries 19 RDs of multi-agent orchestration provenance, including RD15 / RD17 / RD18 — substance flagged by Mac B#1 as candidates for PR-D's decision-record lane.

The carry-forward records (§B ARTIFACTS AT RISK and §"Operational noise") that raw v1.4 ledger content was deliberately **not** promoted to a committed path by PR-A. Principal Engineer ruling deferred raw-ledger promotion to PR-E ledger schema ADR, on the explicit ground that committing the raw v1.4 ledger before resolving an alleged v1.4-vs-v2.0 schema divergence would embed structural debt.

Inspection of the worktree as of 2026-05-18 finds:

- The `ho-control-room` SKILL (`.hestai-sys/library/skills/ho-control-room/SKILL.md`) §3.LEDGER and §4.LEDGER_TEMPLATE specify a schema substantially congruent with the v1.4 instance: §META + §STRATEGY + §EXECUTION + §RECOVERY with named field lists.
- The concrete v1.4 instance carries additional META fields (`PRIOR_SESSION_ID`, `CONTINUATION_STATE`, `ANCHOR_SESSION_ID`, `PHASE`, `WORKTREE`, `LAST_UPDATED`) and STRATEGY fields (`DISPATCHED_NODES`, `RESOLVED_NODES`) plus EXECUTION field `ANCHOR_TENSIONS_RECORDED` that the SKILL template does not enumerate but does not prohibit.
- **No file in the repository defines a v2.0 schema.** The phrase "v2.0 has been mooted" appears in the operator briefing but no concrete v2.0 candidate was surfaced in this session or located on disk.

In the absence of a concrete v2.0 candidate, the schema "divergence" reduces to a versioning ambiguity: the v1.4 ledger uses MINOR-level versions but no spec writes down what a MINOR or MAJOR bump means; downstream consumers (PR-D once it lands, future workbench Phase 3C observation) cannot programmatically parse without that semantics.

PR-E closes that ambiguity for the L4 ephemeral artifact only. It does **not** elevate the ledger to authoritative (PR-α's category is preserved), it does **not** define decision-record format (PR-D's lane), it does **not** define routing between RFC #38 and RFC #40 (PR-B's lane), and it does **not** edit the SKILL upstream (Vault's lane).

## 2. Decision

### 2.1 Binding schema: v1.4 with reconciled fields

The binding schema for `.hestai/state/sessions/control-room-ledger.oct.md` is **v1.4 as observed in the Mac B#1 instance**, reconciled with the `ho-control-room` SKILL §3.LEDGER + §4.LEDGER_TEMPLATE substance. The reconciled schema is:

#### §META (required)

| Field | Required | Type | Notes |
|---|---|---|---|
| `TYPE` | yes | literal | MUST be `CONTROL_ROOM_LEDGER` |
| `VERSION` | yes | semver-2-segment | `MAJOR.MINOR` string. See §2.2. |
| `SESSION_ID` | yes | UUID string | Identifies the current control-room session |
| `FSM_STATE` | yes | enum | One of `INIT`, `SUSPENDED`, `RESUMED`, `EXHAUSTED`, `FAULT`, `RETIRED`, `DISPATCHED` (the last is observed in the v1.4 instance and is admitted in v1.4 by precedent) |
| `LAST_UPDATED` | yes | ISO-8601 timestamp | Updated on every checkpoint |
| `PRIOR_SESSION_ID` | optional | UUID string | Present when the session resumes from a closed prior session |
| `CONTINUATION_ID` | optional | UUID string | PAL clink continuation handle; present when an ADVISORY session is alive |
| `CONTINUATION_STATE` | optional | string | Human-readable description of continuation state at last checkpoint |
| `ANCHOR_SESSION_ID` | optional | UUID string | When the anchor-ceremony session differs from `SESSION_ID` |
| `PHASE` | optional | string | Project phase identifier (e.g. `B1_FOUNDATION_COMPLETE`) |
| `WORKTREE` | optional | string | Worktree name when authoring from a git worktree |

#### §STRATEGY (required)

| Field | Required | Type | Notes |
|---|---|---|---|
| `ACTIVE_TOPIC` | yes | string | One-line description of the current control-room topic |
| `RATIFIED_DIRECTIVES` | yes | list | Ordered list of `RD<n>::<substance>` items. Mac B#1 demonstrates these are the durable substance candidates for PR-D promotion. |
| `UNRESOLVED_NODES` | yes | list | Open questions / pending decisions |
| `THRESHOLDS` | yes | list | Trigger conditions for state transitions |
| `RESOLVED_NODES` | optional | list | Closed-nodes log; promoted to optional because not every session has closures |
| `DISPATCHED_NODES` | optional | list | In-flight oa-router dispatches; present when execution is parallel |

#### §EXECUTION (required)

| Field | Required | Type | Notes |
|---|---|---|---|
| `DELEGATION_LOG` | yes | list | Append-only log of oa-router and pal_clink dispatches with `agent_id` / `continuation_id` |
| `DEBATE_REFERENCES` | yes | list | May be empty `[]` |
| `ANCHOR_TENSIONS_RECORDED` | optional | list | Records the anchor-ceremony tensions for audit; present when ceremony was performed in-session |

#### §RECOVERY (required)

| Field | Required | Type | Notes |
|---|---|---|---|
| `FAULT_CONTEXT` | yes | string or `None` | Required even when absent; serialised as `None` |
| `LAST_CHECKPOINT` | yes | ISO-8601 timestamp | Last successful ledger write |
| `RESUME_NOTES` | optional | string | Free-form notes to guide session resume |

OCTAVE envelope: file uses the `===CONTROL_ROOM_LEDGER===` opening sentinel and `===END===` closing sentinel as observed in v1.4. Section markers are `§META`, `§1::STRATEGY`, `§2::EXECUTION`, `§3::RECOVERY` (numbering is descriptive, not load-bearing; parsers MUST locate sections by name, not by ordinal).

### 2.2 Version field semantics

The `VERSION` field is a two-segment string `MAJOR.MINOR`:

- **MAJOR bump** — breaking change. Any of: rename of a required field, removal of a required field, change of an existing field's type, change of a section name. Parsers written against `MAJOR=N` MUST refuse to parse `MAJOR=N+1` ledgers.
- **MINOR bump** — additive only. New optional fields, new admissible enum values for `FSM_STATE`, new optional sections. Parsers written against `MAJOR=N.MINOR=K` MUST tolerate ledgers at `MAJOR=N.MINOR>K` by ignoring unknown optional fields.
- No patch-level segment. Patch-level changes do not exist for this artifact; corrections are written into the next MINOR bump.

The current MAJOR for the binding schema is **1**. The current MINOR is **4** (as observed). Future additive extensions land at `1.5`, `1.6`, etc.

A `MAJOR=2` ledger is **not defined by this ADR**. See §2.4.

### 2.3 The mooted v2.0 candidate

No concrete v2.0 schema exists in this repository as of 2026-05-18. The carry-forward (§B) and the PR-E briefing both reference v2.0 as "mooted but not formalised." Accordingly:

- v2.0 is **NOT FORMALISED**. It has no fields, no sections, no migration path defined.
- Until and unless an operator surfaces a concrete v2.0 specification, the binding schema for the L4 ledger is the v1.x line defined in §2.1.
- The label `v2.0 (mooted)` is **SUPERSEDED-BY** v1.4 (this ADR) on grounds of non-formalisation, not on grounds of merit. An operator-surfaced v2.0 spec would supersede v1.x via a new ADR, not by overriding this one.

### 2.4 Migration note (forward-looking)

When a concrete v2.0 spec is surfaced, the migration path is:

1. A new ADR (`ADR-RFC-ARCH-002.1` or successor) ratifies v2.0 with explicit field-by-field breaking-change list.
2. The new ADR marks this ADR's §2.1 schema **SUPERSEDED** with a forward link.
3. Because the ledger is per-session ephemeral (PR-α), there is **no in-place migration of historical ledgers**. Existing v1.x ledgers remain readable by v1.x parsers; v2.x parsers do not have to read v1.x.
4. The session lifecycle tools (`clock_in` / `clock_out`) are not consumers of this artifact and therefore require no migration.

### 2.5 Promotion path (which RD shapes ever flow to `.hestai/decisions/`)

The ledger remains **EPHEMERAL** per PR-α. This ADR governs FORMAT, not authority. Promotion semantics:

- **Default**: no automatic promotion. RD entries in `§STRATEGY.RATIFIED_DIRECTIVES` are session-scoped provenance and disappear with the session.
- **On-demand**: RDs whose substance is durable governance (e.g. Mac B#1's RD15 / RD17 / RD18 per the carry-forward) are surfaced by the operator or the HO and flow into PR-D's decision-record lane as fresh records authored from scratch, citing the originating ledger by `SESSION_ID` and RD number as historical provenance.
- **PR-E does not define decision-record format**. The shape into which an RD promotes is PR-D's concern.
- **No silent promotion**: ledger content MUST NOT be copied verbatim to `.hestai/decisions/` under any path. The pattern is "extract substance, draft a record, cite the ledger as source."

This preserves PR-α's ephemeral category. The ledger is provenance, not authority; the act of promotion is the act of authoring a new committed record.

## 3. Consequences

**Immediate (this ADR):**

- The §2.1 schema is binding for all new control-room sessions in `hestai-context-mcp`. Existing v1.4 ledgers are conformant by construction.
- The `ho-control-room` SKILL §3.LEDGER and §4.LEDGER_TEMPLATE remain the runtime consumer reference; this ADR cites them, does not modify them. Any divergence between the SKILL and this ADR is a Vault-lane issue, not a PR-E issue.
- Mac B#1's claim of v1.4-vs-v2.0 divergence is resolved by recording that v2.0 was never formalised; the substance of "what v2.0 might add" remains an open question for the operator to surface or close.

**Sequenced (NOT in this ADR):**

- **PR-D (RFC #40 AGR)** owns decision-record format. RD15 / RD17 / RD18 from Mac B#1's ledger are candidates listed in the carry-forward and flow into PR-D once it lands.
- **PR-B (IA Contract ADR)** owns query-routing between RFC #38 and RFC #40, and the CI gate spec that enforces PR-α's placement invariant. PR-B may incidentally consume the version semantics defined here.
- **Workbench Phase 3C-β** (B2 gate) may eventually observe session ledgers via `get_context` or a successor read-only tool. The §2.2 version semantics make that observation forward-compatible.

**Out of scope here (do not infer):**

- Authority elevation of the ledger (forbidden by PR-α).
- Decision-record format (PR-D).
- Routing between #38 and #40 (PR-B).
- Edits to `ho-control-room` SKILL upstream (Vault's lane).
- Definition of a v2.0 schema (requires operator surfacing).
- Promotion of any historical v1.4 ledger to a committed path.

## 4. Invariant chain

- **PROD::I1 SESSION_LIFECYCLE_INTEGRITY** — A ledger whose schema is implicit cannot support clean create-and-archive lifecycle when consumed by anyone but its author. Pinning the schema makes lifecycle artifacts mechanically parseable and the version field makes parser compatibility decidable. The artifact remains ephemeral, so PR-α's category is unviolated; archival of *promotable substance* happens via PR-D.
- **PROD::I4 STRUCTURED_RETURN_SHAPES** — Although the immutable's literal scope is MCP tool returns, the same discipline (named fields, defined types, programmatic extraction over blobs) is the right design for any structured artifact a programmatic consumer reads. PR-E applies that discipline to the ledger by analogy.

## 5. Verification

TIER_3, facets [GOVERNANCE]. CIV + SR review per `/review` skill. No code is added by this ADR. No CI gate is required at PR-E (PR-G owns CI gate work). Verification of this ADR is review-only.

A parser-conformance test is NOT required by this ADR but is welcomed as future work if a programmatic consumer of the ledger materialises. The version semantics in §2.2 are deliberately designed to be testable.

## 6. Open questions to operator

1. Is the carry-forward's reference to "v2.0 mooted" intended to surface a concrete v2.0 spec in this PR, or to acknowledge that no such spec exists and v1.4 is the binding line by default? This ADR assumes the latter. Operator may amend.
2. Should the `FSM_STATE` value `DISPATCHED` (observed in the v1.4 instance, not in the SKILL §2 LIFECYCLE_FSM enum) be canonised as a v1.4 enum value or retired as a one-off? This ADR canonises it on the principle of preserving observed behaviour; operator may retire.
3. Mac B#1's `ANCHOR_TENSIONS_RECORDED` field has no precedent in the SKILL template. This ADR admits it as optional; operator may promote to required or strike.

These questions do not block PR-E ratification — they are bookkeeping. Operator answers may land as MINOR bumps to the binding schema (1.5 / 1.6 / …).

## 7. Supersession

This ADR is **subordinate to** ADR-RFC-ARCH-001 (placement invariant). PR-α defines that the ledger lives at an ephemeral path; PR-E defines what fields the ledger contains at that path. If PR-α is later widened or refined by PR-B's IA Contract ADR, PR-E's §2 schema travels with the ledger to whatever ephemeral location PR-B re-confirms; supersession of PR-α does not automatically supersede PR-E.

A future v2.x ledger ADR supersedes PR-E's §2.1 schema by explicit field-by-field breaking-change list per §2.4.
