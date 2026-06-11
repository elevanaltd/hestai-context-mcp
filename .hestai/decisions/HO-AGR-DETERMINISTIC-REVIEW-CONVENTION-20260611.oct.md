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
  DECISION::"AGR pull requests under .hestai/decisions/ are cleared by the deterministic validators only (Gate A schema/token regex, the lineage guard, Gate B octave-mcp); no LLM clears an AGR gate, the human merge is the sole semantic gate, and the engine appends a deterministic neighbourhood block as a precedence aid."
  BECAUSE::"An LLM re-checking deterministic schema is schema-theatre that adds no value over the validators and erodes Human Primacy (PROD I3) by displacing human semantic attention; authority must match capability so validators own schema and the human owns semantics (Wind/Wall/Door debate 2026-06-11)."
===END===
