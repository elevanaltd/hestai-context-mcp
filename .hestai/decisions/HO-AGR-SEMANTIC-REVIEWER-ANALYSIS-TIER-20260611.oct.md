===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.0"
  TOKEN::HO-AGR-SEMANTIC-REVIEWER-ANALYSIS-TIER-20260611
  STATUS::RATIFIED
  TIER::TACTICAL
  AUTHORED_AT::"2026-06-11T00:00:00Z"
  RATIFIED_BY::"human:operator"
  RATIFIED_AT::"2026-06-11T00:00:00Z"
  ISSUE_REF::"repo:hestai-context-mcp#77"
  HUMAN_ADR_REF::".hestai/decisions/rfc-arch/ADR-RFC-ARCH-004-agent-readable-governance-records.md"
  AMENDS::[HO-AGR-DETERMINISTIC-REVIEW-CONVENTION-20260611]
  SCOPE::"hestai-context-mcp"
  DECISION::"AGR pull requests retain a scoped SEMANTIC reviewer (precedence, contradiction, scope, concept-validity only, never schema) run at the ANALYSIS tier; the deterministic validators remain the schema gate and the human merge remains the final semantic gate."
  BECAUSE::"Operator experience shows a semantic second opinion catches what the human misses and reduces load; the redundancy the prior convention eliminated was schema-rechecking, not semantic review, so the reviewer is retained but scoped to semantics and run at a stronger analysis tier."
===END===
