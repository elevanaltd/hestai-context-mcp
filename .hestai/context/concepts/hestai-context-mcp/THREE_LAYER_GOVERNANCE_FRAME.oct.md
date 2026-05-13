===META===
TYPE::FRAME_CARD
REPO_ID::hestai-context-mcp
ID::THREE_LAYER_GOVERNANCE_FRAME
STATUS::proposed
CARD_SCHEMA_VERSION::1
GENERATED_AT_COMMIT::"N/A_operator_authored"
SOURCE_HASH::"N/A_for_aggregator"
===END===

===EXACT===
IDS::[THREE_LAYER_GOVERNANCE_FRAME,L0_HUMAN_ADR,L1_AGENT_GOVERNANCE_RECORD,L1S_FACET_ABI,L2_PER_MACHINE_CACHE,ADR_GOVERNANCE_LAYER,RFC_40_DECISION_RECORDS,RFC_38_FACET_ABI]
PROD_IMMUTABLES::[I3,I4,I5]
ADR_REFS::[ADR-0013]
ISSUE_REFS::[33,38,40]
LAYER_OWNERS::[
  "L0: docs/adr/ — human-authored, per-repo, unchanged by any current RFC",
  "L1: .hestai/decisions/<token>.oct.md — agent-readable governance records (RFC #40)",
  "L1S: .hestai/context/concepts/<repo_id>/ — facet ABI cards (RFC #38)",
  "L2: gitignored per-machine cache — content-hash keyed, never authoritative"
]
MUST_PRESERVE::[
  "Each layer has exactly one owner — mixing ownership breaks coherence",
  "L0 human ADRs are human-authored and unchanged by RFC #38 or RFC #40",
  "L1 records MUST be syntactic superset of elevana-studio HO-token convention",
  "L1 records: HUMAN_ADR_REF field is OPTIONAL",
  "L1S facet cards COMMITTED to git, reviewed via PR — not derived per machine",
  "L2 cache NEVER authoritative — content-hash invalidated, NEVER mtime",
  "ADR-0013 PSS is SUBSTRATE only — never the canonical governance registry",
  "raw .hestai/state/ is LOCAL_MUTABLE — never invert to authoritative",
  "projections from PSS are DERIVED_PROJECTION — not source of truth",
  "PSS proposals are PORTABLE_MEMORY — not governance records",
  "Adoption of this architecture is opt-in; non-adopters fully supported indefinitely"
]
===END===

===SOURCE_REFS===
[
  "https://github.com/elevanaltd/hestai-context-mcp/issues/40 (RFC #40 — agent-readable governance records)",
  "https://github.com/elevanaltd/hestai-context-mcp/issues/38 (RFC #38 — facet ABI cards)",
  "https://github.com/elevanaltd/hestai-context-mcp/issues/33 (option space, superseded)",
  "docs/adr/ADR-0013.md (PSS substrate ruling)",
  "operator-attached governance synthesis: multi-agent disentanglement analyses 2026-05-13 (not yet committed)"
]
===END===

===FACETS===
INTENT::"Codify the three-peer-layer governance architecture so agents never conflate ownership. L0 human ADRs carry rationale + alternatives + consequences for humans. L1 atomic OCTAVE decision records carry agent-readable governance. L1S facet ABI cards carry projected concept knowledge for retrieval. L2 cache accelerates reads only. Binding ruling from cross-debate convergent verdict 2026-05-13: ADR-0013 PSS is substrate only."
LAYER_DEFINITIONS:
  L0:
    LABEL::"Human ADRs"
    PATH_PATTERN::"docs/adr/ (per-repo)"
    OWNER::"human authors"
    CONTENT::"architectural rationale, alternatives, consequences"
    MUTATION_RULE::"unchanged by any current RFC"
    AUTHORITATIVE::true
  L1:
    LABEL::"Agent-Readable Governance Records"
    RFC::"RFC #40 (issue #40)"
    PATH_PATTERN::".hestai/decisions/<token>.oct.md"
    OWNER::"hestai-context-mcp repo"
    SCHEMA_CONSTRAINT::"syntactic superset of elevana-studio HO-token convention"
    HUMAN_ADR_REF::"OPTIONAL"
    AUTHORITATIVE::true
  L1S:
    LABEL::"Facet ABI Cards"
    RFC::"RFC #38 (issue #38)"
    PATH_PATTERN::".hestai/context/concepts/<repo_id>/"
    CARD_TYPES::[CONCEPT_CARD,FRAME_CARD,CLUSTER_CARD,PHASE_CARD]
    OWNER::"hestai-context-mcp repo"
    COMMITTED::true
    REVIEW_GATE::"PR review required"
    AUTHORITATIVE::true
  L2:
    LABEL::"Per-Machine Cache"
    PATH_PATTERN::".hestai/state/cache/ (gitignored)"
    OWNER::"local machine"
    INVALIDATION::"content-hash keyed — NEVER mtime"
    AUTHORITATIVE::false
    CLASSIFICATION::DERIVED_PROJECTION
