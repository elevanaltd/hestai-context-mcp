===DECISION_RECORD===
META:
  HUMAN_ADR_REF::"HO-REMOVE-GOVERNANCE-AUTO-RATIFY-20260626"
  TYPE::DECISION_RECORD
  VERSION::"1.0"
  TOKEN::HO-REMOVE-GOVERNANCE-AUTO-RATIFY-20260626
  STATUS::RATIFIED
  TIER::STRATEGIC
  COMPRESSION_TIER::CONSERVATIVE
  LOSS_PROFILE::"[preserve:removal_of_auto_ratify_workflow_and_script_and_test,drop:narrative_history_of_how_it_was_introduced_without_backing_decision]"
  AUTHORED_AT::"2026-06-26T00:00:00Z"
  RATIFIED_BY::"human:operator<shaunbuswell>"
  RATIFIED_AT::"2026-06-26T00:00:00Z"
  SCOPE::"hestai-context-mcp"
  AFFECTS::[governance_ratify_workflow,ratify_decision_script,ratification_process]
  SCOPE_GUARD::"governs ratification workflow ∧ scripts ONLY; authoring (submit_governance) ∧ reading (lookup_decision) are EXCLUDED"
  DECISION::"Remove governance auto-ratify workflow ∧ script entirely → ratification reverts to explicit manual human editing of individual records ∴ preserves Human Primacy (PROD I3) ⊕ prevents collateral ratification of unrelated proposed decisions."
  BECAUSE::"Auto-ratify was non-selective ∧ mandatory ⇌ collaterally ratified unrelated pending decisions ∧ conflated PR mergeability with decision ratification ∴ category error violating human primacy ⊕ introduced without backing governance decision."
===END===