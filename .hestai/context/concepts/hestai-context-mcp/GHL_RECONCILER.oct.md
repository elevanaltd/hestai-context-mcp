===META===
TYPE::CONCEPT_CARD
REPO_ID::hestai-context-mcp
ID::GHL_RECONCILER
STATUS::proposed
CARD_SCHEMA_VERSION::1
GENERATED_AT_COMMIT::"2909a8b"
SOURCE_HASH::"N/A_pending_G2_baseline"
===END===

===EXACT===
IDS::[GHL_RECONCILER,PORTAL_OPPORTUNITY_GHL_SYNC]
PROD_IMMUTABLES::[]
ADR_REFS::[]
ISSUE_REFS::[]
TOOL_NAMES::[]
FILE_PATHS::[]
MUST_PRESERVE::[
  "The GHL reconciler is the authoritative consumer of portal opportunity state for GHL sync; portal is upstream, GHL is downstream",
  "Reconciliation runs on a polling cadence; portal mutations are NOT pushed to GHL in real-time",
  "Reconciliation is idempotent — re-running against unchanged inputs produces no GHL writes",
  "GHL state divergence from portal is a reconciler concern, not a portal concern — portal does not adapt to GHL drift"
]
===END===

===FACETS===
INTENT::"GHL_RECONCILER names the subsystem boundary that consumes elevana-studio portal opportunity state and projects it into GoHighLevel (GHL) CRM. It is an actor concept — the card encodes the reconciler's polling cadence, idempotence guarantee, and directional contract (portal upstream, GHL downstream). This card stress-tests the §1.1 four-kind set by encoding actor/behaviour content; per the G4 analysis brief §3 it documents the OPERATIONAL_RULES strain (no dedicated BEHAVIOR section in v1) as a candidate for a future MINOR-bump issue against ADR-RFC-ARCH-005 §1.2."
CONSTRAINTS::[
  "Portal is the source of truth; GHL is a projection target — reconciler MUST NOT write back to portal",
  "Polling cadence is configurable; real-time push is explicitly out of scope for v1",
  "Idempotence is a contract: same portal state on two consecutive runs MUST produce zero GHL writes",
  "Reconciliation failures MUST be retryable without compensating writes (i.e. partial GHL state from a failed run MUST converge on retry)"
]
FAILURE_MODES::[
  "GHL→portal write — inverts the directional contract and corrupts the source of truth",
  "Non-idempotent reconciliation — duplicates GHL records on retry; pollutes GHL audit trail",
  "Real-time push attempted as 'optimisation' — breaks the cadence contract and surfaces race conditions against portal mutations",
  "Reconciler treating GHL drift as authoritative — silently overwrites portal corrections during reconciliation"
]
OPERATIONAL_RULES::[
  "BEHAVIOUR (strain — see card-level note): the reconciler polls portal at a configured interval; for each ENGAGEMENT_UMBRELLA with pending changes, it computes a diff against last-known GHL state and emits the minimum write set",
  "BEHAVIOUR: on transient GHL API failure, the reconciler retries with backoff; on persistent failure, it logs and proceeds to the next umbrella rather than blocking the whole cycle",
  "BEHAVIOUR: reconciliation does not delete GHL records that no longer exist in portal unless explicit operator approval is given (soft-delete semantic)",
  "Adding a new GHL field requires updating the reconciler diff logic; portal schema changes are surfaced via the canonical client model"
]
INTEGRATION_POINTS::[
  "PORTAL_COMMUNICATION — the reconciler consumes the portal interface defined by that card",
  "PORTAL_OPPORTUNITY_GHL_SYNC — names the specific portal-to-GHL sync surface; this card is the actor that operates it",
  "ENGAGEMENT_UMBRELLA — reconciliation iterates at umbrella granularity",
  "FOUNDATIONAL — reconciler depends on the foundational deployment and monorepo governance invariants"
]
CURRENT_STATUS::"proposed — authored as part of the G4 facet-card corpus (ADR-RFC-ARCH-005 §4 G4). Strain documented: actor/behaviour content has no dedicated section in v1 schema; BEHAVIOUR notes folded into OPERATIONAL_RULES as a future MINOR-bump candidate (G4 analysis brief §3 + §9). Awaits ratification once G5 validator CLI lands and CI gate green."
WHEN_TO_LOAD::[
  "GHL sync behaviour question",
  "portal-to-GHL reconciliation cadence or idempotence question",
  "GHL drift or divergence investigation",
  "actor-concept authoring (this card is the strain-prone reference for actor cards)"
]
WHEN_NOT_TO_LOAD::[
  "portal interface contract details (load PORTAL_COMMUNICATION instead)",
  "engagement-vs-project model question (load ENGAGEMENT_UMBRELLA instead)",
  "video lifecycle question (load VIDEO_STATUS_CANONICAL_MODEL instead)"
]
===END===

===EDGES===
EXTENDS::[]
CONSTRAINS::[PORTAL_COMMUNICATION]
IMPLEMENTED_BY::[]
TESTED_BY::[]
RELATED::[ENGAGEMENT_UMBRELLA,FOUNDATIONAL]
CONFLICTS_WITH::[]
PART_OF_FRAME::[]
===END===

===SOURCE_REFS===
[
  "repo:elevana-studio:.hestai/decisions/DECISIONS.oct.md#HO-GHL-RECONCILER-PIVOT-20260420"
]
===END===

===VALIDATION===
SOURCE_REF_RESOLVES::true
MARKERS_RESOLVE_TO_CARD::N/A
CHANGED_MARKED_FILE_REQUIRES_REVIEW::false
===END===