BINDING_RULING::"ADR-0013 PSS is SUBSTRATE only. Classify: raw .hestai/state/ → LOCAL_MUTABLE; PSS projections → DERIVED_PROJECTION; PSS proposals → PORTABLE_MEMORY. Never invert these classifications to authoritative governance status."
CONSTRAINTS::[
  "Each layer has one owner — do not mix authorship across layers",
  "L1 records at .hestai/decisions/ are owned here, NOT at PSS or any other substrate",
  "L1S facet cards are committed governance artifacts, NOT derived cache",
  "L2 cache MUST NOT be treated as source of truth for any governance query",
  "ADR-0013 PSS substrate scope is binding — violating this breaks coherence",
  "Non-adopters of this architecture are fully supported indefinitely (opt-in adoption)"
]
FAILURE_MODES::[
  "Treating PSS portable artifacts as L1 governance records — inverts LOCAL_MUTABLE to authoritative",
  "Writing L1S facet cards as per-machine derived cache — removes review gate, enables silent drift",
  "Conflating L0 ADR rationale with L1 atomic decision records — different owners, different purposes",
  "Using mtime for L2 cache invalidation — false positives, integration hazard with PSS local mutation",
  "Assuming adoption is mandatory — non-adopters must remain fully supported"
]
OPERATIONAL_RULES::[
  "When authoring a governance record, determine layer first (L0 vs L1 vs L1S) before writing",
  "L1 records: validate schema is syntactic superset of elevana-studio HO-token convention before commit",
  "L1S cards: always route through PR review — octave_write alone does not constitute committed governance",
  "Any query about PSS scope: consult ADR-0013 binding ruling first",
  "Cross-repo interop: L1 HO-token superset requirement ensures elevana-studio compatibility without forking"
]
INTEGRATION_POINTS::[
  "Extends CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME (RFC #38) — adds L0 and binding PSS ruling to four-layer picture",
  "Governs scope of ADR-0013 PSS — PSS is substrate for L2 acceleration, never L1 canonical registry",
  "RFC #40 defines L1 record schema — this frame defines where L1 sits in the ownership hierarchy",
  "RFC #38 defines L1S facet ABI — this frame defines where L1S sits and that it is committed not derived"
]
CURRENT_STATUS::"PROPOSED — binding frame codified from cross-debate convergent verdict 2026-05-13. Operator-attached governance synthesis not yet committed. Supersedes any prior framing that placed PSS as canonical governance registry."
WHEN_TO_LOAD::[
  "question about which governance layer owns a record",
  "confusion between L0 ADR vs L1 decision record vs L1S facet card",
  "ADR-0013 PSS scope question (substrate vs registry)",
  "RFC #40 or RFC #38 authoring work",
  "cross-repo governance interop with elevana-studio",
  "any agent attempting to write governance records to PSS state",
  "disentanglement of LOCAL_MUTABLE vs DERIVED_PROJECTION vs PORTABLE_MEMORY"
]
WHEN_NOT_TO_LOAD::[
  "concrete PSS implementation details (clock_in, clock_out) — load B1_PSS_FOUNDATION",
  "context retrieval tool design (lookup_concept, query_context) — load CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME",
  "specific ADR-0013 risk gates (RISK_001..010) — load ADR_0013 card"
]
===END===

===AUDIENCE_VIEW_SEEDS===
GLOBAL::"FRAME_CARD for three-peer-layer governance architecture. L0 human ADRs (docs/adr/), L1 agent governance records (RFC #40, .hestai/decisions/), L1S facet ABI cards (RFC #38, .hestai/context/concepts/), L2 per-machine cache. Binding ruling 2026-05-13: ADR-0013 PSS is substrate only — never canonical registry."
AGENT::"Three layers, three owners. Never mix. L0=human ADRs at docs/adr/ (unchanged by RFC). L1=atomic OCTAVE decision records at .hestai/decisions/ (RFC #40, superset of HO-token convention, owned here). L1S=committed facet ABI cards at .hestai/context/concepts/ (RFC #38, PR-reviewed, owned here). L2=gitignored per-machine cache (content-hash keyed, never authoritative). PSS scope: LOCAL_MUTABLE∨DERIVED_PROJECTION∨PORTABLE_MEMORY — never invert to authoritative. Adoption opt-in."
REVIEWER::"Risk gates: (a) L1 records MUST be syntactic superset of elevana-studio HO-token convention; (b) L1S cards MUST be committed to git with PR review — not derived; (c) PSS MUST NOT be treated as canonical governance registry (ADR-0013 substrate ruling is binding); (d) L2 cache MUST use content-hash invalidation only; (e) non-adopters must remain fully supported. Any PR writing governance records to PSS state is a coherence violation."
ONBOARDING::"HestAI governance has three peer layers. Human ADRs live in docs/adr/ and are written by humans. Agent-readable decision records live at .hestai/decisions/ (being defined in RFC #40). Facet ABI concept cards live at .hestai/context/concepts/ (RFC #38). A per-machine cache in .hestai/state/cache/ is optional and never authoritative. The PSS (ADR-0013) is infrastructure for the cache layer only."
===END===

===EDGES===
EXTENDS::[CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME]
CONSTRAINS::[ADR_0013]
IMPLEMENTED_BY::[]
TESTED_BY::[]
RELATED::[ADR_0013,B1_PSS_FOUNDATION]
CONFLICTS_WITH::[]
PART_OF_FRAME::[]
===END===

===PROVENANCE===
MARKERS::[]
BINDING_VERDICT_DATE::"2026-05-13"
BINDING_VERDICT_SOURCE::"cross-debate convergent verdict — operator-attached governance synthesis (not yet committed)"
===END===

===VALIDATION===
SOURCE_REF_RESOLVES::false
MARKERS_RESOLVE_TO_CARD::N/A
CHANGED_MARKED_FILE_REQUIRES_REVIEW::true
===END===
