===META===
TYPE::CONCEPT_CARD
REPO_ID::hestai-context-mcp
ID::HO_MULTI_MACHINE_COORDINATION_20260429
STATUS::proposed
CARD_SCHEMA_VERSION::1
GENERATED_AT_COMMIT::"3c547af"
SOURCE_HASH::"N/A_for_aggregator"
===END===

===EXACT===
IDS::[HO_MULTI_MACHINE_COORDINATION_20260429,HO_DECISION_GOVERNANCE_GRAVITY_TIERED_20260428,ADR_0060,ADR_0013,issue_643,visibility_rules_v2_3,WRITE_DISCIPLINE,OBSERVABILITY_TEST,ARCHITECTURAL]
PROD_IMMUTABLES::[I1,I4,I5,I6]
ADR_REFS::[ADR-0013,ADR-0060]
ISSUE_REFS::[33,38,643]
TOOL_NAMES::[octave_write,octave_secretary]
FILE_PATHS::[
  "elevana-studio:.hestai-state/orchestration/multi-machine-collaborator-coordination-architecture.md (LOCAL_MUTABLE; gitignored in elevana-studio)",
  "elevana-studio:.hestai/decisions/DECISIONS.oct.md (canonical)",
  "elevana-studio:.hestai/decisions/inbound/<token>.oct.md (proposed CQRS write path)"
]
MUST_PRESERVE::[
  "Canonical read model unchanged: .hestai/decisions/DECISIONS.oct.md remains single source of truth",
  "Write model changes only: branch-local fragments under .hestai/decisions/inbound/",
  "Compile step (octave-secretary/system-steward) merges fragments into canonical and removes consumed fragments",
  "PSS remote adapter classified as long-term advocacy NOT mandatory for collaborator readiness",
  "Day-one onboarding must function from Git alone, honoring ADR-0013 PROD I6",
  "Architectural fragments still require ISSUE_REF, preserving ADR-0060",
  "EXTENDS HO_DECISION_GOVERNANCE_GRAVITY_TIERED_20260428, does not replace it"
]
===END===

===SOURCE_REFS===
[
  "elevana-studio:.hestai-state/orchestration/multi-machine-collaborator-coordination-architecture.md:1-44#full_doc"
]
===END===

===FACETS===
INTENT::"Bounded CQRS extension to gravity-tiered governance, addressing two coupled failures: structural merge conflicts on DECISIONS.oct.md monolith authoring, and invisible Tier-3 context for fresh clones. Read model preserved; write model adds branch-local staged fragments compiled into canonical by octave-secretary."
CONSTRAINTS::[
  "EXTENDS HO_DECISION_GOVERNANCE_GRAVITY_TIERED_20260428 (not a replacement pattern)",
  "Canonical .hestai/decisions/DECISIONS.oct.md is the only read model loaded by agents",
  "Inbound fragments have NO authority until compiled into canonical",
  "Architectural fragments still require ISSUE_REF (ADR-0060)",
  "Day-one collaborator seed = single committed file (e.g., docs/development/day-one-context.md or .hestai/rules/onboarding/day-one-context.oct.md)",
  "Day-one seed must NOT become the live PROJECT-CONTEXT replacement",
  "PSS remote adapter is long-term advocacy, NOT a blocker for day-one readiness"
]
FAILURE_MODES::[
  "Inbound fragments treated as authoritative -> second source of truth, governance drift",
  "Day-one seed allowed to grow into full PROJECT-CONTEXT replacement -> token weight problem migrates",
  "Compile step automated before tests/CE review -> unsafe governance mutations",
  "PSS remote adapter conflated with day-one requirement -> unnecessary blocking dependency",
  "Grandfathered in-flight branches (PR #634, M1, PR2c, status-name-resolution, feat/portal-opportunity-ghl-sync) forced into inbound model -> avoidable rework"
]
OPERATIONAL_RULES::[
  "Inbound fragments: mark unratified, require compile-and-delete, load only canonical in normal agent context",
  "Day-one seed: keep small, link canonical sources, update only at phase transitions or collaborator-relevant changes",
  "Compile: start manual via octave-secretary, automate only after tests + CE review",
  "Grandfathering: resolve in-flight branch conflicts manually/semantically in merge order; switch new branches to inbound model after they merge or are abandoned",
  "Dispatch sequence: requirements-steward (jurisdiction validation) -> system-steward+octave-secretary (decision token + schema) -> implementation-lead (mechanics, not governance) -> TMG (tests) -> CRS+CE (quality gates) -> system-steward (onboarding)"
]
INTEGRATION_POINTS::[
  "RFC #38 (this repo): adopts the spirit (committed structured layer, deterministic projection) but adds L1S facet ABI as the bridge between L1 canonical and L3 retrieval. Solution lands here first, then propagates to elevana-studio.",
  "ADR-0013 PSS: orthogonal — PSS holds session memory, decisions stay in git",
  "ADR-0060: architectural decisions still require issue backing in either canonical or inbound fragment",
  "octave-secretary skill: owner of the compile step (inbound -> canonical merge)",
  "Day-one seed pattern: bootstrap mechanism for fresh clones; complementary to L1S facet ABI proposed in RFC #38"
]
CURRENT_STATUS::"PROPOSED in elevana-studio (not yet ratified). Status::PROPOSED until operator ratification per the orchestration doc. Decision token HO-MULTI-MACHINE-COORDINATION-20260429 will be authored in DECISIONS.oct.md after ratification. Currently being studied here as input to RFC #38; this card carries it as committed governance reference."
WHEN_TO_LOAD::[
  "DECISIONS.oct.md merge conflict resolution",
  "cross-worktree governance authoring",
  "fresh-clone onboarding pattern question",
  "CQRS or inbound fragment design",
  "elevana-studio multi-machine coordination",
  "RFC #38 architecture validation against existing orchestration"
]
WHEN_NOT_TO_LOAD::[
  "PSS remote adapter design — explicitly out of this doc's scope",
  "single-repo decision authoring without write conflict — vanilla DECISIONS.oct.md suffices",
  "session memory questions — load B1_PSS_FOUNDATION"
]
===END===

