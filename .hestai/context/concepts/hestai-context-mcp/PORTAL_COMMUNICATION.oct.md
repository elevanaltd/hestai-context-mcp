===META===
TYPE::CONCEPT_CARD
REPO_ID::hestai-context-mcp
ID::PORTAL_COMMUNICATION
STATUS::proposed
CARD_SCHEMA_VERSION::1
GENERATED_AT_COMMIT::"2909a8b"
SOURCE_HASH::"N/A_pending_G2_baseline"
===END===

===EXACT===
IDS::[PORTAL_COMMUNICATION,PORTAL_OPPORTUNITY_GHL_SYNC,GENIEAI_INTEGRATION_BOUNDARY]
PROD_IMMUTABLES::[]
ADR_REFS::[]
ISSUE_REFS::[]
TOOL_NAMES::[]
FILE_PATHS::[]
MUST_PRESERVE::[
  "The portal communication surface is the authoritative interface for client-facing opportunity state",
  "All cross-system writes to opportunity state MUST flow through the portal interface, never directly to downstream stores",
  "The portal interface is versioned; breaking changes require a new interface version, not a silent shape change",
  "The portal is upstream of GHL, finance, and external integrations — downstream consumers project from portal, not vice versa"
]
===END===

===FACETS===
INTENT::"PORTAL_COMMUNICATION names the contract surface for client-facing opportunity and engagement state in the elevana-studio portal. It is a contract-surface concept — the card encodes the directional invariant (portal upstream, downstream consumers project), the versioning discipline, and the integration-boundary semantics. This card stress-tests the §1.1 four-kind set by encoding interface-definition content; per the G4 analysis brief §3 it documents the CONSTRAINTS-strictness strain (no dedicated CONTRACT section in v1) as a candidate for a future MINOR-bump issue against ADR-RFC-ARCH-005 §1.2."
CONSTRAINTS::[
  "CONTRACT (strain — see card-level note): portal exposes a typed interface over opportunity state; consumers MUST resolve types from the interface, not from the underlying storage",
  "CONTRACT: interface version is part of the surface identity; v1 and v2 coexist during migration windows and are explicit, not implicit",
  "All opportunity-state writes flow into the portal interface; direct writes to finance, GHL, or genieAI stores are FORBIDDEN",
  "Downstream projections (GHL, finance, genieAI) are read-only consumers of the portal interface"
]
FAILURE_MODES::[
  "Bypass write to GHL or finance — fragments opportunity state across stores and silently desynchronises portal",
  "Silent interface shape change — breaks downstream projections without version-bump signal",
  "Coupling consumer code to portal storage internals instead of the interface — locks the portal to a specific storage choice",
  "Inferring opportunity state from downstream projections (e.g. reading GHL as authoritative) — inverts the directional contract"
]
OPERATIONAL_RULES::[
  "CONTRACT (strain): when adding a new opportunity attribute, decide upfront whether it belongs in the portal interface (cross-consumer) or in a downstream-specific projection (consumer-local)",
  "CONTRACT: interface version bumps follow semver — additive fields are MINOR, removals or shape changes are MAJOR and require a coexistence window",
  "Downstream consumers (GHL_RECONCILER, finance, genieAI) MUST reference the interface version they consume",
  "Portal-side mutations are atomic per opportunity; cross-opportunity transactions are out of scope for v1"
]
INTEGRATION_POINTS::[
  "ENGAGEMENT_UMBRELLA — portal opportunities reference the umbrella for cross-sub-project context",
  "GHL_RECONCILER — primary downstream consumer of the portal interface",
  "VIDEO_STATUS_CANONICAL_MODEL — video state is one of the projections served via the portal interface",
  "GENIEAI_INTEGRATION_BOUNDARY — the genieAI surface is a peer consumer; the portal is its upstream"
]
CURRENT_STATUS::"proposed — authored as part of the G4 facet-card corpus (ADR-RFC-ARCH-005 §4 G4). Strain documented: contract-surface content has no dedicated CONTRACT section in v1 schema; interface-definition rules folded into CONSTRAINTS and OPERATIONAL_RULES as a future MINOR-bump candidate (G4 analysis brief §3 + §9). Awaits ratification once G5 validator CLI lands and CI gate green."
WHEN_TO_LOAD::[
  "portal interface design or change question",
  "downstream integration (GHL, finance, genieAI) wiring question",
  "opportunity state authority question",
  "contract-surface authoring (this card is the strain-prone reference for surface cards)"
]
WHEN_NOT_TO_LOAD::[
  "GHL reconciler behaviour question (load GHL_RECONCILER instead)",
  "engagement-vs-project model question (load ENGAGEMENT_UMBRELLA instead)",
  "internal portal storage schema question (out of scope — the interface is the boundary)"
]
===END===

===EDGES===
EXTENDS::[]
CONSTRAINS::[GHL_RECONCILER]
IMPLEMENTED_BY::[]
TESTED_BY::[]
RELATED::[ENGAGEMENT_UMBRELLA,VIDEO_STATUS_CANONICAL_MODEL]
CONFLICTS_WITH::[]
PART_OF_FRAME::[]
===END===

===SOURCE_REFS===
[
  "repo:elevana-studio:.hestai/decisions/DECISIONS.oct.md#HO-PORTAL-COMMUNICATION-20260329"
]
===END===

===VALIDATION===
SOURCE_REF_RESOLVES::true
MARKERS_RESOLVE_TO_CARD::N/A
CHANGED_MARKED_FILE_REQUIRES_REVIEW::false
===END===
