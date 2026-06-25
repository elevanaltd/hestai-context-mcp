===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.0"
  TOKEN::HO-REVIEW-GATE-PLACEMENT-TRANSITION-20260620
  STATUS::RATIFIED
  TIER::STRATEGIC
  COMPRESSION_TIER::CONSERVATIVE
  LOSS_PROFILE::"[preserve:prior_decision_context_and_superseded_relationship_and_inherited_P0_issues_and_PROD_I6_isolation,drop:narrative_history_of_HestAI_MCP_reorganization]"
  AUTHORED_AT::"2026-06-20T00:00:00Z"
  RATIFIED_BY::"human:operator<shaunbuswell>"
  RATIFIED_AT::"2026-06-25T00:00:00Z"
  ISSUE_REF::"repo:hestai-context-mcp#115"
  SUPERSEDES::["review-tool-placement"]
  SCOPE::"hestai-context-mcp"
  AFFECTS::[validate_review,review_gate,review_formats,submit_review,submit_governance]
  SCOPE_GUARD::"governs review-gate validation engine ∧ workflow templates ONLY; governance auto-ratify is EXCLUDED"
  DECISION::"Host Review Gate (validate_review.py, review-gate.yml, review_formats.py) in hestai-context-mcp alongside submit_review, superseding 2026-02-14 review-tool-placement."
  BECAUSE::"hestai-context-mcp owns review infrastructure (submit_review structured verdicts) ⊕ co-hosting eliminates cross-repo format-coupling risk → remote consumers pull tooling from single source ⇌ inherits two P0 trust-model issues (#116) ∧ preserves PROD I6 namespace isolation."
===END===