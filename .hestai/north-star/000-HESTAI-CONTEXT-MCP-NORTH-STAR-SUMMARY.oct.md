===NORTH_STAR_SUMMARY===
META:
  TYPE::NORTH_STAR_SUMMARY
  VERSION::"1.0"
  NAMESPACE::PROD
  STATUS::APPROVED
  APPROVED_BY::"Human operator (2026-04-17)"
  FULL_DOCUMENT::"000-HESTAI-CONTEXT-MCP-NORTH-STAR.md"
  COMPRESSION::"311 to 95 lines (3.3:1)"
  LAST_UPDATED::"2026-04-30"
§1::IDENTITY
PURPOSE::"Persistent memory and environmental context for AI-assisted development sessions"
ROLE_IN_ECOSYSTEM::"Memory and Environment in Three-Service Model (ADR-0353)"
TRANSPORT::"stdio JSON-RPC (python -m hestai_context_mcp)"
PHASE::B1_FOUNDATION_COMPLETE
§2::IMMUTABLES
I1::"SESSION_LIFECYCLE_INTEGRITY<PRINCIPLE::every_session_has_clean_create_and_archive_lifecycle,WHY::memory_accumulation_collapses_if_sessions_orphan_or_lose_provenance,STATUS::IMPLEMENTED>"
I2::"CREDENTIAL_SAFETY<PRINCIPLE::zero_credentials_persist_in_archives_fail_closed_redaction,WHY::single_leaked_credential_is_security_incident_data_loss_over_data_exposure,STATUS::IMPLEMENTED>"
I3::"PROVIDER_AGNOSTIC_CONTEXT<PRINCIPLE::context_synthesis_identical_regardless_of_AI_provider_or_CLI,WHY::three_service_separation_collapses_if_context_engine_couples_to_provider,STATUS::IMPLEMENTED>"
I4::"STRUCTURED_RETURN_SHAPES<PRINCIPLE::all_tools_return_structured_dicts_with_defined_fields_not_blobs,WHY::Payload_Compiler_programmatically_extracts_fields_for_KVAEPH_Position_3,STATUS::IMPLEMENTED>"
I5::"READ_ONLY_CONTEXT_QUERY<PRINCIPLE::get_context_has_zero_side_effects_pure_read,WHY::Payload_Compiler_calls_freely_repeatedly_in_parallel_must_be_safe,STATUS::IMPLEMENTED>"
I6::"LEGACY_INDEPENDENCE<PRINCIPLE::no_runtime_or_install_dependency_on_hestai_mcp,WHY::A_B_comparison_impossible_if_dependency_exists_deprecation_cascades,STATUS::IMPLEMENTED>"
§3::ASSUMPTIONS
A1::"STDIO_TRANSPORT_SUFFICIENT[85%] HIGH_CONFIDENCE"
A2::"JSONL_LEARNINGS_SCALES[80%] MEDIUM_CONFIDENCE"
A3::"ADAPTER_PATTERN_COVERS_PROVIDERS[90%] HIGH_CONFIDENCE"
A4::"REDACTION_PATTERN_COVERAGE[80%] CRITICAL<CADENCE::adversarial_review_each_minor_release_or_on_new_provider_adapter>"
A5::"GET_CONTEXT_SUFFICIENT_FOR_POSITION_3[80%] CRITICAL"
A6::"PORTABLE_STATE_DEFAULT_LOCAL_FILESYSTEM[90%] HIGH_CONFIDENCE"
A7::"BRANCH_FOCUS_RESOLUTION_USEFUL[70%] LOW_CONFIDENCE"
§4::SCOPE_BOUNDARIES
IS::[
  "session lifecycle management (clock_in, clock_out)",
  "context synthesis engine (.hestai state, North Stars, git state)",
  "learnings extraction pipeline (transcript parsing, redaction, indexing)",
  "review infrastructure (structured PR verdicts, CI gate clearing)",
  "portable session state (StorageAdapter, IdentityTuple, PortableArtifact union) per ADR-0013"
]
IS_NOT::[
  "agent identity or governance (Vault owns)",
  "UI or dispatch system (Workbench owns)",
  "deliberation system (Debate Hall owns)",
  "document format system (octave-mcp owns)"
]
§5::CONSTRAINED_VARIABLES
TRANSPORT::[
  IMMUTABLE::stdio_JSON_RPC,
  FLEXIBLE::protocol_version,
  NEGOTIABLE::additional_transports
]
TRANSCRIPT_PARSING::[
  IMMUTABLE::provider_agnostic_adapter_pattern,
  FLEXIBLE::specific_parser_implementations
]
ARCHIVAL_FORMAT::[
  IMMUTABLE::redacted_structured_persistent,
  FLEXIBLE::JSONL_vs_OCTAVE
]
COVERAGE::[
  IMMUTABLE::"85_percent_minimum_CI_enforced",
  FLEXIBLE::test_strategies
]
STORAGE_BACKEND::[
  IMMUTABLE::StorageAdapter_protocol,
  FLEXIBLE::adapter_implementation,
  NEGOTIABLE::carrier_namespace_layout
]
§6::GATES
GATES::"D1[DONE] B1[DONE_Phase_1+Phase_1.5+PSS_B1_2026-04-29] B2[PENDING_workbench_Phase_3C_integration] B3[FUTURE_NS_injection_unification] B4[FUTURE_git_hooks_legacy_deprecation]"
§7::ESCALATION
ESCALATION_ROUTING::[
  requirements_steward::[
    "violates PROD I#",
    scope_boundary_question,
    immutable_change
  ],
  technical_architect::[
    transport_design,
    adapter_architecture,
    cross_service_integration
  ],
  implementation_lead::[
    "assumption A# validation",
    Phase_2_execution,
    new_provider_adapter
  ]
]
§8::TRIGGERS
LOAD_FULL_NORTH_STAR_IF::[
  "violates PROD I1 through I6 = immutable conflict",
  "credential or redaction or security = I2 safety critical",
  "provider specific or Claude only or format assumption = I3 coupling risk",
  "side effect or mutation or get_context writes = I5 purity violation",
  "import hestai_mcp or legacy dependency = I6 independence breach",
  "scope boundary or feature creep = identity boundary question",
  "B2 or Phase 2 or workbench integration = decision gate approaching",
  "identity tuple or carrier_namespace or storage adapter or multi_directory = ADR-0013 boundary question"
]
§9::PROTECTION
IF::agent_detects_work_contradicting_North_Star
THEN::[
  STOP::current_work_immediately,
  CITE::"specific requirement violated (PROD I#)",
  ESCALATE::to_requirements_steward
]
FORMAT::"NORTH_STAR_VIOLATION: [work] violates [PROD I#] because [evidence]"
===END===
