===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.0"
  TOKEN::HO-GOVERNANCE-AMENDMENT-REQUEST-AS-PR-COMMENT-20260921
  STATUS::PROPOSED
  TIER::STRATEGIC
  COMPRESSION_TIER::CONSERVATIVE
  LOSS_PROFILE::"[preserve:operator_ruling∧routing_order∧comment_fallback∧no_identity_enforcement∧scope∧parent_token,drop:discussion]"
  AUTHORED_AT::"2026-09-21T00:00:00Z"
  ISSUE_REF::"repo:hestai-context-mcp#173"
  AMENDS::[HO-GOVERNANCE-IN-FLIGHT-TOKEN-AMENDMENT-20260921]
  CEREMONY_REF::"e18b0e88-638e-4b69-8e02-931def10e470"
  AUTHORING_SESSION::"holistic-orchestrator:governance-authoring"
  OPERATOR_RULING::"Shaun Buswell, 2026-09-21, governance-authoring session: 'For 173 amendments, it would be looking at the branch and the only way I can tell would be to find the agent working on it. If it's not possible, it should be that a request is added as a comment, no different to when a review is blocked.'"
  SCOPE::"hestai-context-mcp only; submit_governance amendment routing for an in-flight TOKEN"
  AFFECTS::[
    "submit_governance",
    "tools/governance/linker.py"
  ]
  SCOPE_GUARD::"No identity enforcement: PR author is always the operator's GitHub login ∴ 'instigating agent' is located by lane coordination, never asserted by the tool ∧ no push to another lane's in-flight branch ∧ no second PR ∧ human merge remains sole semantic gate"
  DECISION::"in-flight TOKEN amendment → caller locates agent working in-flight branch → hands amendment over; agent unlocatable → submit_governance posts amendment request as comment on in-flight PR[blocked-review channel] → owning agent applies on own branch"
  BECAUSE::"Instigating agent identifiable only via lane working branch; tool cannot[every PR = operator login] ∴ PR comment = existing blocked-review async channel → owner handles amendments like review findings ⊕ no new ownership model ∧ no cross-lane push"
===END===