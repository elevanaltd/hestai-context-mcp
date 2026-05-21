===META===
TYPE::CONCEPT_CARD
REPO_ID::hestai-context-mcp
ID::VIDEO_STATUS_CANONICAL_MODEL
STATUS::proposed
CARD_SCHEMA_VERSION::1
GENERATED_AT_COMMIT::"2909a8b"
SOURCE_HASH::"N/A_pending_G2_baseline"
===END===

===EXACT===
IDS::[VIDEO_STATUS_CANONICAL_MODEL]
PROD_IMMUTABLES::[]
ADR_REFS::[]
ISSUE_REFS::[]
TOOL_NAMES::[]
FILE_PATHS::[]
MUST_PRESERVE::[
  "Video status progresses through a canonical S0..D1 lifecycle; ad-hoc status strings are FORBIDDEN",
  "Status transitions are uni-directional within the lifecycle; backward transitions require an explicit rework status, not a silent revert",
  "Every video status value is enumerated; consumers MUST treat unknown values as a schema-violation error, not as 'unknown'",
  "The canonical model is the single source of truth for cross-system status reporting (portal, finance, GHL projection)"
]
===END===

===FACETS===
INTENT::"VIDEO_STATUS_CANONICAL_MODEL names the enumerated S0..D1 lifecycle that governs video status across the elevana-studio production pipeline. It is a data-model concept — the card encodes the canonical status set, the directional transition semantics, and the cross-system reporting contract. This is a clean-fit card in the §1.1 schema and serves as a positive-case reference alongside the strain-prone GHL_RECONCILER and PORTAL_COMMUNICATION cards."
CONSTRAINTS::[
  "Status values MUST come from the canonical enumeration; new statuses require an amendment to the canonical model, not a local extension",
  "Forward transitions follow the S0→…→D1 sequence; backward transitions are modelled as rework statuses with explicit names",
  "Status is video-scoped, not engagement-scoped — videos within the same ENGAGEMENT_UMBRELLA progress independently",
  "Cross-system status projection (portal display, finance milestone trigger, GHL stage mapping) MUST resolve via the canonical model, not via direct storage read"
]
FAILURE_MODES::[
  "Free-text status fields — destroys enumeration discipline and breaks downstream projection",
  "Silent backward transition without rework status — corrupts the lifecycle audit trail",
  "Local status extension in a consumer (e.g. portal adding 'archived' without canonical-model amendment) — fragments the cross-system view",
  "Engagement-scoped status inference — collapses independent video progress into umbrella-level state"
]
OPERATIONAL_RULES::[
  "When proposing a new video status, write an amendment to the canonical model FIRST; downstream consumers update second",
  "Status display in the portal UI MUST use the canonical name; localised labels are display-only and resolve to the canonical name",
  "Finance milestone triggers MUST reference canonical status values; renaming a canonical status is a versioned change",
  "Reporting queries MUST treat unknown status values as schema-violation errors and surface them, not silently bucket as 'other'"
]
INTEGRATION_POINTS::[
  "PORTAL_COMMUNICATION — the canonical model is exposed via the portal interface for client-facing status display",
  "ENGAGEMENT_UMBRELLA — videos are sub-projects under the umbrella; status is sub-project state, not umbrella state",
  "GHL_RECONCILER — projects canonical status into GHL stage values per the directional contract"
]
CURRENT_STATUS::"proposed — authored as part of the G4 facet-card corpus (ADR-RFC-ARCH-005 §4 G4). Clean fit reference for data-model concept cards. Awaits ratification once G5 validator CLI lands and CI gate green."
WHEN_TO_LOAD::[
  "video status question",
  "production pipeline lifecycle question",
  "S0..D1 status semantics or transition question",
  "cross-system status reporting question"
]
WHEN_NOT_TO_LOAD::[
  "engagement-vs-project model question (load ENGAGEMENT_UMBRELLA instead)",
  "portal interface design (load PORTAL_COMMUNICATION instead)",
  "media-pipeline vendor architecture (load THREE_LAYER_MEDIA_ARCHITECTURE_FRAME instead)"
]
===END===

===EDGES===
EXTENDS::[]
CONSTRAINS::[]
IMPLEMENTED_BY::[]
TESTED_BY::[]
RELATED::[ENGAGEMENT_UMBRELLA,PORTAL_COMMUNICATION]
CONFLICTS_WITH::[]
PART_OF_FRAME::[]
===END===

===SOURCE_REFS===
[
  "repo:elevana-studio:.hestai/decisions/DECISIONS.oct.md#HO-VIDEO-STATUS-CANONICAL-MODEL-AMENDED-20260501"
]
===END===

===VALIDATION===
SOURCE_REF_RESOLVES::true
MARKERS_RESOLVE_TO_CARD::N/A
CHANGED_MARKED_FILE_REQUIRES_REVIEW::false
===END===
