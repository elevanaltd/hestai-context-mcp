===B1_BUILD_PLAN_ADR_0013_LOCAL_FILESYSTEM_ADAPTER===

§META
  PHASE_ID::phase-pss-b1
  PHASE_NAME::"B1 BUILD-PLAN"
  DOCUMENT_TYPE::BUILD_PLAN
  DOCUMENT_FORMAT::OCTAVE
  STATUS::DRAFT_READY_FOR_B1_GATE_REVIEW
  CREATED_AT_UTC::"2026-04-26"
  WORKTREE::"/Volumes/HestAI-Projects/hestai-context-mcp/worktrees/control-room"
  OWNER_ROLE::TECHNICAL_ARCHITECT
  IMPLEMENTATION_OWNER_NEXT::IMPLEMENTATION_LEAD
  REVIEW_OWNER_NEXT::CRITICAL_ENGINEER
  ADR_REF::"docs/adr/adr-0013-portable-session-state-via-storage-adapters.md"
  ADR_NUMBER::ADR-0013
  ADR_TITLE::"Portable Session State via Storage Adapters"
  ADR_STATUS::ACCEPTED
  ADR_RATIFIED::"2026-04-26"
  ADR_GITHUB_ISSUE::"#13"
  ADR_PHASE::D2_DESIGN
  BUILD_SCOPE::LOCAL_FILESYSTEM_ADAPTER_ONLY
  REMOTE_SCOPE::DEFERRED_BY_ADR_R12
  PRODUCTION_CODE_IN_THIS_ARTIFACT::NO
  REAL_PYTHON_ALLOWED_HERE::"§PROTOCOL_SIGNATURES only"
  TDD_MODE::MANDATORY_RED_FIRST
  COVERAGE_GATE::"85 percent minimum in CI"
  TYPE_GATE::"Python 3.11+, full type hints, mypy strict"
  FORMAT_GATE::"black + ruff, line length 100"
  DEPENDENCY_GATE::"No new runtime dependency on remote service"
  TRANSPORT_GATE::"No MCP transport change; stdio JSON-RPC remains unchanged"
  GET_CONTEXT_GATE::"Pure local read, zero adapter calls, zero writes"
  SECURITY_GATE::"Publication fails closed without complete redaction provenance"
  CONCURRENCY_GATE::"Append-first monotonic IDs, no Last-Write-Wins"
  CLASSIFICATION_GATE::"Unknown state classification -> LOCAL_MUTABLE"
  SNAPSHOT_GATE::"clock_in binds a named local snapshot to session_id"
  OUTBOX_GATE::".hestai/state/portable/outbox/ is durable Local State"
  TOMBSTONE_GATE::"Restore excludes tombstoned artifacts"
  MIGRATION_GATE::"Schema framework exists even while only v1 exists"
  LOCAL_DEFAULT_GATE::"LocalFilesystemAdapter is the only shipped adapter in B1"

  SOURCE_OF_TRUTH
    ADR::"docs/adr/adr-0013-portable-session-state-via-storage-adapters.md"
    NORTH_STAR_SUMMARY::".hestai/north-star/000-HESTAI-CONTEXT-MCP-NORTH-STAR-SUMMARY.oct.md"
    SYSTEM_STANDARD::".hestai-sys/SYSTEM-STANDARD.md"
    SERVER_REGISTRATION::"src/hestai_context_mcp/server.py"
    CLOCK_IN::"src/hestai_context_mcp/tools/clock_in.py"
    CLOCK_OUT::"src/hestai_context_mcp/tools/clock_out.py"
    GET_CONTEXT::"src/hestai_context_mcp/tools/get_context.py"
    REDACTION::"src/hestai_context_mcp/core/redaction.py"
    SESSION::"src/hestai_context_mcp/core/session.py"
    CONTEXT_STEWARD::"src/hestai_context_mcp/core/context_steward.py"
    PORT_CONVENTION::"src/hestai_context_mcp/ports/ai_client.py"
    ADAPTER_CONVENTION::"src/hestai_context_mcp/adapters/openai_compat_ai_client.py"
    TEST_CONVENTION::"tests/unit/test_source_invariants.py"
    PROJECT_CONFIG::"pyproject.toml"

  CURRENT_SYSTEM_FACTS
    SERVER_FACT_001::"server.py registers exactly four tools."
    SERVER_FACT_002::"clock_in, clock_out, get_context, submit_review are tool registrations."
    SERVER_FACT_003::"No storage tools are registered today."
    CLOCK_IN_FACT_001::"clock_in validates role and working_dir."
    CLOCK_IN_FACT_002::"clock_in resolves branch, focus, phase, git state."
    CLOCK_IN_FACT_003::"clock_in creates a session through SessionManager.create_session."
    CLOCK_IN_FACT_004::"clock_in currently reads PROJECT-CONTEXT directly from local state."
    CLOCK_IN_FACT_005::"clock_in currently updates FAST layer through create_session."
    CLOCK_OUT_FACT_001::"clock_out validates session_id against traversal."
    CLOCK_OUT_FACT_002::"clock_out loads active session metadata from session.json."
    CLOCK_OUT_FACT_003::"clock_out detects transcript parser through provider adapter registry."
    CLOCK_OUT_FACT_004::"clock_out uses RedactionEngine.copy_and_redact for archive safety."
    CLOCK_OUT_FACT_005::"clock_out appends learnings-index.jsonl."
    CLOCK_OUT_FACT_006::"clock_out removes active session directory after local archive path."
    GET_CONTEXT_FACT_001::"get_context signature is get_context(working_dir: str)."
    GET_CONTEXT_FACT_002::"get_context currently creates no .hestai directory."
    GET_CONTEXT_FACT_003::"get_context has no session_id argument."
    GET_CONTEXT_FACT_004::"get_context tests assert no session dirs, no FAST files, no session.json."
    REDACTION_FACT_001::"RedactionEngine has RedactionResult with redaction_count and redacted_types."
    REDACTION_FACT_002::"RedactionEngine has PATTERNS but no ruleset hash helper today."
    REDACTION_FACT_003::"RedactionEngine has no explicit engine version today."
    SESSION_FACT_001::"SessionManager.ensure_hestai_structure creates .hestai-state dirs."
    SESSION_FACT_002::".hestai/state is expected to be symlink to ../.hestai-state."
    SESSION_FACT_003::"SessionManager currently has no portable snapshot helpers."
    CONTEXT_FACT_001::"ContextSteward currently parses workflow phase constraints."
    CONTEXT_FACT_002::"Context Projection rebuild from portable artifacts does not exist today."
    PORT_FACT_001::"Existing Protocol style uses runtime_checkable Protocol."
    PORT_FACT_002::"Existing ports avoid concrete provider names and SDK imports."
    ADAPTER_FACT_001::"Existing concrete adapter lives outside ports."
    TEST_FACT_001::"Source invariant tests already grep structural boundaries."
    PYPROJECT_FACT_001::"mypy disallow_untyped_defs is true."
    PYPROJECT_FACT_002::"ruff target-version is py311."
    PYPROJECT_FACT_003::"black line length is 100."

  R_TRACE_SUMMARY
    R1::"State classification: LOCAL_MUTABLE, PORTABLE_MEMORY, DERIVED_PROJECTION."
    R2::"StorageAdapter protocol and carrier capability matrix."
    R3::"Identity tuple validation and mismatch refusal."
    R4::"Portable schema versioning and migration framework."
    R5::"Lifecycle binding: restore at clock_in, pure snapshot read, publish at clock_out."
    R6::"Redaction provenance metadata as publication gate."
    R7::"Publish acknowledgement, durable outbox, unpublished status."
    R8::"Tombstone and revocation semantics."
    R9::"Append-first monotonic IDs, no Last-Write-Wins."
    R10::"Five testable invariants before complete behavior."
    R11::"No custom Git refs as storage carrier."
    R12::"Remote adapter decisions out of scope."

  ORGANIZING_PRINCIPLE
    TENSION::"Portable memory is needed across machines, but raw state must remain local."
    PATTERN::"Classified artifacts pass through a storage boundary only after provenance validation."
    CLARITY::"Local state remains mutable and private; portable memory is append-first, redacted, versioned."

  COMPONENT_RELATIONSHIP_MAP
    REL_001::"clock_in -> identity resolver -> LocalFilesystemAdapter.list/read -> schema migrator -> Context Projection -> session snapshot."
    REL_002::"session snapshot -> get_context local read -> caller-visible context shape."
    REL_003::"clock_out -> transcript parser -> RedactionEngine -> provenance builder -> archive -> artifact builder -> adapter publish."
    REL_004::"adapter publish failure -> outbox durable queue -> clock_out unpublished status."
    REL_005::"artifact stream + tombstones -> restore filter -> deterministic projection."
    REL_006::"schema reader -> migration registry -> local projection only, never rewrite original artifact during restore."
    REL_007::"identity tuple -> namespace path -> artifact validation -> mismatch structured error."
    REL_008::"source invariant tests -> prevent remote dependencies, Git refs, and get_context adapter calls."

  STATUS_BY_PHASE
    D2::ACCEPTED_ADR
    B1::THIS_BUILD_PLAN
    B2::IMPLEMENTATION_WITH_RED_TESTS_FIRST
    B3::INTEGRATION_VALIDATION
    B4::RELEASE_GATE

