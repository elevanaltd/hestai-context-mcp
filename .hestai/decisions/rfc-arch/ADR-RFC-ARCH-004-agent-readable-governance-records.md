# ADR-RFC-ARCH-004 — Agent-Readable Governance Records (AGR) — Format, Lifecycle, Tool Contracts

- **Status**: RATIFIED — 2026-06-11 (SR + CIV stamped close-out; see §13). **Schema v1.1** — MINOR-additive amendment transcribing HO-AGR-BYTECODE-FORMAT-TWO-BIRDS-20260620 (#101, RATIFIED): §1.2 `DECISION`/`BECAUSE` bytecode density (≤40 words, no newline), §1.5 v1.1 semantics, §4.1 #13 value-level guard, `HUMAN_ADR_REF` greppable-TOKEN form. No structural parser change; v1.0 records remain valid.
- **Ratified-by**: standards-reviewer + critical-implementation-validator (stamped close-out 2026-06-11), HO-orchestrated, operator-authorised
- **Date**: 2026-05-19
- **Scope**: `hestai-context-mcp` repository. Specifies the L1 AGR record format and consumer-side MCP tool contracts. Specification only; code implementation is deferred to a successor PR (PR-D′ / PR-H) routed via oa-router to implementation-lead.
- **Sequence**: PR-D in the RFC-arch series. Subordinate to ADR-RFC-ARCH-002 (PR-B IA Contract §1.5 routing rules, §3 governance-class TYPE registry) and ADR-RFC-ARCH-001 (PR-α placement invariant). Adjacent to ADR-RFC-ARCH-003 (PR-E ledger schema, ephemerality preserved).
- **Related**: RFC #40 (Agent-Readable Governance Records — operator-ratified direction, 2026-05-13); RFC #38 (Facet ABI, peer projection layer); ADR-0013 (PSS substrate ruling); Mac B#1 carry-forward `.hestai/decisions/handoff/2026-05-16-rfc-40-mac-b1-carry-forward.md` (RD15 / RD17 / RD18 promotion candidates).
- **Reconciles**: Issue #25 (Decision Journal Light — SUPERSEDED-BY this ADR on direction; see §7).
- **Authority**: HOLISTIC_ORCHESTRATOR drafting; RFC #40 operator-ratification 2026-05-13; convergent L0–L5 architecture (debate-hall 2026-05-16, carried forward via PR-B).
- **Invariants invoked**: PROD::I1 (SESSION_LIFECYCLE_INTEGRITY), PROD::I3 (PROVIDER_AGNOSTIC_CONTEXT), PROD::I4 (STRUCTURED_RETURN_SHAPES), PROD::I5 (READ_ONLY_CONTEXT_QUERY), PROD::I6 (LEGACY_INDEPENDENCE applied as opt-in adoption discipline), SYS::I1 (CONTEXT_INTEGRITY), SYS::I6 (scope boundary discipline).
- **Implementation owners (deferred)**: PR-D′ / PR-H — implementation-lead via oa-router. D1–D6 preflight gates (§9) are binding preconditions for code authorisation.

## 0. Reading guide

This ADR contains four governance artefacts in one document:

- **§1 — Schema v1** defines the OCTAVE record format (fields, types, lifecycle, supersession DAG semantics).
- **§2 — Placement, layer mapping, and projection rules** locate AGRs in the L0–L5 topology and rule on derived projections.
- **§3 — MCP tool contracts** specify three read tools and one optional write broker, all PROD::I4-conformant and PROD::I5-conformant where applicable.
- **§4 — Validator CLI** specifies the invariants the validator enforces.

§§5–10 close the invariant chain, verify the ADR itself, reconcile issue #25, name out-of-scope items, list preflight gates, and enumerate operator-direction open questions.

### 0.1 Defense-in-depth note

The AGR layer composes with PR-B's defenses: AGR files inherit governance-class TYPE registration (PR-B §3.2.2) via `META.TYPE::DECISION_RECORD`, so any future fail-fast tool (PR-F) automatically rejects governance-class writes to non-authoritative paths. The CI gate (PR-G) treats `.hestai/decisions/**` as the only authoritative AGR root.

### 0.2 Immutable operator-ratified inputs

The following are immutable in PR-D scope and not re-debated:

1. **RFC #40's three-layer model**: L0 human ADRs (unchanged), L1 AGRs (this ADR), L1S Facet ABI (RFC #38 / PR-B). Operator-ratified 2026-05-13.
2. **Substrate-not-registry binding** (ADR-0013): the AGR canonical store is plain committed files at `.hestai/decisions/`; PSS is substrate, never the registry. Any write tool is a broker that creates a PR; no tool mutates the canonical store directly.
3. **Schema-superset commitment** (RFC #40): the v1 schema MUST be a syntactic superset of elevana-studio's existing HO-token convention so legacy records validate verbatim.
4. **Opt-in adoption**: consumer repos adopt voluntarily; non-adopters remain fully supported indefinitely.

## 1. Schema v1

### 1.1 File layout

An AGR record is a single OCTAVE document committed at:

```
.hestai/decisions/<token>.oct.md
```

where `<token>` is the record's `TOKEN` value (see §1.2). Sub-grouping under `.hestai/decisions/<group>/<token>.oct.md` is admissible when a coherent group exists (e.g. `.hestai/decisions/rfc-arch/HO-ARCH-…`); the validator MUST treat both layouts as equivalent and resolve `<token>` to whichever path holds it.

OCTAVE envelope (canonical form is **bare** `TOKEN`):

```
===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.0"
  TOKEN::<TOKEN>
  AUTHORED_AT::"<ISO-8601-UTC>"
…
===END===
```

The opening sentinel `===DECISION_RECORD===` and closing `===END===` are required; they signal governance-class to PR-B §3.2.2.

**Canonical TOKEN form (AGR canonical-form convergence)**: `TOKEN` is written **bare** — `TOKEN::<TOKEN>`, not `TOKEN::"<TOKEN>"`. This reconciles §1.1 with §1.6, where the `AMENDS` / `EXTENDS` (and `SUPERSEDED_BY`) edge references are bare TOKENs; a record's own `TOKEN` declaration and the TOKENs it cites in its lineage edges therefore share one canonical form. Gate A readers are **quote-optional**: the legacy quoted form `TOKEN::"<TOKEN>"` continues to validate verbatim (preserving the §0.2 schema-superset commitment over elevana-studio's existing HO-token convention), but bare is canonical for new records. The §1.3 TOKEN-format regex constrains the value identically in either form — quote-optionality does not relax §1.3.

### 1.2 Fields

#### Required (every record, every lifecycle state)

| Field | Type | Notes |
|---|---|---|
| `TYPE` | literal | MUST be `DECISION_RECORD` |
| `VERSION` | semver-2-segment | `MAJOR.MINOR` per §1.5. Current: `1.1` (records authored before the v1.1 amendment remain valid at `1.0`; v1.1 is MINOR-additive — see §1.5). |
| `TOKEN` | string | Globally unique identifier within the repository (see §1.3) |
| `STATUS` | enum | One of `PROPOSED`, `RATIFIED`, `SUPERSEDED`, `VOID` (see §1.4) |
| `TIER` | enum | One of `STRATEGIC`, `TACTICAL`, `OPERATIONAL`. Semantic gravity per the cited research brief. |
| `DECISION` | string | One-sentence statement of what is binding. Mandatory even on `PROPOSED`. **v1.1 bytecode form**: a single double-quoted flat line. §4.1 #13 **machine-enforces** AT MOST 40 words and NO embedded newline (per HO-AGR-BYTECODE-FORMAT-TWO-BIRDS-20260620). Compressed-OCTAVE operators (`→ ⇌ ∴ ⊕`) are the **recommended style** for fitting connectives within budget — not machine-checked. Nested custom keys are excluded by the flat-string grammar (the structural parse), not by #13. |
| `BECAUSE` | string | One-sentence rationale. Mandatory even on `PROPOSED`. **v1.1 bytecode form**: same as `DECISION` — §4.1 #13 machine-enforces ≤40 words + no-newline; compressed-OCTAVE operators are the recommended (not enforced) style. |
| `AUTHORED_AT` | ISO-8601 timestamp | UTC. Set once at record creation; never edited. |

#### Optional (any record, any lifecycle state)

| Field | Type | Notes |
|---|---|---|
| `ISSUE_REF` | string | GitHub issue URL or `repo:<repo-id>#<n>` shorthand. Optional on `PROPOSED`/`RATIFIED`; recommended on `SUPERSEDED`/`VOID` if origin is on issue tracker. |
| `HUMAN_ADR_REF` | string | Reference to a human ADR. Optional; records without a human ADR are first-class. **v1.0**: a repository-relative path (resolved by §4.1 #11). **v1.1**: a greppable cross-repo-survivable TOKEN is the canonical form (per HO-AGR-BYTECODE-FORMAT-TWO-BIRDS-20260620 `ADR_REF_FORM::greppable_TOKEN`); a path remains accepted for back-compat and is path-resolved under §4.1 #11 only when it is path-shaped. |
| `SUPERSEDED_BY` | string | TOKEN of the superseding record. Required iff `STATUS == SUPERSEDED`. |
| `EXTENDS` | list of TOKENs | Records this record extends (additive, not replacing). May be empty. |
| `AMENDS` | list of TOKENs | Records this record amends (partial replacement). May be empty. |
| `SCOPE` | string or list | Free-form scope qualifier (e.g. `"hestai-context-mcp"`, `["L1", "AGR"]`). Optional. |
| `EFFECTIVE_FROM` | ISO-8601 timestamp | When the decision takes effect; defaults to `AUTHORED_AT` if absent. |
| `EFFECTIVE_UNTIL` | ISO-8601 timestamp | When the decision lapses (independent of supersession). Optional. |
| `ORIGIN_SESSION` | string | UUID of the session in which the decision was ratified, when known. Citations to control-room ledger SESSION_IDs land here. |
| `ORIGIN_LEDGER_RD` | string | `RD<n>` identifier from the originating ledger, when known. Used by PR-E §2.5 promotion-by-citation pattern. |
| `RATIFIED_BY` | string | Identity of the human or agent that ratified the record (e.g. `human:shaun.buswell@elevana.com`, `agent:HOLISTIC_ORCHESTRATOR`). Optional on `PROPOSED`. The validator (§4.1) emits a **warning** when `STATUS != PROPOSED` and `RATIFIED_BY` is absent. Recommended but not required for non-`PROPOSED` records (operator may close the loophole in a MINOR bump if TOKEN-squatting becomes a real problem; see §11 Q5). |
| `RATIFIED_AT` | ISO-8601 timestamp | When the record entered its current non-`PROPOSED` STATUS. Optional. Independent of `AUTHORED_AT` (records may be authored as `PROPOSED` and ratified later). |

#### Reserved (not yet defined; MUST NOT appear in v1.x records)

`DEPENDS_ON`, `CONFLICTS_WITH`, `ARCHIVED_AT`. These names are reserved against future MINOR additions; v1.x validators MUST reject records carrying them.

### 1.3 TOKEN format

`TOKEN` MUST match the regular expression:

```
^[A-Z][A-Z0-9_-]{1,126}[A-Z0-9_]-[0-9]{8}$
```

Three semantic parts, joined by `-`:

1. Prefix: uppercase letters, digits, underscores, and internal hyphens (hyphens are admissible as word-separators, e.g. `HO-DECISION-GOVERNANCE`); 3–128 chars total before the trailing date separator; MUST start with an uppercase letter and MUST NOT end with a hyphen (so the trailing `-` before the date is unambiguous). Examples: `HO-CONTEXT-MCP-OWNS-AGR-STANDARD`, `HO-OCTAVE-WRITE-MULTI-ENVELOPE-WORKAROUND`.
2. Hyphen separator.
3. Date suffix: `YYYYMMDD` (UTC). MUST equal the UTC date portion of `AUTHORED_AT` — the validator (§4.1) enforces this consistency.

This regex is a syntactic superset of elevana-studio's existing HO-token convention (e.g. `HO-DECISION-GOVERNANCE-GRAVITY-TIERED-20260428`); legacy tokens validate verbatim, including those whose prefix contains multiple hyphens.

Uniqueness is enforced repo-wide by the validator (§4). A token collision is a hard error.

### 1.4 Lifecycle states and transitions

The `STATUS` enum and its admissible transitions:

```
            ┌──── VOID  (terminal; never returns)
            │
PROPOSED ───┼──── RATIFIED ───┬──── SUPERSEDED  (terminal for this token; chain continues via SUPERSEDED_BY)
            │                 │
            └──── VOID        └──── VOID
```

Rules:

1. A new record starts in `PROPOSED` or `RATIFIED`. Authoring straight to `RATIFIED` is permitted when the operator/HO ratifies in the authoring session.
2. `PROPOSED → RATIFIED` is the standard adoption transition.
3. `RATIFIED → SUPERSEDED` is the standard evolution transition; `SUPERSEDED_BY` MUST point to a record that is itself `PROPOSED` or `RATIFIED` (not `SUPERSEDED` or `VOID`) at the moment of transition. The validator does not re-check this on every read; it checks on write.
4. `PROPOSED → VOID` / `RATIFIED → VOID` / `SUPERSEDED → VOID` are all admissible (e.g. when a decision is retracted entirely). `VOID` records remain on disk for provenance.
5. No transition out of `VOID`. A `VOID` record is dead.
6. The `STATUS` field is mutable in-place per SYS §1 LAW SOURCE_FIDELITY (no versioned copies). Mutation is a normal git commit; history lives in git, not in the record.

### 1.5 Version semantics

`VERSION` is `MAJOR.MINOR`:

- **MAJOR bump** — breaking. Any of: required-field rename, required-field removal, type change, enum value removal, tightening of an existing field's regex. Parsers written against `MAJOR=N` MUST refuse to parse `MAJOR=N+1` records.
- **MINOR bump** — additive. New optional fields, new admissible enum values for non-required fields, new reserved names. Parsers written against `MAJOR=N.MINOR=K` MUST tolerate `MAJOR=N.MINOR>K` by ignoring unknown optional fields.
- No patch level. Spec corrections land at the next MINOR.

Current schema is `1.1`. Future additive extensions become `1.2`, `1.3`, etc.

**v1.1 (MINOR-additive, per HO-AGR-BYTECODE-FORMAT-TWO-BIRDS-20260620 / #101)**: AGRs are treated as LLM "bytecode". The reasoning-bearing fields `DECISION` and `BECAUSE` are constrained to a single flat line of ≤40 words with no embedded newline, using compressed-OCTAVE operators for connectives (new value-level invariant §4.1 #13; no structural parser change). `HUMAN_ADR_REF` gains a greppable-TOKEN canonical form alongside the legacy path form. Both are MINOR-additive: a `1.0` record that already satisfies the ≤40-word/no-newline density (as every conforming one-sentence `DECISION`/`BECAUSE` does) remains valid, and v1.1 introduces no new required field. Parsers written against `1.0` continue to parse `1.1` records (the structural grammar is unchanged).

**Spec-only period (CLOSED)**: Between this ADR's merge and the code landing, AGR records were authored by hand and conformed to §1.1–§1.6 as if the validator (§4) were running. The validator has now landed: Gate A (`type_checker.validate_octave_content`) enforces the §4.1 invariants against every record under `.hestai/decisions/**/*.oct.md`, regardless of authoring date — the **v1.0 envelope PLUS the v1.1 additive §4.1 #13 density invariant** (≤40 words, no embedded newline on `DECISION`/`BECAUSE`). There is no grandfather clause: every record, old or new, MUST satisfy the currently-enforced invariant set (the three pre-existing verbose records were migrated to compliant bytecode when #13 landed).

### 1.6 Supersession DAG semantics

`SUPERSEDED_BY`, `EXTENDS`, and `AMENDS` together form three **edge-typed** directed graphs over TOKENs. Acyclicity is enforced **per edge-type**, not globally — the three edge classes have distinct semantics and a record may legitimately appear in cycles when only the union graph is considered.

- The validator (§4) MUST detect cycles **within each edge-type independently** and reject the offending write:
  - `SUPERSEDED_BY` subgraph MUST be acyclic and MUST form a chain (every `SUPERSEDED` record points at exactly one successor); the chain MUST terminate at a `PROPOSED`, `RATIFIED`, or `VOID` record.
  - `EXTENDS` subgraph MUST be acyclic. Arbitrary DAG shapes within `EXTENDS` are admissible.
  - `AMENDS` subgraph MUST be acyclic. Arbitrary DAG shapes within `AMENDS` are admissible.
- **Cross-edge interactions are NOT treated as cycles.** Specifically: an old record carrying `SUPERSEDED_BY=NEW` combined with the new record carrying `AMENDS=OLD` is **admissible** and is the canonical pattern for "this new record supersedes the old one and explicitly amends what it changed." The validator MUST NOT flag this as a cycle.
- `EXTENDS` does not imply `SUPERSEDED_BY`; an extension is additive — both records remain live (`RATIFIED`).
- `AMENDS` does not by itself supersede; an amendment refines the cited record without retiring it. Combined `AMENDS` + `SUPERSEDED_BY` (as above) is admissible.
- Edges MUST reference TOKENs that exist in the same repository (cross-repo edges are out of scope for §1.6 enforcement; see §4.1 invariant #8 scoping note).

## 2. Placement, layer mapping, and projection rules

### 2.1 Placement

AGR records live in the `committed_governance` category (PR-α §2 / PR-B §1.2):

```
committed_governance::.hestai/decisions/**/*.{md,oct.md}
```

Specifically, AGRs land at `.hestai/decisions/<token>.oct.md` or `.hestai/decisions/<group>/<token>.oct.md` per §1.1. They are L1 (Phase governance) in the convergent L0–L5 topology per PR-B §1.1.

AGRs MUST NOT live in `.hestai/state/sessions/` (L4 ephemeral per PR-α / PR-E), `.hestai/state/cache/` (L2 cache per PR-α), or anywhere outside `.hestai/decisions/`. This invariant is enforced by PR-B §3.3 (tool-boundary fail-fast on the `DECISION_RECORD` TYPE) and PR-B §2 (CI gate).

### 2.2 ADR-0013 substrate ruling

AGRs are not stored in PSS. PSS is substrate (per ADR-0013); AGRs are content. The AGR canonical store is plain committed files; any retrieval acceleration over AGRs lives at L2 (optional cache) and is non-authoritative.

### 2.3 Derived projections

A consumer repo MAY generate a monolithic projection (e.g. `DECISIONS.oct.md` or `decisions.index.json`) from the atomic AGR files. Projections are `DERIVED_PROJECTION` per ADR-0013's vocabulary; they are:

1. Non-authoritative. Reads MUST resolve canonically against atomic AGR files. The projection is a convenience, not the truth.
2. Rebuildable. The projection MUST be reproducible from the atomic files plus the schema; no information is lost on deletion.
3. Out of scope for fail-fast. PR-B §3 does not apply to derived projections at non-governance paths (e.g. `.hestai/state/cache/decisions.index.json`).

Generation of projections is OPTIONAL and may be performed by the validator CLI (§4.4) or by a separate tool. The choice is implementation-lane; this ADR does not legislate.

### 2.4 Cross-repo AGR references

A cross-repo AGR reference resolves per PR-B §1.4.1: `repo:<repo-id>:<repo-relative-path>@<rev>` or `pin:<url>@<rev>`. Bare URLs are not authoritative references. Cross-repo reciprocity is advisory per PR-B §1.4.3 — this ADR does not impose AGR obligations on other repositories.

## 3. MCP tool contracts

### 3.1 Tools introduced

PR-D names four MCP tools:

| Tool | Kind | I5? | I4? |
|---|---|---|---|
| `lookup_decision` | read | yes (pure read) | yes (structured return) |
| `list_decisions` | read | yes (pure read) | yes (structured return) |
| `trace_supersedure` | read | yes (pure read) | yes (structured return) |
| `propose_decision_amendment` | write **broker** (creates a PR; never mutates canonical store) | n/a (the broker is not a read tool; the canonical store remains read-only at the tool boundary) | yes (structured return) |

`get_context` is **not** modified by PR-D. PROD::I5 on `get_context` is preserved unconditionally.

#### 3.1.1 Common error envelope (PROD::I4)

Every tool in §3 — read or broker — MUST return errors in this envelope. The envelope is mandatory; opaque-blob errors are forbidden.

```
{
  "ok": false,
  "error": {
    "code": "<error-code-from-tool-specific-list>",
    "category": "input_validation" | "schema_violation" | "io_failure" | "concurrency" | "broker_failure",
    "message": "<one-line human-readable explanation>",
    "tool": "lookup_decision" | "list_decisions" | "trace_supersedure" | "propose_decision_amendment",
    "context": { /* tool-specific structured payload — e.g. token, path, current_hash, broken_chain */ },
    "contract_ref": "ADR-RFC-ARCH-004 §3.<n>"
  }
}
```

Implementations MAY add fields to `error` (e.g. timing, tool_version) but MUST NOT remove or rename the required keys. The same envelope shape applies to per-tool error lists below.

### 3.2 `lookup_decision(working_dir, token, audience?)`

Resolves a single AGR by `TOKEN`. Pure read.

**Input** (PROD::I4-conformant):

```
{
  "working_dir": "<absolute or repo-rooted path>",
  "token": "<TOKEN string>",
  "audience": "agent" | "human"  // optional; default "agent"
}
```

`audience` controls return verbosity. `"agent"` returns the structured record verbatim. `"human"` MAY additionally include rendered prose where the spec is unambiguous (e.g. resolved supersession chain summarised in English). Implementations MAY ignore `audience` and always return `"agent"` shape; consumers MUST tolerate this.

**Return shape** (PROD::I4-conformant):

```
{
  "ok": true,
  "record": {
    "token": "<TOKEN>",
    "type": "DECISION_RECORD",
    "version": "1.0",
    "status": "PROPOSED" | "RATIFIED" | "SUPERSEDED" | "VOID",
    "tier": "STRATEGIC" | "TACTICAL" | "OPERATIONAL",
    "decision": "<DECISION string>",
    "because": "<BECAUSE string>",
    "authored_at": "<ISO-8601>",
    "path": "<repo-relative path to the .oct.md file>",
    "fields": { /* all other present fields, key→value */ }
  },
  "resolution_chain": [ /* see trace_supersedure shape; populated when STATUS == SUPERSEDED */ ],
  "resolution_chain_status": "complete" | "broken" | "cyclic"  // additive (issue #87); see note below
}
```

The `resolution_chain_status` field (additive per §3.1.1; issue #87) is a completeness signal so a caller can distinguish a `resolution_chain` that reached its terminal from one truncated by a broken link or a cycle. It is derived from the same `walk_supersession_chain` outcome that produces `resolution_chain`, with **no** extra read:

- `"complete"` — the walk reached a terminal record (walk outcome `ok`). This is also the value for a non-`SUPERSEDED` record, whose `resolution_chain` is empty and therefore not truncated.
- `"broken"` — a successor `TOKEN` referenced by `SUPERSEDED_BY` does not exist on disk (walk outcome `broken`, the same condition `trace_supersedure` reports as `CHAIN_BROKEN`). The partial chain gathered so far is still returned.
- `"cyclic"` — a `SUPERSEDED_BY` cycle was detected by fail-closed cycle detection (walk outcome `cycle`, the same condition `trace_supersedure` reports as `CHAIN_CYCLE_DETECTED`). The partial chain is still returned; the walk never runs unbounded.

The field is **always present** (a defined PROD::I4 key) and never removes or renames an existing key; a consumer that ignores it is unaffected. `trace_supersedure` remains the authoritative source for the broken/cyclic *error*; `resolution_chain_status` is an in-band observability signal on `lookup_decision` that agrees with it.

**Error cases** (per §3.1.1 envelope):

- `TOKEN_NOT_FOUND` (category: `input_validation`) — no record at the requested TOKEN; `context.token` echoed.
- `TOKEN_MALFORMED` (`input_validation`) — TOKEN does not match §1.3 regex.
- `RECORD_PARSE_FAILED` (`schema_violation`) — file found but OCTAVE envelope or required fields fail to parse; `context.path` and `context.parse_error` populated. Implementation choice: treat as fatal for the read, do NOT silently skip.
- `WORKING_DIR_INVALID` (`io_failure`) — path does not exist or is not a directory.

### 3.3 `list_decisions(working_dir, scope?, status?, tier?)`

Lists AGRs with optional filtering. Pure read.

**Input**:

```
{
  "working_dir": "<path>",
  "scope": "<string or null>",     // matches SCOPE field exactly when provided; null = no filter
  "status": "PROPOSED" | "RATIFIED" | "SUPERSEDED" | "VOID" | null,
  "tier": "STRATEGIC" | "TACTICAL" | "OPERATIONAL" | null
}
```

**Return shape**:

```
{
  "ok": true,
  "records": [
    {
      "token": "<TOKEN>",
      "status": "<status>",
      "tier": "<tier>",
      "decision": "<short>",
      "authored_at": "<ISO-8601>",
      "path": "<repo-relative path>"
    },
    …
  ],
  "total": <integer>,
  "skipped": [
    {
      "path": "<repo-relative path>",
      "parse_error": "<reason the record could not be parsed>"
    },
    …
  ]
}
```

The list is sorted by `authored_at` descending. No paging in v1; implementations MUST handle the full set in a single response. If repository scale requires paging, that is a MINOR schema addition for v1.1.

`skipped` (additive per §3.1.1) is ALWAYS present — an empty array when every in-scope record parsed. It names every file that IS a `DECISION_RECORD` but failed to parse its required §1.2 fields, so a consumer can detect that the listing is incomplete and exactly which records are missing. Entries are sorted by `path` for deterministic output.

**Error cases** (per §3.1.1 envelope):

- `FILTER_INVALID` (`input_validation`) — `status` or `tier` is non-null and not a member of the admissible enum; `context.field` and `context.value` populated.
- `WORKING_DIR_INVALID` (`io_failure`) — as in §3.2.

**Incompleteness handling**: a record under `.hestai/decisions/**` that IS a `DECISION_RECORD` but fails to parse does NOT fail the whole call. It is reported in the `skipped` array (above) — never silently dropped, and never blinding the rest of the index. This satisfies the hard requirement (consumers MUST be able to detect that the list is incomplete) while a single legacy or non-conforming record no longer makes the tool appear dead. (An earlier revision named whole-call `RECORD_PARSE_FAILED` as the recommended choice; the `skipped`-array form is the chosen implementation — detectability is preserved, resilience is improved. `lookup_decision` §3.2 still returns `RECORD_PARSE_FAILED` because a by-TOKEN read targets exactly one record.)

### 3.4 `trace_supersedure(working_dir, token)`

Returns the supersession chain for a token. Pure read.

**Input**:

```
{ "working_dir": "<path>", "token": "<TOKEN>" }
```

**Return shape**:

```
{
  "ok": true,
  "chain": [
    {
      "token": "<TOKEN>",
      "status": "<status>",
      "authored_at": "<ISO-8601>",
      "superseded_by": "<TOKEN or null>",
      "path": "<repo-relative path>"
    },
    …
  ],
  "terminal_token": "<TOKEN of the chain end>",
  "terminal_status": "PROPOSED" | "RATIFIED" | "VOID"
}
```

The chain starts at the requested token and follows `SUPERSEDED_BY` pointers to a record whose `SUPERSEDED_BY` is null. `terminal_status` is never `SUPERSEDED` (chain follows further) and is `VOID` only if the chain ends in retraction.

**Error cases** (per §3.1.1 envelope):

- `TOKEN_NOT_FOUND` (`input_validation`) — starting TOKEN does not exist.
- `CHAIN_BROKEN` (`schema_violation`) — a record in the chain points `SUPERSEDED_BY` at a TOKEN that does not exist; `context.broken_at_token` and `context.missing_successor_token` populated. Distinct from `TOKEN_NOT_FOUND` so consumers can distinguish missing-start from missing-middle.
- `CHAIN_CYCLE_DETECTED` (`schema_violation`) — `SUPERSEDED_BY` traversal revisited a TOKEN already in the chain; `context.cycle_at_token` populated. This SHOULD be unreachable if the validator (§4.1 #8) has been run, but the tool MUST fail closed rather than infinite-loop.
- `WORKING_DIR_INVALID` (`io_failure`) — as in §3.2.

When the requested token is found but has no `SUPERSEDED_BY` (it is itself terminal), the chain contains exactly one entry and `terminal_token == token`.

### 3.5 `propose_decision_amendment(working_dir, token, patch, expected_record_hash)` — OPTIONAL broker

Creates a pull request proposing an amendment to an AGR. **Does not mutate the canonical store.** Per ADR-0013 substrate ruling; cited in §0.2.

**Input**:

```
{
  "working_dir": "<path>",
  "token": "<TOKEN of the record to amend>",
  "patch": { "field": "value", … },                       // partial field updates
  "expected_record_hash": "sha256:<64-hex-digits>"        // optimistic concurrency — per-record content hash
}
```

`expected_record_hash` is a SHA-256 over the canonical UTF-8 bytes of the AGR file as the proposer last read it (the full `.oct.md` file content, byte-for-byte, including OCTAVE envelope). The broker recomputes the hash from current on-disk content **on the default/protected branch HEAD** (NOT from an arbitrary worktree state) and rejects on mismatch (concurrent edit detected — proposer must re-read and recompute). Schema `VERSION` is **not** suitable here — it tracks schema-level breaking changes, not per-record edits, so two simultaneous amendments under the same `VERSION` (e.g. both `1.0`) would not be detected by a version-equality check. The content hash is the per-record CAS primitive.

**Behaviour (proposal-time)**: the broker:

1. Fetches the repository's default/protected branch HEAD (configured at broker init; typically `main`).
2. Reads the AGR file at that HEAD and computes its content hash; rejects with `EXPECTED_HASH_MISMATCH` if it differs from `expected_record_hash` (proposer is stale).
3. Creates a git branch **from default-branch HEAD** (never from an arbitrary local state).
4. Applies the patch, commits with a conventional-commits message.
5. Opens a pull request via the `gh` CLI (or equivalent) **against the default/protected branch** (PR target is not caller-controlled — the broker pins it).
6. Returns the PR URL plus the `from_record_hash` / `to_record_hash` pair.

The broker MUST NOT write to the canonical store path on the base branch directly. The broker MUST NOT accept a caller-supplied PR target (no `branch_target` parameter); this prevents bypass via PR against a long-lived feature branch.

**Behaviour (merge-time staleness)**: the proposal-time hash check is necessary but not sufficient — between PR open and merge, another PR could land that changes the same AGR file. PR-D′ / PR-H MUST land one of these two merge-time defenses:

- **(a) Required merge-time recheck** — a GitHub Action triggered on `pull_request` events for paths under `.hestai/decisions/**/*.oct.md` that re-reads the touched AGRs at PR HEAD and at base branch HEAD, recomputes content hashes, and fails the PR check if the PR's claimed `from_record_hash` no longer equals the base-branch hash. This forces rebase-and-retest. **Recommended.**
- **(b) Branch protection requiring up-to-date base** — GitHub branch protection setting "require branches to be up to date before merging" applied to the default branch. Coarser-grained than (a) (rebases on any change, not just AGR conflicts) but simpler.

PR-D′ / PR-H MUST implement (a) OR document operator selection of (b). The choice is implementation-lane, but one of the two MUST be in force; without it the broker CAS protects only against simultaneous proposals, not against sequential stale merges.

**Return shape**:

```
{
  "ok": true,
  "pr_url": "<URL>",
  "branch": "<branch name>",
  "head_sha": "<git commit sha of the proposal branch HEAD>",
  "token": "<TOKEN>",
  "from_record_hash": "sha256:<64-hex>",                  // hash that matched expected_record_hash
  "to_record_hash":   "sha256:<64-hex>"                   // hash of the file after the patch was applied
}
```

Error cases (PROD::I4-conformant):

- `EXPECTED_HASH_MISMATCH` — concurrent edit detected; returned with the current on-disk hash so the proposer can re-read.
- `TOKEN_NOT_FOUND`.
- `PATCH_REJECTED` — patch violates schema (e.g. would create cycle in supersession DAG, would introduce reserved field name, would change immutable fields such as `TOKEN` or `AUTHORED_AT`).
- `GH_BROKER_FAILED` — wrapper for any `gh` CLI failure; includes upstream error message.

This tool is OPTIONAL in PR-D′ / PR-H. Adopters MAY ship read tools only. The optionality is intentional — the broker is sugar over `gh pr create`; a workflow that pushes directly via standard git tooling remains supported.

### 3.6 Provider agnosticism (PROD::I3)

All four tool contracts MUST yield identical results across providers (Claude / Codex / Gemini / Goose / others). OCTAVE's deterministic parsing is the operational basis. Provider-specific behaviour at any of these tools is a PROD::I3 violation.

## 4. Validator CLI

The validator is a CLI tool (name suggestion: `validate_agent_readable_governance_records` — abbreviated `validate_agr`) that enforces the schema invariants. It is run pre-commit, in CI, and on demand.

### 4.1 Invariants checked

1. **OCTAVE envelope** — `===DECISION_RECORD===` / `===END===` present, `META.TYPE::DECISION_RECORD`, `META.VERSION` is a parseable `MAJOR.MINOR` string.
2. **Required fields present** — TYPE, VERSION, TOKEN, STATUS, TIER, DECISION, BECAUSE, AUTHORED_AT.
3. **TOKEN format and date consistency** — matches §1.3 regex AND the `YYYYMMDD` suffix equals the UTC date portion of `AUTHORED_AT` (per the §1.3 MUST). Mismatch is a hard error.
4. **TOKEN uniqueness** — every TOKEN appears exactly once across `.hestai/decisions/**/*.oct.md`.
5. **STATUS enum** — one of the four admissible values.
6. **TIER enum** — one of the three admissible values.
7. **Reserved names** — `DEPENDS_ON`, `CONFLICTS_WITH`, `ARCHIVED_AT` MUST NOT appear in v1.x records.
8. **Supersession DAG (same-repo only)** — `SUPERSEDED_BY`, `EXTENDS`, `AMENDS` references resolve to TOKENs that exist **in the same repository**; per §1.6 each edge-type subgraph is acyclic independently (cross-edge interactions per §1.6 are admissible and NOT cycles); `SUPERSEDED_BY` chain is a chain not a tree. Cross-repo edges (per §2.4) are **out of scope** for automated validation — the validator does not fetch remote repositories. This is consistent with ADR-RFC-ARCH-002 PE amendment 1 (CI gate scoped to LOCAL repo-relative paths only) and §2.4's "cross-repo reciprocity is advisory" stance. Cross-repo edge correctness is enforced by editorial review.
9. **`SUPERSEDED_BY` invariant** — present iff `STATUS == SUPERSEDED`.
10. **`ISSUE_REF` shape** — when present, parses as a GitHub URL or `repo:<repo-id>#<n>`.
11. **`HUMAN_ADR_REF` form (v1.1)** — when present, the ref is EITHER a well-formed greppable TOKEN (matches the §1.3 TOKEN regex; the v1.1 canonical cross-repo-survivable form per HO-AGR-BYTECODE-FORMAT-TWO-BIRDS-20260620 — validated as a token, NOT path-resolved) OR a v1.0 path that resolves to a file under the repository. The §1.3 TOKEN pattern admits no path separator and no `.`, so the two forms are mutually exclusive: token-form is matched first; anything else is treated as a path and must resolve under the repo. A ref that is neither is a hard error.
12. **Ratification provenance (warning)** — when `STATUS != PROPOSED` and `RATIFIED_BY` is absent, the validator emits a **warning** (not error) per §4.2. Closes a portion of the TOKEN-squatting / lookalike-record gap without forcing legacy `HO-*` records into rework. May be promoted to error in a MINOR bump (see §11 Q5).
13. **Reasoning-field density (v1.1)** — `DECISION` and `BECAUSE` are each AT MOST 40 words and contain NO embedded newline (the v1.1 bytecode form, §1.2). A value-level check ONLY: the structural flat-regex parse is unchanged (no structural parser change), so write/read parity (the shared `type_checker` ↔ `agr_read` constants) is preserved. Per HO-AGR-BYTECODE-FORMAT-TWO-BIRDS-20260620 (#101). Severity: error.

### 4.2 Severities

- **error** — hard block on commit / CI fail. All §4.1 invariants.
- **warning** — advisory only. Future MINOR additions may introduce warning-level checks (e.g. `BECAUSE` field too short, `TOKEN` semantically unclear).

### 4.3 Outputs

- **Default**: human-readable diagnostic plus non-zero exit on error.
- **`--json`**: PROD::I4-conformant structured output suitable for CI consumption.
- **`--quiet`**: exit code only; no stdout output.

### 4.4 Optional projection generation

The validator MAY ship with a `--emit-projection` flag that produces a `DECISIONS.oct.md` projection from the atomic records. The projection is `DERIVED_PROJECTION` per §2.3 and is written to a non-authoritative path (default: `.hestai/state/cache/decisions/DECISIONS.oct.md`). This flag is OPTIONAL; PR-D′ / PR-H choose whether to ship it in the first implementation.

## 5. Invariant chain

- **PROD::I1 SESSION_LIFECYCLE_INTEGRITY** — AGRs preserve decision provenance across sessions. The `ORIGIN_SESSION` + `ORIGIN_LEDGER_RD` optional fields are the citation pattern for content lifted out of ephemeral ledgers (per PR-E §2.5 promotion-by-citation, not by copy).
- **PROD::I3 PROVIDER_AGNOSTIC_CONTEXT** — OCTAVE deterministic parsing + identical tool contracts across providers yields identical reads.
- **PROD::I4 STRUCTURED_RETURN_SHAPES** — every tool return is a structured dictionary with defined fields; opaque blobs are forbidden. Error shapes mirror PR-B §3.4 conventions.
- **PROD::I5 READ_ONLY_CONTEXT_QUERY** — `lookup_decision`, `list_decisions`, and `trace_supersedure` are pure reads. `propose_decision_amendment` is a broker, not a writer to the canonical store; the canonical store remains read-only at the tool boundary.
- **PROD::I6 LEGACY_INDEPENDENCE** — interpreted as opt-in adoption discipline per RFC #40: consumer repos adopt voluntarily; non-adopters remain fully supported indefinitely; no consumer is forced to migrate.
- **SYS::I1 CONTEXT_INTEGRITY** — `META.TYPE::DECISION_RECORD` declares governance-class at the artefact level; PR-B §3.2.2 picks this up automatically.
- **SYS::I6 (scope boundary)** — PR-D specifies AGR records and consumer-side tool contracts within hestai-context-mcp. Vault (agent definitions, skills), Workbench (UI, dispatch), DebateHall (deliberation records), and octave-mcp (grammar) lanes are not encroached.

## 6. Verification of this ADR

This ADR is governance specification with no code attached. Verification is review-only:

- **Tier**: TIER_3
- **Facets**: GOVERNANCE
- **Gate**: CIV + SR per `/review` skill
- **Debate-hall escalation**: discretionary, recommended if reviewers find §1.4 (lifecycle transitions), §1.6 (supersession DAG), or §3.5 (broker pattern) ambiguous in practice.

Enforcement of the AGR contract itself begins on this ADR's merge:

- **By review discipline** until PR-D′/PR-H lands — PR authors authoring new AGR records by hand follow §1; reviewers verify against §4.1.
- **By tool boundary** once PR-F (PR-B §3) lands and PR-D′/PR-H lands — `octave_write` rejects `DECISION_RECORD` writes outside `.hestai/decisions/**` via PR-B §3.2.2; the validator CLI enforces §4.1.

## 7. Reconciliation with issue #25 (Decision Journal Light)

Issue #25 proposed an append-only `DECISION-JOURNAL.oct.md` extracted by `clock_out` from `#DECISION` tags. PR-D supersedes issue #25 on direction.

**Reasons**:

1. The journal's "audit-only, no blocking" model is incompatible with AGRs being authoritative for "what is currently binding". A reader cannot tell whether the journal records a decision that is binding now or one that has been superseded since.
2. The journal's tag-extraction pattern (`#DECISION:` in session content) is provider-coupled and PROD::I3-fragile: providers that strip or rewrite tags break the audit trail. AGRs require explicit authorship and validate against §4.1; provider variance does not corrupt them.
3. The journal's flat append model has no supersession semantics. AGRs supersede via `SUPERSEDED_BY` with full DAG enforcement (§1.6).
4. Issue #40's three-layer model (operator-ratified 2026-05-13) reserves "what was decided and why" to L1 AGRs and "stable structure" to L1S Facet ABI. The journal is neither; it is an orphaned design.

**Status of issue #25**: PR-D, on merge, reduces issue #25 to a closeable issue with disposition `SUPERSEDED-BY RFC #40 / ADR-RFC-ARCH-004`. The operator may close it post-merge with a short comment citing this section.

**Migration**: there is no in-place migration of historical session content. The `#DECISION` tag pattern is retired. Session content that contained ratified decisions during the journal's brief life can be promoted by hand to AGR records by citing the originating session (`ORIGIN_SESSION`) — same pattern as PR-E §2.5.

## 8. Promotion path for Mac B#1 RD15 / RD17 / RD18

Mac B#1's carry-forward (`.hestai/decisions/handoff/2026-05-16-rfc-40-mac-b1-carry-forward.md` §"Decision-record promotion candidates for PR-D") names three durable decision substances from the v1.4 ledger that should land as AGR records once PR-D ratifies.

PR-D **does not author** the three records here — that authorship is the first concrete use of the schema and is performed by a follow-up PR (operator-discretionary, may be bundled with PR-D′/PR-H or kept separate). PR-D instead specifies the **shape** of those records so the follow-up is mechanical:

| Candidate | Suggested TOKEN | Suggested STATUS at authoring | `ORIGIN_SESSION` | `ORIGIN_LEDGER_RD` |
|---|---|---|---|---|
| RD17 — AGR Standard Ownership Ruling | `HO-CONTEXT-MCP-OWNS-AGR-STANDARD-20260513` (verbatim from carry-forward) | `RATIFIED` | `646ddcc6-7ba4-48f5-b55f-fa16e26ca8bb` | `RD17` |
| RD18 — OCTAVE_WRITE multi-envelope workaround (provisional) | `HO-OCTAVE-WRITE-MULTI-ENVELOPE-WORKAROUND-20260513` (verbatim) | `RATIFIED` (with note: VOID-on-#420-land) | same | `RD18` |
| RD15 — Decisions-as-Context platform scope (historical) | `HO-DECISIONS-AS-CONTEXT-PLATFORM-SCOPE-20260505` (verbatim) | `RATIFIED` with explicit `SUPERSEDED_BY` set when the IA Contract umbrella token lands (per carry-forward §"Status after umbrella") | same | `RD15` |

These three TOKENs validate against §1.3 regex verbatim. None require schema extension.

Substance flows by citation, not verbatim copy, per PR-E §2.5: each record's `DECISION` and `BECAUSE` are authored fresh from the ledger's RD substance, and the originating ledger is cited via `ORIGIN_SESSION` + `ORIGIN_LEDGER_RD`.

## 9. Preflight gates (D1–D6 — binding for PR-D′ / PR-H code authorisation)

Issue #40 §"Preflight empirical gates" enumerates six gates. PR-D carries them forward verbatim as binding preconditions for code authorisation in the implementation PR. PR-D itself is the spec; the gates do not need to execute before PR-D merges, but the implementation PR MUST NOT bypass them.

| Gate | Pass condition | Owner |
|---|---|---|
| **D1** Schema audit | Survey elevana-studio's `DECISIONS.oct.md` schema + our existing ADR header conventions. Confirm §1 schema is syntactic superset. | implementation-lead, pre-code |
| **D2** First-record migration | Hand-author one AGR record here (recommend `HO-ADR-0013.oct.md`). | implementation-lead, pre-code |
| **D3** Cross-link with L0 / L1S | Confirm optional `HUMAN_ADR_REF` → `docs/adr/` resolves; confirm a CONCEPT_CARD can cite the AGR via EDGES. | implementation-lead with RFC #38 consumer |
| **D4** Validator CLI | Implement `validate_agr` before any retrieval tool. | implementation-lead |
| **D5** Retrieval benchmark | Hand-author 5 gold-set retrieval tasks, including cross-repo / cross-layer queries. Measure precision/recall. | implementation-lead |
| **D6** Cross-repo dry run | A consumer repo (operator-authorised, not assumed) authors 3 AGR records using the standard. | implementation-lead with operator-named consumer repo |

The "consumer repo" in D6 is **explicitly gated on operator approval per consumer**; this ADR does not pre-authorise elevana-studio or any other repo.

## 10. Out of scope (do not infer from PR-D)

PR-D does **not** define, decide, or constrain:

- **Code implementation.** Deferred to PR-D′ / PR-H, owner implementation-lead via oa-router.
- **CI gate implementation, MCP-tool fail-fast implementation.** Owned by PR-G and PR-F respectively, per PR-B.
- **Ledger schema.** Owned by PR-E (ADR-RFC-ARCH-003); the ledger is L4 ephemeral and never an AGR canonical store.
- **Placement invariant rules.** Owned by PR-α / PR-B.
- **Routing rules between RFC #38 and RFC #40.** Owned by PR-B §1.5; PR-D conforms.
- **PSS substrate or registry use.** ADR-0013 substrate ruling stands; PR-D does not invoke PSS.
- **Agent definitions, skill definitions, standards documents.** Vault lane.
- **UI, dispatch, payload compiler design.** Workbench lane.
- **Debate-hall artefact format.** DebateHall lane.
- **OCTAVE grammar additions or changes.** octave-mcp lane.
- **Authorship of the RD15 / RD17 / RD18 AGR records.** Specified in §8; authorship is operator-discretionary follow-up.
- **Closure of issue #25.** §7 specifies disposition; operator closes the issue.
- **Session-extraction workflow (session-ledger → AGR promotion).** Deferred. The placement-layer fix (PR-α / PR-B) prevents *new* session content from being treated as authoritative, but operators making binding decisions mid-session still have no automated on-ramp to `.hestai/decisions/`. Until that workflow exists (separate PR, separate SKILL update), operators must manually author committed AGR records per §1; `ho-control-room` SKILL §3 already marks ledger content as ephemeral, which is the operational defense. The risk if this remains unfixed is that the issue #25 pattern reappears by accident — an operator writes a decision into the ledger, the session ends, the decision substance is provenance-only. Acceptable risk for PR-D ratification; tracked as an open workflow gap.

## 11. Open questions for the operator (non-blocking)

These do not block PR-D ratification. Operator answers may land as MINOR additions (`1.1`, `1.2`).

1. **Token prefix convention** — §1.3 admits any uppercase-letter-led prefix. Is there value in canonising a small set of recommended prefixes (e.g. `HO-`, `OP-`, `ADR-`)? Current draft does not; legacy `HO-` tokens remain valid by regex.
2. **`ISSUE_REF` on `RATIFIED`** — current draft makes `ISSUE_REF` optional even on `RATIFIED`. Should it be required when the originating decision was filed on the issue tracker? Recommendation: keep optional; mandatory would block hand-ratified HO-tokens that have no issue.
3. **`EFFECTIVE_FROM` vs `AUTHORED_AT` divergence** — current draft permits `EFFECTIVE_FROM > AUTHORED_AT` (future-dated decisions). Acceptable, or should the validator reject as a foot-gun? Recommendation: permit; useful for staged rollouts.
4. **Monolithic projection generation** — should the validator CLI ship `--emit-projection` in v1, or defer to a separate tool? Current draft leaves it OPTIONAL; PR-D′ / PR-H chooses.
5. **TOKEN namespace authority / reserved prefixes** — §1.3 admits any uppercase-letter-led prefix and §4.1 #12 warns (not errors) on missing `RATIFIED_BY`. Should specific prefixes be reserved (e.g. `HO-` may only be authored by `agent:HOLISTIC_ORCHESTRATOR`; `OP-` only by `human:*`) with validator hard-error enforcement? Current draft does not; uniqueness + `RATIFIED_BY` warning is the operational floor. Promotion to a hard rule is a MINOR addition if TOKEN-squatting becomes observable.
6. **Session-extraction workflow** — see §10 closing entry. When (if ever) the workflow exists, what is its shape: an `extract_decisions` tool in this service, a SKILL update in the Vault lane, or a manual operator-driven pattern? Operator decision; not specced here.

## 12. Supersession

This ADR is **subordinate to**:

- ADR-RFC-ARCH-001 (PR-α placement invariant) — AGR placement category derives from PR-α §2.
- ADR-RFC-ARCH-002 (PR-B IA Contract) — AGRs are queried via PR-B §1.5 `lookup_decision` routing; AGRs inherit governance-class fail-fast via PR-B §3.2.2; AGR placement is bounded by PR-B §1.2.

This ADR is **adjacent to** ADR-RFC-ARCH-003 (PR-E ledger schema) — AGRs and ledgers are disjoint artefact classes; the ledger never holds AGR records, and AGRs never substitute for the ledger's session-local provenance role.

This ADR **supersedes on direction** issue #25 (Decision Journal Light) per §7.

A future v2.x AGR ADR would supersede §1 by explicit field-by-field breaking-change list, per §1.5 MAJOR-bump rules.

## 13. Ratification record (2026-06-11)

ADR-004 is **RATIFIED** via a stamped SR + CIV close-out. The substantive matter ruled was not merely the v1 schema but its convergence with the cross-repo AGR canonical form and the TIER projection.

### 13.1 What changed before ratification

- **§1.1 canonical form → BARE TOKEN** (merged PR #68, `396b888`). The operator-sanctioned writer `octave_write` dequotes identifiers under every `format_style`, so a quoted `TOKEN::"…"` is un-writable by the actual toolchain. Canonical form is therefore bare; Gate A readers (`type_checker`, `lexer`, `manifest`) are quote-optional and end-anchored (reject trailing-garbage TOKEN/ID lines). This heals the §1.1↔§1.6 split (§1.6 already used bare `AMENDS`/`EXTENDS`).
- **§4.1 #8 lineage guard enforced** in the linker (`governance/lineage.py`): in-repo `AMENDS`/`EXTENDS`/`SUPERSEDED_BY` edges must resolve; dangling same-repo edges are reported as a structured finding (PROD I4), never a crash; cross-repo edges remain advisory (§2.4); cohort-isolation is a handled expected case.

### 13.2 TIER crosswalk (3-row) — ratified

The AGR `TIER` enum (semantic gravity: STRATEGIC/TACTICAL/OPERATIONAL) receives a projection from elevana-studio's storage/process-gravity tiers, defined by *their* RATIFIED gravity-tiered decision (`HO-DECISION-GOVERNANCE-GRAVITY-TIERED-20260428`). The crosswalk **EXTENDS** HestAI-MCP ADR-0060 (RFC/ADR alignment + ISSUE_REF compliance); it does **not** amend it — AGR retains `ISSUE_REF` and the cohort carries it, so ADR-0060's compliance contract is preserved. Amendment authority for the tier vocabulary sits on the elevana-studio side.

| Source (process/storage gravity) | → AGR TIER (semantic gravity) | Empirical status |
|---|---|---|
| ARCHITECTURAL (issue + ISSUE_REF) | STRATEGIC | **PROVEN** — 5 cohort tokens, Gate-A clean |
| CONVENTION (inline-only) | TACTICAL | ruled-by-reasoning (unexercised) |
| MICRO (tooling + ENFORCEMENT_REF) | OPERATIONAL | ruled-by-reasoning (unexercised) |

CONVENTION→TACTICAL and MICRO→OPERATIONAL are ratified **by reasoning** with empirically-unexercised status; the first CONVENTION/MICRO AGR record is the natural validation point.

### 13.3 Evidence

Post-#68 anchored readers re-validated against the real 5-token elevana-studio cohort (2026-06-11): all 5 bare-canonical tokens validate clean; lineage guard reports the dangling same-repo `AMENDS` edge as a structured finding by default and as expected cohort-isolation when declared. Full suite 1070 green; governance coverage `lineage` 100% / `lexer` 100% / `manifest` 94% / `type_checker` 95%.

### 13.4 Sign-off

- **SR (standards-reviewer)** — APPROVED: schema complete and non-contradictory; 3-row crosswalk structurally sound (monotone co-ranking preserves ordinal gravity); ADR-0060 preserved via EXTENDS + ISSUE_REF retention.
- **CIV (critical-implementation-validator)** — APPROVED: merged implementation matches the spec (anchored quote-optional readers, lineage structured findings, ISSUE_REF retained); empirical cohort green; ready to ratify.

Authority pack: `.hestai/state/coordination/2026-06-11-agr-tier-crosswalk-authority-pack.md`. Downstream: elevana-studio D6 gate unblocks on this RATIFIED status.
