===DECISION_RECORD===
META:
  TYPE::DECISION_RECORD
  VERSION::"1.1"
  TOKEN::HO-TOPIC-RECORDS-AND-APPEND-RULING-20261015
  STATUS::RATIFIED
  TIER::STRATEGIC
  COMPRESSION_TIER::CONSERVATIVE
  LOSS_PROFILE::"[preserve:operator_ruling∧issue_ref∧amends_edges∧amended_fields∧scope,drop:discussion∧amended_content]"
  AUTHORED_AT::"2026-10-15T00:00:00Z"
  ISSUE_REF::"repo:hestai-context-mcp#203"
  AMENDS::[HO-GOVERNANCE-AMEND-IN-PLACE-20260926,HO-GOVERNANCE-IN-FLIGHT-TOKEN-AMENDMENT-20260921,HO-GOVERNANCE-AMENDMENT-REQUEST-AS-PR-COMMENT-20260921]
  CEREMONY_REF::"c52da839-8daf-4bbc-90f1-a3e5b5bc13c0"
  AUTHORING_SESSION::"holistic-orchestrator:read-topic-records"
  OPERATOR_RULING::"Shaun Buswell, 2026-10-15: (1) elevana-studio control room, relayed, quoted in #203: 'A long running record per topic and i dislike decision records that just update somethig and supersede another decision. It's a small setup and this feels like massive overhead. I'd like to be able to ppend to decisions easily and update them better and easier and make them more topic or ruling focused.'; (2) HC control room session, relayed then confirmed first-party: 'Proceed with your recommendations and file one issue covering both'; (3) read-topic-records session, first-party, answering design-note §9: '1. go 2. a) 3. TYou're right' (2. a) chose the issue to file, #203 covering S1-S5 plus governance); (4) read-topic-records session, first-party, ratification: '1. I ratify these changes. 2. Reword the line 3. Yes, make recommended changes'"
  SCOPE::"HestAI ecosystem → every repo carrying governance artefacts; standard owned by hestai-context-mcp"
  AMENDED_ARTEFACTS::".hestai/decisions/HO-GOVERNANCE-AMEND-IN-PLACE-20260926.oct.md → META THIN_RULING_RECORD, DECISION, INTERIM_PATH, REVISION; .hestai/decisions/HO-GOVERNANCE-IN-FLIGHT-TOKEN-AMENDMENT-20260921.oct.md → META STATUS, LANE_MARKER_TEST, MARKER_RULING, RATIFIED_BY, RATIFIED_AT, REVISION; .hestai/decisions/HO-GOVERNANCE-AMENDMENT-REQUEST-AS-PR-COMMENT-20260921.oct.md → META STATUS, SCOPE_GUARD, MARKER_FALLBACK, RATIFIED_BY, RATIFIED_AT, REVISION; .hestai/decisions/rfc-arch/ADR-RFC-ARCH-004-agent-readable-governance-records.md v1.2→v1.3 in place (topic records read side, PR #204); TOKEN-less → no AMENDS edge per ADR-RFC-ARCH-004 §1.6"
  DELIVERY::"AMEND-IN-PLACE, IN-FLIGHT and PR-COMMENT deltas travel in PR #207 (branch governance/20261015-topic-records-ratifications); ADR-RFC-ARCH-004 v1.3 travels in PR #204"
  SCOPE_GUARD::"human merge sole semantic gate ∧ no auto-merge ∧ TOKEN uniqueness unchanged ∧ in-place rule, no-stacking, SCOPE_GUARD of amended AMEND-IN-PLACE record unchanged"
  DECISION::"Amend three governance records in place → topic RULINGS entries ∧ append_ruling broker admitted; ceremony-marker test identifies lane; two in-flight records ratified; design note option B approved, tracked #203"
  BECAUSE::"Record-per-ruling ∧ supersession chains = overhead → one long-running record per topic; verbatim ruling inside it = its own ruling record"
  RATIFIED_BY::"human:operator<shaunbuswell>"
  RATIFIED_AT::"2026-10-15T00:00:00Z"
===END===