§SCOPE
  IN_SCOPE
    ITEM_001
      NAME::"StorageAdapter Protocol foundation"
      R_TRACE::[R2]
      FILES::["src/hestai_context_mcp/storage/protocol.py", "src/hestai_context_mcp/storage/types.py"]
      ACCEPTANCE::"Protocol signatures compile under mypy strict."
      ACCEPTANCE::"Capability matrix is represented by StorageCapabilities."
      ACCEPTANCE::"LocalFilesystemAdapter advertises required publication capabilities."
      NOT_INCLUDED::"No RemoteHTTP, S3, Git, auth, hosting, or wire format."
    ITEM_002
      NAME::"LocalFilesystemAdapter default implementation"
      R_TRACE::[R2,R7,R8,R9,R11]
      FILES::["src/hestai_context_mcp/storage/local_filesystem.py"]
      ACCEPTANCE::"Only shipped adapter is local filesystem."
      ACCEPTANCE::"Writes are conditional create-only by default."
      ACCEPTANCE::"List order is deterministic by monotonic sequence."
      ACCEPTANCE::"No custom Git refs are used or mentioned as an implementation option."
    ITEM_003
      NAME::"clock_in restore and named snapshot creation"
      R_TRACE::[R3,R4,R5,R8,R9,R10]
      FILES::["src/hestai_context_mcp/tools/clock_in.py", "src/hestai_context_mcp/storage/snapshots.py"]
      ACCEPTANCE::"Restore runs before session snapshot binding."
      ACCEPTANCE::"Artifacts with mismatched identity fail restore with structured error."
      ACCEPTANCE::"Tombstoned artifacts are excluded before projection."
      ACCEPTANCE::"Named snapshot path includes session_id."
      ACCEPTANCE::"Existing clock_in return shape is extended only with structured portable_state metadata."
    ITEM_004
      NAME::"get_context pure local-snapshot read"
      R_TRACE::[R5,R10]
      FILES::["src/hestai_context_mcp/tools/get_context.py", "src/hestai_context_mcp/storage/snapshots.py"]
      ACCEPTANCE::"No StorageAdapter imports in get_context.py."
      ACCEPTANCE::"No adapter calls happen from get_context."
      ACCEPTANCE::"Filesystem snapshot diff is empty before and after get_context."
      ACCEPTANCE::"Visible behavior remains a structured local context response."
    ITEM_005
      NAME::"clock_out redact -> archive -> publish via adapter"
      R_TRACE::[R5,R6,R7,R8,R9,R10]
      FILES::["src/hestai_context_mcp/tools/clock_out.py", "src/hestai_context_mcp/storage/provenance.py", "src/hestai_context_mcp/storage/outbox.py"]
      ACCEPTANCE::"Local archive remains independently successful."
      ACCEPTANCE::"Portable publication requires complete redaction provenance."
      ACCEPTANCE::"Publish failures leave durable outbox entries."
      ACCEPTANCE::"Return includes portable publish status and unpublished_memory_exists."
    ITEM_006
      NAME::"Portable types contract"
      R_TRACE::[R1,R2,R3,R4,R6,R7,R8,R9]
      FILES::["src/hestai_context_mcp/storage/types.py"]
      ACCEPTANCE::"PortableMemoryArtifact exists with required R4 fields."
      ACCEPTANCE::"TombstoneArtifact exists with target id, reason, timestamp, publisher identity."
      ACCEPTANCE::"PublishAck exists with carrier namespace, sequence, receipt, status."
      ACCEPTANCE::"WritePrecondition exists for conditional writes."
      ACCEPTANCE::"ArtifactRef, PortableNamespace, StorageCapabilities, RedactionProvenance exist."
      ACCEPTANCE::"IdentityTuple exists and is validated before restore/publish."
    ITEM_007
      NAME::"Identity tuple validation"
      R_TRACE::[R3,R5,R10]
      FILES::["src/hestai_context_mcp/storage/identity.py"]
      ACCEPTANCE::"project_id, workspace_id, user_id, state_schema_version, carrier_namespace are required."
      ACCEPTANCE::"Unsafe path characters are rejected before local path construction."
      ACCEPTANCE::"Restore mismatch is structured error, not empty fallback."
      ACCEPTANCE::"Publish mismatch is hard failure before writing."
    ITEM_008
      NAME::"Schema versioning and migration framework"
      R_TRACE::[R4,R10]
      FILES::["src/hestai_context_mcp/storage/schema.py"]
      ACCEPTANCE::"Current schema is v1."
      ACCEPTANCE::"Migration registry exists even with only v1 identity migration."
      ACCEPTANCE::"Schema too new fails closed with structured schema_too_new."
      ACCEPTANCE::"Older supported schema migrates into local projection without rewriting original artifact."
    ITEM_009
      NAME::"Redaction provenance metadata enforcement"
      R_TRACE::[R6,R10]
      FILES::["src/hestai_context_mcp/storage/provenance.py", "src/hestai_context_mcp/core/redaction.py"]
      ACCEPTANCE::"Ruleset hash is deterministic for current RedactionEngine.PATTERNS."
      ACCEPTANCE::"Engine name and version are present."
      ACCEPTANCE::"Input and output hashes are present."
      ACCEPTANCE::"Classification label is PORTABLE_MEMORY."
      ACCEPTANCE::"write_artifact fails closed without complete provenance."
    ITEM_010
      NAME::"Append-first monotonic-ID storage with tombstones"
      R_TRACE::[R8,R9]
      FILES::["src/hestai_context_mcp/storage/local_filesystem.py", "src/hestai_context_mcp/storage/types.py"]
      ACCEPTANCE::"Artifact ids are sortable by monotonic sequence."
      ACCEPTANCE::"Duplicate artifact id writes are idempotent only if payload hash matches."
      ACCEPTANCE::"Conflicting duplicate ids fail instead of overwriting."
      ACCEPTANCE::"Tombstones append as separate artifacts."
      ACCEPTANCE::"Restore excludes target artifacts covered by valid tombstones."
    ITEM_011
      NAME::"Durable outbound queue"
      R_TRACE::[R7,R10]
      FILES::["src/hestai_context_mcp/storage/outbox.py"]
      ACCEPTANCE::".hestai/state/portable/outbox/{artifact_id}.json is created on publish failure."
      ACCEPTANCE::"Outbox is LOCAL_MUTABLE."
      ACCEPTANCE::"Queue scanning is deterministic and read-only when asked for status."
      ACCEPTANCE::"get_context never drains or writes the outbox."
    ITEM_012
      NAME::"Named snapshot binding"
      R_TRACE::[R5,R10]
      FILES::["src/hestai_context_mcp/storage/snapshots.py", "src/hestai_context_mcp/core/session.py"]
      ACCEPTANCE::".hestai/state/portable/snapshots/{session_id}/context-projection.json exists after clock_in."
      ACCEPTANCE::"Snapshot metadata records identity tuple and artifact refs."
      ACCEPTANCE::"Snapshot content does not drift inside session."
      ACCEPTANCE::"Snapshot is DERIVED_PROJECTION."

  OUT_OF_SCOPE
    R12_ITEM_001
      NAME::"RemoteHTTP adapter"
      STATUS::DEFERRED_TO_FUTURE_ADR
      B1_RULE::"Do not design class, path, API, retry model, auth, or wire format."
    R12_ITEM_002
      NAME::"S3 adapter"
      STATUS::DEFERRED_TO_FUTURE_ADR
      B1_RULE::"Do not design bucket layout, credentials, KMS, region, or object schema."
    R12_ITEM_003
      NAME::"Git adapter"
      STATUS::DEFERRED_TO_FUTURE_ADR
      B1_RULE::"Do not design Git storage. Custom refs are prohibited by R11."
    R12_ITEM_004
      NAME::"Hosting target and region"
      STATUS::DEFERRED_TO_FUTURE_ADR
      B1_RULE::"Do not choose cloud, edge, hosted API, region, tenancy, or SLA."
    R12_ITEM_005
      NAME::"Auth model"
      STATUS::DEFERRED_TO_FUTURE_ADR
      B1_RULE::"Do not design login, bearer tokens, key exchange, claims, or refresh."
    R12_ITEM_006
      NAME::"Remote wire format"
      STATUS::DEFERRED_TO_FUTURE_ADR
      B1_RULE::"Do not define HTTP routes, request schemas, response schemas, or error wire shape."
    R12_ITEM_007
      NAME::"First-run UX state taxonomy"
      STATUS::DEFERRED_TO_FUTURE_ADR
      B1_RULE::"Do not design user prompts, onboarding states, namespace UX, or setup flows."
    R12_ITEM_008
      NAME::"Specific non-local adapter implementations"
      STATUS::DEFERRED_TO_FUTURE_ADR
      B1_RULE::"Do not add runtime dependencies, configs, feature flags, or stubs for remote carriers."

  SCOPE_DISCIPLINE
    RULE_001::"If a decision is needed for remote behavior, record it in §RISKS_AND_OPEN_QUESTIONS."
    RULE_002::"If a decision is needed for auth identity, record it in §RISKS_AND_OPEN_QUESTIONS."
    RULE_003::"If a decision changes public MCP tool semantics, record it for critical-engineer review."
    RULE_004::"If a test would require network I/O, rewrite it as a local adapter test."
    RULE_005::"If a component cannot be classified, treat it as LOCAL_MUTABLE."

  TENSION_PATTERN_CLARITY
    TENSION_001::"Need adapter abstraction now; remote adapters are out of scope."
    PATTERN_001::"Define capability-bearing StorageAdapter Protocol and ship only LocalFilesystemAdapter."
    CLARITY_001::"Future carriers can conform later without B1 deciding their transport or auth."
    TENSION_002::"Need restore before clock_in context; get_context must stay pure."
    PATTERN_002::"clock_in hydrates and freezes a session snapshot; get_context reads only local files."
    CLARITY_002::"A session sees stable context; repeated get_context calls cannot publish or hydrate."
    TENSION_003::"Need revocation without losing append history."
    PATTERN_003::"Tombstone artifacts are appended and applied during projection rebuild."
    CLARITY_003::"History remains auditable while sensitive or invalid memory is excluded."
    TENSION_004::"Need schema evolution but only v1 exists."
    PATTERN_004::"Build migration registry with identity v1 migration and too-new fail-closed path."
    CLARITY_004::"B1 avoids schema debt without inventing v2 content."

§FILE_LAYOUT
  NEW_PACKAGE
    PATH::"src/hestai_context_mcp/storage/__init__.py"
    PURPOSE::"Public storage package exports for B1 PSS foundation."
    R_TRACE::[R2]
    CONTENT_RULE::"Re-export stable protocol and type names only."
    CONTENT_RULE::"Do not import concrete remote adapters."
    CONTENT_RULE::"May export LocalFilesystemAdapter because it is the B1 default."
    TESTS::["tests/storage/test_storage_package_exports.py"]

  NEW_FILE
    PATH::"src/hestai_context_mcp/storage/types.py"
    PURPOSE::"Dataclass and enum contract for PSS artifacts, identity, refs, capabilities, acks."
    R_TRACE::[R1,R2,R3,R4,R6,R7,R8,R9]
    STRUCTURE::"Pure type definitions; no filesystem I/O."
    STRUCTURE::"No environment reads."
    STRUCTURE::"No adapter imports."
    REQUIRED_TYPES::[StorageCapabilities,ArtifactRef,PortableMemoryArtifact,TombstoneArtifact]
    REQUIRED_TYPES::[PublishAck,WritePrecondition,PortableNamespace,RedactionProvenance,IdentityTuple]
    TESTS::["tests/storage/test_types_contract.py"]

  NEW_FILE
    PATH::"src/hestai_context_mcp/storage/protocol.py"
    PURPOSE::"StorageAdapter Protocol boundary."
    R_TRACE::[R2,R5,R7,R8,R9]
    STRUCTURE::"Protocol only; no concrete storage implementation."
    STRUCTURE::"Must not mention RemoteHTTP, S3, Git implementation details."
    STRUCTURE::"Method names match B1 contract."
    TESTS::["tests/storage/test_storage_protocol.py"]

  NEW_FILE
    PATH::"src/hestai_context_mcp/storage/identity.py"
    PURPOSE::"IdentityTuple validation and namespace path-token safety."
    R_TRACE::[R3]
    STRUCTURE::"Pure validation helpers."
    STRUCTURE::"Reject blank ids."
    STRUCTURE::"Reject path traversal and separators."
    STRUCTURE::"Reject unsupported state_schema_version."
    STRUCTURE::"Return structured validation errors."
    TESTS::["tests/storage/test_identity.py"]

  NEW_FILE
    PATH::"src/hestai_context_mcp/storage/schema.py"
    PURPOSE::"Portable schema version checks and migration registry."
    R_TRACE::[R4]
    STRUCTURE::"CURRENT_SCHEMA_VERSION constant."
    STRUCTURE::"SUPPORTED_SCHEMA_VERSIONS set."
    STRUCTURE::"minimum_reader_version gate."
    STRUCTURE::"v1 identity migration returns artifact unchanged."
    STRUCTURE::"Too-new artifacts fail closed."
    TESTS::["tests/storage/test_schema.py"]

  NEW_FILE
    PATH::"src/hestai_context_mcp/storage/provenance.py"
    PURPOSE::"Redaction provenance construction and validation."
    R_TRACE::[R6]
    STRUCTURE::"Use RedactionEngine metadata without duplicating redaction rules."
    STRUCTURE::"Compute deterministic ruleset hash from RedactionEngine.PATTERNS."
    STRUCTURE::"Compute input and output hashes."
    STRUCTURE::"Validate complete RedactionProvenance before publication."
    TESTS::["tests/storage/test_provenance.py"]

  NEW_FILE
    PATH::"src/hestai_context_mcp/storage/local_filesystem.py"
    PURPOSE::"Default B1 LocalFilesystemAdapter implementation."
    R_TRACE::[R2,R3,R6,R7,R8,R9,R11]
    STRUCTURE::"Rooted under .hestai/state/portable for local carrier state."
    STRUCTURE::"Use pathlib and atomic local writes."
    STRUCTURE::"Use exclusive create for append artifacts."
    STRUCTURE::"Use deterministic directory listing for restore."
    STRUCTURE::"Reject unsafe namespace components before path construction."
    STRUCTURE::"No git commands."
    STRUCTURE::"No network I/O."
    STRUCTURE::"No keyring."
    TESTS::["tests/storage/test_local_filesystem_adapter.py"]

  NEW_FILE
    PATH::"src/hestai_context_mcp/storage/outbox.py"
    PURPOSE::"Durable queue for unpublished Portable Memory Artifacts."
    R_TRACE::[R7]
    STRUCTURE::"Queue entry path is .hestai/state/portable/outbox/{artifact_id}.json."
    STRUCTURE::"Queue entries are LOCAL_MUTABLE."
    STRUCTURE::"Writes use temp file then atomic replace."
    STRUCTURE::"Status scan is read-only."
    STRUCTURE::"No get_context integration."
    TESTS::["tests/storage/test_outbox.py"]

  NEW_FILE
    PATH::"src/hestai_context_mcp/storage/snapshots.py"
    PURPOSE::"Named session snapshot creation and pure snapshot reads."
    R_TRACE::[R5,R10]
    STRUCTURE::"Snapshot path is .hestai/state/portable/snapshots/{session_id}/context-projection.json."
    STRUCTURE::"Snapshot metadata records session_id, identity tuple, artifact refs, created_at."
    STRUCTURE::"Snapshot writes happen in clock_in only."
    STRUCTURE::"Snapshot reads do not mutate files."
    TESTS::["tests/storage/test_snapshots.py"]

  NEW_FILE
    PATH::"src/hestai_context_mcp/storage/classification.py"
    PURPOSE::"State classification helpers for migration and fail-closed unknowns."
    R_TRACE::[R1]
    STRUCTURE::"Map known local paths to LOCAL_MUTABLE, PORTABLE_MEMORY, DERIVED_PROJECTION."
    STRUCTURE::"Unknown classification returns LOCAL_MUTABLE."
    STRUCTURE::"No filesystem mutation."
    TESTS::["tests/storage/test_classification.py"]

  NEW_FILE
    PATH::"src/hestai_context_mcp/storage/projection.py"
    PURPOSE::"Build deterministic Context Projection from local state plus portable artifacts."
    R_TRACE::[R1,R4,R5,R8,R9,R10]
    STRUCTURE::"Pure projection builder over in-memory artifacts."
    STRUCTURE::"Apply tombstones before payload merge."
    STRUCTURE::"Sort by sequence_id then artifact_id."
    STRUCTURE::"Machine-specific absolute paths allowed only in local fields."
    STRUCTURE::"Do not call adapters directly."
    TESTS::["tests/storage/test_projection.py"]

  MODIFIED_FILE
    PATH::"src/hestai_context_mcp/core/redaction.py"
    PURPOSE::"Expose redaction engine name/version and provenance-friendly redaction result."
    R_TRACE::[R6]
    EDIT_RULE::"Keep existing redact/copy_and_redact behavior backward compatible."
    EDIT_RULE::"Add deterministic ruleset hash support through provenance module if possible."
    EDIT_RULE::"Do not weaken fail-closed archive behavior."
    TESTS::["tests/core/test_redaction.py", "tests/storage/test_provenance.py"]

  MODIFIED_FILE
    PATH::"src/hestai_context_mcp/core/session.py"
    PURPOSE::"Ensure portable directories exist during structure creation."
    R_TRACE::[R5,R7]
    EDIT_RULE::"Extend _ensure_state_directory to create portable/outbox and portable/snapshots."
    EDIT_RULE::"Do not create portable dirs from get_context."
    EDIT_RULE::"Do not change session_id generation."
    TESTS::["tests/unit/core/test_session.py", "tests/storage/test_snapshots.py"]

  MODIFIED_FILE
    PATH::"src/hestai_context_mcp/core/context_steward.py"
    PURPOSE::"Integrate Context Projection rebuild seam without breaking workflow parsing."
    R_TRACE::[R1,R4,R5,R8,R9]
    EDIT_RULE::"Prefer adding a small pure projection entrypoint or delegating to storage.projection."
    EDIT_RULE::"Keep existing synthesize_active_state behavior untouched."
    EDIT_RULE::"Do not introduce adapter dependency into ContextSteward."
    TESTS::["tests/core/test_context_steward.py", "tests/storage/test_projection.py"]

  MODIFIED_FILE
    PATH::"src/hestai_context_mcp/tools/clock_in.py"
    PURPOSE::"Restore portable artifacts through LocalFilesystemAdapter and bind named snapshot."
    R_TRACE::[R3,R4,R5,R8,R9,R10]
    EDIT_RULE::"Validate input as today before PSS work."
    EDIT_RULE::"Create/resolve session identity before restore."
    EDIT_RULE::"Restore before final context response construction."
    EDIT_RULE::"Create snapshot bound to session_id after session creation."
    EDIT_RULE::"Return portable_state metadata without removing existing fields."
    TESTS::["tests/tools/test_clock_in.py", "tests/integration/test_clock_in_portable_state.py"]

  MODIFIED_FILE
    PATH::"src/hestai_context_mcp/tools/clock_out.py"
    PURPOSE::"Publish Portable Memory Artifacts after local archive."
    R_TRACE::[R5,R6,R7,R8,R9,R10]
    EDIT_RULE::"Keep local archive and learnings index behavior."
    EDIT_RULE::"Build artifact only after redaction succeeds and provenance is complete."
    EDIT_RULE::"Write to LocalFilesystemAdapter."
    EDIT_RULE::"Queue outbox on publish failure after local archive success."
    EDIT_RULE::"Expose portable publication status."
    TESTS::["tests/unit/tools/test_clock_out.py", "tests/integration/test_clock_out_portable_publish.py"]

  MODIFIED_FILE
    PATH::"src/hestai_context_mcp/tools/get_context.py"
    PURPOSE::"Read local snapshot/projection only; never call adapter."
    R_TRACE::[R5,R10]
    EDIT_RULE::"Preserve public signature unless critical-engineer approves otherwise."
    EDIT_RULE::"No StorageAdapter import."
    EDIT_RULE::"No storage.local_filesystem import."
    EDIT_RULE::"No file writes."
    EDIT_RULE::"No outbox mutation."
    TESTS::["tests/tools/test_get_context.py", "tests/integration/test_get_context_purity.py"]

  MODIFIED_FILE
    PATH::"src/hestai_context_mcp/server.py"
    PURPOSE::"Registration review."
    R_TRACE::[R2,R5,R12]
    EDIT_RULE::"No new public MCP tool in B1 unless explicitly approved."
    EDIT_RULE::"No Publish Portable State or Restore Portable State tool in B1."
    EDIT_RULE::"Existing four-tool registration should remain stable."
    TESTS::["tests/test_server.py"]

  NEW_TEST_DIR
    PATH::"tests/storage/"
    PURPOSE::"B1 PSS storage foundation tests."
    R_TRACE::[R1,R2,R3,R4,R6,R7,R8,R9,R10,R11]
    FILES::[
      "test_storage_package_exports.py",
      "test_types_contract.py",
      "test_storage_protocol.py",
      "test_identity.py",
      "test_schema.py",
      "test_provenance.py",
      "test_local_filesystem_adapter.py",
      "test_outbox.py",
      "test_snapshots.py",
      "test_classification.py",
      "test_projection.py",
      "test_source_invariants_pss.py"
    ]

  NEW_INTEGRATION_TESTS
    PATH::"tests/integration/"
    PURPOSE::"Tool lifecycle tests for PSS."
    FILES::[
      "test_clock_in_portable_state.py",
      "test_clock_out_portable_publish.py",
      "test_get_context_purity.py",
      "test_pss_lifecycle_local_filesystem.py"
    ]

  NO_NEW_RUNTIME_DEPENDENCIES
    RULE_001::"Use dataclasses, pathlib, json, hashlib, tempfile, datetime, typing."
    RULE_002::"Do not add remote SDKs."
    RULE_003::"Do not add file locking packages."
    RULE_004::"Do not add crypto packages for B1 local adapter."
    RULE_005::"Do not add GitPython or shell git dependency for storage."

