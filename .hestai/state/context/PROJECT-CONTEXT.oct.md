===PROJECT_CONTEXT===
META:
  TYPE::PROJECT_CONTEXT
  NAME::"HestAI Context Management MCP Server"
  VERSION::"1.0.0"
  PHASE::B1_FOUNDATION_COMPLETE
  STATUS::ACTIVE
  LAST_UPDATED::"2026-04-17"
  PYTHON_VERSION::">=3.11"
  CI_MATRIX::[3.11,3.12]
PURPOSE::"Standalone governance engine providing session lifecycle, context synthesis, learnings extraction, and review infrastructure via stdio MCP transport. The Memory and Environment layer in the Three-Service Model (ADR-0353)."
ARCHITECTURE::"THREE_SERVICE_MODEL<ADR-0353>"
§1::CURRENT_STATE
TOOLS::[
  clock_in,
  clock_out,
  get_context,
  submit_review
]
QUALITY_GATES::[
  pytest::"PASSING<361_tests>",
  mypy::"PASSING<0_errors>",
  ruff::"PASSING<0_errors>",
  black::PASSING,
  CI::"OPERATIONAL<ci.yml>"
]
COVERAGE::"89%"
TRANSPORT::"stdio_JSON_RPC<python_-m_hestai_context_mcp>"
§2::ARCHITECTURE
THREE_SERVICES::[
  WORKBENCH::"UI + dispatch + Payload Compiler (Eyes and Hands). Consumer of this service at KVAEPH Position 3.",
  VAULT::"Git-backed library at ~/.hestai-workbench/library/ (DNA). Agent defs, skills, cognitions, standards.",
  HESTAI_CONTEXT_MCP::"THIS SERVICE. Session lifecycle + context synthesis + learnings + review (Memory and Environment)."
]
WHAT_THIS_SERVICE_OWNS::[
  clock_in,
  clock_out,
  get_context,
  submit_review,
  RedactionEngine,
  ContextSteward,
  SessionManager,
  TranscriptParser_adapter_pattern,
  ".hestai/state/_management"
]
WHAT_IS_NOT_HERE::[
  bind_tool,
  ensure_system_governance,
  bootstrap_system_governance,
  _bundled_hub,
  agent_definitions,
  skills,
  standards_injection
]
§3::HARVEST_PHASES
PHASE_1::"COMPLETE — 4 tools harvested from hestai-mcp. clock_out redesigned with provider adapter pattern (TranscriptParser ABC + ClaudeTranscriptParser). 361 tests, 89% coverage."
PHASE_2::"PENDING — Workbench Payload Compiler calls this via stdio for KVAEPH Position 3. Blocked on workbench Step 3B Phase 2."
PHASE_3::"PENDING — North Star injection unification (System NS from Vault, Product NS from this service during clock_in)."
PHASE_4::"PENDING — Git hooks for .hestai/ enforcement. Deprecate ADR-0033 Phase 3 tools."
§4::KNOWN_GAPS
CLOCK_OUT_ADAPTERS::"Only Claude transcript adapter implemented. Codex/Gemini/Goose adapters are Phase 2+."
AI_SYNTHESIS::"clock_in AI synthesis deferred (returns null). Needs provider integration."
WORKBENCH_INTEGRATION::"No integration test with Workbench yet (Phase 2 dependency)."
§5::ECOSYSTEM_STATE
WORKBENCH::"hestai-workbench — Step 3B Phase 2. PayloadCompiler done. DispatchService Phase 1 merged."
VAULT::"~/.hestai-workbench/library/ — 5 V9 agents, 16 V9 skills, 3 cognitions."
LEGACY::"hestai-mcp — maintenance mode. 1033 tests. Stays for A/B comparison."
OCTAVE_MCP::"v1.9.6 production. Foundation layer."
DEBATE_HALL::"v0.5.0 production. 17 tools."
===END===
