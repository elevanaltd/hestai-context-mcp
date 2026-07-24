===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.0"
  TOKEN::HO-AGR-SEMANTIC-REVIEWER-ABSTAIN-ON-FAILURE-20260724
  STATUS::PROPOSED
  TIER::TACTICAL
  COMPRESSION_TIER::CONSERVATIVE
  LOSS_PROFILE::"[preserve:abstain_on_infrastructure_failure,raise_HESTAI_REVIEW_MAX_OUTPUT_TOKENS_to_10000,amends_HO-AGR-SEMANTIC-REVIEWER-ANALYSIS-TIER-20260611,drop:narrative_of_production_outage_details]"
  AUTHORED_AT::"2026-07-24T00:00:00Z"
  ISSUE_REF::"repo:hestai-context-mcp#141"
  AMENDS::["HO-AGR-SEMANTIC-REVIEWER-ANALYSIS-TIER-20260611"]
  SCOPE::"hestai-context-mcp"
  AFFECTS::[submit_governance,semantic_review,HESTAI_REVIEW_MAX_OUTPUT_TOKENS]
  SCOPE_GUARD::"governs submit_governance semantic reviewer failure-handling ∧ token limits ONLY; core validation rules are EXCLUDED"
  DECISION::"On submit_governance operational failure (no client/credential, cost-cap, transport error, truncation, empty response) → Stage-5 semantic reviewer ABSTAINS ∧ posts no PR verdict ∧ records error in return block ∴ PR remains unblocked ⊕ raise HESTAI_REVIEW_MAX_OUTPUT_TOKENS from 2000 to 10000."
  BECAUSE::"Reviewer execution failure ≠ defective record evidence ⇌ fail-closed BLOCKED on infra failure wrongly blocked PRs (e.g., 404 model slug, finish_reason='length' truncation) ∴ distinguishing operational failure from genuine semantic judgment preserves Human Primacy (PROD I3) ⊕ never-fabricate-APPROVED integrity."
===END===