§PROTOCOL_SIGNATURES
```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, Mapping, Protocol, TypeAlias, runtime_checkable

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = Mapping[str, JsonValue]


class StateClassification(StrEnum):
    LOCAL_MUTABLE = "LOCAL_MUTABLE"
    PORTABLE_MEMORY = "PORTABLE_MEMORY"
    DERIVED_PROJECTION = "DERIVED_PROJECTION"


class ArtifactKind(StrEnum):
    PORTABLE_MEMORY = "portable_memory"
    TOMBSTONE = "tombstone"


class PublishStatus(StrEnum):
    PUBLISHED = "published"
    QUEUED = "queued"
    DUPLICATE = "duplicate"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class StorageCapabilities:
    strong_list_consistency: bool
    atomic_compare_and_swap: bool
    conditional_writes: bool
    advisory_locking: bool
    streaming_writes: bool
    encryption_at_rest: bool
    encryption_in_transit: bool
    hard_delete: bool
    read_only: bool


@dataclass(frozen=True, slots=True)
class IdentityTuple:
    project_id: str
    workspace_id: str
    user_id: str
    state_schema_version: int
    carrier_namespace: str


@dataclass(frozen=True, slots=True)
class PortableNamespace:
    project_id: str
    workspace_id: str
    user_id: str
    state_schema_version: int
    carrier_namespace: str


@dataclass(frozen=True, slots=True)
class RedactionProvenance:
    engine_name: str
    engine_version: str
    ruleset_hash: str
    input_artifact_hash: str
    output_artifact_hash: str
    redacted_at: datetime
    classification_label: Literal["PORTABLE_MEMORY"]
    redacted_credential_categories: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    artifact_id: str
    identity: IdentityTuple
    artifact_kind: ArtifactKind
    sequence_id: int
    created_at: datetime
    payload_hash: str
    carrier_path: str


@dataclass(frozen=True, slots=True)
class PortableMemoryArtifact:
    artifact_id: str
    artifact_kind: Literal[ArtifactKind.PORTABLE_MEMORY]
    identity: IdentityTuple
    schema_version: int
    producer_version: str
    minimum_reader_version: int
    created_at: datetime
    sequence_id: int
    parent_ids: tuple[str, ...]
    redaction_provenance: RedactionProvenance
    classification_label: Literal["PORTABLE_MEMORY"]
    payload_hash: str
    payload: JsonObject


@dataclass(frozen=True, slots=True)
class TombstoneArtifact:
    artifact_id: str
    artifact_kind: Literal[ArtifactKind.TOMBSTONE]
    identity: IdentityTuple
    schema_version: int
    producer_version: str
    minimum_reader_version: int
    created_at: datetime
    sequence_id: int
    parent_ids: tuple[str, ...]
    target_artifact_id: str
    reason: str
    publisher_identity: IdentityTuple
    redaction_provenance: RedactionProvenance | None
    classification_label: Literal["PORTABLE_MEMORY"]
    payload_hash: str


@dataclass(frozen=True, slots=True)
class WritePrecondition:
    if_absent: bool = True
    expected_current_hash: str | None = None
    expected_parent_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PublishAck:
    artifact_id: str
    identity: IdentityTuple
    carrier_namespace: str
    sequence_id: int
    status: PublishStatus
    durable_carrier_receipt: str | None
    queued_path: str | None
    published_at: datetime | None
    error_code: str | None
    error_message: str | None


PortableArtifact: TypeAlias = PortableMemoryArtifact | TombstoneArtifact


@runtime_checkable
class StorageAdapter(Protocol):
    capabilities: StorageCapabilities

    def list_artifacts(
        self,
        namespace: PortableNamespace,
        after_id: str | None = None,
    ) -> list[ArtifactRef]:
        """List artifacts in deterministic monotonic order."""
        ...

    def read_artifact(self, ref: ArtifactRef) -> PortableArtifact:
        """Read the artifact identified by ref."""
        ...

    def write_artifact(
        self,
        ref: ArtifactRef,
        artifact: PortableMemoryArtifact,
        precondition: WritePrecondition,
    ) -> PublishAck:
        """Write a provenance-validated Portable Memory Artifact."""
        ...

    def write_tombstone(
        self,
        ref: ArtifactRef,
        tombstone: TombstoneArtifact,
        precondition: WritePrecondition,
    ) -> PublishAck:
        """Append a tombstone artifact without overwriting the target."""
        ...
```

  SIGNATURE_NOTES
    NOTE_001::"The StorageAdapter method set is R2-shaped."
    NOTE_002::"read_artifact returns PortableArtifact so R8 tombstones can be hydrated."
    NOTE_003::"This union return is a B1 formalization of R2 plus R8 and requires CE acknowledgement."
    NOTE_004::"No remote carrier fields are included."
    NOTE_005::"carrier_path is an abstract local/path-like receipt, not a RemoteHTTP wire format."
    NOTE_006::"PortableNamespace repeats IdentityTuple fields to keep list_artifacts namespace explicit."
    NOTE_007::"Identity validation must assert PortableNamespace equals artifact.identity."
    NOTE_008::"classification_label uses the ADR string value, not a UX taxonomy."
    NOTE_009::"RedactionProvenance categories may be empty when no credentials were detected."
    NOTE_010::"Complete provenance still requires engine, version, ruleset hash, hashes, timestamp, label."
    NOTE_011::"Tombstone redaction_provenance is nullable except when reason represents post-hoc redaction failure."
    NOTE_012::"WritePrecondition defaults to append/create semantics."
    NOTE_013::"PublishAck.QUEUED is used when outbox durability succeeds after publish failure."
    NOTE_014::"PublishAck.FAILED is used only when neither publish nor outbox durability succeeds."

