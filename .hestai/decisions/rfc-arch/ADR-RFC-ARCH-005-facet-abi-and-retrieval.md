# ADR-RFC-ARCH-005 — Facet ABI, L3 Retrieval Contract, and G1..G10 Preflight Gates

- **Status**: PROPOSED (awaiting CIV + SR review)
- **Date**: 2026-05-20
- **Scope**: `hestai-context-mcp` repository. Ratifies the L1S Facet ABI (RFC #38), specifies the L3 retrieval contract, declares the L2 acceleration-cache contract, and binds the G1..G10 preflight gates. Specification only; code implementation is deferred to successor PRs routed via oa-router to implementation-lead.
- **Sequence**: PR-C in the RFC-arch series. Subordinate to ADR-RFC-ARCH-001 (PR-α placement invariant) and ADR-RFC-ARCH-002 (PR-B IA Contract). Adjacent to ADR-RFC-ARCH-003 (PR-E ledger schema) and ADR-RFC-ARCH-004 (PR-D AGR records). L1S is **peer** to L1 AGR (not subordinate, not parent) per ADR-RFC-ARCH-004 §0.2.
- **Related**: RFC #38 (Facet ABI — operator-ratified architectural direction 2026-05-08); RFC #40 (AGR — peer projection layer); `.hestai/context/concepts/hestai-context-mcp/CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME.oct.md` (the PROPOSED frame card this ADR ratifies and supersedes in-place — see §7); `.hestai/decisions/handoff/2026-05-19-registry-research-inputs.md` and the two `docs/research/2026-05-19-*.md` reports (load-bearing non-authoritative reference).
- **Closes**: hestai-mcp issue #87 (Concepts claim Code) — reframed and resolved by this ADR (see §7.3).
- **Authority**: HOLISTIC_ORCHESTRATOR drafting; convergent L0–L5 architecture (debate-hall 2026-05-16, carried forward via PR-B); CE / PE / CIV amendments from the PR-α → PR-D sequence folded in as immutable preconditions (see §0.2).
- **Invariants invoked**: PROD::I1 (SESSION_LIFECYCLE_INTEGRITY), PROD::I3 (PROVIDER_AGNOSTIC_CONTEXT), PROD::I4 (STRUCTURED_RETURN_SHAPES), PROD::I5 (READ_ONLY_CONTEXT_QUERY), PROD::I6 (LEGACY_INDEPENDENCE — applied as scope-boundary discipline), SYS::I1 (CONTEXT_INTEGRITY), SYS::I6 (scope boundary).
- **Implementation owners (deferred)**: PR-C′ / PR-J — implementation-lead via oa-router for the L3 read tools; G5 validator CLI — implementation-lead via oa-router; G1 / G2 audits — implementation-lead, pre-code. G1..G10 (§4) are binding preconditions for code authorisation.

## 0. Reading guide

This ADR contains four governance artefacts in one document, sequenced so each builds on the prior:

- **§1 — L1S Facet ABI** ratifies the four card kinds (Concept, Frame, Cluster, Phase), their OCTAVE envelope schemas, placement, edge typology, single-envelope rule, status lifecycle, and the `Concept::<ID>` source-marker convention.
- **§2 — L3 Retrieval Contract** specifies four MCP tools (one preserved, three new): `get_context` (unchanged), `lookup_concept`, `query_context`, `explain_context_selection`. All four are pure read-only.
- **§3 — L2 Acceleration Cache Contract** specifies the cache's non-authoritative semantics; PR-C does **not** decide the L2 implementation (SQLite FTS5 vs BM25-only). That decision is empirical, gated by G6.
- **§4 — G1..G10 Preflight Gates** binds ten preflight gates as preconditions for v1 code authorisation.

§5 closes the invariant chain. §6 specifies the verification process for this ADR itself. §7 records the supersession of the existing FRAME card, the compatibility audit against ADR-RFC-ARCH-001..004, and the closure of hestai-mcp #87. §8 enumerates out-of-scope items. §9 lists open questions for the operator.

### 0.1 Defense-in-depth ordering

This ADR composes with the PR-α / PR-B / PR-D defenses already in force:

- L1S facet cards inherit governance-class TYPE registration (PR-B §3.2.2) via `META.TYPE::FRAME_CARD | CONCEPT_CARD | CLUSTER_CARD | PHASE_CARD`, so any future fail-fast tool (PR-F) automatically rejects governance-class writes to non-authoritative paths.
- The CI gate (PR-G) treats `.hestai/context/**` as the only authoritative L1S root.
- L3 tools are **read-only** at the canonical store; they may consult L2 but never mutate it from the tool boundary (PR-B §3 fail-fast contract semantics carry over).

### 0.2 Immutable inputs (not re-debated)

The following are immutable in PR-C scope and not re-litigated:

1. **L3 tools MUST be pure** (no LLM at runtime; no writes; no cache mutation; no session creation). PROD::I5 + ADR-RFC-ARCH-002 §1.4.
2. **L1 canonical** (DECISIONS, North Stars, L0 ADRs) **MUST remain UNCHANGED** by RFC #38 v1. CE amendment.
3. **L2 cache MUST be content-hash invalidated, NEVER mtime.** PE amendment.
4. **Facet cards MUST be COMMITTED governance, NOT derived cache.** HestAI I3 Human Primacy + I4 Discoverable Persistence; reasserted via PR-α §2 + PR-B §1.2.
5. **`Concept::<ID>` source markers are CI-validated claims; rot triggers gate failure.** Revives + reframes hestai-mcp #87.
6. **SQLite FTS5 vs BM25 as L2 implementation is DEFERRABLE** to the G6 empirical benchmark; this ADR declares the criterion only.
7. **Embeddings are DEFERRED from v1**; revisit only if G6 recall <90%.
8. **Pre-flight gates G1..G10 MUST execute before any v1 code is written.**
9. **`get_context` signature and purity MUST be preserved** (PROD::I5 + RISK_003 OPTION_C).
10. **Cross-machine determinism MUST be empirically proven via G10.**
11. **LOCAL repo-relative paths only.** Cross-repo facet-card resolution is deferred to a future amendment (PE amendment carried forward from PR-α / PR-B §1.4).
12. **Single OCTAVE envelope per file** (route around `octave-mcp` issue #420; defer multi-envelope optimisation until #420 fixes).

## 1. L1S Facet ABI

### 1.1 Card kinds (v1: exactly four)

The L1S Facet ABI v1 defines exactly four card kinds. Adding a fifth kind is a MAJOR schema bump (§1.7) and requires a successor ADR.

| Kind | Purpose | Granularity | Example |
|---|---|---|---|
| **Concept** | A single named structural concept (an invariant, a tool boundary, a constraint, an actor, a contract surface) | Atomic | `PROD_I5`, `STORAGE_ADAPTER_PROTOCOL`, `OCTAVE_WRITE_GATE` |
| **Frame** | An orientation map over a cluster of related concepts; the "what kind of question is this?" surface | Aggregator | `CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME`, `THREE_LAYER_GOVERNANCE_FRAME` |
| **Cluster** | An explicit grouping of concepts that travel together for retrieval purposes (a curated bundle, not all concepts of a kind) | Aggregator | `B1_PSS_FOUNDATION` (the bundle of storage-adapter / identity-tuple / portable-artifact concepts that load together) |
| **Phase** | The **definition** of a phase — what constraints govern it, what artefacts gate progression, what the success criteria are. **NOT** the temporal state of whether the phase is currently active or complete | Atomic-or-aggregator (per phase) | `PHASE_B1_FOUNDATION_DEFINITION`, `PHASE_B2_WORKBENCH_INTEGRATION_DEFINITION` |

**Critical boundary** (drawn explicitly to prevent collision with RFC #40 / ADR-RFC-ARCH-004): a `Phase` card describes the **stable structural shape** of a phase — its constraints, gates, and success criteria. A `Phase` card does **not** record whether the phase is active, complete, in progress, or which RD entries marked transitions. Phase **state** (transitions, completions, ratifications) lives in L1 AGRs (RFC #40), the L4 ledger, and git history. A `Phase` card whose content drifts into temporal/historic claims is a §1.7 violation and is rejected by the validator (G5).

### 1.2 OCTAVE envelope per kind (required sections)

Every L1S facet card is a single OCTAVE document with the following required sections, in order. Section names are normative.

```
===META===
TYPE::FRAME_CARD | CONCEPT_CARD | CLUSTER_CARD | PHASE_CARD
REPO_ID::<repo-id>
ID::<CARD_ID>
STATUS::proposed | ratified | superseded
CARD_SCHEMA_VERSION::1
GENERATED_AT_COMMIT::"<short git sha or N/A>"
SOURCE_HASH::"<sha-256 of source-of-truth content or N/A for aggregators>"
===END===

===EXACT===
IDS::[<list of card IDs and exact-match identifiers this card resolves>]
PROD_IMMUTABLES::[<I1..I6 referenced>]
ADR_REFS::[<ADR identifiers cited>]
ISSUE_REFS::[<issue numbers cited>]
TOOL_NAMES::[<tool names cited>]
FILE_PATHS::[<repo-relative or pattern paths cited>]
MUST_PRESERVE::[<load-bearing invariants this card encodes>]
===END===

===FACETS===
INTENT::"<one-paragraph statement of the card's purpose>"
CONSTRAINTS::[<list of constraints the card encodes>]
FAILURE_MODES::[<known ways the encoded structure breaks>]
OPERATIONAL_RULES::[<actionable how-to-use-this-structure rules>]
INTEGRATION_POINTS::[<how this card relates to other governance>]
CURRENT_STATUS::"<one-line status — for FRAME/PHASE cards, this is the META.STATUS plus a one-line gloss>"
WHEN_TO_LOAD::[<triggers that should pull this card into context>]
WHEN_NOT_TO_LOAD::[<scenarios where another card is more appropriate>]
===END===

===EDGES===
EXTENDS::[<TOKENs this card extends>]
CONSTRAINS::[<TOKENs this card constrains>]
IMPLEMENTED_BY::[<TOKENs implementing this card>]
TESTED_BY::[<TOKENs that test the structure>]
RELATED::[<TOKENs related but not in another edge>]
CONFLICTS_WITH::[<TOKENs whose claims conflict>]
PART_OF_FRAME::[<frame TOKENs that include this card>]
===END===

===VALIDATION===
SOURCE_REF_RESOLVES::true | false
MARKERS_RESOLVE_TO_CARD::true | false | N/A
CHANGED_MARKED_FILE_REQUIRES_REVIEW::true | false
===END===
```

Optional sections (admissible but not required): `===SOURCE_REFS===` (external citation list), `===AUDIENCE_VIEW_SEEDS===` (audience-aware projection seeds; see §2.6), `===PROVENANCE===` (`Concept::<ID>` marker registry; see §1.8).

Sections beyond this set are reserved against future MINOR additions; v1.x validators MUST reject unknown section names.

### 1.3 ID rules

`<CARD_ID>` MUST match the regular expression:

```
^[A-Z][A-Z0-9_]{2,127}$
```

Constraints:

1. Uppercase letters, digits, underscores. No hyphens (this differentiates facet-card IDs from AGR `TOKEN`s, which mandate the trailing `-YYYYMMDD` date suffix per ADR-RFC-ARCH-004 §1.3).
2. 3–128 characters total.
3. MUST start with an uppercase letter.
4. MUST be unique repo-wide across `.hestai/context/**/*.oct.md`. A collision is a hard validator error (G5).

**Reserved prefixes** (v1 — extend in MINOR bumps): `PROD_` (PROD North Star immutables, e.g. `PROD_I5`), `SYS_` (SYSTEM-STANDARD references, e.g. `SYS_I1`), `ADR_` (ADR identifiers, e.g. `ADR_0013`), `PHASE_` (phase definition cards, e.g. `PHASE_B1_FOUNDATION_DEFINITION`). Authoring a card whose ID begins with a reserved prefix without corresponding META content is a validator warning (G5); promotion to error is a MINOR bump candidate.

### 1.4 Placement (per ADR-RFC-ARCH-001 §2 / ADR-RFC-ARCH-002 §1.2)

L1S facet cards live in the `committed_context_cards` category at:

```
.hestai/context/concepts/<repo-id>/<CARD_ID>.oct.md
```

Where:

- `<repo-id>` is the repository slug (e.g. `hestai-context-mcp`). Sub-grouping under `<repo-id>/<group>/<CARD_ID>.oct.md` is admissible when a coherent group exists; the validator MUST resolve `<CARD_ID>` to whichever path holds it, regardless of intermediate grouping.
- `<CARD_ID>` matches §1.3.

Facet cards MUST NOT live in `.hestai/state/sessions/` (L4 ephemeral), `.hestai/state/cache/` (L2 cache), or anywhere outside `.hestai/context/`. This invariant is enforced by PR-B §3.3 (tool-boundary fail-fast on the facet-card `META.TYPE` set) and PR-B §2 (CI gate).

### 1.5 Edge typology

Edge classes are fixed in v1 to the seven listed in §1.2's `===EDGES===` block. The semantics are:

| Edge | Direction | Meaning |
|---|---|---|
| `EXTENDS` | this → other | This card additively extends the other (does not replace it) |
| `CONSTRAINS` | this → other | This card imposes a constraint on the other (e.g. an invariant constrains an implementation) |
| `IMPLEMENTED_BY` | this → other | The structure described here is implemented by the cited card (typically a code-grounded concept) |
| `TESTED_BY` | this → other | The structure described here is tested by the cited card or marker |
| `RELATED` | this → other | Related but not in another more specific edge — use sparingly |
| `CONFLICTS_WITH` | this → other | The two cards make claims that cannot both be live; expected to resolve via supersession |
| `PART_OF_FRAME` | this → other | This card is included in the cited Frame card's orientation map |

Edge subgraphs are not constrained to be globally acyclic; cycles **within an edge class** are validator errors per G5. Cross-edge cycles (e.g. `A EXTENDS B`, `B CONFLICTS_WITH A`) are admissible and signal an unresolved supersession candidate.

Additional edge classes are reserved against future MINOR additions; v1.x validators MUST reject unknown edge names.

### 1.6 Single-envelope per file (octave-mcp #420 workaround)

Every L1S facet card is a **single OCTAVE envelope** per file. Multi-envelope documents (multiple `===NAME=== … ===END===` blocks of distinct types) are forbidden in v1.

Rationale: `octave-mcp` issue #420 produces inconsistent parsing on multi-envelope documents. Until #420 lands a fix, single-envelope is the only safe authoring shape. This is a deferral, not a permanent commitment; multi-envelope facet cards may be admitted in a MINOR bump once #420 is resolved.

Optional sub-sections (`===SOURCE_REFS===`, `===AUDIENCE_VIEW_SEEDS===`, `===PROVENANCE===`) are admissible because they are sub-sections of the same outer envelope (delimited by their own `===NAME===` / `===END===` markers but operating as named blocks within the single document), not parallel envelopes; the validator (G5) treats them as part of the single facet-card envelope.

### 1.7 Status lifecycle

The `META.STATUS` enum and its admissible transitions match ADR-RFC-ARCH-004 §1.4 vocabulary (subset — no `VOID`):

```
proposed ───── ratified ───── superseded  (terminal for this card; chain continues via successor reference)
```

Rules:

1. A new card starts in `proposed` or `ratified`. Authoring straight to `ratified` is permitted when this ADR or a successor ADR ratifies the card at authoring time (the present ADR does so for `CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME` — see §7.1).
2. `proposed → ratified` is the standard adoption transition. Performed via a ratifying ADR (cited at the reference site or via a `===PROVENANCE===` `RATIFIED_BY` atom).
3. `ratified → superseded` is the standard evolution transition. The superseding card's `EDGES.EXTENDS` or successor ADR MUST cite the superseded card; the superseded card's `META.STATUS` flips to `superseded` and an `EDGES.RELATED` or in-block `===PROVENANCE===` `SUPERSEDED_BY::<CARD_ID>` atom MUST identify the successor.
4. The `STATUS` field is mutable in-place per SYS::§1 LAW `SOURCE_FIDELITY` (no versioned copies of the card file). Mutation is a normal git commit; history lives in git, not in the card.
5. No `VOID` state in v1. A card that is no longer applicable transitions to `superseded` with the successor citing what replaced it; if nothing replaced it, the successor is a deliberately-empty placeholder card with `META.STATUS::ratified` and `FACETS.INTENT::"<superseded card> retired; no replacement"`.

This subset deliberately omits AGR `VOID` because facet cards encode stable structure; retraction without replacement is structurally suspicious and should be made explicit via a placeholder rather than a silent disappearance.

### 1.8 `Concept::<ID>` source-marker convention (closure of hestai-mcp #87)

Source code MAY carry markers of the form:

```
# Concept::<ID>
```

(or the language-appropriate comment prefix) immediately preceding the symbol the marker claims. A marker is a **CI-validated claim** that the source code at that site implements, exemplifies, or is constrained by the cited L1S Concept card.

Rules:

1. The marker's `<ID>` MUST resolve to a card matching §1.3 whose `META.TYPE::CONCEPT_CARD`. Validator (G5) rejects markers that resolve to other kinds or unresolved IDs.
2. The marker MAY be repeated in multiple source sites; each site is an independent claim.
3. The card's `===PROVENANCE===` section (optional) MAY list known marker sites as `MARKERS::["<repo-relative-path>:<line-or-symbol>", ...]`. The validator does not require this to be complete; the source-of-truth direction is **source → card**, not the reverse.
4. A pull request whose diff modifies a source file containing a `Concept::<ID>` marker MUST carry the `concept-review` label (G5 enforces; PR-G CI gate semantics extend by analogy). The reviewer's job is to confirm the marker still applies after the source change.
5. Removing or renaming a marker without a corresponding card update is a validator warning (G5).

This convention closes hestai-mcp issue #87 (Concepts claim Code) by reframing the original objection: in #87, the concern was that concepts asserting ownership of code with no validation pathway invited rot. The `Concept::<ID>` marker + G5 validator pathway converts the assertion into a CI-validated claim. Markers without corresponding cards fail CI; cards without markers are valid (a card may describe purely structural concepts that have no direct source-code implementation, e.g. `PROD_I5`). The asymmetry is intentional: cards are the source of truth, markers are the trace evidence.

## 2. L3 Retrieval Contract

### 2.1 Tools introduced (and the boundary against RFC #40)

PR-C names four MCP tools at the L3 layer:

| Tool | Kind | Status | I5? | I4? |
|---|---|---|---|---|
| `get_context` | read | **unchanged** | yes (preserved) | yes (preserved) |
| `lookup_concept` | read | **new** | yes (pure read) | yes (structured return) |
| `query_context` | read | **new** | yes (pure read) | yes (structured return) |
| `explain_context_selection` | read | **new** | yes (pure read) | yes (structured return) |

`get_context` is preserved verbatim per PROD::I5 + RISK_003 OPTION_C. It is **not** modified by PR-C. The new tools are additive.

**Critical boundary against ADR-RFC-ARCH-002 §1.5 and ADR-RFC-ARCH-004 §3** (drawn explicitly to prevent the retrieval-layer overreach risk identified by ho-liaison consult 2026-05-20):

- `lookup_concept` and `query_context` index and return **only** L1S facet cards (Concept / Frame / Cluster / Phase per §1.1). They MUST NOT search L0 canonical ADRs/North-Stars as primary search corpus, MUST NOT search L1 AGR records, MUST NOT search L4 ledger entries, and MUST NOT compose temporal/historic answers.
- Questions of the form "what did we decide about X, and when?" route to **`lookup_decision`** (ADR-RFC-ARCH-004 §3.2), not `query_context`.
- Composite questions of the form "what is the authoritative current state of X?" are composed **client-side** at L3 per ADR-RFC-ARCH-002 §1.5: the caller invokes `lookup_concept` for structure and `lookup_decision` for the most recent non-superseded decision, and joins the results. The L3 layer does not provide a server-side composition tool in v1.
- `get_context` is unchanged and continues to synthesise context per its existing contract (PROD::I5); it is not a routing target for the §1.5 boundary.

The IDs and tool names cited in L1S `===EXACT===` blocks MAY reference ADRs, issues, and other governance artefacts — but resolution of those references is **direct file read or `lookup_decision`**, not `lookup_concept`. The `===EXACT===` block is provenance metadata, not a search index over external corpora.

### 2.2 `lookup_concept(working_dir, concept_id, audience?)`

Resolves a single L1S facet card by exact `ID`. Pure read.

**Input** (PROD::I4-conformant):

```
{
  "working_dir": "<absolute or repo-rooted path>",
  "concept_id": "<CARD_ID string>",
  "audience": "agent" | "human"  // optional; default "agent"
}
```

`audience` controls return verbosity. `"agent"` returns the structured card verbatim. `"human"` MAY additionally include rendered prose where the spec is unambiguous (e.g. resolved edge expansion summarised). Implementations MAY ignore `audience` and always return `"agent"` shape; consumers MUST tolerate this.

**Return shape** (PROD::I4-conformant):

```
{
  "ok": true,
  "card": {
    "id": "<CARD_ID>",
    "type": "FRAME_CARD" | "CONCEPT_CARD" | "CLUSTER_CARD" | "PHASE_CARD",
    "status": "proposed" | "ratified" | "superseded",
    "card_schema_version": 1,
    "repo_id": "<repo-id>",
    "path": "<repo-relative path to the .oct.md file>",
    "exact": { /* contents of ===EXACT=== section */ },
    "facets": { /* contents of ===FACETS=== section */ },
    "edges": { /* contents of ===EDGES=== section */ },
    "validation": { /* contents of ===VALIDATION=== section */ },
    "optional_sections": { /* SOURCE_REFS, AUDIENCE_VIEW_SEEDS, PROVENANCE if present */ }
  }
}
```

**Error cases** (per the §2.10 error envelope):

- `CONCEPT_NOT_FOUND` (`input_validation`) — no card at the requested ID.
- `CONCEPT_ID_MALFORMED` (`input_validation`) — ID fails §1.3 regex.
- `CARD_PARSE_FAILED` (`schema_violation`) — file found but OCTAVE envelope or required sections fail to parse; `context.path` and `context.parse_error` populated. Implementation choice: treat as fatal for the read, do NOT silently skip or partial-return.
- `WORKING_DIR_INVALID` (`io_failure`).

### 2.3 `query_context(working_dir, role, phase, query, budget_tokens?, audience?)`

Returns a ranked list of L1S facet cards scoped by audience and token budget. Pure read. Scope is **L1S facet cards only** per the §2.1 boundary.

**Input** (PROD::I4-conformant):

```
{
  "working_dir": "<path>",
  "role": "<agent-role string, e.g. 'implementation-lead', 'reviewer', 'agent'>",
  "phase": "<phase identifier, e.g. 'B1_FOUNDATION_COMPLETE'>",
  "query": "<free-form query string>",
  "budget_tokens": <integer or null>,         // optional; null = caller-default
  "audience": "agent" | "human"               // optional; default "agent"
}
```

**Return shape** (PROD::I4-conformant):

```
{
  "ok": true,
  "results": [
    {
      "id": "<CARD_ID>",
      "type": "<card type>",
      "path": "<repo-relative path>",
      "score": <float 0..1>,                  // total ranking score after pipeline
      "signals": {
        "exact_id_match": <bool>,
        "concept_marker_path_match": <bool>,
        "file_glob_match": <bool>,
        "bm25_score": <float>,
        "edge_expansion_distance": <int>      // graph distance from a seed match
      },
      "audience_view": "<rendered seed from AUDIENCE_VIEW_SEEDS for this audience, if present>"
    },
    …
  ],
  "total_candidates_scored": <integer>,
  "budget_tokens_used": <integer>,
  "budget_tokens_requested": <integer or null>,
  "explicit_omissions": [
    { "id": "<CARD_ID>", "reason": "budget_exceeded" | "audience_filter" }
  ]
}
```

The `explicit_omissions` field is mandatory; when the token budget excludes relevant cards, the tool MUST surface their IDs and reason so the caller can decide whether to retry with a larger budget. Silent omission is forbidden.

**Error cases**:

- `QUERY_INVALID` (`input_validation`) — empty query or query exceeds implementation max length.
- `ROLE_PHASE_UNKNOWN` (`input_validation`) — `role` or `phase` cannot be resolved against the known set. Implementation MAY accept arbitrary strings and fall back to a generic ranking; if so, this error is not raised.
- `BUDGET_TOO_SMALL` (`input_validation`) — `budget_tokens` below an implementation-defined floor that cannot pack even a single card.
- `CARD_PARSE_FAILED` (`schema_violation`) — any card under `.hestai/context/**` fails to parse; fail the whole call rather than silently dropping the bad card.
- `WORKING_DIR_INVALID` (`io_failure`).

### 2.4 `explain_context_selection(working_dir, query, returned_ids, role?, phase?)`

Returns a trace of which ranking signals produced the given result set. Pure read. This is the audit surface for `query_context` — every ranked card MUST be traceable to a signal; silent retrievals are forbidden (G9).

**Input** (PROD::I4-conformant):

```
{
  "working_dir": "<path>",
  "query": "<the original query string>",
  "returned_ids": ["<CARD_ID>", …],
  "role": "<agent-role string or null>",
  "phase": "<phase identifier or null>"
}
```

**Return shape** (PROD::I4-conformant):

```
{
  "ok": true,
  "trace": [
    {
      "id": "<CARD_ID>",
      "rank": <integer, 1-indexed>,
      "score": <float>,
      "contributing_signals": [
        { "signal": "exact_id_match", "weight": <float>, "evidence": "<short string>" },
        { "signal": "concept_marker_path_match", "weight": <float>, "evidence": "<path:line>" },
        { "signal": "bm25_score", "weight": <float>, "evidence": "<terms matched>" },
        { "signal": "edge_expansion_distance", "weight": <float>, "evidence": "<seed_id, hops>" }
      ],
      "audience_filter_applied": <bool>,
      "budget_status": "included" | "omitted_for_budget"
    },
    …
  ],
  "ranking_pipeline_version": "<semver of the ranking pipeline implementation>"
}
```

The `ranking_pipeline_version` is part of the determinism contract (§2.7) — two calls with the same `(checkout, query, role, phase, returned_ids, ranking_pipeline_version)` MUST return identical traces.

**Error cases**:

- `QUERY_INVALID`, `WORKING_DIR_INVALID` — as in §2.3.
- `RETURNED_IDS_NOT_IN_RECENT_CALL` (`input_validation`) — implementation MAY require that `returned_ids` correspond to a recent `query_context` result; if so, this error fires when the trace cannot be reconstructed. Implementations MAY instead recompute the ranking deterministically from `query`, in which case the requirement is relaxed and this error is not raised.

### 2.5 `get_context` — unchanged (supersession-safe)

`get_context` is preserved verbatim from B1 (PROJECT-CONTEXT.oct.md §1 TOOLS; RISK_003 OPTION_C; PROD::I5). PR-C does **not** modify:

- The tool's input or output schema.
- The tool's purity contract (zero side effects).
- The tool's content sources (`.hestai/state/context/PROJECT-CONTEXT.oct.md`, North Stars, git state per the existing ContextSteward).

This explicit preservation is the supersession-safe statement required by ADR-RFC-ARCH-002 §1.4 and PROD::I5 §8 TRIGGERS ("side effect or mutation or get_context writes = I5 purity violation"). Any future amendment that modifies `get_context` is a successor ADR with mandatory operator ratification.

### 2.6 Ranking v1

The v1 ranking pipeline for `query_context` is, in order:

1. **Exact ID match.** If `query` exactly matches a `<CARD_ID>` per §1.3, that card scores 1.0 and is emitted first.
2. **Concept marker path match.** If `query` contains a repo-relative source path that carries a `Concept::<ID>` marker (per §1.8), the cards cited by those markers score next-highest with weight proportional to marker-site proximity to query terms.
3. **File glob match.** If `query` contains a path glob (e.g. `src/**/*.py`), cards whose `===EXACT===.FILE_PATHS` list intersects the glob score next.
4. **BM25 over cards.** Free-form lexical match against the card body (META.ID + EXACT.IDS + FACETS.INTENT + FACETS.CONSTRAINTS + AUDIENCE_VIEW_SEEDS, weighted; see G6 for the precise column weighting decision).
5. **Edge expansion.** Cards reachable from any of the above seeds within 2 hops along `EXTENDS` / `PART_OF_FRAME` / `IMPLEMENTED_BY` / `CONSTRAINS` edges receive an expansion boost.
6. **Token pack.** Results are packed into the requested `budget_tokens` budget; audience-aware projection (§1.2 `===AUDIENCE_VIEW_SEEDS===`) selects which facet sub-fields fit. Cards excluded for budget appear in `explicit_omissions`.

This pipeline is the v1 contract. Tuning of weights, BM25 column weights, and edge-expansion radius is implementation-lane (PR-C′ / PR-J), subject to G3 gold-set regression detection.

### 2.7 Determinism contract

Same checkout + same `(query, role, phase, budget_tokens, audience)` + same `ranking_pipeline_version` → byte-identical result.

This is binding on all four L3 tools and is enforced empirically by G8 (single-machine reproducibility) and G10 (three-machine cross-machine determinism). Any non-determinism (random seeds, time-dependent ranking, per-machine cache priming that affects ranking) is a G8/G10 failure and blocks v1 code merge.

`get_context` inherits its existing determinism characteristics; this contract does not strengthen or weaken them.

### 2.8 L2 implementation deferral (G6 criterion)

The L3 retrieval contract does **not** decide the L2 implementation. The choice between SQLite FTS5, BM25-only (in-process), or both is empirical, decided by G6 (§4).

The criterion declared here (not the decision):

- **G6 PASS_CRITERION**: a candidate L2 implementation must achieve ≥90% recall against the G3 gold-set with p95 query latency ≤200ms on a representative checkout (size to be operationalised in the G6 measurement protocol).
- If BM25-only achieves the criterion, the SQLite FTS5 implementation cost is not justified for v1 and is deferred.
- If neither achieves the criterion, embeddings move from "deferred" to "v2 in-scope"; see §4 G6 BLOCKS_WHAT.

The research handoff (`.hestai/decisions/handoff/2026-05-19-registry-research-inputs.md` §"Concrete schemas") provides candidate SQLite FTS5 + BM25 column-weighting schemas as **non-binding** reference. The G6 owner consults these but is not bound by them.

### 2.9 Provider agnosticism (PROD::I3)

All four L3 tool contracts MUST yield identical results across providers (Claude / Codex / Gemini / Goose / others). OCTAVE's deterministic parsing is the operational basis. Provider-specific behaviour at any of these tools is a PROD::I3 violation and blocks v1 merge.

### 2.10 Common error envelope (PROD::I4)

Every L3 tool — read or future broker — MUST return errors in this envelope, mirroring ADR-RFC-ARCH-004 §3.1.1:

```
{
  "ok": false,
  "error": {
    "code": "<error-code-from-tool-specific-list>",
    "category": "input_validation" | "schema_violation" | "io_failure" | "ranking_failure",
    "message": "<one-line human-readable explanation>",
    "tool": "lookup_concept" | "query_context" | "explain_context_selection",
    "context": { /* tool-specific structured payload */ },
    "contract_ref": "ADR-RFC-ARCH-005 §2.<n>"
  }
}
```

Implementations MAY add fields to `error` (e.g. timing, tool_version) but MUST NOT remove or rename the required keys. Opaque-blob errors are forbidden.

## 3. L2 Acceleration Cache Contract

### 3.1 Non-authoritative by construction

The L2 acceleration cache is **never authoritative**. ADR-RFC-ARCH-002 §1.3 names this as the source-of-authority statement: an authoritative path is one whose category is `committed_governance` or `committed_context_cards` and whose layer is L0, L1, or L1S. L2 falls outside this set categorically.

L1S facet cards are the canonical store for the L3 retrieval contract. The L2 cache exists solely to accelerate L3 queries that would otherwise re-parse every facet card on every invocation.

### 3.2 Content-hash keying

The L2 cache MUST be keyed by content hashes computed over the canonical UTF-8 bytes of the source artefacts (facet card files; source-code marker sites for `Concept::<ID>` indexes). Mtime-based invalidation is forbidden — it is a known failure mode that integrates badly with PSS local mutation and with cross-machine clock skew (carry-forward from PR-α / PR-B).

A cache entry's key includes:

- The content hash of the L1S card file(s) the entry indexes.
- The `ranking_pipeline_version` (§2.7).
- The `card_schema_version` declared in `META`.

A change to any of these invalidates the entry. The cache may be rebuilt incrementally; the rebuild MUST be deterministic from L1S facet cards alone (no external state contributes to entries beyond the keying inputs).

### 3.3 Gitignored placement

The L2 cache is placed under the `optional_cache` category (PR-α §2 / PR-B §1.2) at:

```
.hestai/state/cache/context-index/
```

This subtree is gitignored. The cache MUST NOT be referenced as authoritative from any open issue, ADR, RFC, PR body, or committed facet card; references into `.hestai/state/cache/` from governance artefacts MUST carry an `EPHEMERAL` or `NON_AUTHORITATIVE` marker per PR-α §2.

### 3.4 Rebuildability

The L2 cache MUST be fully rebuildable from L1S facet cards (and source-code `Concept::<ID>` markers, where the cache indexes them). No information lives only in the cache.

Deletion of the entire `.hestai/state/cache/context-index/` subtree MUST be safe: the next `query_context` invocation triggers rebuild from L1S, and the rebuilt cache yields byte-identical query results (§2.7).

### 3.5 Read fall-through

L3 tools MAY consult the L2 cache for performance. They MUST fall through to L1S read on cache miss. They MUST NOT fail or degrade query semantics when the cache is absent or stale (per §3.2, stale entries are invalidated by content hash; "stale" is a transient state during rebuild).

L3 tools MUST NOT mutate the L2 cache from the tool boundary. Cache population is performed by a separate write path (PR-C′ / PR-J implementation detail) that is invoked outside L3 query handling — typically on a file-watch trigger, on validator (G5) run, or on explicit operator command. Mixing query and cache-write at the L3 boundary violates PROD::I5.

### 3.6 What this section does not specify

This section specifies the **contract**: non-authoritativeness, content-hash keying, gitignored placement, rebuildability, read fall-through. It does **not** specify:

- The L2 implementation (SQLite FTS5 vs BM25-only vs both). PR-C′ / PR-J chooses, gated by G6.
- The cache file format, schema, or indexing scheme. Implementation-lane.
- The cache population trigger (file-watch, validator-run, on-demand). PR-C′ / PR-J chooses, subject to the constraint that population MUST NOT occur during an L3 query call.

## 4. G1..G10 Preflight Gates

Issue #38 §"Preflight empirical gates" and the existing `CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME` card name ten gates. PR-C carries them forward as **binding preconditions** for v1 code authorisation in the implementation PR. PR-C itself is the spec; the gates need not all execute before PR-C merges, but the implementation PR (PR-C′ / PR-J) MUST NOT bypass them.

Gate format: PURPOSE / MEASUREMENT / PASS_CRITERION / OWNER / BLOCKS_WHAT.

| Gate | PURPOSE | MEASUREMENT | PASS_CRITERION | OWNER | BLOCKS_WHAT |
|---|---|---|---|---|---|
| **G1** | Divergence audit | Inventory of `.hestai/state/context/PROJECT-CONTEXT.oct.md` separating semantic facts from session ephemera | Every semantic fact in PROJECT-CONTEXT either lifted to an L1S facet card or explicitly retained with reason; zero unaccounted facts | implementation-lead, pre-code | PR-C′ / PR-J (no v1 build without G1 closed); also blocks PR-K (PROJECT-CONTEXT pruning) |
| **G2** | Source-marker rot baseline | Count of broken `Concept::<ID>` references in the current `src/**` tree | Baseline count recorded; G5 validator wires this baseline as the regression-detection floor (CI fails on any net-new broken marker once G5 is live) | implementation-lead, pre-code | G5 (validator needs the baseline to draw the line); PR-C′ / PR-J |
| **G3** | Gold-set construction | Hand-authored 50–100 known-good `query→expected_cards` pairs frozen as the ranking regression baseline | ≥50 pairs ratified by operator; pairs cover all four card kinds; pairs include role/phase variation | implementation-lead with operator approval | G6 (gold-set is the recall measurement substrate); PR-C′ / PR-J |
| **G4** | Manual facet cards | 5–10 cards hand-authored as schema proof and as ranking-seed corpus | ≥5 cards across ≥3 of the four kinds (Concept/Frame/Cluster/Phase); each card validates against §1.1–§1.8 invariants under the G5 CLI | implementation-lead, pre-code | G5 (validator needs real cards to test against); G6 (ranking needs a corpus); PR-C′ / PR-J |
| **G5** | `validate_concept_cards` CLI | A CLI tool that enforces §1.1–§1.8 invariants and rejects schema violations and unresolved markers | CI gate green on a representative checkout; rejects every G4 negative-test card; rejects every G2 broken marker; exits 0 on the G4 positive corpus | implementation-lead | PR-C′ / PR-J (no v1 retrieval tools without G5 CI gate); enables the §1.8 `concept-review` label workflow |
| **G6** | Retrieval benchmark (L2 implementation choice) | Per §2.8 — measure candidate L2 implementations against G3 gold-set | Recall ≥90% with p95 query latency ≤200ms; if both BM25-only and SQLite FTS5 satisfy, prefer the lower-cost implementation; if neither satisfies, embeddings move to v2 in-scope | implementation-lead with universal-test-engineer | L2 implementation choice for PR-C′ / PR-J; embedding deferral / un-deferral decision |
| **G7** | Token-budget pack benchmark | Measure that the §2.6 token-pack stage fits role+phase windows without truncating relevant cards | 95% of G3 gold-set queries return without truncating any card whose `signals.score ≥ 0.5`; explicit_omissions correctly populated when truncation occurs | implementation-lead with universal-test-engineer | PR-C′ / PR-J (no v1 query_context without G7 closed) |
| **G8** | Single-machine determinism | Same checkout + same query + same tool version → byte-identical result, repeated invocations | 100 sequential invocations of a representative query set yield byte-identical responses; ranking_pipeline_version matches across invocations | implementation-lead with test-infrastructure-steward | G10 (single-machine determinism is the precondition for cross-machine); PR-C′ / PR-J |
| **G9** | `explain_context_selection` completeness | Every ranked card in every G3 gold-set result traceable to ≥1 signal in the explain trace; zero silent retrievals | 100% of `query_context` results from the G3 gold-set produce a `trace` entry with ≥1 `contributing_signals` entry whose weight > 0 | implementation-lead with universal-test-engineer | PR-C′ / PR-J (no v1 query_context shipping without audit completeness); blocks elevana-studio propagation |
| **G10** | Cross-machine determinism (full) | Same git history + same query + same tool version on three independent machines → byte-identical result | A representative query set executed on three operator-authorised machines yields byte-identical responses across all three; differences trigger root-cause analysis and block release | implementation-lead with operator-named three-machine fleet | elevana-studio propagation; v1 release sign-off |

Gate ordering note: G1, G3, G4 may execute in parallel (analysis only). G2 depends on no prior gate. G5 depends on G2 + G4. G6 depends on G3 + G5. G7 depends on G6. G8 depends on G5. G9 depends on G5 + G7. G10 depends on G8. The implementation PR (PR-C′ / PR-J) MUST present evidence of each gate's PASS_CRITERION being met before merge; bypassing a gate is a hard block per ADR-RFC-ARCH-002 §3.3-style fail-fast semantics adapted to the gate workflow.

## 5. Invariant chain

This ADR is an instantiation of the following invariants from the System Standard and Product North Star:

- **PROD::I1 SESSION_LIFECYCLE_INTEGRITY** — Facet cards are committed governance; their content survives session close. The `Concept::<ID>` marker convention (§1.8) ties source-code claims to durable cards, so session work product does not orphan structural knowledge.
- **PROD::I3 PROVIDER_AGNOSTIC_CONTEXT** — §2.9 explicitly binds all four L3 tools to identical-across-providers behaviour. OCTAVE deterministic parsing is the operational basis.
- **PROD::I4 STRUCTURED_RETURN_SHAPES** — Every tool return shape in §2.2–§2.4 is a structured dictionary with defined fields; §2.10 error envelope mirrors ADR-RFC-ARCH-004 §3.1.1; opaque-blob returns or errors are forbidden.
- **PROD::I5 READ_ONLY_CONTEXT_QUERY** — All four L3 tools are pure reads (§2.1). `get_context` is preserved verbatim (§2.5). L2 cache mutation is excluded from the L3 tool boundary (§3.5). PROD::I5 is the load-bearing invariant for §2.
- **PROD::I6 LEGACY_INDEPENDENCE** — Interpreted as scope-boundary discipline per North Star §4: PR-C does not import or depend on `hestai-mcp`. The L1S Facet ABI lives entirely in this repository's `.hestai/context/` subtree; cross-repo facet-card resolution is explicitly deferred (§8).
- **SYS::I1 CONTEXT_INTEGRITY** — `META.TYPE::FRAME_CARD | CONCEPT_CARD | CLUSTER_CARD | PHASE_CARD` declares governance-class at the artefact level; PR-B §3.2.2 picks this up automatically and routes governance-class fail-fast.
- **SYS::I6 (scope boundary)** — PR-C specifies L1S facet ABI and L3 retrieval contract within hestai-context-mcp. Vault (agent definitions, skills), Workbench (UI, dispatch, payload compiler), DebateHall (deliberation records), and octave-mcp (grammar) lanes are not encroached.
- **SYS::§1 SOURCE_FIDELITY** — The CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME card is amended **in place** (§7.1). No versioned copy of the card is created.

## 6. Verification of this ADR

This ADR is governance specification with no code attached. Verification is review-only:

- **Tier**: TIER_3
- **Facets**: GOVERNANCE, ARCHITECTURE
- **Gate**: CIV + SR per `/review` skill
- **Debate-hall escalation**: discretionary, recommended if reviewers find §2.6 (ranking pipeline), §4 (gate definitions), or the §1.1 four-kind set ambiguous in practice. The Wind/Wall/Door framing is the right venue for ranking-design debates.

Enforcement of the L1S Facet ABI and L3 contract begins on this ADR's merge:

- **By review discipline** until PR-C′ / PR-J and G5 land — PR authors authoring new facet cards by hand follow §1; reviewers verify against §4 (G5) invariants enumerated below.
- **By tool boundary** once PR-F (PR-B §3) lands — `octave_write` rejects facet-card-typed writes outside `.hestai/context/**` via PR-B §3.2.2.
- **By G5 validator CLI** once PR-C′ / PR-J lands — schema invariants and marker resolution enforced mechanically.

## 7. Supersession and compatibility audit

### 7.1 Supersession of `CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME` (in-place STATUS amendment)

The existing PROPOSED frame card at `.hestai/context/concepts/hestai-context-mcp/CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME.oct.md` is **ratified by this ADR**. Supersession is performed by **in-place STATUS amendment** per SYS::§1 SOURCE_FIDELITY ("Modify in-place ONLY; NO versioned copies"):

- `META.STATUS` changes from `proposed` to `ratified`.
- `FACETS.CURRENT_STATUS` is updated to cite this ADR as the ratification record.
- No other content changes. The card's `===EXACT===`, `===FACETS===`, `===EDGES===`, and `===VALIDATION===` sections are preserved verbatim. The G1..G10 gate names enumerated in the card's `===EXACT===.IDS` set are now bound by §4 of this ADR (which fills in PURPOSE / MEASUREMENT / PASS_CRITERION / OWNER / BLOCKS_WHAT for every gate including G2, G7, G8, G9 — which the original card named but did not fully specify).

The frame card remains the orientation surface for cross-machine context retrieval work. Its `WHEN_TO_LOAD` triggers continue to apply. This ADR is the ratification record cited from `FACETS.CURRENT_STATUS`.

### 7.2 Compatibility audit (ADR-RFC-ARCH-001..004)

| ADR | Section | PR-C clause | Compatibility |
|---|---|---|---|
| ADR-RFC-ARCH-001 (PR-α) | §2 placement categories | §1.4 (facet card placement under `committed_context_cards`) | Carries forward verbatim. PR-C does not introduce a new placement category; L1S facet cards land in the existing `committed_context_cards` category. |
| ADR-RFC-ARCH-002 (PR-B) | §1.1 L0–L5 topology | §1.1 (card kinds) + §2 (L3 contract) + §3 (L2 contract) | PR-C ratifies the L1S layer (one row of PR-B's topology table) without altering any other row. L0/L1/L4 are untouched. |
| ADR-RFC-ARCH-002 (PR-B) | §1.5 routing rules | §2.1 (boundary against `lookup_decision`) | Compatible. PR-C tightens the boundary: `lookup_concept` / `query_context` index L1S only; "what did we decide" routes to `lookup_decision`; composite questions joined client-side. PR-C does not modify §1.5; it implements §1.5's intent for the RFC #38 side. |
| ADR-RFC-ARCH-002 (PR-B) | §1.3 authoritativeness | §3.1 (L2 non-authority) | Compatible. PR-C reasserts L2 non-authority from the L3-tool perspective; the source-of-authority statement is PR-B §1.3. |
| ADR-RFC-ARCH-002 (PR-B) | §3 fail-fast contract | §1.4 + §6 (TYPE registration; tool boundary enforcement) | Compatible. Facet-card TYPEs register as governance-class per PR-B §3.2.2 by name (`FRAME_CARD`, `CONCEPT_CARD`, `CLUSTER_CARD`, `PHASE_CARD`); PR-F implementation picks this up automatically without amendment. |
| ADR-RFC-ARCH-003 (PR-E) | ledger schema (L4) | n/a | Adjacent. L4 ledger and L1S facet cards are disjoint artefact classes. PR-C does not modify the ledger. |
| ADR-RFC-ARCH-004 (PR-D) | §1.4 lifecycle vocabulary (PROPOSED/RATIFIED/SUPERSEDED/VOID) | §1.7 (subset: proposed/ratified/superseded) | Compatible. PR-C uses a subset of PR-D's vocabulary (no `VOID`), with explicit rationale (§1.7 rule 5). The casing differs (lowercase here, uppercase in PR-D) because PR-D records are AGRs and PR-C cards are L1S; the validator (G5) and PR-D validator (§4) operate on disjoint corpora, so the casing convention does not collide. |
| ADR-RFC-ARCH-004 (PR-D) | §3.1.1 error envelope | §2.10 | PR-C reuses the same envelope shape, substituting tool names and `contract_ref`. Consumers that handle PR-D errors handle PR-C errors with identical parsing. |
| ADR-RFC-ARCH-004 (PR-D) | L1S–L1 AGR peer relationship | §0 header + §2.1 boundary | PR-C makes the peer relationship explicit: L1S is **peer** to L1 AGR. Neither subordinates the other. The boundary between `lookup_concept` (structural) and `lookup_decision` (temporal) is the operational manifestation. |
| ADR-RFC-ARCH-004 (PR-D) | §9 D1–D6 preflight gates | §4 G1–G10 | Parallel pattern. Both ADRs adopt the same preflight-gate-binds-implementation discipline. The gate sets are disjoint (D-gates govern AGR implementation; G-gates govern L1S/L3 implementation). |

### 7.3 Closure of hestai-mcp issue #87 (Concepts claim Code)

Issue elevanaltd/HestAI-MCP#87 (Concepts claim Code) is **closed** by this ADR's ratification. The original objection — that concepts asserting ownership of code without a validation pathway invites rot — is resolved by:

1. The `Concept::<ID>` marker convention (§1.8) replacing the previous "concepts cite code in prose" pattern.
2. The G2 source-marker rot baseline and G5 validator CLI gate, which convert marker resolution into a CI-enforced invariant.
3. The `concept-review` label workflow (§1.8 rule 4), which forces reviewer attention when source changes might invalidate a marker.

The closure is **reframing**, not denial of the original concern: the original ticket was correct that unsupervised concept-to-code citation is structurally weak. PR-C's reframing is to make the citation explicit (marker + card), validated (G5), and reviewer-supervised (`concept-review` label). hestai-mcp #87 can be closed with disposition `RESOLVED-BY ADR-RFC-ARCH-005 §1.8 + §4 G2 + §4 G5`.

## 8. Out of scope (do not infer from PR-C)

PR-C does **not** define, decide, or constrain:

- **L3 tool code implementation.** Deferred to PR-C′ / PR-J via oa-router to implementation-lead.
- **G5 validator CLI implementation.** Deferred to implementation-lead via oa-router.
- **L2 implementation choice** (SQLite FTS5 vs BM25-only vs both). G6 empirical decision; this ADR declares the criterion only (§2.8 + §4 G6).
- **Embedding adoption.** Deferred unless G6 demonstrates recall <90%; this ADR does not pre-decide embeddings even contingently.
- **L0 canonical content changes.** L0 (DECISIONS.oct.md, North Stars, ADRs) remains UNCHANGED in RFC #38 v1.
- **IPG kernel adoption as default authoring format.** PR-C stays Markdown. The IPG-vs-Markdown question is a separate ADR if it ever happens.
- **Cross-repo facet-card resolution.** LOCAL repo-relative paths only (PE amendment carried forward from PR-α / PR-B). Cross-repo is a future amendment.
- **L0–L5 topology re-debate.** Settled at PR-B; carried forward verbatim.
- **`.hestai-sys/` content changes.** Vault lane.
- **`elevana-studio` `DECISIONS.oct.md` migration.** Separate workstream; G10 cross-machine determinism is a prerequisite, not the migration itself.
- **ADR-RFC-ARCH-004's AGR / `lookup_decision` boundary re-derivation.** Already ratified; §2.1 cites the boundary but does not redraw it.
- **CI gate implementation, MCP-tool fail-fast implementation.** Owned by PR-G and PR-F respectively, per PR-B; PR-C's facet-card TYPEs plug into both by name.
- **Multi-envelope OCTAVE documents.** Single-envelope only in v1 per §1.6; deferred until `octave-mcp` #420 fixes.
- **Agent definitions, skill definitions, standards documents.** Vault lane.
- **UI, dispatch, payload compiler design.** Workbench lane; consumer of the L3 contract via `get_context` (PROD::I5) at KVAEPH Position 3.
- **Deliberation records or debate-hall artefact format.** DebateHall lane.

## 9. Open questions for the operator (non-blocking)

These do not block PR-C ratification. Operator answers may land as MINOR additions (`card_schema_version 1.1`, `1.2`).

1. **Card-kind completeness** — §1.1 ratifies exactly four kinds (Concept, Frame, Cluster, Phase). The ho-liaison consult 2026-05-20 flagged that System Constraints (e.g. `PROD::I5`) and Actors/Agents may warrant distinct exact-match kinds rather than folding into `Concept`. Current draft folds both into `Concept` with reserved prefixes (`PROD_`, `SYS_`) for distinguishability. Should a fifth (or sixth) kind be added in v1? Recommendation: hold at four; promote to additional kinds in MINOR bumps if the reserved-prefix convention proves insufficient.
2. **Phase card semantic risk** — §1.1's "Phase card = definition not state" boundary is explicit but the temptation to drift into temporal claims (esp. when a phase completes and the definition card needs updating) is real. Should the validator (G5) enforce a stronger separation — e.g. reject any `===FACETS===.CURRENT_STATUS` value that contains tokens like "complete", "in progress", "ratified by RD…"? Recommendation: warning-level in v1; promote to error in a MINOR bump if drift is observed.
3. **`Concept::<ID>` marker syntax variants** — §1.8 specifies the comment-prefix form. Some source languages (e.g. SQL, JSON) lack line comments. Should the marker be admissible in adjacent OCTAVE atoms (e.g. `# Concept::<ID>` in a YAML-style front-matter) or in dedicated `.concepts.json` sidecar files? Current draft does not specify; v1 markers are comment-prefix only, and unsupported languages are out of scope until G2 baseline shows demand.
4. **Audience-aware projection seeds** — §1.2 `===AUDIENCE_VIEW_SEEDS===` is optional. Should the validator (G5) require at least the `AGENT` and `REVIEWER` seeds for every card, or remain fully optional? Current draft: optional. Reviewer-side ergonomics may motivate making it required in a MINOR bump.
5. **Edge typology extension** — §1.5 fixes seven edge classes for v1. Should the operator pre-authorise specific extensions (e.g. `DEPRECATES`, `INVALIDATES`, `BLOCKED_BY`) as MINOR-bump candidates, or leave the extension surface fully open? Current draft: leave open; surface extensions case-by-case.

## 10. Supersession

This ADR is **subordinate to**:

- ADR-RFC-ARCH-001 (PR-α placement invariant) — L1S facet card placement derives from PR-α §2 / PR-B §1.2.
- ADR-RFC-ARCH-002 (PR-B IA Contract) — L1S is one row of PR-B's L0–L5 topology; L3 retrieval boundary against `lookup_decision` is bounded by PR-B §1.5.

This ADR is **peer to** ADR-RFC-ARCH-004 (PR-D AGR records). L1S facet cards and L1 AGR records are sibling layers; neither subordinates the other.

This ADR is **adjacent to** ADR-RFC-ARCH-003 (PR-E ledger schema). L4 ledger and L1S facet cards are disjoint artefact classes.

This ADR **ratifies and supersedes in-place** the PROPOSED `CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME` card per §7.1.

This ADR **closes** hestai-mcp issue #87 per §7.3.

A future v2.x L1S Facet ABI ADR would supersede §1 by explicit field-by-field breaking-change list, per §1.7 / §1.2 (CARD_SCHEMA_VERSION bump). A successor ADR that adds a fifth card kind is a MAJOR bump; an ADR that adds optional fields, reserved prefixes, or edge classes is a MINOR bump.
