===META===
TYPE::CONCEPT_CARD
REPO_ID::hestai-context-mcp
ID::PROD_I5
STATUS::ratified
CARD_SCHEMA_VERSION::1
GENERATED_AT_COMMIT::"3c547af"
SOURCE_HASH::"N/A_for_aggregator"
===END===

===EXACT===
IDS::[PROD_I5,PURITY_GUARD_G3,OPTION_C,INVARIANT_001,R10,TEST_139,TEST_140,TEST_141,TEST_142,TEST_143,TEST_144,TEST_145,TEST_146,TEST_147,TEST_148]
PROD_IMMUTABLES::[I5]
ADR_REFS::[ADR-0013]
ISSUE_REFS::[13]
TOOL_NAMES::[get_context]
FILE_PATHS::[
  "src/hestai_context_mcp/tools/get_context.py",
  "tests/integration/test_get_context_purity.py",
  "tests/storage/test_source_invariants_pss.py"
]
MUST_PRESERVE::[
  "get_context(working_dir: str) signature frozen under OPTION_C",
  "PURITY_GUARD::G3 — no StorageAdapter or LocalFilesystemAdapter symbols in get_context.py",
  "INVARIANT_001: filesystem snapshot diff is empty before and after get_context",
  "get_context MUST NOT import adapter modules",
  "get_context MUST NOT create portable subdirectories",
  "get_context MUST NOT mutate snapshot/outbox mtimes",
  "get_context MUST NOT drain or enqueue outbox entries",
  "get_context MUST NOT surface hydration as a successful response key",
  "Response top-level keys are exactly {working_dir, context}"
]
===END===

===SOURCE_REFS===
[
  "src/hestai_context_mcp/tools/get_context.py:1-30#PURITY_GUARD_G3_docstring",
  "src/hestai_context_mcp/tools/get_context.py:68-100#get_context_signature_and_return_shape",
  "tests/integration/test_get_context_purity.py:1-30#GROUP_013_module_docstring",
  "tests/integration/test_get_context_purity.py:44-70#TestGetContextSignatureContract",
  "tests/integration/test_get_context_purity.py:73-103#TestGetContextFilesystemPurity",
  "tests/integration/test_get_context_purity.py:106-170#TestGetContextSnapshotStability",
  "tests/integration/test_get_context_purity.py:173-235#TestGetContextSnapshotRead",
  "tests/integration/test_get_context_purity.py:238-280#TestGetContextSourceLevelGuard"
]
===END===