§TDD_TEST_LIST
  ORDERING_RULE
    RULE_001::"Every group starts RED before implementation in its component."
    RULE_002::"Run smallest focused test file first."
    RULE_003::"After GREEN, run related integration tests."
    RULE_004::"Before B2 gate, run full pytest, ruff, black --check, mypy."
    RULE_005::"R10 invariant tests are acceptance criteria, not optional coverage."

  GROUP_001_TYPES_CONTRACT
    TEST_001
      FILE::"tests/storage/test_types_contract.py"
      NAME::"test_storage_capabilities_has_required_matrix_fields"
      RED_EXPECTATION::"Import fails before StorageCapabilities exists."
      R_TRACE::[R2]
    TEST_002
      FILE::"tests/storage/test_types_contract.py"
      NAME::"test_identity_tuple_contains_all_r3_fields"
      RED_EXPECTATION::"IdentityTuple is missing before implementation."
      R_TRACE::[R3]
    TEST_003
      FILE::"tests/storage/test_types_contract.py"
      NAME::"test_portable_namespace_contains_all_adapter_scope_fields"
      RED_EXPECTATION::"PortableNamespace is missing before implementation."
      R_TRACE::[R2,R3]
    TEST_004
      FILE::"tests/storage/test_types_contract.py"
      NAME::"test_redaction_provenance_contains_all_r6_fields"
      RED_EXPECTATION::"RedactionProvenance is missing before implementation."
      R_TRACE::[R6]
    TEST_005
      FILE::"tests/storage/test_types_contract.py"
      NAME::"test_artifact_ref_contains_sequence_identity_kind_and_hash"
      RED_EXPECTATION::"ArtifactRef is missing before implementation."
      R_TRACE::[R2,R3,R9]
    TEST_006
      FILE::"tests/storage/test_types_contract.py"
      NAME::"test_portable_memory_artifact_contains_all_r4_fields"
      RED_EXPECTATION::"PortableMemoryArtifact is missing before implementation."
      R_TRACE::[R4,R6]
    TEST_007
      FILE::"tests/storage/test_types_contract.py"
      NAME::"test_tombstone_artifact_contains_target_reason_publisher_and_hash"
      RED_EXPECTATION::"TombstoneArtifact is missing before implementation."
      R_TRACE::[R8]
    TEST_008
      FILE::"tests/storage/test_types_contract.py"
      NAME::"test_publish_ack_contains_acknowledgement_and_queue_fields"
      RED_EXPECTATION::"PublishAck is missing before implementation."
      R_TRACE::[R7]
    TEST_009
      FILE::"tests/storage/test_types_contract.py"
      NAME::"test_write_precondition_defaults_to_append_create_only"
      RED_EXPECTATION::"WritePrecondition is missing before implementation."
      R_TRACE::[R2,R9]
    TEST_010
      FILE::"tests/storage/test_types_contract.py"
      NAME::"test_portable_artifact_union_accepts_memory_or_tombstone"
      RED_EXPECTATION::"PortableArtifact alias missing before implementation."
      R_TRACE::[R2,R8]
    TEST_011
      FILE::"tests/storage/test_types_contract.py"
      NAME::"test_classification_enum_contains_three_r1_tiers"
      RED_EXPECTATION::"StateClassification is missing before implementation."
      R_TRACE::[R1]
    TEST_012
      FILE::"tests/storage/test_types_contract.py"
      NAME::"test_publish_status_enum_contains_published_queued_duplicate_failed"
      RED_EXPECTATION::"PublishStatus is missing before implementation."
      R_TRACE::[R7]

  GROUP_002_PROTOCOL
    TEST_013
      FILE::"tests/storage/test_storage_protocol.py"
      NAME::"test_storage_adapter_protocol_is_runtime_checkable"
      RED_EXPECTATION::"StorageAdapter import fails before protocol exists."
      R_TRACE::[R2]
    TEST_014
      FILE::"tests/storage/test_storage_protocol.py"
      NAME::"test_storage_adapter_protocol_requires_capabilities_attribute"
      RED_EXPECTATION::"Stub without capabilities passes before enforcement."
      R_TRACE::[R2]
    TEST_015
      FILE::"tests/storage/test_storage_protocol.py"
      NAME::"test_storage_adapter_protocol_lists_artifacts_by_namespace"
      RED_EXPECTATION::"Protocol method missing before implementation."
      R_TRACE::[R2,R3]
    TEST_016
      FILE::"tests/storage/test_storage_protocol.py"
      NAME::"test_storage_adapter_protocol_reads_portable_artifact_union"
      RED_EXPECTATION::"read_artifact signature unavailable."
      R_TRACE::[R2,R8]
    TEST_017
      FILE::"tests/storage/test_storage_protocol.py"
      NAME::"test_storage_adapter_protocol_writes_memory_artifact_with_precondition"
      RED_EXPECTATION::"write_artifact signature unavailable."
      R_TRACE::[R2,R6,R9]
    TEST_018
      FILE::"tests/storage/test_storage_protocol.py"
      NAME::"test_storage_adapter_protocol_writes_tombstone_with_precondition"
      RED_EXPECTATION::"write_tombstone signature unavailable."
      R_TRACE::[R2,R8,R9]
    TEST_019
      FILE::"tests/storage/test_storage_protocol.py"
      NAME::"test_protocol_module_contains_no_remote_adapter_names"
      RED_EXPECTATION::"Fails until invariant scan is added."
      R_TRACE::[R2,R12]
    TEST_020
      FILE::"tests/storage/test_storage_protocol.py"
      NAME::"test_protocol_module_contains_no_git_ref_storage_language"
      RED_EXPECTATION::"Fails until source invariant exists."
      R_TRACE::[R11]

  GROUP_003_IDENTITY_VALIDATION
    TEST_021
      FILE::"tests/storage/test_identity.py"
      NAME::"test_valid_identity_tuple_passes_validation"
      RED_EXPECTATION::"validate_identity_tuple is missing."
      R_TRACE::[R3]
    TEST_022
      FILE::"tests/storage/test_identity.py"
      NAME::"test_blank_project_id_is_rejected"
      RED_EXPECTATION::"Blank project id not rejected before implementation."
      R_TRACE::[R3]
    TEST_023
      FILE::"tests/storage/test_identity.py"
      NAME::"test_blank_workspace_id_is_rejected"
      RED_EXPECTATION::"Blank workspace id not rejected before implementation."
      R_TRACE::[R3]
    TEST_024
      FILE::"tests/storage/test_identity.py"
      NAME::"test_blank_user_id_is_rejected"
      RED_EXPECTATION::"Blank user id not rejected before implementation."
      R_TRACE::[R3]
    TEST_025
      FILE::"tests/storage/test_identity.py"
      NAME::"test_blank_carrier_namespace_is_rejected"
      RED_EXPECTATION::"Blank carrier namespace not rejected before implementation."
      R_TRACE::[R3]
    TEST_026
      FILE::"tests/storage/test_identity.py"
      NAME::"test_unsupported_schema_version_is_rejected"
      RED_EXPECTATION::"Unsupported schema version not rejected before implementation."
      R_TRACE::[R3,R4]
    TEST_027
      FILE::"tests/storage/test_identity.py"
      NAME::"test_path_separator_in_identity_component_is_rejected"
      RED_EXPECTATION::"Unsafe path component not rejected before implementation."
      R_TRACE::[R3]
    TEST_028
      FILE::"tests/storage/test_identity.py"
      NAME::"test_dot_dot_in_identity_component_is_rejected"
      RED_EXPECTATION::"Traversal component not rejected before implementation."
      R_TRACE::[R3]
    TEST_029
      FILE::"tests/storage/test_identity.py"
      NAME::"test_control_character_in_identity_component_is_rejected"
      RED_EXPECTATION::"Control character not rejected before implementation."
      R_TRACE::[R3]
    TEST_030
      FILE::"tests/storage/test_identity.py"
      NAME::"test_namespace_and_identity_mismatch_is_structured_error"
      RED_EXPECTATION::"Mismatch falls through before implementation."
      R_TRACE::[R3,R10]
    TEST_031
      FILE::"tests/storage/test_identity.py"
      NAME::"test_restore_identity_mismatch_does_not_return_empty_success"
      RED_EXPECTATION::"No restore error type before implementation."
      R_TRACE::[R3,R10]
    TEST_032
      FILE::"tests/storage/test_identity.py"
      NAME::"test_identity_validation_has_no_filesystem_side_effects"
      RED_EXPECTATION::"Helper missing before implementation."
      R_TRACE::[R3,R10]

  GROUP_004_SCHEMA_AND_MIGRATION
    TEST_033
      FILE::"tests/storage/test_schema.py"
      NAME::"test_current_schema_version_is_one"
      RED_EXPECTATION::"CURRENT_SCHEMA_VERSION missing."
      R_TRACE::[R4]
    TEST_034
      FILE::"tests/storage/test_schema.py"
      NAME::"test_v1_artifact_supported_by_reader"
      RED_EXPECTATION::"Schema support function missing."
      R_TRACE::[R4]
    TEST_035
      FILE::"tests/storage/test_schema.py"
      NAME::"test_minimum_reader_version_above_supported_fails_closed"
      RED_EXPECTATION::"Too-new artifact is not rejected before implementation."
      R_TRACE::[R4,R10]
    TEST_036
      FILE::"tests/storage/test_schema.py"
      NAME::"test_schema_too_new_error_is_structured"
      RED_EXPECTATION::"schema_too_new error type missing."
      R_TRACE::[R4,R10]
    TEST_037
      FILE::"tests/storage/test_schema.py"
      NAME::"test_unknown_optional_fields_ignored_when_min_reader_allows"
      RED_EXPECTATION::"Artifact parser missing."
      R_TRACE::[R4]
    TEST_038
      FILE::"tests/storage/test_schema.py"
      NAME::"test_v1_migration_returns_projection_artifact_without_rewriting_source"
      RED_EXPECTATION::"Migration registry missing."
      R_TRACE::[R4]
    TEST_039
      FILE::"tests/storage/test_schema.py"
      NAME::"test_migration_registry_has_entry_for_v1"
      RED_EXPECTATION::"Registry missing."
      R_TRACE::[R4]
    TEST_040
      FILE::"tests/storage/test_schema.py"
      NAME::"test_schema_validation_rejects_identity_schema_mismatch"
      RED_EXPECTATION::"Identity/schema mismatch not rejected."
      R_TRACE::[R3,R4]
    TEST_041
      FILE::"tests/storage/test_schema.py"
      NAME::"test_schema_validation_rejects_missing_payload_hash"
      RED_EXPECTATION::"Missing hash not rejected."
      R_TRACE::[R4]
    TEST_042
      FILE::"tests/storage/test_schema.py"
      NAME::"test_schema_validation_rejects_negative_sequence_id"
      RED_EXPECTATION::"Negative sequence not rejected."
      R_TRACE::[R4,R9]
    TEST_043
      FILE::"tests/storage/test_schema.py"
      NAME::"test_schema_validation_rejects_non_portable_classification"
      RED_EXPECTATION::"Wrong classification not rejected."
      R_TRACE::[R1,R4]
    TEST_044
      FILE::"tests/storage/test_schema.py"
      NAME::"test_restore_failure_is_not_silent_empty_projection"
      RED_EXPECTATION::"Hydration failure path missing."
      R_TRACE::[R4,R10]

  GROUP_005_REDACTION_PROVENANCE
    TEST_045
      FILE::"tests/storage/test_provenance.py"
      NAME::"test_ruleset_hash_is_deterministic_for_redaction_patterns"
      RED_EXPECTATION::"Ruleset hash helper missing."
      R_TRACE::[R6]
    TEST_046
      FILE::"tests/storage/test_provenance.py"
      NAME::"test_redaction_provenance_contains_engine_name_and_version"
      RED_EXPECTATION::"Engine metadata missing."
      R_TRACE::[R6]
    TEST_047
      FILE::"tests/storage/test_provenance.py"
      NAME::"test_redaction_provenance_contains_input_and_output_hashes"
      RED_EXPECTATION::"Hash builder missing."
      R_TRACE::[R6]
    TEST_048
      FILE::"tests/storage/test_provenance.py"
      NAME::"test_redaction_provenance_timestamp_is_timezone_aware"
      RED_EXPECTATION::"Timestamp not available."
      R_TRACE::[R6]
    TEST_049
      FILE::"tests/storage/test_provenance.py"
      NAME::"test_redaction_provenance_classification_must_be_portable_memory"
      RED_EXPECTATION::"Classification gate missing."
      R_TRACE::[R1,R6]
    TEST_050
      FILE::"tests/storage/test_provenance.py"
      NAME::"test_redacted_categories_can_be_empty_but_not_none"
      RED_EXPECTATION::"Category normalization missing."
      R_TRACE::[R6]
    TEST_051
      FILE::"tests/storage/test_provenance.py"
      NAME::"test_missing_engine_name_fails_complete_provenance_validation"
      RED_EXPECTATION::"Validation missing."
      R_TRACE::[R6,R10]
    TEST_052
      FILE::"tests/storage/test_provenance.py"
      NAME::"test_missing_ruleset_hash_fails_complete_provenance_validation"
      RED_EXPECTATION::"Validation missing."
      R_TRACE::[R6,R10]
    TEST_053
      FILE::"tests/storage/test_provenance.py"
      NAME::"test_missing_input_hash_fails_complete_provenance_validation"
      RED_EXPECTATION::"Validation missing."
      R_TRACE::[R6,R10]
    TEST_054
      FILE::"tests/storage/test_provenance.py"
      NAME::"test_missing_output_hash_fails_complete_provenance_validation"
      RED_EXPECTATION::"Validation missing."
      R_TRACE::[R6,R10]
    TEST_055
      FILE::"tests/storage/test_provenance.py"
      NAME::"test_stale_ruleset_hash_fails_publication_validation"
      RED_EXPECTATION::"Stale provenance not detected before implementation."
      R_TRACE::[R6]
    TEST_056
      FILE::"tests/storage/test_provenance.py"
      NAME::"test_existing_redaction_engine_redacted_types_feed_provenance_categories"
      RED_EXPECTATION::"Integration helper missing."
      R_TRACE::[R6]

  GROUP_006_LOCAL_FILESYSTEM_ADAPTER_CAPABILITIES
    TEST_057
      FILE::"tests/storage/test_local_filesystem_adapter.py"
      NAME::"test_local_filesystem_adapter_implements_storage_adapter_protocol"
      RED_EXPECTATION::"LocalFilesystemAdapter missing."
      R_TRACE::[R2]
    TEST_058
      FILE::"tests/storage/test_local_filesystem_adapter.py"
      NAME::"test_local_filesystem_capabilities_meet_required_publication_matrix"
      RED_EXPECTATION::"Capabilities missing."
      R_TRACE::[R2]
    TEST_059
      FILE::"tests/storage/test_local_filesystem_adapter.py"
      NAME::"test_local_filesystem_encryption_capabilities_are_false_for_local_policy"
      RED_EXPECTATION::"Capability values missing."
      R_TRACE::[R2]
    TEST_060
      FILE::"tests/storage/test_local_filesystem_adapter.py"
      NAME::"test_local_filesystem_has_strong_list_consistency"
      RED_EXPECTATION::"Capability values missing."
      R_TRACE::[R2]
    TEST_061
      FILE::"tests/storage/test_local_filesystem_adapter.py"
      NAME::"test_local_filesystem_conditional_writes_required"
      RED_EXPECTATION::"Capability values missing."
      R_TRACE::[R2,R9]
    TEST_062
      FILE::"tests/storage/test_local_filesystem_adapter.py"
      NAME::"test_local_filesystem_uses_portable_state_root_only"
      RED_EXPECTATION::"Root path helper missing."
      R_TRACE::[R1,R2]
    TEST_063
      FILE::"tests/storage/test_local_filesystem_adapter.py"
      NAME::"test_local_filesystem_rejects_unsafe_namespace_before_path_construction"
      RED_EXPECTATION::"Unsafe namespace not rejected."
      R_TRACE::[R3]
    TEST_064
      FILE::"tests/storage/test_local_filesystem_adapter.py"
      NAME::"test_local_filesystem_write_creates_artifact_file"
      RED_EXPECTATION::"write_artifact missing."
      R_TRACE::[R2,R9]
    TEST_065
      FILE::"tests/storage/test_local_filesystem_adapter.py"
      NAME::"test_local_filesystem_write_returns_publish_ack"
      RED_EXPECTATION::"No PublishAck returned."
      R_TRACE::[R7]
    TEST_066
      FILE::"tests/storage/test_local_filesystem_adapter.py"
      NAME::"test_local_filesystem_write_fails_without_complete_redaction_provenance"
      RED_EXPECTATION::"Missing provenance accepted before implementation."
      R_TRACE::[R6,R10]
    TEST_067
      FILE::"tests/storage/test_local_filesystem_adapter.py"
      NAME::"test_local_filesystem_write_is_create_only_by_default"
      RED_EXPECTATION::"Overwrite allowed before implementation."
      R_TRACE::[R2,R9]
    TEST_068
      FILE::"tests/storage/test_local_filesystem_adapter.py"
      NAME::"test_duplicate_artifact_id_same_hash_is_idempotent_duplicate_ack"
      RED_EXPECTATION::"Duplicate handling missing."
      R_TRACE::[R9]
    TEST_069
      FILE::"tests/storage/test_local_filesystem_adapter.py"
      NAME::"test_duplicate_artifact_id_different_hash_fails_precondition"
      RED_EXPECTATION::"Conflicting overwrite allowed."
      R_TRACE::[R2,R9]
    TEST_070
      FILE::"tests/storage/test_local_filesystem_adapter.py"
      NAME::"test_list_artifacts_returns_monotonic_sequence_order"
      RED_EXPECTATION::"List not implemented."
      R_TRACE::[R2,R9]
    TEST_071
      FILE::"tests/storage/test_local_filesystem_adapter.py"
      NAME::"test_list_artifacts_after_id_filters_exclusive"
      RED_EXPECTATION::"after_id ignored before implementation."
      R_TRACE::[R2]
    TEST_072
      FILE::"tests/storage/test_local_filesystem_adapter.py"
      NAME::"test_read_artifact_validates_payload_hash"
      RED_EXPECTATION::"Read validation missing."
      R_TRACE::[R4,R9]
    TEST_073
      FILE::"tests/storage/test_local_filesystem_adapter.py"
      NAME::"test_read_artifact_rejects_identity_mismatch"
      RED_EXPECTATION::"Mismatch accepted before implementation."
      R_TRACE::[R3]
    TEST_074
      FILE::"tests/storage/test_local_filesystem_adapter.py"
      NAME::"test_write_tombstone_appends_tombstone_file"
      RED_EXPECTATION::"write_tombstone missing."
      R_TRACE::[R8,R9]
    TEST_075
      FILE::"tests/storage/test_local_filesystem_adapter.py"
      NAME::"test_write_tombstone_does_not_delete_target_artifact"
      RED_EXPECTATION::"Deletion semantics undefined."
      R_TRACE::[R8,R9]
    TEST_076
      FILE::"tests/storage/test_local_filesystem_adapter.py"
      NAME::"test_write_tombstone_for_redaction_failure_requires_provenance"
      RED_EXPECTATION::"Redaction failure tombstone accepted without provenance."
      R_TRACE::[R6,R8]
    TEST_077
      FILE::"tests/storage/test_local_filesystem_adapter.py"
      NAME::"test_adapter_never_shells_out_to_git"
      RED_EXPECTATION::"Source invariant missing."
      R_TRACE::[R11]
    TEST_078
      FILE::"tests/storage/test_local_filesystem_adapter.py"
      NAME::"test_adapter_has_no_network_imports"
      RED_EXPECTATION::"Source invariant missing."
      R_TRACE::[R12]

  GROUP_007_OUTBOX
    TEST_079
      FILE::"tests/storage/test_outbox.py"
      NAME::"test_outbox_root_is_hestai_state_portable_outbox"
      RED_EXPECTATION::"Outbox path helper missing."
      R_TRACE::[R7]
    TEST_080
      FILE::"tests/storage/test_outbox.py"
      NAME::"test_enqueue_unpublished_artifact_writes_json_by_artifact_id"
      RED_EXPECTATION::"Enqueue helper missing."
      R_TRACE::[R7]
    TEST_081
      FILE::"tests/storage/test_outbox.py"
      NAME::"test_enqueue_uses_atomic_replace"
      RED_EXPECTATION::"Atomic write behavior missing."
      R_TRACE::[R7]
    TEST_082
      FILE::"tests/storage/test_outbox.py"
      NAME::"test_outbox_entry_contains_artifact_ack_error_and_retry_metadata"
      RED_EXPECTATION::"Entry shape missing."
      R_TRACE::[R7]
    TEST_083
      FILE::"tests/storage/test_outbox.py"
      NAME::"test_outbox_status_true_when_entries_exist"
      RED_EXPECTATION::"Status helper missing."
      R_TRACE::[R7]
    TEST_084
      FILE::"tests/storage/test_outbox.py"
      NAME::"test_outbox_status_false_when_empty"
      RED_EXPECTATION::"Status helper missing."
      R_TRACE::[R7]
    TEST_085
      FILE::"tests/storage/test_outbox.py"
      NAME::"test_list_outbox_entries_is_deterministic"
      RED_EXPECTATION::"Ordering missing."
      R_TRACE::[R7]
    TEST_086
      FILE::"tests/storage/test_outbox.py"
      NAME::"test_outbox_unknown_entry_parse_error_is_structured"
      RED_EXPECTATION::"Parse error handling missing."
      R_TRACE::[R7,R10]
    TEST_087
      FILE::"tests/storage/test_outbox.py"
      NAME::"test_outbox_is_classified_local_mutable"
      RED_EXPECTATION::"Classification helper missing."
      R_TRACE::[R1,R7]
    TEST_088
      FILE::"tests/storage/test_outbox.py"
      NAME::"test_get_context_does_not_touch_outbox_mtime"
      RED_EXPECTATION::"Purity invariant not enforced."
      R_TRACE::[R7,R10]

  GROUP_008_SNAPSHOTS
    TEST_089
      FILE::"tests/storage/test_snapshots.py"
      NAME::"test_create_session_snapshot_writes_under_session_id"
      RED_EXPECTATION::"Snapshot helper missing."
      R_TRACE::[R5]
    TEST_090
      FILE::"tests/storage/test_snapshots.py"
      NAME::"test_snapshot_metadata_records_identity_tuple"
      RED_EXPECTATION::"Metadata missing."
      R_TRACE::[R3,R5]
    TEST_091
      FILE::"tests/storage/test_snapshots.py"
      NAME::"test_snapshot_metadata_records_artifact_refs"
      RED_EXPECTATION::"Artifact refs missing."
      R_TRACE::[R5,R9]
    TEST_092
      FILE::"tests/storage/test_snapshots.py"
      NAME::"test_snapshot_metadata_records_created_at"
      RED_EXPECTATION::"Timestamp missing."
      R_TRACE::[R5]
    TEST_093
      FILE::"tests/storage/test_snapshots.py"
      NAME::"test_read_session_snapshot_is_pure_read"
      RED_EXPECTATION::"Read helper missing."
      R_TRACE::[R5,R10]
    TEST_094
      FILE::"tests/storage/test_snapshots.py"
      NAME::"test_snapshot_read_rejects_path_traversal_session_id"
      RED_EXPECTATION::"Session id validation missing."
      R_TRACE::[R5]
    TEST_095
      FILE::"tests/storage/test_snapshots.py"
      NAME::"test_snapshot_creation_rejects_identity_mismatch"
      RED_EXPECTATION::"Identity gate missing."
      R_TRACE::[R3,R5]
    TEST_096
      FILE::"tests/storage/test_snapshots.py"
      NAME::"test_snapshot_classified_derived_projection"
      RED_EXPECTATION::"Classification missing."
      R_TRACE::[R1,R5]
    TEST_097
      FILE::"tests/storage/test_snapshots.py"
      NAME::"test_snapshot_does_not_change_when_new_artifact_is_published_after_creation"
      RED_EXPECTATION::"Drift allowed before implementation."
      R_TRACE::[R5,R10]
    TEST_098
      FILE::"tests/storage/test_snapshots.py"
      NAME::"test_snapshot_missing_returns_structured_not_found"
      RED_EXPECTATION::"Missing snapshot behavior undefined."
      R_TRACE::[R5]

  GROUP_009_CLASSIFICATION
    TEST_099
      FILE::"tests/storage/test_classification.py"
      NAME::"test_sessions_active_session_json_is_local_mutable"
      RED_EXPECTATION::"Classification helper missing."
      R_TRACE::[R1]
    TEST_100
      FILE::"tests/storage/test_classification.py"
      NAME::"test_sessions_archive_redacted_jsonl_is_local_mutable"
      RED_EXPECTATION::"Classification helper missing."
      R_TRACE::[R1]
    TEST_101
      FILE::"tests/storage/test_classification.py"
      NAME::"test_learnings_index_is_local_mutable"
      RED_EXPECTATION::"Classification helper missing."
      R_TRACE::[R1]
    TEST_102
      FILE::"tests/storage/test_classification.py"
      NAME::"test_context_state_fast_layer_is_local_mutable"
      RED_EXPECTATION::"Classification helper missing."
      R_TRACE::[R1]
    TEST_103
      FILE::"tests/storage/test_classification.py"
      NAME::"test_portable_outbox_is_local_mutable"
      RED_EXPECTATION::"Classification helper missing."
      R_TRACE::[R1,R7]
    TEST_104
      FILE::"tests/storage/test_classification.py"
      NAME::"test_portable_artifacts_are_portable_memory"
      RED_EXPECTATION::"Classification helper missing."
      R_TRACE::[R1]
    TEST_105
      FILE::"tests/storage/test_classification.py"
      NAME::"test_portable_tombstones_are_portable_memory"
      RED_EXPECTATION::"Classification helper missing."
      R_TRACE::[R1,R8]
    TEST_106
      FILE::"tests/storage/test_classification.py"
      NAME::"test_portable_snapshots_are_derived_projection"
      RED_EXPECTATION::"Classification helper missing."
      R_TRACE::[R1,R5]
    TEST_107
      FILE::"tests/storage/test_classification.py"
      NAME::"test_materialized_project_context_from_portable_memory_is_derived_projection"
      RED_EXPECTATION::"Classification helper missing."
      R_TRACE::[R1]
    TEST_108
      FILE::"tests/storage/test_classification.py"
      NAME::"test_unknown_state_path_defaults_to_local_mutable"
      RED_EXPECTATION::"Unknown classification unsafe before implementation."
      R_TRACE::[R1]

  GROUP_010_PROJECTION_RESTORE
    TEST_109
      FILE::"tests/storage/test_projection.py"
      NAME::"test_projection_sorts_artifacts_by_sequence_then_id"
      RED_EXPECTATION::"Projection builder missing."
      R_TRACE::[R9,R10]
    TEST_110
      FILE::"tests/storage/test_projection.py"
      NAME::"test_projection_rejects_mixed_identity_artifacts"
      RED_EXPECTATION::"Identity mixing allowed before implementation."
      R_TRACE::[R3,R10]
    TEST_111
      FILE::"tests/storage/test_projection.py"
      NAME::"test_projection_applies_tombstones_before_merge"
      RED_EXPECTATION::"Tombstone filtering missing."
      R_TRACE::[R8]
    TEST_112
      FILE::"tests/storage/test_projection.py"
      NAME::"test_projection_excludes_tombstoned_memory_artifact"
      RED_EXPECTATION::"Tombstoned artifact included before implementation."
      R_TRACE::[R8]
    TEST_113
      FILE::"tests/storage/test_projection.py"
      NAME::"test_projection_preserves_tombstone_semantics_after_compaction_input"
      RED_EXPECTATION::"Compaction coverage semantics absent."
      R_TRACE::[R8,R9]
    TEST_114
      FILE::"tests/storage/test_projection.py"
      NAME::"test_duplicate_artifact_ids_same_hash_are_idempotent"
      RED_EXPECTATION::"Duplicate handling missing."
      R_TRACE::[R9]
    TEST_115
      FILE::"tests/storage/test_projection.py"
      NAME::"test_duplicate_artifact_ids_different_hash_are_structured_error"
      RED_EXPECTATION::"Conflict accepted before implementation."
      R_TRACE::[R9,R10]
    TEST_116
      FILE::"tests/storage/test_projection.py"
      NAME::"test_projection_shape_identical_across_machine_roots"
      RED_EXPECTATION::"Machine-root variance not controlled."
      R_TRACE::[R10]
    TEST_117
      FILE::"tests/storage/test_projection.py"
      NAME::"test_projection_allows_absolute_paths_only_in_explicit_local_fields"
      RED_EXPECTATION::"Path leakage not controlled."
      R_TRACE::[R1,R10]
    TEST_118
      FILE::"tests/storage/test_projection.py"
      NAME::"test_projection_failure_is_structured_not_silent_empty"
      RED_EXPECTATION::"Failure handling missing."
      R_TRACE::[R10]

  GROUP_011_CLOCK_IN_INTEGRATION
    TEST_119
      FILE::"tests/integration/test_clock_in_portable_state.py"
      NAME::"test_clock_in_creates_portable_dirs_via_session_structure"
      RED_EXPECTATION::"Portable dirs absent before implementation."
      R_TRACE::[R5,R7]
    TEST_120
      FILE::"tests/integration/test_clock_in_portable_state.py"
      NAME::"test_clock_in_restores_local_filesystem_artifacts_before_context_build"
      RED_EXPECTATION::"Restore not invoked before implementation."
      R_TRACE::[R5]
    TEST_121
      FILE::"tests/integration/test_clock_in_portable_state.py"
      NAME::"test_clock_in_creates_named_snapshot_bound_to_returned_session_id"
      RED_EXPECTATION::"Snapshot absent before implementation."
      R_TRACE::[R5]
    TEST_122
      FILE::"tests/integration/test_clock_in_portable_state.py"
      NAME::"test_clock_in_snapshot_excludes_tombstoned_artifacts"
      RED_EXPECTATION::"Tombstones ignored before implementation."
      R_TRACE::[R8]
    TEST_123
      FILE::"tests/integration/test_clock_in_portable_state.py"
      NAME::"test_clock_in_identity_mismatch_returns_structured_restore_error"
      RED_EXPECTATION::"Mismatch silently ignored before implementation."
      R_TRACE::[R3,R10]
    TEST_124
      FILE::"tests/integration/test_clock_in_portable_state.py"
      NAME::"test_clock_in_schema_too_new_returns_structured_restore_error"
      RED_EXPECTATION::"Too-new schema not handled."
      R_TRACE::[R4,R10]
    TEST_125
      FILE::"tests/integration/test_clock_in_portable_state.py"
      NAME::"test_clock_in_return_shape_preserves_existing_top_level_fields"
      RED_EXPECTATION::"Guard added before implementation."
      R_TRACE::[R5]
    TEST_126
      FILE::"tests/integration/test_clock_in_portable_state.py"
      NAME::"test_clock_in_return_includes_portable_state_metadata"
      RED_EXPECTATION::"portable_state absent."
      R_TRACE::[R5,R7]
    TEST_127
      FILE::"tests/integration/test_clock_in_portable_state.py"
      NAME::"test_clock_in_with_no_artifacts_succeeds_offline"
      RED_EXPECTATION::"No restore path before implementation."
      R_TRACE::[R5,R10]
    TEST_128
      FILE::"tests/integration/test_clock_in_portable_state.py"
      NAME::"test_clock_in_does_not_require_remote_adapter_enabled"
      RED_EXPECTATION::"Invariant missing."
      R_TRACE::[R10,R12]

  GROUP_012_CLOCK_OUT_INTEGRATION
    TEST_129
      FILE::"tests/integration/test_clock_out_portable_publish.py"
      NAME::"test_clock_out_local_archive_success_independent_from_portable_publish"
      RED_EXPECTATION::"Separable outcome missing."
      R_TRACE::[R7]
    TEST_130
      FILE::"tests/integration/test_clock_out_portable_publish.py"
      NAME::"test_clock_out_builds_artifact_after_redaction_success"
      RED_EXPECTATION::"Artifact build absent."
      R_TRACE::[R5,R6]
    TEST_131
      FILE::"tests/integration/test_clock_out_portable_publish.py"
      NAME::"test_clock_out_publishes_artifact_to_local_filesystem_adapter"
      RED_EXPECTATION::"Adapter integration absent."
      R_TRACE::[R5,R7]
    TEST_132
      FILE::"tests/integration/test_clock_out_portable_publish.py"
      NAME::"test_clock_out_return_includes_portable_publication_status"
      RED_EXPECTATION::"Return field absent."
      R_TRACE::[R7]
    TEST_133
      FILE::"tests/integration/test_clock_out_portable_publish.py"
      NAME::"test_clock_out_return_includes_unpublished_memory_exists_false_when_empty"
      RED_EXPECTATION::"Return field absent."
      R_TRACE::[R7]
    TEST_134
      FILE::"tests/integration/test_clock_out_portable_publish.py"
      NAME::"test_clock_out_publish_failure_queues_outbox_and_reports_local_success"
      RED_EXPECTATION::"Queue behavior absent."
      R_TRACE::[R7]
    TEST_135
      FILE::"tests/integration/test_clock_out_portable_publish.py"
      NAME::"test_clock_out_publish_failure_sets_unpublished_memory_exists_true"
      RED_EXPECTATION::"Unpublished status absent."
      R_TRACE::[R7]
    TEST_136
      FILE::"tests/integration/test_clock_out_portable_publish.py"
      NAME::"test_clock_out_missing_redaction_provenance_fails_publication_not_archive"
      RED_EXPECTATION::"Publication gate absent."
      R_TRACE::[R6,R7,R10]
    TEST_137
      FILE::"tests/integration/test_clock_out_portable_publish.py"
      NAME::"test_clock_out_artifact_parent_ids_include_prior_snapshot_refs"
      RED_EXPECTATION::"Parent linkage absent."
      R_TRACE::[R4,R9]
    TEST_138
      FILE::"tests/integration/test_clock_out_portable_publish.py"
      NAME::"test_clock_out_duplicate_publish_is_idempotent_same_hash"
      RED_EXPECTATION::"Duplicate semantics absent."
      R_TRACE::[R9]

  GROUP_013_GET_CONTEXT_PURITY
    TEST_139
      FILE::"tests/integration/test_get_context_purity.py"
      NAME::"test_get_context_filesystem_snapshot_diff_empty_before_after"
      RED_EXPECTATION::"R10 invariant absent."
      R_TRACE::[R10]
    TEST_140
      FILE::"tests/integration/test_get_context_purity.py"
      NAME::"test_get_context_does_not_import_storage_adapter_protocol"
      RED_EXPECTATION::"Source invariant absent."
      R_TRACE::[R5,R10]
    TEST_141
      FILE::"tests/integration/test_get_context_purity.py"
      NAME::"test_get_context_does_not_import_local_filesystem_adapter"
      RED_EXPECTATION::"Source invariant absent."
      R_TRACE::[R5,R10]
    TEST_142
      FILE::"tests/integration/test_get_context_purity.py"
      NAME::"test_get_context_does_not_create_portable_directories"
      RED_EXPECTATION::"Directory purity guard absent."
      R_TRACE::[R10]
    TEST_143
      FILE::"tests/integration/test_get_context_purity.py"
      NAME::"test_get_context_does_not_modify_snapshot_mtime"
      RED_EXPECTATION::"Snapshot read purity absent."
      R_TRACE::[R5,R10]
    TEST_144
      FILE::"tests/integration/test_get_context_purity.py"
      NAME::"test_get_context_does_not_drain_outbox"
      RED_EXPECTATION::"Outbox purity guard absent."
      R_TRACE::[R7,R10]
    TEST_145
      FILE::"tests/integration/test_get_context_purity.py"
      NAME::"test_get_context_visible_return_shape_remains_backward_compatible"
      RED_EXPECTATION::"Shape guard absent."
      R_TRACE::[R5,R10]
    TEST_146
      FILE::"tests/integration/test_get_context_purity.py"
      NAME::"test_get_context_reads_local_snapshot_when_available"
      RED_EXPECTATION::"Snapshot read absent."
      R_TRACE::[R5]
    TEST_147
      FILE::"tests/integration/test_get_context_purity.py"
      NAME::"test_get_context_without_snapshot_falls_back_to_existing_local_projection"
      RED_EXPECTATION::"Fallback undefined."
      R_TRACE::[R5,R10]
    TEST_148
      FILE::"tests/integration/test_get_context_purity.py"
      NAME::"test_get_context_never_reports_hydration_as_successful"
      RED_EXPECTATION::"Hydration boundary absent."
      R_TRACE::[R5,R10]

  GROUP_014_FULL_LOCAL_LIFECYCLE
    TEST_149
      FILE::"tests/integration/test_pss_lifecycle_local_filesystem.py"
      NAME::"test_clock_out_then_next_clock_in_restores_memory_from_local_adapter"
      RED_EXPECTATION::"End-to-end local PSS absent."
      R_TRACE::[R5,R7,R9]
    TEST_150
      FILE::"tests/integration/test_pss_lifecycle_local_filesystem.py"
      NAME::"test_tombstone_published_between_sessions_excludes_memory_on_next_clock_in"
      RED_EXPECTATION::"Tombstone lifecycle absent."
      R_TRACE::[R8]
    TEST_151
      FILE::"tests/integration/test_pss_lifecycle_local_filesystem.py"
      NAME::"test_two_machine_roots_same_artifacts_produce_same_context_shape"
      RED_EXPECTATION::"Determinism invariant absent."
      R_TRACE::[R10]
    TEST_152
      FILE::"tests/integration/test_pss_lifecycle_local_filesystem.py"
      NAME::"test_full_suite_passes_with_remote_adapters_disabled"
      RED_EXPECTATION::"Remote-disabled invariant absent."
      R_TRACE::[R10,R12]
    TEST_153
      FILE::"tests/integration/test_pss_lifecycle_local_filesystem.py"
      NAME::"test_hydration_failure_does_not_publish_over_newer_stream"
      RED_EXPECTATION::"Fail-closed stream guard absent."
      R_TRACE::[R4,R10]
    TEST_154
      FILE::"tests/integration/test_pss_lifecycle_local_filesystem.py"
      NAME::"test_restore_merges_valid_artifacts_by_identity_and_monotonic_order"
      RED_EXPECTATION::"Merge semantics absent."
      R_TRACE::[R3,R9]
    TEST_155
      FILE::"tests/integration/test_pss_lifecycle_local_filesystem.py"
      NAME::"test_restore_refuses_fork_or_workspace_identity_mismatch"
      RED_EXPECTATION::"Mismatch accepted."
      R_TRACE::[R3]
    TEST_156
      FILE::"tests/integration/test_pss_lifecycle_local_filesystem.py"
      NAME::"test_local_filesystem_mode_has_no_network_calls"
      RED_EXPECTATION::"Network guard absent."
      R_TRACE::[R12]
    TEST_157
      FILE::"tests/integration/test_pss_lifecycle_local_filesystem.py"
      NAME::"test_custom_git_ref_storage_is_not_used"
      RED_EXPECTATION::"Git ref guard absent."
      R_TRACE::[R11]
    TEST_158
      FILE::"tests/integration/test_pss_lifecycle_local_filesystem.py"
      NAME::"test_local_archive_and_session_cleanup_still_work_when_publish_queued"
      RED_EXPECTATION::"Separated lifecycle absent."
      R_TRACE::[R1,R7]

  GROUP_015_SOURCE_INVARIANTS
    TEST_159
      FILE::"tests/storage/test_source_invariants_pss.py"
      NAME::"test_no_remote_adapter_class_names_under_storage_package_except_r12_comments"
      RED_EXPECTATION::"Source invariant absent."
      R_TRACE::[R12]
    TEST_160
      FILE::"tests/storage/test_source_invariants_pss.py"
      NAME::"test_no_requests_httpx_boto_gitpython_imports_in_storage"
      RED_EXPECTATION::"Source invariant absent."
      R_TRACE::[R12]
    TEST_161
      FILE::"tests/storage/test_source_invariants_pss.py"
      NAME::"test_no_custom_git_ref_strings_in_storage_implementation"
      RED_EXPECTATION::"Source invariant absent."
      R_TRACE::[R11]
    TEST_162
      FILE::"tests/storage/test_source_invariants_pss.py"
      NAME::"test_get_context_has_no_storage_adapter_imports"
      RED_EXPECTATION::"Source invariant absent."
      R_TRACE::[R5,R10]
    TEST_163
      FILE::"tests/storage/test_source_invariants_pss.py"
      NAME::"test_clock_in_is_only_tool_allowed_to_restore_portable_state"
      RED_EXPECTATION::"Source invariant absent."
      R_TRACE::[R5]
    TEST_164
      FILE::"tests/storage/test_source_invariants_pss.py"
      NAME::"test_clock_out_is_only_tool_allowed_to_publish_portable_state"
      RED_EXPECTATION::"Source invariant absent."
      R_TRACE::[R5,R7]
    TEST_165
      FILE::"tests/storage/test_source_invariants_pss.py"
      NAME::"test_storage_protocol_has_no_provider_sdk_imports"
      RED_EXPECTATION::"Source invariant absent."
      R_TRACE::[R2,R12]
    TEST_166
      FILE::"tests/storage/test_source_invariants_pss.py"
      NAME::"test_local_filesystem_adapter_has_no_keyring_import"
      RED_EXPECTATION::"Source invariant absent."
      R_TRACE::[R12]
    TEST_167
      FILE::"tests/storage/test_source_invariants_pss.py"
      NAME::"test_no_new_tool_registration_for_publish_or_restore"
      RED_EXPECTATION::"Server guard absent."
      R_TRACE::[R5,R12]
    TEST_168
      FILE::"tests/storage/test_source_invariants_pss.py"
      NAME::"test_no_hestai_mcp_imports_added_by_pss"
      RED_EXPECTATION::"Existing invariant covers broad case; PSS guard absent."
      R_TRACE::[R10]

  R10_ACCEPTANCE_INVARIANTS
    INVARIANT_001
      TEST::"tests/integration/test_get_context_purity.py::test_get_context_filesystem_snapshot_diff_empty_before_after"
      REQUIREMENT::"Filesystem snapshot diff is empty before and after get_context."
      R_TRACE::[R10]
      STATUS::MUST_BE_RED_FIRST
    INVARIANT_002
      TEST::"tests/integration/test_pss_lifecycle_local_filesystem.py::test_full_suite_passes_with_remote_adapters_disabled"
      REQUIREMENT::"Full test suite passes with remote adapters disabled."
      R_TRACE::[R10,R12]
      STATUS::MUST_BE_RED_FIRST
    INVARIANT_003
      TEST::"tests/storage/test_local_filesystem_adapter.py::test_local_filesystem_write_fails_without_complete_redaction_provenance"
      REQUIREMENT::"write_artifact fails closed without redaction provenance metadata."
      R_TRACE::[R6,R10]
      STATUS::MUST_BE_RED_FIRST
    INVARIANT_004
      TEST::"tests/integration/test_pss_lifecycle_local_filesystem.py::test_two_machine_roots_same_artifacts_produce_same_context_shape"
      REQUIREMENT::"Same Portable Memory Artifacts on different machines produce identical context shape."
      R_TRACE::[R10]
      STATUS::MUST_BE_RED_FIRST
    INVARIANT_005
      TEST::"tests/storage/test_projection.py::test_projection_failure_is_structured_not_silent_empty"
      REQUIREMENT::"Hydration failure produces structured error, not silent empty fallback."
      R_TRACE::[R10]
      STATUS::MUST_BE_RED_FIRST

