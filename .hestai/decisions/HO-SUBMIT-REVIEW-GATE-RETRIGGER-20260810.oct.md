===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.1"
  TOKEN::HO-SUBMIT-REVIEW-GATE-RETRIGGER-20260810
  STATUS::RATIFIED
  RATIFIED_BY::"SHAUN BUSWELL"
  TIER::STRATEGIC
  COMPRESSION_TIER::CONSERVATIVE
  LOSS_PROFILE::"[preserve:ruleset_trigger_limitation∧head_sha_attachment∧abstain_failure_policy∧rerun_only_scope_guard∧re_review_trigger∧inherited_not_asserted_binding∧caller_token_dependency,drop:narrative_of_the_three_reworks_that_surfaced_it]"
  AUTHORED_AT::"2026-08-10T00:00:00Z"
  ISSUE_REF::"repo:hestai-context-mcp#145"
  SCOPE::"hestai-context-mcp ONLY. This record creates NO downstream binding: consuming repos are ALREADY bound to this repo's gate by org ruleset 12626210, a pre-existing human-configured org-level decision outside this record's authority. This record changes only WHERE the re-trigger lives INSIDE this service. Consuming repos ship no file, grant no permission, and change no config."
  AFFECTS::[submit_review,review-gate.yml,validate_review]
  SCOPE_GUARD::"grants re-run of an EXISTING pull_request-attached workflow run ONLY; merge ∧ approve ∧ arbitrary workflow_dispatch ∧ ruleset ∧ branch_protection mutation are EXCLUDED. actions:write is a property of the CALLER's token (the operator ∨ agent invoking submit_review), NOT a consuming-repo setting — absent scope degrades to abstain, never to a per-repo prerequisite. Failure policy inherits HO-AGR-SEMANTIC-REVIEWER-ABSTAIN-ON-FAILURE-20260724. Re-evaluating a CI gate is NOT ratification (HO-REMOVE-GOVERNANCE-AUTO-RATIFY-20260626); human merge remains sole semantic gate (HO-AGR-DETERMINISTIC-REVIEW-CONVENTION-20260611)."
  RE_REVIEW_TRIGGER::"Premise is an EXTERNAL GitHub platform constraint outside this repo's control. Re-open if ANY holds: (a) ruleset required-workflow gains issue_comment ∨ pull_request_review support → native triggering may obsolete the tool-side re-trigger; (b) issue_comment runs begin attaching to PR head SHA → head-check staleness resolves independently; (c) caller tokens routinely lack actions:write in practice → fall back to org-level GitHub App subscribing to issue_comment (alternative recorded in issue #145)."
  DECISION::"submit_review re-runs pull_request-attached Review Gate run at PR head SHA post-verdict → ruleset_12626210 unchanged ∧ zero per-repo files ⊕ best-effort ∴ failure → post succeeds ∧ reason recorded ∧ NEVER fabricate cleared gate"
  BECAUSE::"ruleset_required_workflow supports pull_request∧pull_request_target∧merge_group ONLY → issue_comment_trigger dropped ⊕ issue_comment_runs attach base_SHA ∴ head_check stale. Per-repo shims REJECTED[new_repos_break_by_default]. Gate∧tool co-located[HO-REVIEW-GATE-PLACEMENT-TRANSITION-20260620] ∴ trigger belongs with verdict flow ⇌ cost: outward Actions coupling."
===END===
