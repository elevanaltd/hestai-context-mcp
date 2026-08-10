===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.0"
  TOKEN::HO-SUBMIT-REVIEW-GATE-RETRIGGER-20260810
  STATUS::PROPOSED
  TIER::STRATEGIC
  COMPRESSION_TIER::CONSERVATIVE
  LOSS_PROFILE::"[preserve:ruleset_trigger_limitation∧head_sha_attachment∧abstain_failure_policy∧rerun_only_scope_guard∧re_review_trigger∧intentional_downstream_binding,drop:narrative_of_the_three_reworks_that_surfaced_it]"
  AUTHORED_AT::"2026-08-10T00:00:00Z"
  ISSUE_REF::"repo:hestai-context-mcp#145"
  SCOPE::"hestai-context-mcp ⊕ INTENTIONAL_DOWNSTREAM_BINDING[every repo enforced by org ruleset 12626210 gains the re-trigger with zero per-repo change — this universality IS the decision's purpose, not a side effect; consuming repos gain NO new obligation ∧ ship NO new file]"
  AFFECTS::[submit_review,review-gate.yml,validate_review,consuming_repo_gate_enforcement]
  SCOPE_GUARD::"grants re-run of an EXISTING pull_request-attached workflow run ONLY; merge ∧ approve ∧ arbitrary workflow_dispatch ∧ ruleset ∧ branch_protection mutation are EXCLUDED. Failure policy inherits HO-AGR-SEMANTIC-REVIEWER-ABSTAIN-ON-FAILURE-20260724. Re-evaluating a CI gate is NOT ratification (HO-REMOVE-GOVERNANCE-AUTO-RATIFY-20260626); human merge remains sole semantic gate (HO-AGR-DETERMINISTIC-REVIEW-CONVENTION-20260611)."
  RE_REVIEW_TRIGGER::"Premise is an EXTERNAL GitHub platform constraint outside this repo's control. Re-open this decision if ANY holds: (a) ruleset required-workflow gains issue_comment ∨ pull_request_review support → native triggering may obsolete the tool-side re-trigger; (b) issue_comment runs begin attaching to PR head SHA → head-check staleness resolves independently; (c) actions:write proves unavailable in practice across consuming repos → fall back to org-level GitHub App subscribing to issue_comment (alternative recorded in issue #145)."
  DECISION::"submit_review re-runs pull_request-attached Review Gate run at PR head SHA post-verdict → ruleset_12626210 unchanged ∧ zero per-repo files ⊕ best-effort ∴ failure → post succeeds ∧ reason recorded ∧ NEVER fabricate cleared gate"
  BECAUSE::"ruleset_required_workflow supports pull_request∧pull_request_target∧merge_group ONLY → issue_comment_trigger dropped ⊕ issue_comment_runs attach base_SHA ∴ head_check stale. Per-repo shims REJECTED[new_repos_break_by_default]. Gate∧tool co-located[HO-REVIEW-GATE-PLACEMENT-TRANSITION-20260620] ∴ trigger belongs with verdict flow ⇌ cost: outward Actions coupling."
===END===