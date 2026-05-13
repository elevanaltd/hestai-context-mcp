===META===
TYPE::FRAME_CARD
REPO_ID::hestai-context-mcp
ID::CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME
STATUS::proposed
CARD_SCHEMA_VERSION::1
GENERATED_AT_COMMIT::"3c547af"
SOURCE_HASH::"N/A_for_aggregator"
===END===

===EXACT===
IDS::[CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME,L1_CANONICAL,L1S_FACET_ABI,L2_OPTIONAL_ACCELERATION,L3_PURE_RETRIEVAL,CONCEPT_CARD,FRAME_CARD,CLUSTER_CARD,PHASE_CARD,DDSG,FACET_ABI,G1,G2,G3,G4,G5,G6,G7,G8,G9,G10]
PROD_IMMUTABLES::[I1,I3,I4,I5,I6]
ADR_REFS::[ADR-0013,ADR-0060]
ISSUE_REFS::[33,38,87]
TOOL_NAMES::[lookup_concept,query_context,explain_context_selection,octave_write]
FILE_PATHS::[
  ".hestai/context/concepts/{repo_id}/{concept_id}.oct.md (L1S path pattern)",
  ".hestai/state/cache/context-index/ (L2 optional cache, gitignored)"
]
MUST_PRESERVE::[
  "L1 canonical git unchanged — DECISIONS.oct.md, North Stars, ADRs, workflow stay where they are",
  "L1S facet ABI cards COMMITTED to git, reviewed via PR (not derived per machine)",
  "L2 cache content-hash keyed (NEVER mtime); never built during query; never authoritative",
  "L3 tools are PURE — no LLM at query time, no writes, no cache mutation, no session creation",
  "get_context purity preserved — new tools are additive (lookup_concept, query_context, explain_context_selection)",
  "Embeddings DEFERRED from v1; add only if gold-set recall <90% (G6 gate)",
  "Concept markers (Concept::<ID>) in source are CI-validated claims; rot triggers gate failure",
  "Author never has to know OCTAVE — freeform prose -> octave_secretary compile -> canonical + facet card",
  "Same git checkout + same query + same tool version -> deterministic identical result"
]
===END===

===SOURCE_REFS===
[
  "https://github.com/elevanaltd/hestai-context-mcp/issues/38#RFC_full_doc",
  "https://github.com/elevanaltd/hestai-context-mcp/issues/33#option_space_superseded",
  "https://github.com/elevanaltd/HestAI-MCP/issues/87#concepts_claim_code_revival",
  "Debate thread: 2026-05-08-cross-machine-context-retrieval-standard-r2",
  "Debate thread: 2026-05-08-cross-machine-context-retrieval-premium"
]
===END===

