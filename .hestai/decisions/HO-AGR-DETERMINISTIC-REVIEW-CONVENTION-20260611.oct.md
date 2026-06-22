===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.0"
  TOKEN::HO-AGR-DETERMINISTIC-REVIEW-CONVENTION-20260611
  STATUS::RATIFIED
  TIER::TACTICAL
  AUTHORED_AT::"2026-06-11T00:00:00Z"
  RATIFIED_BY::"human:operator"
  RATIFIED_AT::"2026-06-11T00:00:00Z"
  ISSUE_REF::"repo:hestai-context-mcp#53"
  HUMAN_ADR_REF::".hestai/decisions/rfc-arch/ADR-RFC-ARCH-004-agent-readable-governance-records.md"
  EXTENDS::[HO-CONTEXT-MCP-ADOPTS-AGR-DOGFOOD-20260611]
  SCOPE::"hestai-context-mcp"
  DECISION::"AGR PRs under .hestai/decisions/ are cleared by deterministic validators ONLY (Gate-A schema/token regex⊕lineage guard⊕Gate-B octave-mcp); no LLM clears an AGR gate, human merge is sole semantic gate, engine appends deterministic neighbourhood precedence block."
  BECAUSE::"LLM re-checking deterministic schema = schema-theatre adding no value over validators∧erodes Human Primacy(PROD I3) by displacing human semantic attention; authority must match capability∴validators own schema⊕human owns semantics (Wind/Wall/Door 2026-06-11)."
===END===