===AUDIENCE_VIEW_SEEDS===
GLOBAL::"PROPOSED HO orchestration doc (token HO-MULTI-MACHINE-COORDINATION-20260429) extending gravity-tiered governance with bounded CQRS: canonical DECISIONS.oct.md unchanged as read model; inbound branch-local fragments compiled by octave-secretary; committed day-one seed for fresh clones."
AGENT::"This doc resolves the elevana-studio DECISIONS.oct.md merge-conflict problem and the fresh-clone invisible-Tier-3 problem in one stroke. Read path unchanged. Write path: drop a fragment at .hestai/decisions/inbound/<token>.oct.md, octave-secretary compiles into canonical at ratification. Day-one seed (single committed file) handles bootstrap. PSS remote adapter is NOT required for this. Dispatch sequence laid out in §Dispatch sequence after ratification of the source doc. Lives in elevana-studio; this repo's RFC #38 builds on its principle."
REVIEWER::"Validate: (a) jurisdiction boundary against visibility-rules v2.3, ADR-0060, ADR-0013, PROD I4 — does the proposed inbound model preserve I4 structured returns and avoid a hidden second source of truth? (b) Compile step automation must NOT precede TMG/CE review (risk: unsafe governance mutations). (c) Day-one seed must NOT become live-context replacement (risk: token weight migrates). Grandfather in-flight branches; do not force them into inbound."
ONBOARDING::"This is the elevana-studio plan for handling decision-doc conflicts when multiple branches author concurrently, plus a day-one onboarding seed for fresh clones. It is PROPOSED, not yet ratified. Read the source doc at elevana-studio:.hestai-state/orchestration/multi-machine-collaborator-coordination-architecture.md (gitignored local path within the elevana-studio repo checkout; SOURCE_REFS uses the repo-id-prefix convention to remain portable across machines)."
===END===

===EDGES===
EXTENDS::[HO_DECISION_GOVERNANCE_GRAVITY_TIERED_20260428]
CONSTRAINS::[]
IMPLEMENTED_BY::[]
TESTED_BY::[]
RELATED::[CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME,ADR_0013,B1_PSS_FOUNDATION]
CONFLICTS_WITH::[]
PART_OF_FRAME::[CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME]
===END===

===PROVENANCE===
MARKERS::[]
===END===

===VALIDATION===
SOURCE_REF_RESOLVES::true
MARKERS_RESOLVE_TO_CARD::N/A
CHANGED_MARKED_FILE_REQUIRES_REVIEW::true
===END===
