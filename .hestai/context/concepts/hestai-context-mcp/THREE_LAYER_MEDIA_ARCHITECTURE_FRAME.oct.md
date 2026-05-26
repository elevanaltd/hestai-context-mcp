===META===
TYPE::FRAME_CARD
REPO_ID::hestai-context-mcp
ID::THREE_LAYER_MEDIA_ARCHITECTURE_FRAME
STATUS::proposed
CARD_SCHEMA_VERSION::1
GENERATED_AT_COMMIT::"2909a8b"
SOURCE_HASH::"N/A_for_aggregator"
===END===

===EXACT===
IDS::[THREE_LAYER_MEDIA_ARCHITECTURE_FRAME,MUX_DELIVERY_LAYER,SUPABASE_METADATA_LAYER,LUCIDLINK_MASTER_LAYER]
PROD_IMMUTABLES::[]
ADR_REFS::[]
ISSUE_REFS::[]
TOOL_NAMES::[]
FILE_PATHS::[]
MUST_PRESERVE::[
  "The media architecture isolates vendors at three distinct layers: delivery (Mux), metadata (Supabase), and master storage (LucidLink)",
  "Layer boundaries are vendor-isolation invariants — vendor swap at any layer MUST NOT cascade to other layers",
  "Cross-layer references travel through metadata (Supabase) — delivery and master layers do NOT reference each other directly",
  "Application code consumes the layered abstraction, never the vendor APIs directly"
]
===END===

===FACETS===
INTENT::"THREE_LAYER_MEDIA_ARCHITECTURE_FRAME is the orientation map for elevana-studio's media pipeline. Three layers isolate three vendor concerns: Mux delivers transcoded video to clients; Supabase stores metadata, identity, and cross-references; LucidLink holds master files for editorial workflow. This frame card encodes the vendor-isolation invariant — vendor swap at any layer is local to that layer, not a cross-pipeline rewrite. Loading this frame answers 'where does X live in the media pipeline?' and 'what is the impact radius of swapping vendor Y?' without requiring direct knowledge of any vendor API."
CONSTRAINTS::[
  "Mux is the sole delivery layer — application code MUST NOT serve transcoded video from any other store",
  "Supabase is the sole metadata layer — cross-layer references and identity live there exclusively",
  "LucidLink is the sole master-file layer — editorial workflows MUST resolve master files through LucidLink, not direct cloud storage",
  "Layer crossings are explicit: delivery references metadata; master references metadata; delivery and master DO NOT reference each other directly",
  "Vendor APIs are encapsulated in layer-specific adapters; application code consumes the adapter, not the vendor SDK"
]
FAILURE_MODES::[
  "Direct vendor coupling in application code — vendor swap becomes a pipeline-wide rewrite instead of a layer-local change",
  "Master-to-delivery direct reference — bypasses metadata layer, fragments the cross-reference graph, breaks audit trail",
  "Metadata leakage into delivery or master layers — pollutes layer boundaries, complicates vendor swap",
  "Treating the layers as interchangeable storage tiers — collapses the vendor-isolation invariant and re-introduces cross-vendor coupling"
]
OPERATIONAL_RULES::[
  "When adding a new media feature, identify which of the three layers it belongs to FIRST; if it spans layers, isolate the cross-layer reference in metadata",
  "Vendor swaps execute as layer-local migrations: pick the layer, change the adapter, leave the other layers untouched",
  "Cross-references between delivery and master flow through metadata; direct adapter-to-adapter calls between non-metadata layers are FORBIDDEN",
  "Cost optimisation per layer is local; cross-layer cost re-balancing (e.g. shifting from Mux to a competing CDN) is a layer-swap, not a cross-layer rewrite"
]
INTEGRATION_POINTS::[
  "VIDEO_STATUS_CANONICAL_MODEL — video status transitions trigger work in delivery (Mux) and master (LucidLink); the canonical model is the cross-layer status surface",
  "ENGAGEMENT_UMBRELLA — media artefacts are scoped to sub-projects under the umbrella; the layered architecture is the storage substrate for that scope",
  "PORTAL_COMMUNICATION — portal consumes the delivery layer (Mux) for client-facing playback; metadata layer (Supabase) for cross-system identity",
  "FOUNDATIONAL — the layered architecture builds on the foundational monorepo and deployment governance invariants"
]
CURRENT_STATUS::"proposed — authored as part of the G4 facet-card corpus (ADR-RFC-ARCH-005 §4 G4). Clean fit reference for Frame cards (orientation maps over a cluster of related concepts). Awaits ratification once G5 validator CLI lands and CI gate green."
WHEN_TO_LOAD::[
  "elevana-studio media pipeline question",
  "vendor isolation or vendor swap impact-radius question",
  "media storage layer question (which vendor owns what)",
  "Mux, Supabase, or LucidLink integration question",
  "cross-layer reference design question (where does the cross-reference live)"
]
WHEN_NOT_TO_LOAD::[
  "video status lifecycle question (load VIDEO_STATUS_CANONICAL_MODEL instead)",
  "portal-to-GHL sync question (load GHL_RECONCILER or PORTAL_COMMUNICATION instead)",
  "monorepo deployment topology question (load FOUNDATIONAL instead)"
]
===END===

===AUDIENCE_VIEW_SEEDS===
GLOBAL::"Frame card for elevana-studio's media pipeline. Three vendor-isolated layers: Mux (delivery), Supabase (metadata), LucidLink (master). Vendor swap at any layer is layer-local; cross-layer references flow through metadata."
AGENT::"When working on elevana-studio media features, identify the affected layer first, then walk the adapter boundary. Direct vendor coupling in application code is a failure mode; the layer-specific adapter is the consumption boundary. Cross-layer references go through Supabase metadata, never direct adapter-to-adapter calls between delivery and master."
REVIEWER::"Risk gates: (a) any media-feature PR MUST identify the affected layer; (b) cross-vendor coupling in application code is a structural regression; (c) master-to-delivery direct references bypass the metadata audit trail and are a blocker; (d) vendor swap proposals must be layer-local — pipeline-wide rewrites require an architecture review, not a routine PR."
ONBOARDING::"elevana-studio stores video in three places for three reasons: Mux streams it to viewers, Supabase tracks what it is, LucidLink keeps the master file for editors. The three layers don't talk to each other directly — they talk through Supabase. This isolation lets us swap any one vendor without touching the others."
===END===

===EDGES===
EXTENDS::[]
CONSTRAINS::[]
IMPLEMENTED_BY::[]
TESTED_BY::[]
RELATED::[VIDEO_STATUS_CANONICAL_MODEL,ENGAGEMENT_UMBRELLA,FOUNDATIONAL]
CONFLICTS_WITH::[]
PART_OF_FRAME::[]
===END===

===SOURCE_REFS===
[
  "repo:elevana-studio:.hestai/decisions/DECISIONS.oct.md#HO-THREE-LAYER-MEDIA-ARCHITECTURE-20260424"
]
===END===

===VALIDATION===
SOURCE_REF_RESOLVES::true
MARKERS_RESOLVE_TO_CARD::N/A
CHANGED_MARKED_FILE_REQUIRES_REVIEW::false
===END===
