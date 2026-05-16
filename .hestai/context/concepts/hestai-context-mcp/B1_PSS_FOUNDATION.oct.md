===META===
TYPE::PHASE_CARD
REPO_ID::hestai-context-mcp
ID::B1_PSS_FOUNDATION
STATUS::ratified
CARD_SCHEMA_VERSION::1
GENERATED_AT_COMMIT::"3c547af"
SOURCE_HASH::"N/A_for_aggregator"
===END===

===EXACT===
IDS::[B1_PSS_FOUNDATION,B1_FOUNDATION_COMPLETE,B2_PENDING,ADR_0013,RISK_001,RISK_002,RISK_003,RISK_004,RISK_005,RISK_006,RISK_007,RISK_008,RISK_010,G1,G2,G3,G4,G5,G6,G7,A1,A2,A3,A4,OPTION_C]
PROD_IMMUTABLES::[I1,I2,I3,I4,I5,I6]
ADR_REFS::[ADR-0013]
ISSUE_REFS::[13,15,16,17,33,38]
TOOL_NAMES::[clock_in,clock_out,get_context,submit_review]
FILE_PATHS::[
  "src/hestai_context_mcp/storage/types.py",
  "src/hestai_context_mcp/storage/protocol.py",
  "src/hestai_context_mcp/storage/identity.py",
  "src/hestai_context_mcp/storage/identity_resolver.py",
  "src/hestai_context_mcp/storage/local_filesystem.py",
  "src/hestai_context_mcp/storage/outbox.py",
  "src/hestai_context_mcp/storage/snapshots.py",
  "src/hestai_context_mcp/storage/projection.py",
  "src/hestai_context_mcp/storage/classification.py",
  "src/hestai_context_mcp/storage/provenance.py",
  "src/hestai_context_mcp/storage/schema.py",
  "src/hestai_context_mcp/tools/clock_in.py",
  "src/hestai_context_mcp/tools/clock_out.py",
  "src/hestai_context_mcp/tools/get_context.py",
  "src/hestai_context_mcp/core/redaction.py",
  "src/hestai_context_mcp/core/session.py"
]
MUST_PRESERVE::[
  "Only LocalFilesystemAdapter ships in B1 — R12 defers RemoteHTTP/S3/Git/auth/wire-format",
  "4-tool MCP registration unchanged (clock_in, clock_out, get_context, submit_review)",
  "PSS path layout: .hestai/state/portable/pss/{ns}/{p}/{w}/{u}/artifacts/{id}.json",
  "v1 payload keys exactly: {session_id, role, focus, archive_path, decisions, blockers, learnings, description}",
  "REDACTION_ENGINE_VERSION='1' constant persisted in artifact metadata",
  "fail-closed identity (RISK_001) and fail-closed publish (RISK_010)",
  "PortableArtifact = PortableMemoryArtifact | TombstoneArtifact discriminated union (RISK_002)",
  "get_context signature and purity unchanged (RISK_003 OPTION_C, PROD_I5)"
]
===END===

===SOURCE_REFS===
[
  ".hestai/north-star/000-HESTAI-CONTEXT-MCP-NORTH-STAR-SUMMARY.oct.md:14#PHASE_B1_FOUNDATION_COMPLETE",
  ".hestai/north-star/000-HESTAI-CONTEXT-MCP-NORTH-STAR-SUMMARY.oct.md:62-63#GATES_B1_DONE_B2_PENDING",
  "docs/adr/adr-0013-portable-session-state-via-storage-adapters.md:1#ADR_HEADER",
  "PR #17 (merged): https://github.com/elevanaltd/hestai-context-mcp/pull/17"
]
===END===

