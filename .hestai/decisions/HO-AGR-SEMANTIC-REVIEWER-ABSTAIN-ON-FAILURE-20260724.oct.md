===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.0"
  TOKEN::HO-AGR-SEMANTIC-REVIEWER-ABSTAIN-ON-FAILURE-20260724
  STATUS::RATIFIED
  TIER::TACTICAL
  COMPRESSION_TIER::CONSERVATIVE
  LOSS_PROFILE::"[preserve:abstain_on_infrastructure_failure∧genuine_verdict_still_gates∧token_cap_subordinate_corollary∧amends_HO-AGR-SEMANTIC-REVIEWER-ANALYSIS-TIER-20260611,drop:narrative_of_production_outage_details]"
  AUTHORED_AT::"2026-07-24T00:00:00Z"
  ISSUE_REF::"repo:hestai-context-mcp#141"
  AMENDS::[HO-AGR-SEMANTIC-REVIEWER-ANALYSIS-TIER-20260611]
  SCOPE::hestai-context-mcp
  AFFECTS::[
    submit_governance,
    semantic_review,
    HESTAI_REVIEW_MAX_OUTPUT_TOKENS
  ]
  SCOPE_GUARD::"governs submit_governance semantic reviewer failure-handling ∧ token limits ONLY; core validation rules are EXCLUDED"
  DECISION::"Stage-5 reviewer operational failure[no_client∨cost_cap∨auth∨transport∨protocol∨truncation∨empty] → ABSTAIN: zero PR verdict ∧ reason recorded ∧ WARNING logged ∴ SR requirement stays visibly unmet without infra-derived BLOCKED. Genuine CONCERNS∨BLOCKED still gates ∧ APPROVED never fabricated."
  BECAUSE::"Reviewer execution failure ≠ defective-record evidence ⇌ fail-closed BLOCKED wrongly blocked every affected AGR PR[404_retired_slug ∧ finish_reason_length] ∴ operational ≠ semantic ⊕ preserves PROD_I3 Human_Primacy. Merge enforcement = branch-protection Review_Gate."
  RATIFIED_BY::"human:operator<shaunbuswell>"
  RATIFIED_AT::"2026-07-27T00:00:00Z"
  OPERATIONAL_COROLLARY::"SUBORDINATE ∧ NOT independent: HESTAI_REVIEW_MAX_OUTPUT_TOKENS 2000→10000 [reasoning models exhaust budget pre-verdict → truncation]. Env-overridable ∴ revisable without amending. VERIFIED::no_other_active_AGR_governs_this_parameter."
===END===