§INTEGRATION_PLAN
  SEQUENCE_OVERVIEW
    STEP_001::"Write RED tests for storage type contract."
    STEP_002::"Implement storage/types.py until type tests pass."
    STEP_003::"Write RED protocol tests and source invariants."
    STEP_004::"Implement storage/protocol.py exports."
    STEP_005::"Write RED identity tests."
    STEP_006::"Implement identity validation."
    STEP_007::"Write RED schema tests."
    STEP_008::"Implement schema registry and v1 migration framework."
    STEP_009::"Write RED provenance tests."
    STEP_010::"Implement provenance builder and validation."
    STEP_011::"Write RED LocalFilesystemAdapter tests."
    STEP_012::"Implement local adapter with append-first writes."
    STEP_013::"Write RED outbox tests."
    STEP_014::"Implement durable outbox."
    STEP_015::"Write RED snapshot tests."
    STEP_016::"Implement snapshot helpers."
    STEP_017::"Write RED projection tests."
    STEP_018::"Implement deterministic projection builder."
    STEP_019::"Write RED clock_in integration tests."
    STEP_020::"Integrate restore and named snapshot into clock_in."
    STEP_021::"Write RED clock_out integration tests."
    STEP_022::"Integrate artifact publication and outbox into clock_out."
    STEP_023::"Write RED get_context purity tests."
    STEP_024::"Integrate local snapshot read only if CE approves resolver semantics."
    STEP_025::"Run full checks."

  CLOCK_IN_EDIT_PLAN
    CURRENT_FLOW_001::"validate role and working_dir."
    CURRENT_FLOW_002::"get current branch."
    CURRENT_FLOW_003::"resolve focus."
    CURRENT_FLOW_004::"create session."
    CURRENT_FLOW_005::"detect conflicts."
    CURRENT_FLOW_006::"discover context paths."
    CURRENT_FLOW_007::"read local North Star and PROJECT-CONTEXT."
    CURRENT_FLOW_008::"build AI synthesis."
    CURRENT_FLOW_009::"return structured dict."
    TARGET_FLOW_001::"validate role and working_dir."
    TARGET_FLOW_002::"get current branch."
    TARGET_FLOW_003::"resolve focus."
    TARGET_FLOW_004::"resolve or validate PSS IdentityTuple."
    TARGET_FLOW_005::"instantiate LocalFilesystemAdapter rooted at working_dir .hestai/state/portable."
    TARGET_FLOW_006::"list artifacts for PortableNamespace."
    TARGET_FLOW_007::"read artifacts through adapter."
    TARGET_FLOW_008::"validate identity, schema, hashes, provenance."
    TARGET_FLOW_009::"apply tombstones."
    TARGET_FLOW_010::"migrate supported schema artifacts into current projection model."
    TARGET_FLOW_011::"build Context Projection deterministically."
    TARGET_FLOW_012::"create session through SessionManager."
    TARGET_FLOW_013::"write named snapshot under snapshots/{session_id}."
    TARGET_FLOW_014::"read context for response from snapshot plus current local files."
    TARGET_FLOW_015::"detect conflicts and assemble current return."
    TARGET_FLOW_016::"add portable_state metadata."
    TARGET_FLOW_017::"on restore failure return structured portable_state restore_error."
    TARGET_FLOW_018::"do not silently return empty restored memory on failure."
    RESPONSE_EXTENSION
      FIELD::"portable_state"
      SHAPE::"dict[str, Any]"
      CONTAINS::["restore_status","identity","artifact_count","tombstone_count","snapshot_path","error"]
      BACKWARD_COMPAT::"Existing top-level fields remain."
      REVIEW_NEEDED::"Exact response shape should be CE-reviewed before B2 GREEN."
    FAILURE_POLICY
      IDENTITY_MISMATCH::"structured restore error."
      SCHEMA_TOO_NEW::"structured restore error and publish guard."
      LOCAL_ADAPTER_IO_ERROR::"structured restore error."
      NO_ARTIFACTS::"success with artifact_count 0."
      IDENTITY_UNAVAILABLE::"see §RISKS_AND_OPEN_QUESTIONS."

  CLOCK_OUT_EDIT_PLAN
    CURRENT_FLOW_001::"validate session_id."
    CURRENT_FLOW_002::"resolve working_dir."
    CURRENT_FLOW_003::"load active session metadata."
    CURRENT_FLOW_004::"resolve transcript path."
    CURRENT_FLOW_005::"parse messages."
    CURRENT_FLOW_006::"extract learnings."
    CURRENT_FLOW_007::"redact and archive transcript."
    CURRENT_FLOW_008::"append learnings index."
    CURRENT_FLOW_009::"remove active session dir."
    CURRENT_FLOW_010::"return archive result."
    TARGET_FLOW_001::"preserve current validation and local archive behavior."
    TARGET_FLOW_002::"capture redaction result and provenance during archive creation."
    TARGET_FLOW_003::"if no transcript exists, publish a learnings/session-summary artifact only if provenance can be complete."
    TARGET_FLOW_004::"build PortableMemoryArtifact from redacted archive metadata and extracted learnings."
    TARGET_FLOW_005::"validate identity tuple before publish."
    TARGET_FLOW_006::"validate complete RedactionProvenance before adapter call."
    TARGET_FLOW_007::"allocate append-first monotonic ArtifactRef."
    TARGET_FLOW_008::"call LocalFilesystemAdapter.write_artifact."
    TARGET_FLOW_009::"if adapter publish succeeds, return published ack."
    TARGET_FLOW_010::"if adapter publish fails after archive success, enqueue outbox entry."
    TARGET_FLOW_011::"if outbox enqueue succeeds, return local success plus queued portable status."
    TARGET_FLOW_012::"if archive fails, do not publish portable artifact."
    TARGET_FLOW_013::"remove active session dir only according to existing lifecycle safety behavior."
    TARGET_FLOW_014::"return unpublished_memory_exists based on outbox status."
    RESPONSE_EXTENSION
      FIELD::"portable_publication"
      CONTAINS::["status","artifact_id","sequence_id","carrier_namespace","queued_path","error"]
      FIELD::"unpublished_memory_exists"
      TYPE::bool
      BACKWARD_COMPAT::"Existing status/session/archive/extracted_learnings fields remain."
    FAILURE_POLICY
      REDACTION_FAILURE::"archive blocked as today; portable publish skipped."
      PROVENANCE_INCOMPLETE::"portable publish fails closed; local archive outcome reported."
      ADAPTER_PRECONDITION_FAILED::"queue if artifact is unpublished and outbox can persist."
      OUTBOX_WRITE_FAILED::"return portable status failed."

  GET_CONTEXT_EDIT_PLAN
    CURRENT_FLOW_001::"validate working_dir."
    CURRENT_FLOW_002::"read North Star."
    CURRENT_FLOW_003::"read PROJECT-CONTEXT."
    CURRENT_FLOW_004::"read git state."
    CURRENT_FLOW_005::"read active session focuses."
    CURRENT_FLOW_006::"read phase constraints."
    CURRENT_FLOW_007::"return structured context."
    TARGET_FLOW_001::"preserve public function signature unless CE approves optional session_id."
    TARGET_FLOW_002::"perform no adapter import."
    TARGET_FLOW_003::"perform no storage publish/restore operation."
    TARGET_FLOW_004::"perform no directory creation."
    TARGET_FLOW_005::"when a local snapshot is safely resolvable, read it as DERIVED_PROJECTION."
    TARGET_FLOW_006::"when no snapshot is resolvable, preserve existing local PROJECT-CONTEXT behavior."
    TARGET_FLOW_007::"do not surface hydration as happening from get_context."
    TARGET_FLOW_008::"return shape remains visibly compatible."
    PURITY_ENFORCEMENT
      SOURCE_GUARD::"No StorageAdapter or LocalFilesystemAdapter imports."
      BEHAVIOR_GUARD::"Filesystem diff empty before/after."
      OUTBOX_GUARD::"No outbox file changes."
      SNAPSHOT_GUARD::"Snapshot mtime unchanged."
      REMOTE_GUARD::"No remote adapter toggles or calls."
    REVIEW_NEEDED::"Session-bound snapshot selection is unresolved because public get_context has no session_id."

  SERVER_EDIT_PLAN
    CURRENT_REGISTRATION::[clock_in,clock_out,get_context,submit_review]
    TARGET_REGISTRATION::[clock_in,clock_out,get_context,submit_review]
    NO_NEW_TOOL::"No publish_portable_state tool in B1."
    NO_NEW_TOOL::"No restore_portable_state tool in B1."
    NO_TRANSPORT_CHANGE::"FastMCP stdio main remains unchanged."
    TEST_GUARD::"tests/test_server.py still passes."

  SESSION_EDIT_PLAN
    EDIT_001::"Extend SessionManager._ensure_state_directory to create portable/outbox."
    EDIT_002::"Extend SessionManager._ensure_state_directory to create portable/snapshots."
    EDIT_003::"Do not create portable/artifacts from get_context."
    EDIT_004::"Do not alter existing active/archive/context/state creation."
    EDIT_005::"Do not alter _ensure_state_symlink semantics."

  REDACTION_EDIT_PLAN
    EDIT_001::"Add RedactionEngine engine name constant or provenance module fallback."
    EDIT_002::"Add RedactionEngine version constant or provenance module fallback."
    EDIT_003::"Compute ruleset hash from PATTERNS names and regex patterns."
    EDIT_004::"Prefer new method that returns RedactionResult for archive pipeline."
    EDIT_005::"Keep copy_and_redact backward compatible for existing tests."
    EDIT_006::"Never log secret values."

  CONTEXT_PROJECTION_EDIT_PLAN
    EDIT_001::"Add pure projection builder in storage/projection.py."
    EDIT_002::"ContextSteward may delegate to projection builder if a seam is needed."
    EDIT_003::"Keep workflow phase parser untouched."
    EDIT_004::"Projection input is already-read artifacts; projection does not call adapter."
    EDIT_005::"Projection output is JSON-compatible local read model."

  VALIDATION_COMMANDS
    COMMAND_001::"pytest tests/storage/test_types_contract.py -q"
    COMMAND_002::"pytest tests/storage/test_storage_protocol.py -q"
    COMMAND_003::"pytest tests/storage/test_identity.py -q"
    COMMAND_004::"pytest tests/storage/test_schema.py -q"
    COMMAND_005::"pytest tests/storage/test_provenance.py -q"
    COMMAND_006::"pytest tests/storage/test_local_filesystem_adapter.py -q"
    COMMAND_007::"pytest tests/storage/test_outbox.py -q"
    COMMAND_008::"pytest tests/storage/test_snapshots.py -q"
    COMMAND_009::"pytest tests/storage/test_projection.py -q"
    COMMAND_010::"pytest tests/integration/test_clock_in_portable_state.py -q"
    COMMAND_011::"pytest tests/integration/test_clock_out_portable_publish.py -q"
    COMMAND_012::"pytest tests/integration/test_get_context_purity.py -q"
    COMMAND_013::"pytest tests/integration/test_pss_lifecycle_local_filesystem.py -q"
    COMMAND_014::"pytest"
    COMMAND_015::"ruff check src tests"
    COMMAND_016::"black --check src tests"
    COMMAND_017::"mypy src"

