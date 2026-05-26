===META===
TYPE::PHASE_CARD
REPO_ID::hestai-context-mcp
ID::PHASE_B1_FOUNDATION_DEFINITION
STATUS::proposed
CARD_SCHEMA_VERSION::1
GENERATED_AT_COMMIT::"2909a8b"
SOURCE_HASH::"N/A_for_aggregator"
===END===

===EXACT===
IDS::[PHASE_B1_FOUNDATION_DEFINITION]
PROD_IMMUTABLES::[I1,I3,I4,I5,I6]
ADR_REFS::[ADR_0013]
ISSUE_REFS::[]
TOOL_NAMES::[clock_in,clock_out,get_context,submit_review]
FILE_PATHS::[
  ".hestai/state/portable/pss/{carrier_namespace}/{project_id}/{workspace_id}/{user_id}/artifacts/{artifact_id}.json",
  "src/hestai_context_mcp/storage/"
]
MUST_PRESERVE::[
  "Phase B1 FOUNDATION defines the structural shape of the hestai-context-mcp foundation phase — its constraints, gates, and success criteria",
  "This card describes the STABLE STRUCTURAL DEFINITION of the phase, not its current temporal state (per ADR-RFC-ARCH-005 §1.1)",
  "Temporal state (current activity, completions, RD transitions) lives in PROJECT-CONTEXT.oct.md, git history, and L1 AGRs — NOT in this card",
  "Phase definition is stable across the phase's lifetime; mutations to the definition are governance amendments, not status updates"
]
===END===

===FACETS===
INTENT::"PHASE_B1_FOUNDATION_DEFINITION is the structural definition of the hestai-context-mcp foundation phase. It encodes what constraints govern the phase (provider-agnostic context, read-only get_context, structured return shapes, legacy independence), what artefacts gate progression (the four MCP tools, the storage adapter protocol, the redaction engine), and what success criteria mark phase completion (CI matrix passing, coverage ≥85%, ADR-0013 ratified, PSS portable artefacts implemented). Per ADR-RFC-ARCH-005 §1.1, this card describes the stable structural shape, NOT the current temporal state — whether the phase is active, complete, or under amendment is recorded elsewhere."
CONSTRAINTS::[
  "Phase scope is bounded by PROD I1, I3, I4, I5, I6 — every artefact in scope MUST preserve these invariants",
  "Phase deliverables are the four MCP tools (clock_in, clock_out, get_context, submit_review) plus their supporting storage and redaction infrastructure",
  "Phase MUST NOT introduce runtime dependencies on hestai-mcp (PROD I6 LEGACY_INDEPENDENCE)",
  "Phase MUST preserve the read-only purity of get_context (PROD I5)",
  "Phase MUST land structured return shapes for all four tools (PROD I4)"
]
FAILURE_MODES::[
  "Drift of this card into temporal claims (e.g. 'Phase B1 completed on date X') — violates ADR-RFC-ARCH-005 §1.1 phase-as-definition boundary",
  "Phase-scope creep — adding deliverables outside the foundation surface (clock_in/clock_out/get_context/submit_review + storage + redaction) without a successor phase definition",
  "Coupling to hestai-mcp at runtime — silently re-introduces legacy dependency, violating PROD I6",
  "get_context purity regression — any change that adds side effects to get_context violates PROD I5 and exits phase scope"
]
OPERATIONAL_RULES::[
  "When adding a deliverable, check it against the phase scope (four tools + storage + redaction); deliverables outside scope require a successor phase definition card",
  "Phase completion criteria (CI green, coverage ≥85%, ADR-0013 ratified, PSS B1 implemented) are evaluation gates — phase ends when all are met, not when a calendar date passes",
  "Phase definition mutations follow the §1.7 status lifecycle (proposed → ratified → superseded); status drift is a governance event, not a routine update",
  "Temporal state lookups (is phase active? when did it complete?) MUST route to PROJECT-CONTEXT.oct.md, git history, or L1 AGRs — NEVER to this card"
]
INTEGRATION_POINTS::[
  "PROJECT-CONTEXT.oct.md — temporal state for B1 lives there (PHASE_PSS_B1 COMPLETE 2026-04-29); this card is structural complement",
  "ADR_0013 — the PSS portable-state ADR that ratifies B1's storage substrate; this phase definition cites ADR-0013 as a gating artefact",
  "FOUNDATIONAL — phase B1 establishes the foundational infrastructure; the FOUNDATIONAL cluster names the elevana-studio analog",
  "Successor phase: PHASE_B2_WORKBENCH_INTEGRATION (future card) — successor phase definition for workbench Payload Compiler integration"
]
CURRENT_STATUS::"proposed — authored as part of the G4 facet-card corpus (ADR-RFC-ARCH-005 §4 G4). This card is the Phase-kind reference and substitutes for the strain-prone elevana-studio PHASE_3 candidate (brief §3 and §6 candidate #10), which had a fresh-authorship problem because the source corpus encoded phase ACTIVATION as annotation markers rather than phase DEFINITION. Substitution rationale documented in this directory's README. Awaits ratification once G5 validator CLI lands and CI gate green."
WHEN_TO_LOAD::[
  "hestai-context-mcp foundation phase scope question",
  "phase boundary or deliverable-in-scope question",
  "ADR-RFC-ARCH-005 §1.1 Phase-card example reference",
  "phase definition vs phase state distinction question",
  "successor phase planning (B2 workbench integration)"
]
WHEN_NOT_TO_LOAD::[
  "current phase status (is B1 complete?) — load PROJECT-CONTEXT.oct.md §3 instead",
  "specific tool implementation question (load the relevant ADR or source instead)",
  "PSS storage adapter design (load ADR_0013 instead)"
]
===END===

===EDGES===
EXTENDS::[]
CONSTRAINS::[]
IMPLEMENTED_BY::[]
TESTED_BY::[]
RELATED::[FOUNDATIONAL]
CONFLICTS_WITH::[]
PART_OF_FRAME::[CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME]
===END===

===VALIDATION===
SOURCE_REF_RESOLVES::true
MARKERS_RESOLVE_TO_CARD::N/A
CHANGED_MARKED_FILE_REQUIRES_REVIEW::true
===END===