===FACETS===
INTENT::"Phase B1 of ADR-0013 ships the LocalFilesystemAdapter as the only storage carrier; establishes the StorageAdapter Protocol contract; integrates clock_in restore + clock_out publish + named snapshot semantics; preserves get_context purity. Foundation for B2 workbench integration."
CONSTRAINTS::[
  "R12: no RemoteHTTP, S3, Git carrier, auth, or wire format work",
  "All write paths must be fail-closed: no publish without complete redaction provenance (RISK_010)",
  "Identity unavailable -> structured no_identity_configured skip (RISK_001), no auth invention",
  "Storage layering acyclic: types <- protocol <- provenance <- local_filesystem <- outbox <- snapshots <- projection <- classification (G1)",
  "85% CI coverage gate; mypy strict; ruff+black line 100; Python 3.11+",
  "No new runtime dependencies (stdlib only)"
]
FAILURE_MODES::[
  "Attempting to use B1 across machines without symlink discipline yields per-worktree silos",
  "Identity tuple format unspecified in B1 -> tracked as issue #15 follow-up #1, blocks remote adoption",
  "PROJECT-CONTEXT.oct.md misused as semantic substrate -> per-machine divergence (see RFC #38)",
  "Skipping CE/CIV gates risks reintroducing RISK_010 swallow-and-publish regression caught at PR #17 review"
]
OPERATIONAL_RULES::[
  "On clock_in: identity required; structured restore_error on failure; snapshot bound to session_id",
  "On clock_out: archive first, then publish under provenance gate; outbox status record on skip",
  "On get_context: pure local read; no adapter imports; signature frozen at get_context(working_dir: str)",
  "Concept markers (Concept::B1_PSS_FOUNDATION) anchor source files to this card per RFC #38"
]
INTEGRATION_POINTS::[
  "Three-Service Model (ADR-0353): hestai-context-mcp = Memory + Environment; Vault = Identity; Workbench = UI/dispatch",
  "B2 phase pending: workbench integration; identity supplied by Workbench at first-run",
  "RFC #38 Facet ABI architecture: builds on B1 PSS for session memory, decoupled from context retrieval which uses git+L1S",
  "Issue #15 follow-up ADRs (4): explicit identity config schema, retry orchestration, public snapshot API, compaction policy"
]
CURRENT_STATUS::"COMPLETE — PR #17 merged 2026-04-29. 853 tests passing, mypy strict, coverage 91.29%. 5 deferred items tracked as named follow-up ADRs (issue #15) and 1 minor polish item (issue #16, G5 TypeGuard helpers). Identity config supplied by hand-authoring .hestai/state/portable/identity.json until issue #15 #1 ratifies a schema. B2 (workbench integration) PENDING."
WHEN_TO_LOAD::[
  "PSS or portable session state implementation question",
  "clock_in or clock_out lifecycle modification",
  "storage layer touch (storage/*.py)",
  "B1 to B2 phase transition planning",
  "identity tuple or fail-closed identity design",
  "RISK_001..RISK_010 binding ruling lookup",
  "G1..G7 or A1..A4 CIV guardrail check"
]
WHEN_NOT_TO_LOAD::[
  "get_context purity questions — load PROD_I5 directly",
  "context retrieval architecture — load CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME",
  "elevana-studio governance — load HO_MULTI_MACHINE_COORDINATION_20260429"
]
===END===

===AUDIENCE_VIEW_SEEDS===
GLOBAL::"B1 of ADR-0013 is the LocalFilesystem-only foundation for portable session state. Ships PSS protocol + adapter + identity resolution + redaction provenance. Remote carriers, auth, and cross-machine sync are deliberately deferred to follow-up ADRs (issue #15)."
AGENT::"B1_PSS_FOUNDATION is COMPLETE on main. The 4-tool MCP surface (clock_in, clock_out, get_context, submit_review) is unchanged. New code lives under storage/* with strict layering. To exercise PSS: drop .hestai/state/portable/identity.json with 5 fields, then clock_in/clock_out cycle. Cross-machine sync NOT yet supported — that's RFC #38's territory using L1 git + L1S facet ABI, not PSS remote. All 8 CE risk rulings + 7 G-guardrails landed; see arbitration record at .hestai/decisions/phase-pss-b1/arbitration-1-b1-gate-review.oct.md."
REVIEWER::"Any change touching storage/* or tools/clock_in.py / clock_out.py invokes the B1 binding rulings: union return (R002), OPTION_C purity for get_context (R003), v1 payload exact keys (R005), mirror local path layout (R006), fail-closed publish (R010). Layering must remain acyclic (G1). The PR #17 review caught a RISK_010 swallow-and-publish regression — that test (test_clock_out_rework_redaction_failclose.py) is the canary; do not weaken it."
ONBOARDING::"B1 of ADR-0013 added portable session state to hestai-context-mcp. Today: works locally per-worktree. To use it: write .hestai/state/portable/identity.json with project_id/workspace_id/user_id/state_schema_version/carrier_namespace, then clock_in/clock_out. Cross-machine: not yet — see RFC #38 for the architecture being designed."
===END===

===EDGES===
EXTENDS::[]
CONSTRAINS::[]
IMPLEMENTED_BY::[
  "src/hestai_context_mcp/storage/",
  "src/hestai_context_mcp/tools/clock_in.py",
  "src/hestai_context_mcp/tools/clock_out.py"
]
TESTED_BY::[
  "tests/storage/",
  "tests/integration/test_clock_in_portable_state.py",
  "tests/integration/test_clock_out_portable_publish.py",
  "tests/integration/test_pss_lifecycle_local_filesystem.py",
  "tests/integration/test_clock_out_rework_redaction_failclose.py"
]
RELATED::[ADR_0013,PROD_I5,HO_MULTI_MACHINE_COORDINATION_20260429,CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME]
CONFLICTS_WITH::[]
PART_OF_FRAME::[CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME]
===END===

===PROVENANCE===
MARKERS::[
  "PATH::src/hestai_context_mcp/storage/__init__.py,CLAIM::Concept::B1_PSS_FOUNDATION,SCOPE::file,CONFIDENCE::definitive",
  "PATH::src/hestai_context_mcp/tools/clock_in.py,CLAIM::Concept::B1_PSS_FOUNDATION,SCOPE::file,CONFIDENCE::definitive",
  "PATH::src/hestai_context_mcp/tools/clock_out.py,CLAIM::Concept::B1_PSS_FOUNDATION,SCOPE::file,CONFIDENCE::definitive"
]
===END===

===VALIDATION===
SOURCE_REF_RESOLVES::true
MARKERS_RESOLVE_TO_CARD::true
CHANGED_MARKED_FILE_REQUIRES_REVIEW::true
===END===
