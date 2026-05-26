===META===
TYPE::CLUSTER_CARD
REPO_ID::hestai-context-mcp
ID::FOUNDATIONAL
STATUS::proposed
CARD_SCHEMA_VERSION::1
GENERATED_AT_COMMIT::"2909a8b"
SOURCE_HASH::"N/A_for_aggregator"
===END===

===EXACT===
IDS::[FOUNDATIONAL,MONOREPO_GOVERNANCE,DEPLOYMENT_MODEL,WORKFLOW_FIRST_BUILD_ORDER,SEARCH_PATH_CONVENTION]
PROD_IMMUTABLES::[]
ADR_REFS::[]
ISSUE_REFS::[]
TOOL_NAMES::[]
FILE_PATHS::[]
MUST_PRESERVE::[
  "FOUNDATIONAL bundles the cards that establish the elevana-studio startup environment: monorepo layout, deployment topology, workflow-first build order, and migration immutability",
  "Loading FOUNDATIONAL pulls every concept needed to safely onboard to the repo or to reason about cross-cutting governance",
  "FOUNDATIONAL is a curated bundle — membership is intentional, not a category sweep",
  "Cards in this cluster are pre-requisites for productive work, not optional context"
]
===END===

===FACETS===
INTENT::"FOUNDATIONAL is the curated bundle of governance concepts that establish the elevana-studio startup environment. Loading this cluster pulls monorepo governance, deployment-model invariants, workflow-first build ordering, search-path conventions, and migration immutability as one coherent context window. The bundle is the agent-onboarding surface — every productive task in elevana-studio assumes these invariants hold, and this cluster makes them retrievable in one query."
CONSTRAINTS::[
  "Cluster membership is intentional and reviewed; cards are added only when they meet the 'foundational for productive work' bar",
  "Cluster membership MUST NOT replicate Frame-card orientation — Frames map relationships; Clusters bundle for retrieval",
  "Cluster cards expose member IDs in EXACT.IDS so retrieval surfaces the bundle as one unit",
  "Cluster bundles travel together — partial loading (one cluster member without its siblings) is a signal to load the whole cluster"
]
FAILURE_MODES::[
  "Cluster bloat — adding tangentially related cards dilutes the bundle and degrades retrieval precision",
  "Cluster shadow-overlap with Frame cards — duplicates orientation surface and creates conflicting load-triggers",
  "Stale cluster membership — cards superseded individually but the cluster keeps citing them",
  "Treating cluster membership as a tagging system — collapses the curated-bundle semantic into ad-hoc tagging"
]
OPERATIONAL_RULES::[
  "When onboarding to elevana-studio, load FOUNDATIONAL first; specific work pulls additional cards via Frame orientation",
  "When proposing a new foundational concept, evaluate whether it belongs in the cluster (bundle of pre-requisites) or in a Frame (orientation over relationships)",
  "Cluster maintenance: review membership when any member card transitions to superseded; remove or replace the entry in the same PR",
  "Cluster cards do NOT prescribe how members relate; they only assert that members travel together for retrieval purposes"
]
INTEGRATION_POINTS::[
  "PROD_MIGRATION_IMMUTABILITY — member; the migration-history invariant is foundational",
  "THREE_LAYER_MEDIA_ARCHITECTURE_FRAME — orthogonal Frame card; loading FOUNDATIONAL does not pull the media frame unless the task implicates media",
  "ENGAGEMENT_UMBRELLA — foundational data-model concept; member of this cluster",
  "Future members (MONOREPO_GOVERNANCE, DEPLOYMENT_MODEL, WORKFLOW_FIRST_BUILD_ORDER, SEARCH_PATH_CONVENTION) — to be authored as separate Concept cards in follow-up PRs; this cluster names them in EXACT.IDS as future-link placeholders"
]
CURRENT_STATUS::"proposed — authored as part of the G4 facet-card corpus (ADR-RFC-ARCH-005 §4 G4). Clean fit reference for Cluster cards (curated bundles). Some EXACT.IDS members (MONOREPO_GOVERNANCE, DEPLOYMENT_MODEL, WORKFLOW_FIRST_BUILD_ORDER, SEARCH_PATH_CONVENTION) are future-link placeholders to be authored in follow-up PRs; G5 validator should treat these as proposed-member references, not as resolution targets. Awaits ratification once G5 validator CLI lands and CI gate green."
WHEN_TO_LOAD::[
  "elevana-studio onboarding question",
  "foundational governance question (monorepo, deployment, migration, build order)",
  "'what do I need to know before starting work in elevana-studio?' question",
  "cross-cutting invariant audit"
]
WHEN_NOT_TO_LOAD::[
  "specific media-pipeline question (load THREE_LAYER_MEDIA_ARCHITECTURE_FRAME instead)",
  "specific data-model question (load ENGAGEMENT_UMBRELLA or VIDEO_STATUS_CANONICAL_MODEL instead)",
  "GHL or portal integration question (load GHL_RECONCILER or PORTAL_COMMUNICATION instead)"
]
===END===

===EDGES===
EXTENDS::[]
CONSTRAINS::[]
IMPLEMENTED_BY::[]
TESTED_BY::[]
RELATED::[PROD_MIGRATION_IMMUTABILITY,ENGAGEMENT_UMBRELLA,THREE_LAYER_MEDIA_ARCHITECTURE_FRAME]
CONFLICTS_WITH::[]
PART_OF_FRAME::[]
===END===

===SOURCE_REFS===
[
  "repo:elevana-studio:.hestai/decisions/DECISIONS.oct.md#HO-MONOREPO-GOVERNANCE-20251107",
  "repo:elevana-studio:.hestai/decisions/DECISIONS.oct.md#HO-DEPLOYMENT-MODEL-20251107"
]
===END===

===VALIDATION===
SOURCE_REF_RESOLVES::true
MARKERS_RESOLVE_TO_CARD::N/A
CHANGED_MARKED_FILE_REQUIRES_REVIEW::false
===END===
