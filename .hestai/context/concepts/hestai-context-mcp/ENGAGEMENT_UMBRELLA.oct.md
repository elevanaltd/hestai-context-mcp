===META===
TYPE::CONCEPT_CARD
REPO_ID::hestai-context-mcp
ID::ENGAGEMENT_UMBRELLA
STATUS::proposed
CARD_SCHEMA_VERSION::1
GENERATED_AT_COMMIT::"2909a8b"
SOURCE_HASH::"N/A_pending_G2_baseline"
===END===

===EXACT===
IDS::[ENGAGEMENT_UMBRELLA,PROJECT_DISAMBIGUATION_SCHEME,CLIENT_DATA_CANONICAL_MODEL]
PROD_IMMUTABLES::[I4]
ADR_REFS::[]
ISSUE_REFS::[]
TOOL_NAMES::[]
FILE_PATHS::[]
MUST_PRESERVE::[
  "An ENGAGEMENT is the umbrella record under which one or more sub-projects (videos, deliverables, opportunities) hang",
  "Disambiguation between umbrella engagement and sub-project is required at every consumer surface",
  "Sub-project lifecycle progression does NOT mutate the umbrella engagement's identity",
  "The umbrella is the durable client-relationship anchor; sub-projects are the unit of execution"
]
===END===

===FACETS===
INTENT::"ENGAGEMENT_UMBRELLA names the parent data-lifecycle concept under which one or more sub-projects (videos, deliverables, opportunities) hang in the elevana-studio client-data model. It is the durable client-relationship anchor that survives sub-project completion and supplies the disambiguation primitive for portal, finance, and GHL reconciliation surfaces. This concept card encodes the umbrella-vs-sub-project distinction as a structural invariant of the client data canonical model."
CONSTRAINTS::[
  "Every sub-project (video, opportunity, deliverable) MUST resolve to exactly one parent ENGAGEMENT_UMBRELLA",
  "ENGAGEMENT_UMBRELLA identity is stable across sub-project lifecycle transitions",
  "Disambiguation MUST occur at the consumer surface (portal, finance, GHL sync) — the umbrella record itself is not lifecycle-bearing",
  "Cross-system identity propagation (portal opportunity id, GHL contact id, finance client id) hangs off the umbrella, not the sub-project"
]
FAILURE_MODES::[
  "Collapsing umbrella and sub-project into a single record — destroys multi-sub-project relationships and breaks finance roll-ups",
  "Lifecycle-state on the umbrella — causes umbrella churn when sub-projects transition, breaks downstream identity references",
  "Sub-project parent-link drift — orphans sub-projects from finance/portal joins, silently fragments client view",
  "Consumer surfaces inferring parent-child from naming heuristics instead of the umbrella primary key"
]
OPERATIONAL_RULES::[
  "When modelling a new client artefact, ask: 'is this a sub-project or an umbrella attribute?' — default to sub-project unless the artefact is shared across all current and future sub-projects for the client",
  "Portal, finance, and GHL integrations resolve identity via the umbrella primary key, then walk to active sub-projects",
  "Sub-project deletion or completion MUST NOT cascade to umbrella deletion",
  "Multi-sub-project umbrellas are the common case, not an exception — model accordingly"
]
INTEGRATION_POINTS::[
  "CLIENT_DATA_CANONICAL_MODEL — the umbrella is the root of the canonical client view",
  "PORTAL_COMMUNICATION — portal opportunity records reference the umbrella for cross-sub-project context",
  "GHL_RECONCILER — reconciliation runs at umbrella granularity, then iterates sub-projects",
  "FINANCE_ITEMS_SCHEMA — finance roll-ups aggregate at the umbrella level for client-wise reporting"
]
CURRENT_STATUS::"proposed — authored as part of the G4 facet-card corpus (ADR-RFC-ARCH-005 §4 G4). Awaits ratification once G5 validator CLI lands and CI gate green."
WHEN_TO_LOAD::[
  "elevana-studio client data model question",
  "engagement-vs-project disambiguation question",
  "portal opportunity or sub-project identity-resolution question",
  "finance roll-up scope question (per-client vs per-sub-project)",
  "GHL reconciliation scope question"
]
WHEN_NOT_TO_LOAD::[
  "video lifecycle state question (load VIDEO_STATUS_CANONICAL_MODEL instead)",
  "portal interface contract question (load PORTAL_COMMUNICATION instead)",
  "GHL reconciler behaviour question (load GHL_RECONCILER instead)"
]
===END===

===EDGES===
EXTENDS::[]
CONSTRAINS::[]
IMPLEMENTED_BY::[]
TESTED_BY::[]
RELATED::[VIDEO_STATUS_CANONICAL_MODEL,PORTAL_COMMUNICATION,GHL_RECONCILER]
CONFLICTS_WITH::[]
PART_OF_FRAME::[]
===END===

===SOURCE_REFS===
[
  "repo:elevana-studio:.hestai/decisions/DECISIONS.oct.md#HO-ENGAGEMENT-UMBRELLA-20260429",
  "repo:elevana-studio:.hestai/decisions/DECISIONS.oct.md#HO-PROJECT-DISAMBIGUATION-SCHEME-20260501"
]
===END===

===VALIDATION===
SOURCE_REF_RESOLVES::true
MARKERS_RESOLVE_TO_CARD::N/A
CHANGED_MARKED_FILE_REQUIRES_REVIEW::false
===END===