===FACETS===
INTENT::"PROD_I5 mandates that get_context is a pure read with zero filesystem side effects, enabling parallel, repeated, and CI-safe invocations by the Payload Compiler."
CONSTRAINTS::[
  "get_context signature frozen: get_context(working_dir: str) — OPTION_C, non-negotiable",
  "No import of StorageAdapter, LocalFilesystemAdapter, or OutboxStore in get_context.py — G3 source guard",
  "Filesystem snapshot diff must be empty across any call — INVARIANT_001",
  "portable/{outbox,snapshots,pss} directories must not be created by get_context",
  "Response must not include forbidden keys: portable_state, restore_status, hydrated, restored_artifacts",
  "Snapshot mtime must be unchanged across calls — R5",
  "Outbox entries must not be drained or created — R7",
  "Explicit PURITY_GUARD::G3 marker must be present in source citing OPTION_C"
]
FAILURE_MODES::[
  "Payload Compiler parallelism broken if get_context creates side effects — silent data corruption risk",
  "CI pipeline contamination if get_context writes session state between test runs",
  "PSS architectural boundary collapsed if adapter symbols appear in get_context.py",
  "Session context drift within a session if snapshot mtime is mutated",
  "Security posture weakened if outbox is drained during a read call"
]
OPERATIONAL_RULES::[
  "grep for PURITY_GUARD::G3 before merging any change to get_context.py",
  "run TestGetContextFilesystemPurity before releasing any get_context change",
  "Any PR touching get_context.py requires CE review per CHANGED_MARKED_FILE_REQUIRES_REVIEW",
  "Signature changes require full requirements-steward arbitration — OPTION_C is load-bearing",
  "Source invariant tests (test_source_invariants_pss.py) are the mechanical G3 gate"
]
INTEGRATION_POINTS::[
  "clock_in: owns snapshot creation — get_context reads only, never creates",
  "clock_out: owns artifact publish — get_context has no publish path",
  "ADR-0013 R2: StorageAdapter protocol explicitly excludes get_context from adapter calls",
  "ADR-0013 R5: lifecycle binding — get_context reads named local snapshot only",
  "Payload Compiler (Position 3 in three-service model): primary caller, depends on purity guarantee"
]
CURRENT_STATUS::"Ratified and implemented. PURITY_GUARD::G3 present in source. Test suite GROUP_013 (TEST_139..TEST_148) covers all invariants. Gate: IMPLEMENTED per North Star §2::I5."
WHEN_TO_LOAD::[
  "side effect or mutation or get_context writes",
  "PURITY_GUARD or G3 or OPTION_C or INVARIANT_001",
  "get_context signature change proposal",
  "adding imports to get_context.py",
  "Payload Compiler parallelism safety questions",
  "I5 purity violation detected"
]
WHEN_NOT_TO_LOAD::[
  "clock_in or clock_out lifecycle implementation — use ADR_0013 or B1_PSS_FOUNDATION",
  "StorageAdapter protocol design — use ADR_0013",
  "session creation or archival",
  "provider adapter or transcript parsing work"
]
===END===

===AUDIENCE_VIEW_SEEDS===
GLOBAL::"PROD_I5 is the binding rule that get_context must have zero side effects — no writes, no adapter calls, no state mutations — enabling safe parallel and repeated invocations."
AGENT::"Before adding any import or write to get_context.py, check PURITY_GUARD::G3. The function signature get_context(working_dir: str) is frozen under OPTION_C. Filesystem snapshot diff must be empty across any call (INVARIANT_001). Forbidden response keys: portable_state, restore_status, hydrated, restored_artifacts. Tests TEST_139..TEST_148 mechanically enforce all invariants. CE review required for any change to this file."
REVIEWER::"Risk gate: any PR touching get_context.py must demonstrate INVARIANT_001 still passes (empty fs diff), G3 source guard holds (no adapter symbols), and signature is unchanged (OPTION_C). Failure breaks Payload Compiler parallelism and collapses the PSS architectural boundary. PROD immutable — escalate signature change proposals to requirements-steward."
ONBOARDING::"get_context is read-only by design. It reads context files and returns a structured dict; it never creates files, never calls storage adapters, and never touches portable memory. The PURITY_GUARD::G3 comment at the top of get_context.py explains why. Do not add imports from hestai_context_mcp.storage to this file."
===END===

===EDGES===
EXTENDS::[]
CONSTRAINS::[ADR_0013]
IMPLEMENTED_BY::[
  "src/hestai_context_mcp/tools/get_context.py"
]
TESTED_BY::[
  "tests/integration/test_get_context_purity.py",
  "tests/storage/test_source_invariants_pss.py"
]
RELATED::[ADR_0013,B1_PSS_FOUNDATION,CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME]
CONFLICTS_WITH::[]
PART_OF_FRAME::[CONTEXT_RETRIEVAL_ARCHITECTURE_FRAME]
===END===

===PROVENANCE===
MARKERS::[
  "PATH::src/hestai_context_mcp/tools/get_context.py,CLAIM::Concept::PROD_I5,SCOPE::file,CONFIDENCE::definitive",
  "PATH::tests/integration/test_get_context_purity.py,CLAIM::Concept::PROD_I5,SCOPE::file,CONFIDENCE::definitive"
]
===END===

===VALIDATION===
SOURCE_REF_RESOLVES::true
MARKERS_RESOLVE_TO_CARD::true
CHANGED_MARKED_FILE_REQUIRES_REVIEW::true
===END===