§MIGRATION_PLAN
  MIGRATION_PRINCIPLE
    PRINCIPLE_001::"No raw .hestai/state folder sync."
    PRINCIPLE_002::"Existing state remains valid Local State."
    PRINCIPLE_003::"Portable artifacts are additive."
    PRINCIPLE_004::"Unknown state classification is LOCAL_MUTABLE."
    PRINCIPLE_005::"No existing local file is rewritten into portable memory without redaction provenance."
    PRINCIPLE_006::"Hydrate rebuilds derived projection; it does not overwrite source portable artifacts."

  EXISTING_STATE_CLASSIFICATION_MAP
    MAP_001
      PATH::".hestai/state/sessions/active/{session_id}/session.json"
      TIER::LOCAL_MUTABLE
      R_TRACE::[R1]
      REASON::"Raw active lifecycle state and local transcript pointers."
    MAP_002
      PATH::".hestai/state/sessions/archive/*-redacted.jsonl"
      TIER::LOCAL_MUTABLE
      R_TRACE::[R1,R6]
      REASON::"Local archive remains local even when it is redacted."
      PORTABLE_RELATION::"Source for future PortableMemoryArtifact only after provenance validation."
    MAP_003
      PATH::".hestai/state/learnings-index.jsonl"
      TIER::LOCAL_MUTABLE
      R_TRACE::[R1]
      REASON::"ADR explicitly lists learnings-index.jsonl under LOCAL_MUTABLE examples."
    MAP_004
      PATH::".hestai/state/sessions/control-room-ledger.oct.md"
      TIER::LOCAL_MUTABLE
      R_TRACE::[R1]
      REASON::"ADR explicitly lists ledger under LOCAL_MUTABLE examples."
    MAP_005
      PATH::".hestai/state/context/state/current-focus.oct.md"
      TIER::LOCAL_MUTABLE
      R_TRACE::[R1]
      REASON::"FAST layer session-specific mutable state."
    MAP_006
      PATH::".hestai/state/context/state/checklist.oct.md"
      TIER::LOCAL_MUTABLE
      R_TRACE::[R1]
      REASON::"FAST layer local checklist state."
    MAP_007
      PATH::".hestai/state/context/state/blockers.oct.md"
      TIER::LOCAL_MUTABLE
      R_TRACE::[R1]
      REASON::"FAST layer local blockers state."
    MAP_008
      PATH::".hestai/state/context/PROJECT-CONTEXT.oct.md"
      TIER::DERIVED_PROJECTION_WHEN_REBUILT_FROM_PORTABLE_MEMORY
      R_TRACE::[R1]
      REASON::"ADR names materialized PROJECT-CONTEXT as DERIVED_PROJECTION when derived."
      FAIL_CLOSED::"Existing unclassified PROJECT-CONTEXT is LOCAL_MUTABLE until explicitly marked derived."
    MAP_009
      PATH::".hestai/state/context/PROJECT-ROADMAP.oct.md"
      TIER::LOCAL_MUTABLE_UNTIL_EXPLICITLY_CLASSIFIED
      R_TRACE::[R1]
      REASON::"No ADR portable classification for existing roadmap file."
    MAP_010
      PATH::".hestai/state/context/PROJECT-CHECKLIST.oct.md"
      TIER::LOCAL_MUTABLE_UNTIL_EXPLICITLY_CLASSIFIED
      R_TRACE::[R1]
      REASON::"No ADR portable classification for existing checklist file."
    MAP_011
      PATH::".hestai/state/context/PROJECT-HISTORY.oct.md"
      TIER::LOCAL_MUTABLE_UNTIL_EXPLICITLY_CLASSIFIED
      R_TRACE::[R1]
      REASON::"No ADR portable classification for existing history file."
    MAP_012
      PATH::".hestai/state/portable/outbox/{artifact_id}.json"
      TIER::LOCAL_MUTABLE
      R_TRACE::[R1,R7]
      REASON::"Durable queue is explicitly Local State."
    MAP_013
      PATH::".hestai/state/portable/artifacts/{namespace}/.../{artifact_id}.json"
      TIER::PORTABLE_MEMORY
      R_TRACE::[R1,R2]
      REASON::"LocalFilesystemAdapter carrier copy of redacted portable artifact."
    MAP_014
      PATH::".hestai/state/portable/tombstones/{namespace}/.../{artifact_id}.json"
      TIER::PORTABLE_MEMORY
      R_TRACE::[R1,R8]
      REASON::"Tombstone is a portable memory revocation artifact."
    MAP_015
      PATH::".hestai/state/portable/snapshots/{session_id}/context-projection.json"
      TIER::DERIVED_PROJECTION
      R_TRACE::[R1,R5]
      REASON::"Snapshot is rebuilt local read model."
    MAP_016
      PATH::".hestai/state/portable/snapshots/{session_id}/metadata.json"
      TIER::DERIVED_PROJECTION
      R_TRACE::[R1,R5]
      REASON::"Snapshot metadata is part of derived local read model."
    MAP_017
      PATH::".hestai/state/portable/tmp/*"
      TIER::LOCAL_MUTABLE
      R_TRACE::[R1]
      REASON::"Temporary local write staging."
    MAP_018
      PATH::"Any unrecognized .hestai/state path"
      TIER::LOCAL_MUTABLE
      R_TRACE::[R1]
      REASON::"R1 fail-closed unknown classification rule."

  FIRST_RUN_DIRECTORY_CREATION
    CREATED_BY::"SessionManager.ensure_hestai_structure during clock_in."
    DIR_001::".hestai/state/portable/"
    DIR_002::".hestai/state/portable/outbox/"
    DIR_003::".hestai/state/portable/snapshots/"
    DIR_004::".hestai/state/portable/artifacts/"
    DIR_005::".hestai/state/portable/tombstones/"
    DIR_006::".hestai/state/portable/tmp/"
    NOT_CREATED_BY::"get_context."
    NOT_CREATED_BY::"module import."
    NOT_CREATED_BY::"server startup."

  EXISTING_CONSUMER_TRANSITION
    CONSUMER_001
      NAME::"clock_in current PROJECT-CONTEXT reader"
      BEFORE::"Reads .hestai/state/context/PROJECT-CONTEXT.oct.md directly."
      AFTER::"Reads projection from named snapshot when available, else current local file."
      COMPATIBILITY::"Return context.project_context remains str | None."
    CONSUMER_002
      NAME::"clock_out archive writer"
      BEFORE::"Writes redacted archive and learnings-index."
      AFTER::"Keeps both writes, then publishes portable artifact if provenance complete."
      COMPATIBILITY::"Local archive success is not dependent on portable publish."
    CONSUMER_003
      NAME::"get_context preview"
      BEFORE::"Pure read from local files."
      AFTER::"Pure read from local snapshot/local projection."
      COMPATIBILITY::"No adapter, no writes, same public signature unless CE approves change."
    CONSUMER_004
      NAME::"tests relying on no .hestai creation from get_context"
      BEFORE::"Assert no .hestai directory created."
      AFTER::"Still pass."
      COMPATIBILITY::"PSS directory creation is only lifecycle-side."
    CONSUMER_005
      NAME::"Payload Compiler"
      BEFORE::"Reads structured context fields."
      AFTER::"Sees same fields; portable_state metadata only from lifecycle tools."
      COMPATIBILITY::"No provider-specific context shape."

  FAIL_CLOSED_CASES
    CASE_001::"Unknown path classification -> LOCAL_MUTABLE."
    CASE_002::"Identity tuple missing -> no restore/publish until identity decision is resolved."
    CASE_003::"Identity mismatch -> structured restore/publish error."
    CASE_004::"Artifact schema too new -> structured schema_too_new error."
    CASE_005::"Provenance incomplete -> write_artifact fails closed."
    CASE_006::"Payload hash mismatch -> structured artifact_integrity error."
    CASE_007::"Duplicate id different hash -> precondition failure."
    CASE_008::"Outbox enqueue failure after publish failure -> portable status failed."
    CASE_009::"Tombstone target missing -> projection records revocation but does not crash."
    CASE_010::"Malformed outbox entry -> structured queue error and unpublished_memory_exists true."