===FACETS===
INTENT::"Resolve four coupled problems (context-file token weight; cross-machine sync conflicts; whole-document reads; bigger-picture loss) with a four-layer architecture: git-canonical L1 unchanged; committed facet ABI L1S as the structured retrieval substrate; optional per-machine L2 acceleration; pure deterministic L3 retrieval tools. Cross-machine sync becomes moot via git distribution + local determinism."
CONSTRAINTS::[
  "L1 canonical (DECISIONS, North Stars, ADRs) MUST remain unchanged in v1",
  "L1S facet cards MUST be committed to git, reviewed via PR (HestAI I3 Human Primacy + I4 Discoverable Persistence)",
  "L2 cache MUST be content-hash invalidated, NEVER mtime, NEVER authoritative",
  "L3 query tools MUST be pure (no LLM at runtime; no writes; no cache mutation; no session creation)",
  "get_context signature and purity MUST be preserved (PROD I5 + RISK_003 OPTION_C)",
  "v1 ranking: exact ID -> Concept marker path -> file glob -> BM25 over cards -> edge expansion -> token pack",
  "Embeddings MUST be deferred unless G6 gold-set recall <90%",
  "Pre-flight gates G1..G10 MUST execute before any v1 code is written",
  "Solution lands here first, battle-tested, THEN propagates to elevana-studio"
]
FAILURE_MODES::[
  "Read-time LLM compression -> per-machine divergence + I5 purity violation",
  "Facet cards as derived cache (premium-tier proposal) -> no review gate, silent drift across model versions",
  "mtime-based cache invalidation -> false positives + integration with PSS local mutation",
  "Embeddings adopted before G6 measurement -> infrastructure cost without proven recall benefit",
  "PROJECT-CONTEXT.oct.md continues mixing semantic facts + session ephemera -> divergence problem persists (G1 must promote semantic facts to git)",
  "Concept markers without CI validation -> rot reintroduces #87 closure rationale",
  "Skipping G3 gold-set -> no measurable proof that retrieval improved over baseline get_context blob"
]
OPERATIONAL_RULES::[
  "Pre-code: execute G1 (divergence audit), G3 (gold set), G4 (manual cards) in parallel — analysis only",
  "Post-G1+G3+G4: draft an ADR for the architecture, gate via TMG/CRS/CE/CIV chain (same pattern as ADR-0013)",
  "v1 build: validate_concept_cards CLI BEFORE retrieval tools (G5 dependency order)",
  "v1 build: lookup_concept BEFORE query_context (simple before composite)",
  "Source markers: Concept::<ID> resolves via CI to existing card; changed marked file requires concept-review label",
  "Audience-aware projection: select facets by role + phase; pack exact fields and source_refs before narrative seeds; emit explicit omissions when budget excludes relevant cards"
]
INTEGRATION_POINTS::[
  "Supersedes issue #33 option-space exploration on architecture; #33 stays open for closure tracking",
  "Extends elevana-studio HO_MULTI_MACHINE_COORDINATION_20260429 — same principle (read model unchanged + structured layer for write/retrieval) plus L1S facet ABI",
  "Revives + reframes HestAI-MCP issue #87 (Concepts claim Code) — markers become validated provenance, not citation comments",
  "Orthogonal to ADR-0013 PSS — facet cards live in git, not PSS portable artifacts",
  "Does not modify get_context (CE OPTION_C purity preserved)",
  "Does not require PSS remote adapter (issue #15 follow-up #1) — git is the distribution mechanism"
]
CURRENT_STATUS::"PROPOSED via RFC #38 (operator-ratified architectural direction 2026-05-08). Pre-flight gates G1+G3+G4 in execution. NOT yet authorised for code. After gates land cleanly: draft architecture ADR, gate via TMG/CRS/CE/CIV, then v1 build."
WHEN_TO_LOAD::[
  "context retrieval architecture question",
  "facet ABI or concept card design",
  "cross-machine governance sync question",
  "L1S layer or schema question",
  "LLM context window or token weight problem in agent corpus",
  "DECISIONS.oct.md scaling question",
  "RFC #38 work or pre-flight gate execution",
  "ANY query touching this architecture should reserve orientation budget for THIS frame card"
]
WHEN_NOT_TO_LOAD::[
  "concrete PSS implementation (clock_in, clock_out, storage/*) — load B1_PSS_FOUNDATION",
  "specific binding ruling lookup (RISK_001..010) — load ADR_0013",
  "single-purity question on get_context — load PROD_I5"
]
===END===

===AUDIENCE_VIEW_SEEDS===
GLOBAL::"FRAME_CARD for RFC #38 — the four-layer architecture (L1 canonical git / L1S committed facet ABI / L2 optional per-machine acceleration / L3 pure retrieval tools) that resolves cross-machine context retrieval without remote sync. Operator-ratified 2026-05-08 via dual-tier debate-hall synthesis."
AGENT::"This is the orientation frame for cross-machine context retrieval work. Four problems (token weight, sync conflicts, whole-doc reads, fragmentation) resolve to one architecture: facet cards committed to git as L1S; per-machine cache as L2 acceleration only; pure read-only retrieval tools as L3. Concept markers in source code provide provenance. Embeddings deferred. No new meta-guru agent (capability dissolves into query_context). Solution lands here first, propagates to elevana-studio after battle-testing. Pre-flight gates G1..G10 must complete before code. CURRENT STATUS: G1, G3, G4 in execution as of 2026-05-08."
REVIEWER::"Risk gates for any work touching this architecture: (a) L1 canonical MUST remain unchanged in v1; (b) facet cards MUST be committed governance, not derived cache (HestAI I3 + I4); (c) L3 tools MUST be pure — no LLM at runtime, no writes, no cache mutation; (d) get_context purity preserved (PROD I5 unchanged); (e) embeddings deferred unless G6 fails recall; (f) cross-machine determinism MUST be empirically proven via G10. Pre-flight gates G1..G10 are non-negotiable before any code merges."
ONBOARDING::"RFC #38 proposes a structured way for agents to retrieve only the context relevant to their current task, instead of reading entire DECISIONS.oct.md and PROJECT-CONTEXT.oct.md files. Architecture is approved; we are gathering empirical evidence (gates G1..G10) before building. Read the RFC at https://github.com/elevanaltd/hestai-context-mcp/issues/38 for the full picture."
===END===

===EDGES===
EXTENDS::[HO_MULTI_MACHINE_COORDINATION_20260429]
CONSTRAINS::[]
IMPLEMENTED_BY::[]
TESTED_BY::[]
RELATED::[ADR_0013,PROD_I5,B1_PSS_FOUNDATION,HO_MULTI_MACHINE_COORDINATION_20260429]
CONFLICTS_WITH::[]
PART_OF_FRAME::[]
===END===

===PROVENANCE===
MARKERS::[]
===END===

===VALIDATION===
SOURCE_REF_RESOLVES::true
MARKERS_RESOLVE_TO_CARD::N/A
CHANGED_MARKED_FILE_REQUIRES_REVIEW::true
===END===
