===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.1"
  TOKEN::HO-GOVERNANCE-IN-FLIGHT-TOKEN-AMENDMENT-20260921
  STATUS::RATIFIED
  TIER::STRATEGIC
  COMPRESSION_TIER::CONSERVATIVE
  LOSS_PROFILE::"[preserve:issue_ref∧token∧in_flight_definition∧collision_cases∧originating_agent_routing∧scope∧uniqueness_invariant∧human_merge_gate∧ceremony_ref∧operator_ruling,drop:operator_narrative]"
  AUTHORED_AT::"2026-09-21T00:00:00Z"
  ISSUE_REF::"repo:hestai-context-mcp#173"
  CEREMONY_REF::e18b0e88-638e-4b69-8e02-931def10e470
  AUTHORING_SESSION::"holistic-orchestrator:governance-authoring"
  OPERATOR_RULING::"Shaun Buswell, 2026-09-21, governance-authoring session: 'We should allow an amendment when there's a token. It should be passed to the agent that instigated it to make amendments.' ∧ fix covers both collision cases ∧ in-flight = branch unmerged into origin/main ∨ open PR"
  SCOPE::"hestai-context-mcp only"
  AFFECTS::[
    submit_governance,
    "tools/governance/linker.py",
    "tools/governance/lexer.py",
    "tools/governance/type_checker.py"
  ]
  SCOPE_GUARD::"TOKEN uniqueness on origin/main unchanged[ADR-RFC-ARCH-004 §4 #4] ∧ human merge remains sole semantic gate ∧ no auto-merge"
  IN_FLIGHT::"governance branch for TOKEN slug unmerged into origin/main ∨ open PR; merged undeleted origin branch excluded"
  COLLISION_CASES::"same-day governance/{date}-{slug} push collision ∧ later-day alternate-date second-PR risk"
  DECISION::"submit_governance TOKEN collision → amendment routed to originating agent → existing in-flight branch/PR updated ∧ same PR carries amendment ∧ no second PR ∧ no refusal"
  BECAUSE::"Check 6 lookup_token_deterministic searches MANIFEST.md + local tree; linker fetch follows validation → duplicate PRs possible ∧ open PRs unamendable. Authoring rules require submit_governance pre-merge → amendment path mandatory; merged origin branches ≠ in-flight"
  LANE_MARKER_TEST::"instigating agent identified by lane ceremony: in-flight PR body POSTED-BY::agent(role@session, ceremony ID) marker matches caller-supplied lane_ceremony → caller owns branch, amendment pushed to it; marker absent ∨ mismatch → amendment request posted as PR comment per HO-GOVERNANCE-AMENDMENT-REQUEST-AS-PR-COMMENT-20260921; cooperative check ≠ identity enforcement"
  MARKER_RULING::"Shaun Buswell, 2026-10-15: HC control room, relayed then confirmed first-party: 'Proceed with your recommendations and file one issue covering both'; read-topic-records session, first-party: '1. go 2. a) 3. TYou're right'; ratification, read-topic-records session, first-party: '1. I ratify these changes. 2. Reword the line 3. Yes, make recommended changes'; issue hestai-context-mcp#203"
  RATIFIED_BY::"human:operator<shaunbuswell>"
  RATIFIED_AT::"2026-10-15T00:00:00Z"
  REVISION::"2026-10-15: STATUS PROPOSED → RATIFIED; LANE_MARKER_TEST ∧ MARKER_RULING added; ruling HO-TOPIC-RECORDS-AND-APPEND-RULING-20261015 (hestai-context-mcp#203)"
===END===