§RISKS_AND_OPEN_QUESTIONS
  RISK_001
    TITLE::"Identity tuple source is not defined in current code or ADR B1 scope."
    R_TRACE::[R3,R5,R12]
    FACT::"clock_in and clock_out do not receive project_id, workspace_id, user_id, carrier_namespace."
    FACT::"ADR says user_id is HestAI user but auth model is deferred by R12."
    FACT::"ADR says project_id is stable and not current folder name."
    DECISION_NEEDED::"How B1 obtains IdentityTuple without designing auth or first-run UX."
    OPTIONS_FOR_REVIEW::[
      "Require explicit local config already present; fail closed if absent.",
      "Add optional tool parameters; public MCP schema change requires approval.",
      "Use temporary test-only injected resolver for B2 implementation until future ADR."
    ]
    RECOMMENDATION::"Fail closed when identity is unavailable; do not invent auth or UX taxonomy."
    GATE::CRITICAL_ENGINEER_PRE_IMPLEMENTATION

  RISK_002
    TITLE::"R2 read_artifact signature needs tombstone formalization for R8."
    R_TRACE::[R2,R8]
    FACT::"ADR code sketch returns PortableMemoryArtifact from read_artifact."
    FACT::"R8 requires restore to read and apply tombstone semantics."
    PLAN_INTERPRETATION::"read_artifact returns PortableArtifact union."
    DECISION_NEEDED::"CE should approve union return or require a separate read_tombstone method."
    RECOMMENDATION::"Approve union return because list_artifacts can return refs for both artifact kinds."
    GATE::CRITICAL_ENGINEER_PRE_IMPLEMENTATION

  RISK_003
    TITLE::"get_context has no session_id but R5 names session-bound snapshots."
    R_TRACE::[R5,R10]
    FACT::"Current get_context signature is get_context(working_dir: str)."
    FACT::"Changing signature changes MCP tool schema."
    FACT::"Implicit latest-session selection can be wrong under concurrent sessions."
    DECISION_NEEDED::"How get_context selects a named snapshot without visible semantic drift."
    OPTIONS_FOR_REVIEW::[
      "Keep signature and read only default local projection.",
      "Add optional session_id with backward compatibility but visible schema change.",
      "Expose session-specific snapshot only through clock_in response for B1."
    ]
    RECOMMENDATION::"Do not change public signature in B1; preserve purity and surface limitation."
    GATE::CRITICAL_ENGINEER_PRE_IMPLEMENTATION

  RISK_004
    TITLE::"RedactionEngine has no explicit version today."
    R_TRACE::[R6]
    FACT::"RedactionEngine.PATTERNS exists."
    FACT::"RedactionResult exposes redacted_types."
    FACT::"No engine version constant exists."
    DECISION_NEEDED::"Whether B1 introduces REDACTION_ENGINE_VERSION='1' in core.redaction."
    RECOMMENDATION::"Add a local constant with tests; version changes when patterns or semantics change."
    GATE::IMPLEMENTATION_REVIEW

  RISK_005
    TITLE::"Artifact payload shape from current learnings is not specified by ADR."
    R_TRACE::[R4,R5,R6]
    FACT::"ADR names redacted summaries, decisions, blockers, checklist deltas as examples."
    FACT::"Current clock_out extracts decisions, blockers, learnings."
    DECISION_NEEDED::"Exact v1 payload keys for LocalFilesystem artifacts."
    RECOMMENDATION::"Use minimal v1 payload: session_id, role, focus, archive_path local field, decisions, blockers, learnings, description."
    GATE::CRITICAL_ENGINEER_REVIEW

  RISK_006
    TITLE::"LocalFilesystemAdapter carrier path layout is not fully specified by ADR."
    R_TRACE::[R1,R2,R3,R12]
    FACT::"ADR gives abstract carrier path pss/{carrier_namespace}/{project_id}/{workspace_id}/{user_id}/artifacts/{artifact_id}."
    FACT::"Remote wire format is deferred."
    DECISION_NEEDED::"Exact local path below .hestai/state/portable/."
    RECOMMENDATION::"Use local-only path mirroring the abstract ADR path; do not infer remote layout."
    GATE::IMPLEMENTATION_REVIEW

  RISK_007
    TITLE::"Compaction is mentioned but not required as B1 implementation."
    R_TRACE::[R8,R9]
    FACT::"ADR says compaction must preserve revocation semantics."
    FACT::"Scope requests append-first monotonic-ID storage with tombstone support."
    DECISION_NEEDED::"Whether B1 includes compaction records or only guards projection semantics."
    RECOMMENDATION::"Do not implement compaction in B1; add tests proving projection would preserve tombstone coverage."
    GATE::CRITICAL_ENGINEER_REVIEW

  RISK_008
    TITLE::"Outbox retry trigger is deferred by ADR wording."
    R_TRACE::[R7,R12]
    FACT::"ADR says retry may happen on later clock_in, clock_out, or explicit Publish Portable State."
    FACT::"Explicit publish tool is not in B1 scope."
    DECISION_NEEDED::"Whether B1 drains outbox during clock_in/clock_out or only records queue."
    RECOMMENDATION::"Implement queue creation and status only in B1; defer retry orchestration unless explicitly approved."
    GATE::CRITICAL_ENGINEER_REVIEW

  RISK_009
    TITLE::"No official registry approval tool is available in this session."
    R_TRACE::[B1_GATE]
    FACT::"The requested output is a local BUILD-PLAN document."
    FACT::"No mcp__hestai__registry tool is exposed in available tools."
    DECISION_NEEDED::"Human or critical-engineer must perform official B1 gate outside this artifact."
    RECOMMENDATION::"Use §HANDOFF as gate checklist."
    GATE::HUMAN_REVIEW

  RISK_010
    TITLE::"Publication from missing transcript path needs clear behavior."
    R_TRACE::[R5,R6,R7]
    FACT::"clock_out currently succeeds with zero messages when transcript is missing."
    FACT::"Portable artifact still needs redaction provenance."
    DECISION_NEEDED::"Whether no-transcript clock_out publishes session metadata artifact."
    RECOMMENDATION::"Do not publish portable artifact without a redacted input/output provenance pair."
    GATE::IMPLEMENTATION_REVIEW

§HANDOFF
  B2_ENTRY_PACKAGE
    ARTIFACT_001::"This BUILD-PLAN document."
    ARTIFACT_002::"ADR-0013 accepted source."
    ARTIFACT_003::"R10 invariant test list."
    ARTIFACT_004::"Protocol signatures in §PROTOCOL_SIGNATURES."
    ARTIFACT_005::"Risk list requiring CE pre-review."

  IMPLEMENTATION_LEAD_RECEIVES
    ITEM_001::"File layout and ownership boundaries."
    ITEM_002::"Exact Protocol/type signatures to implement."
    ITEM_003::"TDD order with RED tests grouped by component."
    ITEM_004::"Integration plan for clock_in, clock_out, get_context, server."
    ITEM_005::"Migration classification map for existing .hestai/state consumers."
    ITEM_006::"Validation command sequence."
    ITEM_007::"Explicit R12 no-design boundaries."

  CRITICAL_ENGINEER_REVIEWS_AT_B1_TO_B2_GATE
    REVIEW_001::"Identity tuple source decision."
    REVIEW_002::"StorageAdapter read_artifact union return vs separate tombstone read."
    REVIEW_003::"get_context session-bound snapshot semantics with unchanged public signature."
    REVIEW_004::"RedactionEngine versioning approach."
    REVIEW_005::"v1 artifact payload shape."
    REVIEW_006::"LocalFilesystemAdapter path layout under .hestai/state/portable."
    REVIEW_007::"Whether outbox retry is in B1 or deferred."
    REVIEW_008::"Whether compaction records are excluded from B1 implementation."

  B2_START_BLOCKERS
    BLOCKER_001::"Do not implement identity fallback that invents auth or UX taxonomy."
    BLOCKER_002::"Do not modify get_context public behavior without CE approval."
    BLOCKER_003::"Do not add remote adapters, remote config, remote dependencies, or wire schemas."
    BLOCKER_004::"Do not publish artifacts without complete redaction provenance."
    BLOCKER_005::"Do not use custom Git refs."

  COMPLETION_CRITERIA_FOR_B1
    CRITERION_001::"BUILD-PLAN exists at .hestai/decisions/phase-pss-b1/BUILD-PLAN.oct.md."
    CRITERION_002::"Plan scopes LocalFilesystemAdapter only."
    CRITERION_003::"Plan repeats R12 deferred items."
    CRITERION_004::"Plan includes concrete file layout."
    CRITERION_005::"Plan includes exact Protocol/type signatures."
    CRITERION_006::"Plan includes ordered RED tests mapped to R1-R11."
    CRITERION_007::"Plan includes five R10 invariant acceptance tests."
    CRITERION_008::"Plan includes integration sequence for clock_in, clock_out, get_context, server."
    CRITERION_009::"Plan includes migration map and fail-closed classification."
    CRITERION_010::"Plan surfaces unresolved decisions instead of silently making them."

===END===
